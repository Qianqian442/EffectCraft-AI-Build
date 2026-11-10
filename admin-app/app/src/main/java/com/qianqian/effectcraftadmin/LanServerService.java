package com.qianqian.effectcraftadmin;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/** Keeps the phone's home-Wi-Fi account API alive while the screen is off. */
public final class LanServerService extends Service {
    private static final String CHANNEL_ID = "effectcraft_home_server";
    private static final int NOTIFICATION_ID = 8787;
    private LanAccountServer server;
    private Thread worker;

    @Override public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        Notification notification = new Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_upload_done)
            .setContentTitle("EffectCraft 家庭账号服务")
            .setContentText("仅在连接的家庭 Wi-Fi 内提供账号服务")
            .setOngoing(true)
            .build();
        startForeground(NOTIFICATION_ID, notification);
        server = new LanAccountServer(getApplicationContext());
        worker = new Thread(server, "EffectCraft-LAN-Account-Server");
        worker.setDaemon(true);
        worker.start();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "EffectCraft 家庭账号服务", NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("保持家庭 Wi-Fi 内的账号服务运行");
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.createNotificationChannel(channel);
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override public void onDestroy() {
        if (server != null) server.stopServer();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) {
        return null;
    }
}
