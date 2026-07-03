package com.leha.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import android.speech.tts.TextToSpeech
import androidx.core.app.NotificationCompat
import ai.picovoice.porcupine.Porcupine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.util.Locale
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * Always-on hands-free assistant service.
 *
 * One foreground service owns the microphone and runs a 4-state machine:
 *
 *   ARMED     -> listening for the "Leha" hotword (Porcupine). On detect -> AWAKE.
 *   AWAKE     -> capturing the spoken command via VAD, capped at MAX_COMMAND_MS.
 *                On silence/cap -> THINKING.
 *   THINKING  -> WAV POSTed to laptop /api/voice; awaiting reply.
 *   SPEAKING  -> phone TTS reads the reply. On done -> ARMED.
 *
 * If no Picovoice AccessKey is configured, Porcupine is skipped and the loop
 * falls back to one-shot tap-to-talk VAD: tap ARM, speak one command, then it
 * returns to Ready. The app never bricks waiting for a key.
 */
class LehaForegroundService : Service(), TextToSpeech.OnInitListener {

    @Volatile private var listening = false
    @Volatile private var speaking = false
    @Volatile private var busy = false
    private var tts: TextToSpeech? = null
    private var porcupine: Porcupine? = null
    @Volatile private var wakeReady = false   // Porcupine loaded + armed

