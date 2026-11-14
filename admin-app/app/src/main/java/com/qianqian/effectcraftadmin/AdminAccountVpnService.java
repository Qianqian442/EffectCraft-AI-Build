package com.qianqian.effectcraftadmin;

import android.app.Activity;
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

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.ref.WeakReference;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import hev.htproxy.TProxyService;

/**
 * Task-scoped VPN for the standalone administrator app.
 * Only this APK's Worker IP traffic is routed into TUN. The local SOCKS
 * bridge can exit directly or through one selected public CONNECT/SOCKS5
 * transport candidate. Its upstream socket is protected from VPN recursion.
 */
public final class AdminAccountVpnService extends VpnService {
    private static final String TAG = "EffectCraftAdminVPN";
    private static final String ACTION_START = "com.qianqian.effectcraftadmin.vpn.START";
    private static final String ACTION_STOP = "com.qianqian.effectcraftadmin.vpn.STOP";
    private static final String CHANNEL_ID = "effectcraft_admin_account_vpn";
    private static final int NOTIFICATION_ID = 8411;
    static final int PERMISSION_REQUEST_CODE = 8412;
    private static final String LOCAL_SOCKS_HOST = "127.0.0.1";
    private static final int LOCAL_SOCKS_PORT = 10808;

    private static volatile WeakReference<Activity> activityRef = new WeakReference<>(null);
    private static volatile CountDownLatch permissionLatch;
    private static volatile boolean permissionGranted;
    private static volatile boolean taskActive;
    private static volatile String lastError = "";

    private ParcelFileDescriptor tunInterface;
    private File configFile;
    private ServerSocket socksServer;
    private Thread acceptThread;
    private final List<Socket> activeSockets = new java.util.concurrent.CopyOnWriteArrayList<>();
    private volatile String workerHost = "";
    private volatile String workerIps = "";
    private volatile String socksSecret = "";
    private volatile String upstreamType = "direct";
    private volatile String upstreamHost = "";
    private volatile int upstreamPort = 0;

    public static void attachActivity(Activity activity) {
        activityRef = new WeakReference<>(activity);
    }

    public static void onPermissionResult(int resultCode) {
        permissionGranted = resultCode == Activity.RESULT_OK;
        CountDownLatch latch = permissionLatch;
        if (latch != null) latch.countDown();
    }

    private static boolean ensurePermission(Context context) {
        Intent prepare = VpnService.prepare(context);
        if (prepare == null) return true;

        Activity activity = activityRef.get();
        if (activity == null || activity.isFinishing()) return false;

        CountDownLatch latch = new CountDownLatch(1);
        permissionGranted = false;
        permissionLatch = latch;
        activity.runOnUiThread(() -> {
            try {
                if (!activity.isFinishing()) {
                    activity.startActivityForResult(prepare, PERMISSION_REQUEST_CODE);
                } else {
                    onPermissionResult(Activity.RESULT_CANCELED);
                }
            } catch (Throwable error) {
                Log.e(TAG, "Could not show Android VPN permission dialog", error);
                onPermissionResult(Activity.RESULT_CANCELED);
            }
        });

        try {
            return latch.await(75, TimeUnit.SECONDS)
                && permissionGranted
                && VpnService.prepare(context) == null;
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            return false;
        } finally {
            if (permissionLatch == latch) permissionLatch = null;
        }
    }

    public static String startForTask(
        Context context,
        String host,
        String workerIpCsv,
        String routeType,
        String routeHost,
        int routePort
    ) {
        if (!isAllowedHost(host)) return "ERROR:账号 VPN 只接受配置的 workers.dev 主机";
        if (taskActive) return "OK";
        if (!ensurePermission(context)) return "VPN_PERMISSION_REQUIRED";

        String type = routeType == null ? "direct" : routeType.toLowerCase(Locale.ROOT);
        if (!"direct".equals(type) && !"http".equals(type) && !"socks5".equals(type)) {
            return "ERROR:VPN 出口类型不受支持";
        }
        if (!"direct".equals(type) && (!isPublicIpv4Literal(routeHost) || routePort < 1 || routePort > 65535)) {
            return "ERROR:VPN 代理出口地址无效";
        }

        try {
            List<String> ips = validateWorkerIps(workerIpCsv);
            if (ips.isEmpty()) return "ERROR:Worker 没有可用的公网 IPv4 地址";
            byte[] random = new byte[32];
            new SecureRandom().nextBytes(random);
            StringBuilder secret = new StringBuilder(64);
            for (byte value : random) secret.append(String.format(Locale.ROOT, "%02x", value & 0xff));

            Intent intent = new Intent(context, AdminAccountVpnService.class)
                .setAction(ACTION_START)
                .putExtra("worker_host", host)
                .putExtra("worker_ips", String.join(",", ips))
                .putExtra("socks_secret", secret.toString())
                .putExtra("upstream_type", type)
                .putExtra("upstream_host", routeHost == null ? "" : routeHost)
                .putExtra("upstream_port", routePort);
            lastError = "";
            Context app = context.getApplicationContext();
            if (Build.VERSION.SDK_INT >= 26) app.startForegroundService(intent);
            else app.startService(intent);

            long deadline = System.currentTimeMillis() + 15000L;
            while (System.currentTimeMillis() < deadline) {
                if (taskActive) return "OK";
                if (!lastError.isEmpty()) return "ERROR:" + lastError;
                Thread.sleep(100L);
            }
            return "ERROR:管理版 VPN 隧道启动超时";
        } catch (Throwable error) {
            Log.e(TAG, "Admin VPN startup request failed", error);
            return "ERROR:" + (error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage());
        }
    }

