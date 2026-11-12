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
    private PeerHealthServer server;
    private LanPeerDiscovery discovery;
    private Thread worker;
    private LanAccountServer accountServer;
    private Thread accountWorker;

    @Override public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        Notification notification = new Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_upload_done)
            .setContentTitle("EffectCraft 手机节点")
            .setContentText("正在启动网络节点并发现附近设备")
            .setOngoing(true)
            .build();
        startForeground(NOTIFICATION_ID, notification);

        accountServer = new LanAccountServer(this);
        accountWorker = new Thread(accountServer, "EffectCraft-Account-Database-Server");
        accountWorker.setDaemon(true);
        accountWorker.start();
        P2PAccountBridge.start(accountServer);
        NativeP2P.start(this);

        server = new PeerHealthServer();
        worker = new Thread(server, "EffectCraft-P2P-Lightweight-Node");
        worker.setDaemon(true);
        worker.start();

        discovery = new LanPeerDiscovery(getApplicationContext());
        discovery.start();
        getSharedPreferences(LanPeerDiscovery.PREFS, MODE_PRIVATE)
            .edit().putBoolean("node_running", true).apply();
        updateNotification();
    }

    private void updateNotification() {
        String ip = PeerHealthServer.getWifiIpv4();
        int count = LanPeerDiscovery.getSavedPeers(this).length();
        String status = ip.isEmpty()
            ? "等待连接 Wi-Fi · 附近节点 " + count + " 台"
            : ip + ":" + LanPeerDiscovery.PORT + " · 附近节点 " + count + " 台";
        Notification notification = new Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_upload_done)
            .setContentTitle("EffectCraft 网络节点运行中")
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
            channel.setDescription("保持用户主动启用的轻量网络节点运行");
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
        if (accountServer != null) accountServer.stopServer();
        P2PAccountBridge.stop();
        NativeP2P.stop();
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
