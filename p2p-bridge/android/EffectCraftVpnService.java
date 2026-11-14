package com.artcraft.effectcraft;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.net.VpnService;
import android.os.Build;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.net.Inet4Address;
import java.net.Inet6Address;
import java.net.InetAddress;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import hev.htproxy.TProxyService;

/**
 * Task-scoped Android VPN. It routes only EffectCraft's Cloudflare Worker
 * connections through the administrator phone's authenticated P2P egress.
 */
public final class EffectCraftVpnService extends VpnService {
    private static final String TAG = "EffectCraftVPN";
    private static final String ACTION_START = "com.artcraft.effectcraft.vpn.START";
    private static final String ACTION_STOP = "com.artcraft.effectcraft.vpn.STOP";
    private static final String CHANNEL_ID = "effectcraft_account_vpn";
    private static final int NOTIFICATION_ID = 8401;
    static final int PERMISSION_REQUEST_CODE = 8402;
    private static final Object PERMISSION_LOCK = new Object();

    private static volatile CountDownLatch permissionLatch;
    private static volatile boolean permissionGranted;
    private static volatile boolean taskActive;
    private static volatile String lastError = "";

    private ParcelFileDescriptor tunInterface;
    private File configFile;
    private String taskSecret;
    private Thread startThread;

    public static void onPermissionResult(boolean granted) {
        permissionGranted = granted;
        CountDownLatch latch = permissionLatch;
        if (latch != null) latch.countDown();
    }

    private static boolean ensurePermission(Context context) {
        Intent permission = VpnService.prepare(context);
        if (permission == null) return true;

        CountDownLatch latch = new CountDownLatch(1);
        synchronized (PERMISSION_LOCK) {
            permissionGranted = false;
            permissionLatch = latch;
        }
        NativeP2P.launchVpnPermission(permission, PERMISSION_REQUEST_CODE);
        try {
            boolean completed = latch.await(75, TimeUnit.SECONDS);
            return completed && permissionGranted && VpnService.prepare(context) == null;
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            return false;
        } finally {
            synchronized (PERMISSION_LOCK) {
                if (permissionLatch == latch) permissionLatch = null;
            }
        }
    }