    public static String stopForTask(Context context) {
        try {
            Context app = context.getApplicationContext();
            Intent stop = new Intent(app, AdminAccountVpnService.class).setAction(ACTION_STOP);
            app.startService(stop);
            long deadline = System.currentTimeMillis() + 8000L;
            while (System.currentTimeMillis() < deadline) {
                if (!taskActive) return "OK";
                Thread.sleep(80L);
            }
            return "ERROR:管理版 VPN 关闭确认超时";
        } catch (Throwable error) {
            return "ERROR:" + error.getClass().getSimpleName();
        }
    }

    private static boolean isAllowedHost(String host) {
        if (host == null || host.length() < 13 || host.length() > 253) return false;
        String value = host.toLowerCase(Locale.ROOT);
        if (!value.endsWith(".workers.dev") || value.startsWith(".") || value.endsWith(".") || value.contains("..")) return false;
        for (String label : value.split("\\.")) {
            if (label.isEmpty() || label.length() > 63 || label.startsWith("-") || label.endsWith("-")) return false;
            for (int i = 0; i < label.length(); i++) {
                char ch = label.charAt(i);
                if (!((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '-')) return false;
            }
        }
        return true;
    }

    private static List<String> validateWorkerIps(String csv) throws Exception {
        ArrayList<String> result = new ArrayList<>();
        if (csv == null) return result;
        for (String item : csv.split(",")) {
            String value = item.trim();
            if (value.isEmpty()) continue;
            InetAddress address = InetAddress.getByName(value);
            if (!(address instanceof Inet4Address) || address.isAnyLocalAddress()
                || address.isLoopbackAddress() || address.isLinkLocalAddress()
                || address.isSiteLocalAddress() || address.isMulticastAddress()) continue;
            String canonical = address.getHostAddress();
            if (!result.contains(canonical)) result.add(canonical);
            if (result.size() >= 16) break;
        }
        return result;
    }

    private static boolean isPublicIpv4Literal(String value) {
        try {
            InetAddress address = InetAddress.getByName(value);
            return address instanceof Inet4Address && !address.isAnyLocalAddress()
                && !address.isLoopbackAddress() && !address.isLinkLocalAddress()
                && !address.isSiteLocalAddress() && !address.isMulticastAddress();
        } catch (Exception ignored) {
            return false;
        }
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
            try {
                if (Build.VERSION.SDK_INT >= 34) {
                    startForeground(
                        NOTIFICATION_ID,
                        buildNotification(),
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_SYSTEM_EXEMPTED);
                } else {
                    startForeground(NOTIFICATION_ID, buildNotification());
                }
            } catch (Throwable error) {
                lastError = "Android 未允许启动 VPN 前台服务：" + error.getClass().getSimpleName();
                Log.e(TAG, lastError, error);
                stopSelf(startId);
                return START_NOT_STICKY;
            }
            workerHost = intent.getStringExtra("worker_host");
            workerIps = intent.getStringExtra("worker_ips");
            socksSecret = intent.getStringExtra("socks_secret");
            upstreamType = intent.getStringExtra("upstream_type");
            upstreamHost = intent.getStringExtra("upstream_host");
            upstreamPort = intent.getIntExtra("upstream_port", 0);
            lastError = "";
            new Thread(this::startTunnel, "EffectCraft-Admin-VPN-start").start();
        }
        return START_NOT_STICKY;
    }