    private val http = OkHttpClient.Builder()
        .connectTimeout(6, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private val sampleRate = 16000
    // Command-capture VAD (same proven values as the previous build).
    private val startRms = 600.0
    private val silenceMsLimit = 800
    private val minSpeechMs = 300
    private val maxCommandMs = 8000   // hard cap so a stuck mic never hangs

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        ensureChannel()
        tts = TextToSpeech(this, this)
        startForeground(NOTIFICATION_ID, notification("Ready"))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START_LISTEN -> startListening()
            ACTION_STOP_LISTEN -> stopListening()
            else -> updateNotification(intent?.getStringExtra("state") ?: "Ready")
        }
        return START_STICKY
    }

    private fun startListening() {
        if (listening) {
            updateNotification("Listening")
            return
        }
        listening = true
        // Lazily (re)build Porcupine each time we arm, so a key entered in
        // Settings takes effect on the next START without an app restart.
        loadPorcupine()
        broadcastStatus(if (wakeReady) "Armed — say Leha" else "Tap-to-talk ready")
        updateNotification(if (wakeReady) "Armed — say Leha" else "Tap-to-talk ready")
        thread(start = true, name = "leha-phone-listener") { captureLoop() }
    }

    private fun stopListening() {
        listening = false
        busy = false
        speaking = false
        tts?.stop()
        releasePorcupine()
        broadcastStatus("Stopped")
        updateNotification("Stopped")
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    /**
     * Build the Porcupine engine from the owner's AccessKey.
     *
     * Wake word precedence:
     *   1. Bundled custom keyword  assets/leha_android.ppn  (best — "Leha")
     *   2. Built-in "jarvis" keyword                            (instant, no .ppn)
     *   3. None -> one-shot tap-to-talk VAD fallback            (no key set)
     *
     * Any failure is logged and leaves wakeReady=false, so the loop keeps
     * working in fallback mode rather than crashing.
     */
    private fun loadPorcupine() {
        releasePorcupine()
        val key = getSharedPreferences("leha", Context.MODE_PRIVATE)
            .getString("access_key", "") ?: ""
        if (key.isBlank()) {
            wakeReady = false
            return
        }
        val sensitivity = getSharedPreferences("leha", Context.MODE_PRIVATE)
            .getFloat("sensitivity", 0.7f)
        try {
            val builder = Porcupine.Builder()
                .setAccessKey(key)
                .setSensitivity(sensitivity)
            val customAsset = bundledKeywordAsset()
            if (customAsset != null) {
                porcupine = builder.setKeywordPath(customAsset).build(this)
                android.util.Log.i(TAG, "Porcupine armed: custom leha keyword from $customAsset")
            } else {
                porcupine = builder.setKeyword(Porcupine.BuiltInKeyword.JARVIS).build(this)
                android.util.Log.i(TAG, "Porcupine armed: built-in 'jarvis' (no leha.ppn bundled)")
            }
            wakeReady = true
        } catch (e: Exception) {
            android.util.Log.e(TAG, "Porcupine init failed — using VAD fallback: ${e.message}")
            porcupine = null
            wakeReady = false
        }
    }

    /**
     * Return the assets-relative path to a bundled leha keyword file, or null.
     * Porcupine's setKeywordPath() accepts paths relative to the assets folder
     * directly, so no copying to filesDir is needed.
     */
    private fun bundledKeywordAsset(): String? {
        return try {
            val names = assets.list("") ?: return null
            val target = names.firstOrNull {
                it.equals("leha_android.ppn", true) || it.equals("leha.ppn", true)
            }
            target  // assets-relative path, e.g. "leha_android.ppn"
        } catch (e: Exception) {
            android.util.Log.w(TAG, "No bundled leha.ppn: ${e.message}")
            null
        }
    }

    private fun releasePorcupine() {
        try { porcupine?.delete() } catch (_: Exception) {}
        porcupine = null
        wakeReady = false
    }

    private fun captureLoop() {
        val minBuf = AudioRecord.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        val rec = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBuf, sampleRate)
        )
        // Porcupine consumes exactly frameLength samples per call; the VAD
        // path is tolerant of any frame size, so size to Porcupine when armed.
        val frame = ShortArray(porcupine?.frameLength ?: 1600)
        val speech = ByteArrayOutputStream()
        var inSpeech = false
        var silentMs = 0
        var speechMs = 0

        try {
            rec.startRecording()
            while (listening) {
                if (speaking || busy) { Thread.sleep(60); continue }
                val n = rec.read(frame, 0, frame.size)
                if (n <= 0) continue
                val rms = rmsOf(frame, n)
                val ms = n * 1000 / sampleRate

                // --- ARMED: hotword detection ---
                if (wakeReady && !inSpeech) {
                    try {
                        val kw = porcupine?.process(frame) ?: -1
                        if (kw >= 0) {
                            // Wake fired -> immediately enter command capture.
                            inSpeech = true
                            speech.reset()
                            speechMs = 0
                            silentMs = 0
                            broadcastStatus("Hearing you")
                            updateNotification("Hearing you")
                            writePcm(frame, n, speech)
                            continue
                        }
                    } catch (e: Exception) {
                        android.util.Log.e(TAG, "Porcupine process failed: ${e.message}")
                        // Disable hotword for this session but keep VAD fallback alive.
                        wakeReady = false
                    }
                    // No wake yet; don't capture audio.
                    continue
                }

                // --- VAD-only fallback (no key): tap ARM, speak one command ---
                if (!wakeReady && !inSpeech && rms > startRms) {
                    inSpeech = true
                    speech.reset()
                    speechMs = 0
                    silentMs = 0
                    broadcastStatus("Hearing you")
                    updateNotification("Hearing you")
                }

                // --- AWAKE: command capture (VAD silence OR hard cap) ---
                if (inSpeech) {
                    speechMs += ms
                    writePcm(frame, n, speech)
                    if (rms > startRms) {
                        silentMs = 0
                    } else {
                        silentMs += ms
                    }
                    val silenceDone = silentMs >= silenceMsLimit && speechMs >= minSpeechMs
                    val capDone = speechMs >= maxCommandMs
                    if (silenceDone || capDone) {
                        inSpeech = false
                        if (speechMs >= minSpeechMs) sendWav(speech.toByteArray())
                        speech.reset()
                        // After a command, re-arm for the next wake word.
                        if (listening && wakeReady) {
                            broadcastStatus("Armed — say Leha")
                            updateNotification("Armed — say Leha")
                        } else {
                            // VAD-only mode: stay continuously listening.
                            // Room audio below threshold won't trigger a second
                            // command until it rises above startRms again.
                            broadcastStatus("Listening")
                            updateNotification("Listening")
                        }
                    }
                }
            }
        } catch (e: Exception) {
            broadcastStatus("Mic error: ${e.message}")
            updateNotification("Mic error")
        } finally {
            try { rec.stop(); rec.release() } catch (_: Exception) {}
        }
    }

    private fun rmsOf(frame: ShortArray, n: Int): Double {
        var sum = 0.0
        for (i in 0 until n) sum += (frame[i] * frame[i]).toDouble()
        return Math.sqrt(sum / n)
    }

    private fun writePcm(frame: ShortArray, n: Int, out: ByteArrayOutputStream) {
        val b = ByteArray(n * 2)
        for (i in 0 until n) {
            b[i * 2] = (frame[i].toInt() and 0xFF).toByte()
            b[i * 2 + 1] = (frame[i].toInt() shr 8).toByte()
        }
        out.write(b)
    }

    private fun wavHeader(pcmLen: Int): ByteArray {
        val total = 36 + pcmLen
        val h = ByteArrayOutputStream()
        fun s(x: String) = h.write(x.toByteArray())
        fun i(x: Int) {
            h.write(x and 0xFF)
            h.write((x shr 8) and 0xFF)
            h.write((x shr 16) and 0xFF)
            h.write((x shr 24) and 0xFF)
        }
        fun sh(x: Int) {
            h.write(x and 0xFF)
            h.write((x shr 8) and 0xFF)
        }
        s("RIFF"); i(total); s("WAVE"); s("fmt "); i(16); sh(1); sh(1)
        i(sampleRate); i(sampleRate * 2); sh(2); sh(16); s("data"); i(pcmLen)
        return h.toByteArray()
    }

    private fun sendWav(pcm: ByteArray) {
        val prefs = getSharedPreferences("leha", Context.MODE_PRIVATE)
        val ip = prefs.getString("ip", "") ?: ""
        val pin = prefs.getString("pin", "") ?: ""
        if (ip.isBlank()) {
            broadcastStatus("Set laptop IP in Settings")
            updateNotification("Settings needed")
            return
        }
        busy = true
        broadcastStatus("Thinking")
        updateNotification("Thinking")
        val wav = wavHeader(pcm.size) + pcm
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("audio", "rec.wav", wav.toRequestBody("audio/wav".toMediaType()))
            .build()
        val req = Request.Builder().url("http://$ip:8001/api/voice")
            .addHeader("X-Leha-Pin", pin)
            .addHeader("X-Leha-Client", "android")
            .post(body).build()
        http.newCall(req).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                busy = false
                broadcastStatus("Can't reach laptop: ${e.message}")
                updateNotification("Connection error")
            }

            override fun onResponse(call: Call, response: Response) {
                val txt = response.body?.string() ?: ""
                busy = false
                try {
                    val j = JSONObject(txt)
                    val heard = j.optString("heard")
                    val reply = j.optString("reply")
                    val ignoredReason = j.optString("ignored_reason")
                    if (reply.isBlank() && ignoredReason.isNotBlank()) {
                        broadcastStatus("Waiting for Leha")
                        updateNotification("Waiting for Leha")
                        return
                    }
                    if (heard.isNotBlank() || reply.isNotBlank()) {
                        broadcastTranscript(heard, reply)
                    }
                    if (reply.isNotBlank()) speak(reply) else {
                        broadcastStatus(if (listening) (if (wakeReady) "Armed — say Leha" else "Tap-to-talk ready") else "Ready")
                        updateNotification(if (listening) (if (wakeReady) "Armed — say Leha" else "Tap-to-talk ready") else "Ready")
                    }
                } catch (_: Exception) {
                    broadcastStatus("Server HTTP ${response.code}")
                    updateNotification("Server error")
                }
            }
        })
    }

    override fun onInit(status: Int) {
        tts?.language = Locale.UK
        tts?.setOnUtteranceProgressListener(object : android.speech.tts.UtteranceProgressListener() {
            override fun onStart(id: String?) {
                speaking = true
                broadcastStatus("Leha speaking")
                updateNotification("Speaking")
            }

            override fun onDone(id: String?) {
                speaking = false
                broadcastStatus(if (listening) (if (wakeReady) "Armed — say Leha" else "Listening") else "Ready")
                updateNotification(if (listening) (if (wakeReady) "Armed — say Leha" else "Listening") else "Ready")
            }

            @Deprecated("deprecated")
            override fun onError(id: String?) {
                speaking = false
                broadcastStatus(if (listening) (if (wakeReady) "Armed — say Leha" else "Listening") else "Ready")
                updateNotification(if (listening) (if (wakeReady) "Armed — say Leha" else "Listening") else "Ready")
            }
        })
    }

    private fun speak(text: String) {
        speaking = true
        tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "leha-service")
    }

    private fun broadcastStatus(text: String) {
        sendBroadcast(Intent(ACTION_EVENT).setPackage(packageName).putExtra("status", text))
    }

    private fun broadcastTranscript(heard: String, reply: String) {
        sendBroadcast(
            Intent(ACTION_EVENT)
                .setPackage(packageName)
                .putExtra("heard", heard)
                .putExtra("reply", reply)
        )
    }

    private fun updateNotification(state: String) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, notification(state))
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Leha Assistant",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Keeps Leha available while you use the phone."
            setShowBadge(false)
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun notification(state: String): Notification {
        val openIntent = Intent(this, MainActivity::class.java)
        val pending = PendingIntent.getActivity(
            this,
            0,
            openIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val stopIntent = Intent(this, LehaForegroundService::class.java).setAction(ACTION_STOP_LISTEN)
        val stopPending = PendingIntent.getService(
            this,
            1,
            stopIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("Leha")
            .setContentText(state)
            .setContentIntent(pending)
            .addAction(android.R.drawable.ic_media_pause, "Stop", stopPending)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    override fun onDestroy() {
        listening = false
        releasePorcupine()
        tts?.stop()
        tts?.shutdown()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "LehaService"
        const val ACTION_START_LISTEN = "com.leha.app.START_LISTEN"
        const val ACTION_STOP_LISTEN = "com.leha.app.STOP_LISTEN"
        const val ACTION_EVENT = "com.leha.app.EVENT"
        const val CHANNEL_ID = "leha_assistant"
        const val NOTIFICATION_ID = 1001
    }
}