    /** Called by the localhost command bridge immediately before one account API operation. */
    public static String startForTask(Context context, String host) {
        if (!isAllowedHost(host)) return "ERROR:账号 VPN 只接受配置的 workers.dev 主机";
        if (taskActive) return "OK";

        if (!ensurePermission(context)) return "VPN_PERMISSION_REQUIRED";

        try {
            List<InetAddress> addresses = new ArrayList<>();
            for (InetAddress address : InetAddress.getAllByName(host)) {
                if (isPublicAddress(address) && !addresses.contains(address)) addresses.add(address);
            }
            if (addresses.isEmpty() || addresses.size() > 32) {
                return "ERROR:Worker DNS 没有返回可用公网地址";
            }

            StringBuilder csv = new StringBuilder();
            for (InetAddress address : addresses) {
                if (csv.length() > 0) csv.append(',');
                csv.append(address.getHostAddress());
            }

            byte[] secretBytes = new byte[32];
            new SecureRandom().nextBytes(secretBytes);
            StringBuilder secret = new StringBuilder();
            for (byte value : secretBytes) secret.append(String.format(java.util.Locale.ROOT, "%02x", value & 0xff));
            String config = NativeP2P.configureVpnProxy(host, csv.toString(), secret.toString());
            if (config == null || !config.equals("OK")) return "ERROR:" + config;

            lastError = "";
            Intent intent = new Intent(context, EffectCraftVpnService.class)
                .setAction(ACTION_START)
                .putExtra("worker_host", host)
                .putExtra("socks_secret", secret.toString())
                .putExtra("worker_ips", csv.toString());
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent);
            else context.startService(intent);

            long deadline = System.currentTimeMillis() + 15000L;
            while (System.currentTimeMillis() < deadline) {
                if (taskActive) return "OK";
                if (!lastError.isEmpty()) return "ERROR:" + lastError;
                Thread.sleep(100L);
            }
            return "ERROR:VPN 隧道启动超时";
        } catch (SecurityException denied) {
            return "VPN_PERMISSION_REQUIRED";
        } catch (Throwable error) {
            Log.e(TAG, "Could not start account VPN task", error);
            return "ERROR:" + error.getClass().getSimpleName();
        }
    }

    /** Stop immediately after the account API request completes or fails. */
    public static String stopForTask(Context context) {
        try {
            Intent intent = new Intent(context, EffectCraftVpnService.class).setAction(ACTION_STOP);
            context.startService(intent);
            long deadline = System.currentTimeMillis() + 8000L;
            while (System.currentTimeMillis() < deadline) {
                if (!taskActive) {
                    NativeP2P.clearVpnProxyConfig();
                    return "OK";
                }
                Thread.sleep(80L);
            }
            NativeP2P.clearVpnProxyConfig();
            return "ERROR:VPN 关闭确认超时";
        } catch (Throwable error) {
            NativeP2P.clearVpnProxyConfig();
            return "ERROR:" + error.getClass().getSimpleName();
        }
    }

    public static boolean isTaskActive() {
        return taskActive;
    }

    private static boolean isAllowedHost(String host) {
        return host != null
            && host.length() > 12
            && host.length() <= 253
            && host.toLowerCase(java.util.Locale.ROOT).endsWith(".workers.dev")
            && host.matches("[A-Za-z0-9.-]+")
            && !host.contains("..")
            && !host.startsWith(".")
            && !host.endsWith(".");
    }

    private static boolean isPublicAddress(InetAddress address) {
        if (address.isAnyLocalAddress() || address.isLoopbackAddress()
            || address.isLinkLocalAddress() || address.isSiteLocalAddress()
            || address.isMulticastAddress()) return false;
        if (address instanceof Inet4Address) {
            byte[] b = address.getAddress();
            int first = b[0] & 0xff;
            return first != 0 && first != 10 && first != 127
                && !(first == 169 && (b[1] & 0xff) == 254)
                && !(first == 172 && (b[1] & 0xff) >= 16 && (b[1] & 0xff) <= 31)
                && !(first == 192 && (b[1] & 0xff) == 168);
        }
        if (address instanceof Inet6Address) {
            byte[] b = address.getAddress();
            return (b[0] & 0xfe) != 0xfc;
        }
        return false;
    }

    @Override public void onCreate() {
        super.onCreate();
        createNotificationChannel();
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? null : intent.getAction();
        if (ACTION_STOP.equals(action)) {
            stopTunnel();
            stopForeground(true);
            stopSelf(startId);
            return START_NOT_STICKY;
        }

        if (ACTION_START.equals(action)) {
            lastError = "";
            try {
                if (Build.VERSION.SDK_INT >= 34) {
                    startForeground(
                        NOTIFICATION_ID,
                        buildNotification(),
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_SYSTEM_EXEMPTED);
                } else {
                    startForeground(NOTIFICATION_ID, buildNotification());
                }
            } catch (RuntimeException foregroundError) {
                lastError = "Android 拒绝启动 VPN 前台服务：" + foregroundError.getClass().getSimpleName();
                Log.e(TAG, lastError, foregroundError);
                stopSelf(startId);
                return START_NOT_STICKY;
            }
            String host = intent.getStringExtra("worker_host");
            String secret = intent.getStringExtra("socks_secret");
            if (startThread == null || !startThread.isAlive()) {
                startThread = new Thread(() -> startTunnel(host, secret, intent.getStringExtra("worker_ips")), "EffectCraft-VPN-start");
                startThread.start();
            }
        }
        return START_NOT_STICKY;
    }

    private void startTunnel(String host, String secret, String ipCsv) {
        try {
            if (!isAllowedHost(host) || secret == null || secret.length() != 64) {
                throw new IllegalArgumentException("VPN task configuration is invalid");
            }

            String[] addresses = ipCsv == null ? new String[0] : ipCsv.split(",");
            Builder builder = new Builder()
                .setSession("EffectCraft account task")
                .setMtu(1400)
                .addAddress("198.18.0.1", 15)
                .addAddress("fd00:ec:1::1", 64)
                .addAllowedApplication("com.artcraft.effectcraft");

            boolean hasV4 = false;
            boolean hasV6 = false;
            for (String value : addresses) {
                InetAddress address = InetAddress.getByName(value);
                if (address instanceof Inet4Address) {
                    builder.addRoute(value, 32);
                    hasV4 = true;
                } else if (address instanceof Inet6Address) {
                    builder.addRoute(value, 128);
                    hasV6 = true;
                }
            }
            if (!hasV4 && !hasV6) throw new IllegalStateException("No Worker route could be installed");

            ParcelFileDescriptor established = builder.establish();
            if (established == null) throw new IllegalStateException("Android did not create the VPN interface");
            tunInterface = established;

            taskSecret = secret;
            configFile = new File(getFilesDir(), "effectcraft-account-vpn.yml");
            String yaml =
                "tunnel:\n" +
                "  name: tun0\n" +
                "  mtu: 1400\n" +
                "  ipv4: 198.18.0.1\n" +
                "  ipv6: 'fd00:ec:1::1'\n" +
                "  icmp: 'off'\n" +
                "socks5:\n" +
                "  address: 127.0.0.1\n" +
                "  port: 10808\n" +
                "  udp: 'tcp'\n" +
                "  username: effectcraft\n" +
                "  password: '" + secret + "'\n" +
                "misc:\n" +
                "  log-level: error\n" +
                "  connect-timeout: 8000\n" +
                "  tcp-read-write-timeout: 30000\n";
            try (FileOutputStream output = new FileOutputStream(configFile, false)) {
                output.write(yaml.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                output.getFD().sync();
            }

            if (!TProxyService.TProxyStartService(configFile.getAbsolutePath(), tunInterface.getFd())) {
                throw new IllegalStateException("Hev tun2socks engine failed to start");
            }
            taskActive = true;
            Log.i(TAG, "Task-scoped Worker-only VPN is active");
        } catch (Throwable error) {
            lastError = error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage();
            Log.e(TAG, "Account VPN startup failed", error);
            stopTunnel();
            stopForeground(true);
            stopSelf();
        }
    }

    private void stopTunnel() {
        taskActive = false;
        try {
            if (TProxyService.TProxyIsRunning()) TProxyService.TProxyStopService();
        } catch (Throwable error) {
            Log.w(TAG, "Hev tunnel stop reported an error", error);
        }
        try {
            if (tunInterface != null) tunInterface.close();
        } catch (Exception ignored) {
        }
        tunInterface = null;
        taskSecret = null;
        if (configFile != null && configFile.exists()) {
            // Best-effort overwrite before deletion; the secret is task-scoped.
            try (FileOutputStream output = new FileOutputStream(configFile, false)) {
                output.write(new byte[128]);
            } catch (Exception ignored) {
            }
            //noinspection ResultOfMethodCallIgnored
            configFile.delete();
        }
        configFile = null;
    }

    @Override public void onRevoke() {
        stopTunnel();
        stopForeground(true);
        stopSelf();
    }

    @Override public void onDestroy() {
        stopTunnel();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) {
        return super.onBind(intent);
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "EffectCraft account network", NotificationManager.IMPORTANCE_LOW);
            channel.setDescription("Short-lived account connection while registering, signing in, or synchronizing account status");
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification() {
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
            ? new Notification.Builder(this, CHANNEL_ID)
            : new Notification.Builder(this);
        return builder
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("EffectCraft 账号网络")
            .setContentText("正在完成一次账号网络任务")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build();
    }
}
