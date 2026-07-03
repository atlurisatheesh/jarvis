package com.leha.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build

/**
 * Restarts the always-on hotword service after a reboot.
 *
 * Only arms the service if the user has completed first-run setup and provided
 * a Picovoice AccessKey. Without a key there is no real wake word, so the app
 * intentionally falls back to manual ARM from the Activity instead of listening
 * to arbitrary room speech after boot.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED) return
        val prefs = context.getSharedPreferences("leha", Context.MODE_PRIVATE)
        if (prefs.getString("ip", "").isNullOrBlank()) return  // not set up yet
        if (prefs.getString("access_key", "").isNullOrBlank()) return  // manual ARM fallback only
        val service = Intent(context, LehaForegroundService::class.java)
            .setAction(LehaForegroundService.ACTION_START_LISTEN)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(service)
        } else {
            context.startService(service)
        }
    }
}
