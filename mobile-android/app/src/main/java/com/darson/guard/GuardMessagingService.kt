package com.darson.guard

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class GuardMessagingService : FirebaseMessagingService() {
    override fun onRegistered(installationId: String) {
        // The current FID is uploaded at the next authenticated foreground sync.
        getSharedPreferences("guard_device", MODE_PRIVATE).edit()
            .putString("installation_id", installationId).apply()
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val taskId = message.data["task_id"] ?: return
        if (taskId.isBlank()) return
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(
            "darson_alerts", "Guard alerts", NotificationManager.IMPORTANCE_HIGH
        ).apply { description = "Assigned DARSON security tasks" })
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
            putExtra("task_id", taskId)
        }
        val pending = PendingIntent.getActivity(this, taskId.hashCode(), intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(this, "darson_alerts")
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle("DARSON security task")
            .setContentText("Open the app to review an assigned task.")
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setAutoCancel(true)
            .setContentIntent(pending)
            .build()
        manager.notify(taskId.hashCode(), notification)
    }
}