    private void startTunnel() {
        try {
            if (!isAllowedHost(workerHost) || socksSecret.length() != 64) {
                throw new IllegalArgumentException("VPN 任务配置无效");
            }
            List<String> ips = validateWorkerIps(workerIps);
            if (ips.isEmpty()) throw new IllegalStateException("没有可安装的 Worker IPv4 路由");

            Builder builder = new Builder()
                .setSession("EffectCraft admin account task")
                .setMtu(1400)
                .addAddress("198.18.0.1", 15)
                .addAllowedApplication("com.qianqian.effectcraftadmin");

            for (String ip : ips) builder.addRoute(ip, 32);
            ParcelFileDescriptor tun = builder.establish();
            if (tun == null) throw new IllegalStateException("Android 未能建立管理版 VPN TUN 接口");
            tunInterface = tun;

            configFile = new File(getFilesDir(), "effectcraft-admin-account-vpn.yml");
            String yaml =
                "tunnel:\n" +
                "  name: tun0\n" +
                "  mtu: 1400\n" +
                "  ipv4: 198.18.0.1\n" +
                "  icmp: 'off'\n" +
                "socks5:\n" +
                "  address: " + LOCAL_SOCKS_HOST + "\n" +
                "  port: " + LOCAL_SOCKS_PORT + "\n" +
                "  udp: 'tcp'\n" +
                "  username: effectcraft\n" +
                "  password: '" + socksSecret + "'\n" +
                "misc:\n" +
                "  log-level: error\n" +
                "  connect-timeout: 8000\n" +
                "  tcp-read-write-timeout: 30000\n";
            try (FileOutputStream output = new FileOutputStream(configFile, false)) {
                output.write(yaml.getBytes(StandardCharsets.UTF_8));
                output.getFD().sync();
            }

            socksServer = new ServerSocket();
            socksServer.setReuseAddress(true);
            socksServer.bind(new InetSocketAddress(LOCAL_SOCKS_HOST, LOCAL_SOCKS_PORT), 8);
            startSocksAcceptLoop();

            if (!TProxyService.TProxyStartService(configFile.getAbsolutePath(), tunInterface.getFd())) {
                throw new IllegalStateException("Hev tun2socks 引擎启动失败");
            }
            taskActive = true;
            Log.i(TAG, "Task-scoped admin VPN is active");
        } catch (Throwable error) {
            lastError = error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage();
            Log.e(TAG, "Admin VPN startup failed", error);
            stopTunnel();
            stopForeground(true);
            stopSelf();
        }
    }

    private void startSocksAcceptLoop() {
        acceptThread = new Thread(() -> {
            while (socksServer != null && !socksServer.isClosed()) {
                try {
                    Socket client = socksServer.accept();
                    if (!client.getInetAddress().isLoopbackAddress()) {
                        client.close();
                        continue;
                    }
                    activeSockets.add(client);
                    Thread worker = new Thread(() -> {
                        try (Socket accepted = client) {
                            handleSocksClient(accepted);
                        } catch (Throwable error) {
                            Log.d(TAG, "SOCKS client closed: " + error.getMessage());
                        } finally {
                            activeSockets.remove(client);
                        }
                    }, "EffectCraft-Admin-VPN-socks");
                    worker.start();
                } catch (Exception error) {
                    if (socksServer != null && !socksServer.isClosed()) {
                        Log.w(TAG, "Local SOCKS accept failed", error);
                    }
                    break;
                }
            }
        }, "EffectCraft-Admin-VPN-listener");
        acceptThread.setDaemon(true);
        acceptThread.start();
    }

