package com.leha.app

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.text.InputType
import android.view.WindowManager
import android.widget.*
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.Locale
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * Leha — hands-free native client (Siri-style "just talk").
 * Tap START once: Leha listens continuously, auto-detects when you finish
 * speaking (VAD), sends to the laptop, speaks the reply, then listens again.
 * Mutes itself while speaking so it doesn't hear its own voice.
 */
class MainActivity : AppCompatActivity(), TextToSpeech.OnInitListener {

    private lateinit var prefs: android.content.SharedPreferences
    private lateinit var status: TextView
    private lateinit var transcript: TextView
    private lateinit var orb: Button
    private var tts: TextToSpeech? = null

    @Volatile private var listening = false
    @Volatile private var speaking = false
    @Volatile private var busy = false

    private val http = OkHttpClient.Builder()
        .connectTimeout(6, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private val SR = 16000
    private val START_RMS = 600.0     // speech onset threshold (PCM16)
    private val SILENCE_MS = 800       // stop after this much quiet
    private val MIN_SPEECH_MS = 300    // ignore blips

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        prefs = getSharedPreferences("leha", Context.MODE_PRIVATE)
        tts = TextToSpeech(this, this)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(48, 64, 48, 48)
            setBackgroundColor(0xFF0A0E14.toInt())
        }
        val title = TextView(this).apply {
            text = "● LEHA"; setTextColor(0xFF22D3EE.toInt()); textSize = 18f; letterSpacing = 0.3f
        }
        status = TextView(this).apply {
            text = "Tap START, then just talk"; setTextColor(0xFF64748B.toInt()); textSize = 13f
            setPadding(0, 16, 0, 0)
        }
        transcript = TextView(this).apply {
            setTextColor(0xFFDBEAFE.toInt()); textSize = 16f; setPadding(0, 32, 0, 32)
        }
        orb = Button(this).apply {
            text = "START"; setTextColor(0xFF001018.toInt()); textSize = 18f
            setBackgroundColor(0xFF22D3EE.toInt())
            setOnClickListener { if (listening) stopListening() else startListening() }
        }
        val settings = Button(this).apply {
            text = "Settings"; setTextColor(0xFF22D3EE.toInt()); setBackgroundColor(0xFF1E293B.toInt())
            setOnClickListener { showSettings() }
        }
        val spacer = View(this).apply {
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        root.addView(title); root.addView(status); root.addView(transcript); root.addView(spacer)
        root.addView(orb, LinearLayout.LayoutParams(440, 200).apply {
            gravity = android.view.Gravity.CENTER_HORIZONTAL
        })
        root.addView(settings)
        setContentView(root)

        ensureMic()
        if (prefs.getString("ip", "").isNullOrBlank()) showSettings()
    }

