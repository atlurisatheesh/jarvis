package com.leha.app

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.MediaRecorder
import android.os.Build
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.text.InputType
import android.view.MotionEvent
import android.widget.*
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.asRequestBody
import org.json.JSONObject
import java.io.File
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * Leha — native Android client.
 * Press-and-hold the orb to talk; release to send. Audio goes to the laptop
 * Leha web server (/api/voice) with the PIN. Reply is shown and spoken.
 */
class MainActivity : AppCompatActivity(), TextToSpeech.OnInitListener {

    private lateinit var prefs: android.content.SharedPreferences
    private lateinit var status: TextView
    private lateinit var transcript: TextView
    private lateinit var orb: Button
    private var tts: TextToSpeech? = null
    private var recorder: MediaRecorder? = null
    private var audioFile: File? = null

    private val http = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = getSharedPreferences("leha", Context.MODE_PRIVATE)
        tts = TextToSpeech(this, this)

        // Build UI in code (no XML layout needed for v1)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 64, 48, 48)
            setBackgroundColor(0xFF0A0E14.toInt())
        }
        val title = TextView(this).apply {
            text = "● LEHA"; setTextColor(0xFF22D3EE.toInt()); textSize = 18f
            letterSpacing = 0.3f
        }
        status = TextView(this).apply {
            text = "Hold the orb and speak"; setTextColor(0xFF64748B.toInt()); textSize = 13f
            setPadding(0, 16, 0, 0)
        }
        transcript = TextView(this).apply {
            setTextColor(0xFFDBEAFE.toInt()); textSize = 16f; setPadding(0, 32, 0, 32)
        }
        orb = Button(this).apply {
            text = "HOLD\nTO TALK"; setTextColor(0xFF001018.toInt()); textSize = 16f
            setBackgroundColor(0xFF22D3EE.toInt())
        }
        val settings = Button(this).apply {
            text = "Settings"; setTextColor(0xFF22D3EE.toInt())
            setBackgroundColor(0xFF1E293B.toInt())
            setOnClickListener { showSettings() }
        }
        val spacer = View(this).apply {
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        root.addView(title); root.addView(status); root.addView(transcript)
        root.addView(spacer)
        val orbLp = LinearLayout.LayoutParams(420, 420).apply { gravity = android.view.Gravity.CENTER_HORIZONTAL }
        root.addView(orb, orbLp)
        root.addView(settings)
        setContentView(root)

        ensureMicPermission()
        orb.setOnTouchListener { _, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> { startRec(); true }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> { stopRecAndSend(); true }
                else -> false
            }
        }

        if (prefs.getString("ip", "").isNullOrBlank()) showSettings()
    }

    // ---- settings (laptop IP + PIN) ----
    private fun showSettings() {
        val ctx = this
        val box = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL; setPadding(48, 24, 48, 0) }
        val ipIn = EditText(ctx).apply {
            hint = "Laptop IP (e.g. 10.108.74.154)"; setText(prefs.getString("ip", ""))
            inputType = InputType.TYPE_CLASS_TEXT
        }
        val pinIn = EditText(ctx).apply {
            hint = "PIN"; setText(prefs.getString("pin", "")); inputType = InputType.TYPE_CLASS_NUMBER
        }
        box.addView(ipIn); box.addView(pinIn)
        AlertDialog.Builder(ctx)
            .setTitle("Connect to Leha")
            .setView(box)
            .setPositiveButton("Save") { _, _ ->
                prefs.edit()
                    .putString("ip", ipIn.text.toString().trim())
                    .putString("pin", pinIn.text.toString().trim())
                    .apply()
                status.text = "Saved. Hold the orb and speak."
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // ---- mic permission ----
    private fun ensureMicPermission() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.RECORD_AUDIO), 1)
        }
    }

    // ---- recording ----
    private fun startRec() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) { ensureMicPermission(); return }
        try {
            audioFile = File(cacheDir, "rec.m4a")
            recorder = (if (Build.VERSION.SDK_INT >= 31) MediaRecorder(this) else @Suppress("DEPRECATION") MediaRecorder()).apply {
                setAudioSource(MediaRecorder.AudioSource.MIC)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setAudioSamplingRate(16000)
                setOutputFile(audioFile!!.absolutePath)
                prepare(); start()
            }
            orb.setBackgroundColor(0xFFDC2626.toInt())
            status.text = "Listening…"
        } catch (e: Exception) {
            status.text = "Mic error: ${e.message}"
        }
    }

    private fun stopRecAndSend() {
        orb.setBackgroundColor(0xFF22D3EE.toInt())
        try { recorder?.stop() } catch (_: Exception) {}
        recorder?.release(); recorder = null
        val f = audioFile ?: return
        if (!f.exists() || f.length() < 1500) { status.text = "Too short, try again"; return }
        send(f)
    }

    // ---- network ----
    private fun send(f: File) {
        val ip = prefs.getString("ip", "") ?: ""
        val pin = prefs.getString("pin", "") ?: ""
        if (ip.isBlank()) { showSettings(); return }
        status.text = "Thinking…"
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("audio", "rec.m4a", f.asRequestBody("audio/mp4".toMediaType()))
            .build()
        val req = Request.Builder()
            .url("http://$ip:8001/api/voice")
            .addHeader("X-Leha-Pin", pin)
            .post(body).build()
        http.newCall(req).enqueue(object : Callback {
            override fun onFailure(call: Call, e: java.io.IOException) {
                runOnUiThread { status.text = "Can't reach laptop: ${e.message}" }
            }
            override fun onResponse(call: Call, response: Response) {
                val txt = response.body?.string() ?: ""
                runOnUiThread {
                    if (response.code == 401) { status.text = "Wrong PIN"; return@runOnUiThread }
                    try {
                        val j = JSONObject(txt)
                        val heard = j.optString("heard"); val reply = j.optString("reply")
                        transcript.text = "You: $heard\n\nLeha: $reply"
                        status.text = "Hold the orb and speak"
                        if (reply.isNotBlank()) speak(reply)
                    } catch (e: Exception) { status.text = "Bad reply" }
                }
            }
        })
    }

    // ---- TTS ----
    override fun onInit(s: Int) { tts?.language = Locale.UK }
    private fun speak(t: String) { tts?.speak(t, TextToSpeech.QUEUE_FLUSH, null, "leha") }

    override fun onDestroy() { tts?.shutdown(); super.onDestroy() }
}
