package com.leha.app

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Build
import android.speech.tts.TextToSpeech
import android.text.InputType
import android.view.View
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
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * Leha — hands-free native client UI.
 *
 * The mic loop + brain call live in [LehaForegroundService]; this Activity is
 * only the control surface (arm/stop), the live transcript view, and settings
 * (laptop IP, PIN, Picovoice AccessKey, sensitivity). It no longer records
 * audio itself.
 */
class MainActivity : AppCompatActivity(), TextToSpeech.OnInitListener {

    private lateinit var prefs: android.content.SharedPreferences
    private lateinit var status: TextView
    private lateinit var transcript: TextView
    private lateinit var orb: Button
    private var tts: TextToSpeech? = null

    @Volatile private var listening = false

    private val serviceReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            val newStatus = intent?.getStringExtra("status")
            if (!newStatus.isNullOrBlank()) status.text = newStatus
            val heard = intent?.getStringExtra("heard")
            val reply = intent?.getStringExtra("reply")
            if (!heard.isNullOrBlank() || !reply.isNullOrBlank()) {
                transcript.text = "You: ${heard ?: ""}\n\nLeha: ${reply ?: ""}"
            }
        }
    }

    private val http = OkHttpClient.Builder()
        .connectTimeout(6, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

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
            text = "Tap ARM, then just talk"; setTextColor(0xFF64748B.toInt()); textSize = 13f
            setPadding(0, 16, 0, 0)
        }
        transcript = TextView(this).apply {
            setTextColor(0xFFDBEAFE.toInt()); textSize = 16f; setPadding(0, 32, 0, 32)
        }
        orb = Button(this).apply {
            text = "ARM LEHA"; setTextColor(0xFF001018.toInt()); textSize = 18f
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
        root.addView(Button(this).apply {
            text = "Test Server"; setTextColor(0xFFDBEAFE.toInt()); setBackgroundColor(0xFF334155.toInt())
            setOnClickListener { testServer() }
        })
        root.addView(Button(this).apply {
            text = "Type Command"; setTextColor(0xFFDBEAFE.toInt()); setBackgroundColor(0xFF334155.toInt())
            setOnClickListener { showTextCommand() }
        })
        root.addView(settings)
        setContentView(root)

        ensureMic()
        ensureNotifications()
        registerServiceReceiver()
        if (prefs.getString("ip", "").isNullOrBlank()) showSettings()
    }

    private fun registerServiceReceiver() {
        val filter = IntentFilter(LehaForegroundService.ACTION_EVENT)
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(serviceReceiver, filter, RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(serviceReceiver, filter)
        }
    }

    private fun ensureMic() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.RECORD_AUDIO), 1)
        }
    }

    private fun ensureNotifications() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2)
        }
    }

    private fun commandService(action: String) {
        val intent = Intent(this, LehaForegroundService::class.java).setAction(action)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent) else startService(intent)
    }

    private fun showSettings() {
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(48, 24, 48, 0) }
        val ipIn = EditText(this).apply { hint = "Laptop IP e.g. 192.168.31.48"; setText(prefs.getString("ip", "")) }
        val pinIn = EditText(this).apply {
            hint = "PIN"; setText(prefs.getString("pin", "")); inputType = InputType.TYPE_CLASS_NUMBER
        }
        val keyIn = EditText(this).apply {
            hint = "Picovoice AccessKey (optional — for 'Leha' hotword)"
            setText(prefs.getString("access_key", ""))
        }
        val sensIn = EditText(this).apply {
            hint = "Sensitivity 0.0-1.0 (default 0.7)"
            setText(prefs.getFloat("sensitivity", 0.7f).toString())
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
        }
        box.addView(ipIn); box.addView(pinIn); box.addView(keyIn); box.addView(sensIn)
        AlertDialog.Builder(this).setTitle("Connect to Leha").setView(box)
            .setPositiveButton("Save") { _, _ ->
                val sens = sensIn.text.toString().trim().toFloatOrNull()?.coerceIn(0f, 1f) ?: 0.7f
                prefs.edit()
                    .putString("ip", ipIn.text.toString().trim())
                    .putString("pin", pinIn.text.toString().trim())
                    .putString("access_key", keyIn.text.toString().trim())
                    .putFloat("sensitivity", sens)
                    .apply()
                status.text = "Saved. Tap ARM."
                testServer()
            }.setNegativeButton("Cancel", null).show()
    }

    // ---- hands-free control ----
    private fun startListening() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) { ensureMic(); return }
        if (prefs.getString("ip", "").isNullOrBlank()) { showSettings(); return }
        listening = true
        orb.text = "STOP"; orb.setBackgroundColor(0xFF34D399.toInt())
        status.text = "Arming…"
        commandService(LehaForegroundService.ACTION_START_LISTEN)
    }

    private fun stopListening() {
        listening = false
        orb.text = "ARM LEHA"; orb.setBackgroundColor(0xFF22D3EE.toInt())
        runOnUiThread { status.text = "Stopped" }
        commandService(LehaForegroundService.ACTION_STOP_LISTEN)
    }

    private fun testServer() {
        val ip = prefs.getString("ip", "") ?: ""
        if (ip.isBlank()) { showSettings(); return }
        status.text = "Testing server..."
        val req = Request.Builder().url("http://$ip:8001/api/health").get().build()
        http.newCall(req).enqueue(object : Callback {
            override fun onFailure(call: Call, e: java.io.IOException) {
                runOnUiThread { status.text = "Server offline: ${e.message}" }
            }

            override fun onResponse(call: Call, response: Response) {
                val body = response.body?.string() ?: ""
                runOnUiThread {
                    status.text = if (response.isSuccessful) "Server online" else "Server HTTP ${response.code}"
                    transcript.text = body.take(600)
                }
            }
        })
    }

    private fun showTextCommand() {
        val input = EditText(this).apply {
            hint = "Ask Leha"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
        }
        AlertDialog.Builder(this)
            .setTitle("Type command")
            .setView(input)
            .setPositiveButton("Send") { _, _ ->
                val text = input.text.toString().trim()
                if (text.isNotBlank()) sendText(text)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun sendText(text: String) {
        val ip = prefs.getString("ip", "") ?: ""
        val pin = prefs.getString("pin", "") ?: ""
        if (ip.isBlank()) { showSettings(); return }
        status.text = "Thinking..."
        commandService("Thinking")
        val body = JSONObject().put("text", text).toString()
            .toRequestBody("application/json".toMediaType())
        val req = Request.Builder().url("http://$ip:8001/api/text")
            .addHeader("X-Leha-Pin", pin).post(body).build()
        http.newCall(req).enqueue(object : Callback {
            override fun onFailure(call: Call, e: java.io.IOException) {
                runOnUiThread { status.text = "Can't reach laptop: ${e.message}" }
                commandService("Connection error")
            }

            override fun onResponse(call: Call, response: Response) {
                val txt = response.body?.string() ?: ""
                runOnUiThread {
                    try {
                        val j = JSONObject(txt)
                        val heard = j.optString("heard", text)
                        val reply = j.optString("reply")
                        transcript.text = "You: $heard\n\nLeha: $reply"
                        if (reply.isNotBlank()) speak(reply) else status.text = "Sent"
                    } catch (_: Exception) {
                        status.text = "Server HTTP ${response.code}"
                    }
                }
            }
        })
    }

    override fun onInit(s: Int) {
        tts?.language = Locale.UK
    }

    private fun speak(t: String) {
        tts?.speak(t, TextToSpeech.QUEUE_FLUSH, null, "leha")
    }

    override fun onDestroy() {
        listening = false
        try { unregisterReceiver(serviceReceiver) } catch (_: Exception) {}
        tts?.shutdown()
        super.onDestroy()
    }
}