    private fun ensureMic() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.RECORD_AUDIO), 1)
        }
    }

    private fun showSettings() {
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(48, 24, 48, 0) }
        val ipIn = EditText(this).apply { hint = "Laptop IP e.g. 192.168.31.48"; setText(prefs.getString("ip", "")) }
        val pinIn = EditText(this).apply {
            hint = "PIN"; setText(prefs.getString("pin", "")); inputType = InputType.TYPE_CLASS_NUMBER
        }
        box.addView(ipIn); box.addView(pinIn)
        AlertDialog.Builder(this).setTitle("Connect to Leha").setView(box)
            .setPositiveButton("Save") { _, _ ->
                prefs.edit().putString("ip", ipIn.text.toString().trim())
                    .putString("pin", pinIn.text.toString().trim()).apply()
                status.text = "Saved. Tap START."
            }.setNegativeButton("Cancel", null).show()
    }

    // ---- continuous hands-free loop ----
    private fun startListening() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) { ensureMic(); return }
        if (prefs.getString("ip", "").isNullOrBlank()) { showSettings(); return }
        listening = true
        orb.text = "STOP"; orb.setBackgroundColor(0xFF34D399.toInt())
        status.text = "Listening… just talk"
        thread(start = true) { captureLoop() }
    }

    private fun stopListening() {
        listening = false
        orb.text = "START"; orb.setBackgroundColor(0xFF22D3EE.toInt())
        runOnUiThread { status.text = "Stopped" }
    }

    private fun captureLoop() {
        val minBuf = AudioRecord.getMinBufferSize(SR, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, SR,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, SR))
        val frame = ShortArray(1600) // 100ms
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
                var sum = 0.0
                for (i in 0 until n) sum += (frame[i] * frame[i]).toDouble()
                val rms = Math.sqrt(sum / n)
                val ms = n * 1000 / SR
                if (rms > START_RMS) {
                    if (!inSpeech) { inSpeech = true; speech.reset(); speechMs = 0 }
                    silentMs = 0; speechMs += ms
                    val b = ByteArray(n * 2)
                    for (i in 0 until n) { b[i*2] = (frame[i].toInt() and 0xFF).toByte(); b[i*2+1] = (frame[i].toInt() shr 8).toByte() }
                    speech.write(b)
                } else if (inSpeech) {
                    silentMs += ms
                    val b = ByteArray(n * 2)
                    for (i in 0 until n) { b[i*2] = (frame[i].toInt() and 0xFF).toByte(); b[i*2+1] = (frame[i].toInt() shr 8).toByte() }
                    speech.write(b)
                    if (silentMs >= SILENCE_MS) {
                        inSpeech = false
                        if (speechMs >= MIN_SPEECH_MS) sendWav(speech.toByteArray())
                        speech.reset()
                    }
                }
            }
        } catch (e: Exception) {
            runOnUiThread { status.text = "Mic error: ${e.message}" }
        } finally {
            try { rec.stop(); rec.release() } catch (_: Exception) {}
        }
    }

    private fun wavHeader(pcmLen: Int): ByteArray {
        val total = 36 + pcmLen
        val h = ByteArrayOutputStream()
        fun s(x: String) = h.write(x.toByteArray())
        fun i(x: Int) { h.write(x and 0xFF); h.write((x shr 8) and 0xFF); h.write((x shr 16) and 0xFF); h.write((x shr 24) and 0xFF) }
        fun sh(x: Int) { h.write(x and 0xFF); h.write((x shr 8) and 0xFF) }
        s("RIFF"); i(total); s("WAVE"); s("fmt "); i(16); sh(1); sh(1); i(SR); i(SR*2); sh(2); sh(16); s("data"); i(pcmLen)
        return h.toByteArray()
    }

    private fun sendWav(pcm: ByteArray) {
        busy = true
        runOnUiThread { status.text = "Thinking…" }
        val wav = wavHeader(pcm.size) + pcm
        val ip = prefs.getString("ip", "") ?: ""; val pin = prefs.getString("pin", "") ?: ""
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("audio", "rec.wav", wav.toRequestBody("audio/wav".toMediaType()))
            .build()
        val req = Request.Builder().url("http://$ip:8001/api/voice")
            .addHeader("X-Leha-Pin", pin).post(body).build()
        http.newCall(req).enqueue(object : Callback {
            override fun onFailure(call: Call, e: java.io.IOException) {
                busy = false; runOnUiThread { status.text = "Can't reach laptop: ${e.message}" }
            }
            override fun onResponse(call: Call, response: Response) {
                val txt = response.body?.string() ?: ""; busy = false
                runOnUiThread {
                    if (response.code == 401) { status.text = "Wrong PIN"; return@runOnUiThread }
                    try {
                        val j = JSONObject(txt)
                        val heard = j.optString("heard"); val reply = j.optString("reply")
                        if (heard.isBlank() && reply.isBlank()) { status.text = "Listening…"; return@runOnUiThread }
                        transcript.text = "You: $heard\n\nLeha: $reply"
                        if (reply.isNotBlank()) speak(reply) else status.text = "Listening…"
                    } catch (e: Exception) { status.text = "Listening…" }
                }
            }
        })
    }

    override fun onInit(s: Int) {
        tts?.language = Locale.UK
        tts?.setOnUtteranceProgressListener(object : android.speech.tts.UtteranceProgressListener() {
            override fun onStart(id: String?) { speaking = true; runOnUiThread { status.text = "Leha speaking…" } }
            override fun onDone(id: String?) { speaking = false; runOnUiThread { if (listening) status.text = "Listening… just talk" } }
            @Deprecated("deprecated") override fun onError(id: String?) { speaking = false }
        })
    }
    private fun speak(t: String) {
        speaking = true
        tts?.speak(t, TextToSpeech.QUEUE_FLUSH, null, "leha")
    }

    override fun onDestroy() { listening = false; tts?.shutdown(); super.onDestroy() }
}
