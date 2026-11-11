package com.qianqian.effectcraftadmin;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/** User-controlled lifecycle for the admin-phone account API. */
public final class AccountServerService extends Service {
    private static final String CHANNEL = "effectcraft_account_server";
    private static final int NOTIFICATION_ID = 8788;
    private LanAccountServer server;
    private Thread worker;

    @Override public void onCreate() {
        super.onCreate();
        createChannel();
        Notification n = new Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_upload_done)
            .setContentTitle("EffectCraft 账号服务器")
            .setContentText("正在启动本机账号服务")
            .setOngoing(true).build();
        startForeground(NOTIFICATION_ID, n);
        server = new LanAccountServer(getApplicationContext());
        worker = new Thread(server, "EffectCraft-Account-Server");
        worker.setDaemon(true);
        worker.start();
        getSharedPreferences("effectcraft_account_server_state", MODE_PRIVATE)
            .edit().putBoolean("requested", true).putBoolean("service_process", true).apply();
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL, "EffectCraft 账号服务器", NotificationManager.IMPORTANCE_LOW);
            channel.setDescription("管理员主动开启的本机账号服务");
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.createNotificationChannel(channel);
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override public void onDestroy() {
        if (server != null) server.stopServer();
        getSharedPreferences("effectcraft_account_server_state", MODE_PRIVATE)
            .edit().putBoolean("requested", false).putBoolean("service_process", false).apply();
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) manager.cancel(NOTIFICATION_ID);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
