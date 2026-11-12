package com.qianqian.effectcraftadmin;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/**
 * Optional phone-hosted node service. The initial P2P milestone advertises
 * this node and discovers nearby EffectCraft nodes on the current Wi-Fi.
 */
public final class LanServerService extends Service {
    private static final String CHANNEL_ID = "effectcraft_p2p_node";
    private static final int NOTIFICATION_ID = 8787;
    private LanAccountServer server;
    private LanPeerDiscovery discovery;
    private Thread worker;

    @Override public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        Notification notification = new Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_upload_done)
            .setContentTitle("EffectCraft 账号主服务器")
            .setContentText("正在启动本机账号服务和自动节点发现")
            .setOngoing(true)
            .build();
        startForeground(NOTIFICATION_ID, notification);

        server = new LanAccountServer(getApplicationContext());
        worker = new Thread(server, "EffectCraft-Phone-Account-Master");
        worker.setDaemon(true);
        worker.start();

        discovery = new LanPeerDiscovery(getApplicationContext());
        discovery.start();
        getSharedPreferences(LanPeerDiscovery.PREFS, MODE_PRIVATE)
            .edit().putBoolean("node_running", true).apply();
        updateNotification();
    }

    private void updateNotification() {
        String ip = LanAccountServer.getWifiIpv4();
        int peers = LanPeerDiscovery.getSavedPeers(this).length();
        int accounts = LanAccountServer.getRegisteredCount(this);
        String status = ip.isEmpty()
            ? "等待连接 Wi-Fi · 已注册账号 " + accounts + " 人"
            : ip + ":" + LanAccountServer.PORT + " · 账号 " + accounts + " 人 · 附近节点 " + peers + " 台";
        Notification notification = new Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_upload_done)
            .setContentTitle("EffectCraft 账号主服务器运行中")
            .setContentText(status)
            .setOngoing(true)
            .build();
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) manager.notify(NOTIFICATION_ID, notification);
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "EffectCraft 手机节点", NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("管理员手机作为账号数据库主服务器，并自动发现可连接的 EffectCraft 设备");
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.createNotificationChannel(channel);
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override public void onDestroy() {
        if (discovery != null) discovery.stop();
        if (server != null) server.stopServer();
        getSharedPreferences(LanPeerDiscovery.PREFS, MODE_PRIVATE)
            .edit().putBoolean("node_running", false).apply();
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) manager.cancel(NOTIFICATION_ID);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) {
        return null;
    }
}