    private void handleSocksClient(Socket client) throws Exception {
        client.setSoTimeout(30000);
        InputStream in = new BufferedInputStream(client.getInputStream());
        OutputStream out = new BufferedOutputStream(client.getOutputStream());
        int version = readU8(in);
        int methodCount = readU8(in);
        if (version != 5 || methodCount < 1 || methodCount > 16) throw new java.io.IOException("SOCKS greeting invalid");
        byte[] methods = readBytes(in, methodCount);
        boolean hasPasswordAuth = false;
        for (byte method : methods) if ((method & 255) == 2) hasPasswordAuth = true;
        if (!hasPasswordAuth) {
            out.write(new byte[] {5, (byte) 0xff}); out.flush();
            throw new java.io.IOException("SOCKS password auth required");
        }
        out.write(new byte[] {5, 2}); out.flush();

        int authVersion = readU8(in);
        int userLength = readU8(in);
        String user = new String(readBytes(in, userLength), StandardCharsets.UTF_8);
        int passLength = readU8(in);
        String password = new String(readBytes(in, passLength), StandardCharsets.UTF_8);
        boolean valid = authVersion == 1 && "effectcraft".equals(user) && constantTimeEquals(password, socksSecret);
        out.write(new byte[] {1, (byte) (valid ? 0 : 1)}); out.flush();
        if (!valid) throw new java.io.IOException("SOCKS authentication failed");

        int requestVersion = readU8(in);
        int command = readU8(in);
        int reserved = readU8(in);
        int addressType = readU8(in);
        if (requestVersion != 5 || command != 1 || reserved != 0) {
            socksReply(out, 7); throw new java.io.IOException("Only SOCKS5 CONNECT is supported");
        }

        String requestedHost;
        String requestedIp = null;
        if (addressType == 1) {
            requestedIp = InetAddress.getByAddress(readBytes(in, 4)).getHostAddress();
            requestedHost = workerHost;
        } else if (addressType == 4) {
            requestedIp = InetAddress.getByAddress(readBytes(in, 16)).getHostAddress();
            requestedHost = workerHost;
        } else if (addressType == 3) {
            int length = readU8(in);
            requestedHost = new String(readBytes(in, length), StandardCharsets.US_ASCII);
        } else {
            socksReply(out, 8); throw new java.io.IOException("SOCKS address type unsupported");
        }
        int port = readU16(in);
        if (!workerHost.equalsIgnoreCase(requestedHost) && !workerHost.equalsIgnoreCase(InetAddress.getByName(requestedHost).getHostName())) {
            if (addressType == 3) {
                socksReply(out, 2);
                throw new java.io.IOException("SOCKS host outside Worker allowlist");
            }
        }
        if (port != 443) {
            socksReply(out, 2);
            throw new java.io.IOException("Only Worker TCP/443 is allowed");
        }
        List<String> ips = validateWorkerIps(workerIps);
        if (requestedIp != null && !ips.contains(requestedIp)) {
            socksReply(out, 2);
            throw new java.io.IOException("SOCKS IP outside Worker route list");
        }

        Socket upstream = new Socket();
        activeSockets.add(upstream);
        if (!protect(upstream)) throw new java.io.IOException("Cannot protect VPN upstream socket");
        upstream.connect(new InetSocketAddress("direct".equals(upstreamType) ? (requestedIp == null ? ips.get(0) : requestedIp) : upstreamHost,
            "direct".equals(upstreamType) ? 443 : upstreamPort), 8000);
        upstream.setSoTimeout(30000);

        if ("http".equals(upstreamType)) {
            OutputStream proxyOut = upstream.getOutputStream();
            String connect = "CONNECT " + workerHost + ":443 HTTP/1.1\r\n"
                + "Host: " + workerHost + ":443\r\n"
                + "Proxy-Connection: keep-alive\r\n\r\n";
            proxyOut.write(connect.getBytes(StandardCharsets.US_ASCII));
            proxyOut.flush();
            String status = readAsciiLine(upstream.getInputStream(), 4096);
            if (status == null || !(status.startsWith("HTTP/1.0 200") || status.startsWith("HTTP/1.1 200"))) {
                socksReply(out, 5);
                throw new java.io.IOException("Upstream HTTP CONNECT was rejected");
            }
            String line;
            int total = status.length();
            while ((line = readAsciiLine(upstream.getInputStream(), 4096)) != null && !line.isEmpty()) {
                total += line.length();
                if (total > 16384) throw new java.io.IOException("Proxy response headers too large");
            }
            if (line == null) throw new java.io.IOException("Proxy CONNECT response incomplete");
        } else if ("socks5".equals(upstreamType)) {
            InputStream proxyIn = upstream.getInputStream();
            OutputStream proxyOut = upstream.getOutputStream();
            proxyOut.write(new byte[] {5, 1, 0});
            proxyOut.flush();
            if (readU8(proxyIn) != 5 || readU8(proxyIn) != 0) throw new java.io.IOException("Upstream SOCKS5 auth mode rejected");
            byte[] host = workerHost.getBytes(StandardCharsets.US_ASCII);
            proxyOut.write(new byte[] {5, 1, 0, 3, (byte) host.length});
            proxyOut.write(host);
            proxyOut.write(new byte[] {1, (byte) 0xbb});
            proxyOut.flush();
            int v = readU8(proxyIn), reply = readU8(proxyIn);
            readU8(proxyIn);
            int atyp = readU8(proxyIn);
            if (v != 5 || reply != 0) throw new java.io.IOException("Upstream SOCKS5 CONNECT rejected");
            if (atyp == 1) readBytes(proxyIn, 4);
            else if (atyp == 4) readBytes(proxyIn, 16);
            else if (atyp == 3) readBytes(proxyIn, readU8(proxyIn));
            else throw new java.io.IOException("Upstream SOCKS5 response address invalid");
            readBytes(proxyIn, 2);
        } else if (!"direct".equals(upstreamType)) {
            throw new java.io.IOException("Unsupported VPN upstream type");
        }

        socksReply(out, 0);
        relay(client, upstream);
        activeSockets.remove(upstream);
        upstream.close();
    }

    private static void relay(Socket client, Socket upstream) throws Exception {
        Thread upload = new Thread(() -> copy(client, upstream), "EffectCraft-Admin-VPN-up");
        Thread download = new Thread(() -> copy(upstream, client), "EffectCraft-Admin-VPN-down");
        upload.start();
        download.start();
        upload.join();
        download.join();
    }

    private static void copy(Socket source, Socket destination) {
        try {
            byte[] buffer = new byte[16 * 1024];
            InputStream in = source.getInputStream();
            OutputStream out = destination.getOutputStream();
            int count;
            while ((count = in.read(buffer)) >= 0) {
                if (count == 0) continue;
                out.write(buffer, 0, count);
                out.flush();
            }
        } catch (Exception ignored) {
        } finally {
            try { destination.shutdownOutput(); } catch (Exception ignored) {}
        }
    }

    private static int readU8(InputStream in) throws Exception {
        int value = in.read();
        if (value < 0) throw new java.io.EOFException("Unexpected SOCKS EOF");
        return value;
    }

    private static int readU16(InputStream in) throws Exception {
        return (readU8(in) << 8) | readU8(in);
    }

    private static byte[] readBytes(InputStream in, int length) throws Exception {
        if (length < 0 || length > 1024) throw new java.io.IOException("Invalid SOCKS field length");
        byte[] out = new byte[length];
        int offset = 0;
        while (offset < length) {
            int count = in.read(out, offset, length - offset);
            if (count < 0) throw new java.io.EOFException("Unexpected SOCKS EOF");
            offset += count;
        }
        return out;
    }

    private static void socksReply(OutputStream out, int code) throws Exception {
        out.write(new byte[] {5, (byte) code, 0, 1, 0, 0, 0, 0, 0, 0});
        out.flush();
    }

    private static String readAsciiLine(InputStream input, int maxBytes) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        while (bytes.size() < maxBytes) {
            int value = input.read();
            if (value < 0) return bytes.size() == 0 ? null : bytes.toString("US-ASCII");
            if (value == '\n') {
                byte[] line = bytes.toByteArray();
                int length = line.length > 0 && line[line.length - 1] == '\r' ? line.length - 1 : line.length;
                return new String(line, 0, length, StandardCharsets.US_ASCII);
            }
            bytes.write(value);
        }
        throw new java.io.IOException("Proxy response line too long");
    }

    private static boolean constantTimeEquals(String left, String right) {
        return MessageDigest.isEqual(
            left.getBytes(StandardCharsets.UTF_8),
            right.getBytes(StandardCharsets.UTF_8));
    }

    private void stopTunnel() {
        taskActive = false;
        try { if (socksServer != null) socksServer.close(); } catch (Exception ignored) {}
        socksServer = null;
        for (Socket socket : activeSockets) {
            try { socket.close(); } catch (Exception ignored) {}
        }
        activeSockets.clear();
        try { if (TProxyService.TProxyIsRunning()) TProxyService.TProxyStopService(); }
        catch (Throwable error) { Log.w(TAG, "tun2socks stop error", error); }
        try { if (tunInterface != null) tunInterface.close(); } catch (Exception ignored) {}
        tunInterface = null;
        socksSecret = "";
        if (configFile != null && configFile.exists()) {
            try (FileOutputStream output = new FileOutputStream(configFile, false)) {
                output.write(new byte[128]);
            } catch (Exception ignored) {}
            //noinspection ResultOfMethodCallIgnored
            configFile.delete();
        }
        configFile = null;
        stopForeground(true);
    }

    @Override public void onRevoke() {
        stopTunnel();
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
                CHANNEL_ID, "EffectCraft admin account VPN", NotificationManager.IMPORTANCE_LOW);
            channel.setDescription("Short-lived tunnel for administrator account operations");
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification() {
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
            ? new Notification.Builder(this, CHANNEL_ID) : new Notification.Builder(this);
        return builder.setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("EffectCraft 管理版 VPN")
            .setContentText("正在处理一次账号管理任务")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build();
    }
}
