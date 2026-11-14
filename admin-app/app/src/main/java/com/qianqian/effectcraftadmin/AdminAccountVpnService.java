package com.qianqian.effectcraftadmin;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.net.VpnService;
import android.os.Build;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.text.Html;
import android.text.method.LinkMovementMethod;
import android.widget.TextView;
import android.util.Base64;
import android.util.Log;

import org.json.JSONObject;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.ref.WeakReference;
import java.net.Inet4Address;
import java.net.Inet6Address;
import java.net.InetAddress;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Main-APK task-scoped Cloudflare WARP / MASQUE VPN.
 *
 * Only this app is allowed into the VPN and only the current Worker IPs are
 * routed into TUN. The MASQUE endpoint addresses are intentionally not added
 * to the TUN routes, preventing tunnel recursion. No admin-phone/P2P egress is
 * used for the Cloudflare account API path.
 */
public final class AdminAccountVpnService extends VpnService {
    private static final String TAG = "EffectCraftAdminWARP";
    private static final String ACTION_START = "com.qianqian.effectcraftadmin.vpn.START";
    private static final String ACTION_STOP = "com.qianqian.effectcraftadmin.vpn.STOP";
    private static final String CHANNEL_ID = "effectcraft_admin_cloudflare_warp";
    private static final int NOTIFICATION_ID = 8401;
    private static final String APP_ID = "com.qianqian.effectcraftadmin";
    private static final String BRIDGE_CLASS = "com.effectcraft.warp.Warpandroid";
    private static final String PREFS = "effectcraft_admin_warp";
    private static final String BUNDLE_KEY = "encrypted_device_bundle";
    private static final String KEY_ALIAS = "effectcraft.admin.cloudflare.warp.device.v1";
    static final int PERMISSION_REQUEST_CODE = 8402;
    private static volatile WeakReference<Activity> attachedActivity = new WeakReference<>(null);

    static void attachActivity(Activity activity) {
        attachedActivity = new WeakReference<>(activity);
    }

    private static void launchVpnPermission(Context context, Intent permission) {
        Activity activity = attachedActivity.get();
        if (activity != null && !activity.isFinishing()) {
            activity.runOnUiThread(() -> {
                try {
                    if (!activity.isFinishing()) {
                        activity.startActivityForResult(permission, PERMISSION_REQUEST_CODE);
                    } else {
                        onPermissionResult(Activity.RESULT_CANCELED);
                    }
                } catch (Throwable error) {
                    Log.e(TAG, "Could not show Android VPN permission dialog", error);
                    onPermissionResult(Activity.RESULT_CANCELED);
                }
            });
            return;
        }
        try {
            permission.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            context.getApplicationContext().startActivity(permission);
        } catch (Throwable error) {
            Log.e(TAG, "Could not launch Android VPN permission dialog", error);
            onPermissionResult(Activity.RESULT_CANCELED);
        }
    }

    private static boolean requestCloudflareTermsConsent(Context context) {
        SharedPreferences prefs = context.getApplicationContext()
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (prefs.getBoolean("cloudflare_terms_accepted", false)) return true;

        Activity activity = attachedActivity.get();
        if (activity == null || activity.isFinishing()) return false;
        CountDownLatch latch = new CountDownLatch(1);
        AtomicBoolean accepted = new AtomicBoolean(false);
        activity.runOnUiThread(() -> {
            try {
                if (activity.isFinishing()) {
                    latch.countDown();
                    return;
                }
                TextView message = new TextView(activity);
                message.setText(Html.fromHtml(
                    "首次启用 Cloudflare WARP 时，会向 Cloudflare 注册本设备的专用隧道身份，并保存加密后的设备密钥。<br><br>" +
                    "继续前请阅读并同意 <a href=\"https://www.cloudflare.com/application/terms/\">Cloudflare 服务条款</a>。<br><br>" +
                    "账号请求将通过管理版内置 VPN 直接连接 Cloudflare；不会接管手机其他应用的网络流量。",
                    Build.VERSION.SDK_INT >= 24 ? Html.FROM_HTML_MODE_LEGACY : 0));
                message.setMovementMethod(LinkMovementMethod.getInstance());
                int padding = (int) (20 * activity.getResources().getDisplayMetrics().density);
                message.setPadding(padding, padding / 2, padding, padding / 2);
                new AlertDialog.Builder(activity)
                    .setTitle("启用 Cloudflare WARP")
                    .setView(message)
                    .setPositiveButton("同意并继续", (dialog, which) -> {
                        prefs.edit().putBoolean("cloudflare_terms_accepted", true).apply();
                        accepted.set(true);
                        latch.countDown();
                    })
                    .setNegativeButton("暂不启用", (dialog, which) -> latch.countDown())
                    .setOnCancelListener(dialog -> latch.countDown())
                    .show();
            } catch (Throwable error) {
                Log.e(TAG, "Could not display Cloudflare terms consent", error);
                latch.countDown();
            }
        });
        try {
            return latch.await(4, TimeUnit.MINUTES) && accepted.get();
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            return false;
        }
    }

    private static volatile CountDownLatch permissionLatch;
    private static volatile boolean permissionGranted;
    private static volatile boolean taskActive;
    private static volatile String lastError = "";

    private ParcelFileDescriptor tunInterface;
    private Thread startThread;
    private static volatile boolean stopping;

    private static Object callWarp(String methodName, Class<?>[] parameterTypes, Object... args) throws Exception {
        try {
            Class<?> bridge = Class.forName(BRIDGE_CLASS);
            Method method = bridge.getMethod(methodName, parameterTypes);
            return method.invoke(null, args);
        } catch (InvocationTargetException error) {
            Throwable cause = error.getCause();
            if (cause instanceof Exception) throw (Exception) cause;
            throw new Exception(cause == null ? error.getMessage() : cause.getMessage(), cause);
        }
    }

    private static String bridgeString(String method) throws Exception {
        Object value = callWarp(method, new Class<?>[0]);
        return value == null ? "" : value.toString();
    }

    private static void bridgeStop() {
        try {
            callWarp("stopTunnel", new Class<?>[0]);
        } catch (Throwable error) {
            Log.w(TAG, "MASQUE stop reported an error", error);
        }
    }

    private static boolean ensurePermission(Context context) {
        Intent prepare = VpnService.prepare(context);
        if (prepare == null) return true;

        CountDownLatch latch = new CountDownLatch(1);
        permissionGranted = false;
        permissionLatch = latch;
        launchVpnPermission(context, prepare);
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

    static void onPermissionResult(int resultCode) {
        permissionGranted = resultCode == Activity.RESULT_OK;
        CountDownLatch latch = permissionLatch;
        if (latch != null) latch.countDown();
    }

    /** Called immediately before one Cloudflare account API operation. */
    public static synchronized String startForTask(Context context, String host) {
        if (!isAllowedHost(host)) return "ERROR:账号 VPN 只允许配置的 workers.dev 账号服务器";
        if (taskActive) return "OK";

        String stage = "读取本机加密的 WARP 设备身份";
        try {
            String bundle = loadEncryptedBundle(context);
            if (bundle == null) {
                stage = "等待 Cloudflare 服务条款确认";
                if (!requestCloudflareTermsConsent(context)) {
                    return "CLOUDFLARE_TERMS_REQUIRED";
                }
                // First-time registration is a direct Cloudflare enrollment call.
                // It creates a per-device MASQUE key; the private key is persisted encrypted.
                stage = "首次向 Cloudflare 注册 WARP 设备并登记 MASQUE 密钥（此步骤需要手机网络能访问 Cloudflare 注册接口）";
                Object registered = callWarp("registerDevice", new Class<?>[0]);
                bundle = registered == null ? "" : registered.toString();
                if (bundle.isEmpty()) return "ERROR:Cloudflare 没有返回 WARP 设备配置";
                saveEncryptedBundle(context, bundle);
            }

            // Android allows only one active VpnService per user/profile.
            // Complete first-time Cloudflare registration over the phone's
            // current network first; only then ask Android to hand the VPN slot
            // from a third-party VPN to EffectCraft's embedded WARP service.
            stage = "申请管理版内置 WARP VPN 权限（Android 可能会切换当前第三方 VPN）";
            if (!ensurePermission(context)) return "VPN_PERMISSION_REQUIRED";

            JSONObject json = new JSONObject(bundle);
            stage = "解析 Cloudflare Worker 账号服务域名";
            List<InetAddress> workers = resolveWorkerAddresses(host);
            if (workers.isEmpty()) return "ERROR:Worker DNS 没有返回可用的公网地址";

            stage = "启动 Android 内置 WARP VPN 服务";
            Intent intent = new Intent(context.getApplicationContext(), AdminAccountVpnService.class)
                .setAction(ACTION_START)
                .putExtra("worker_host", host)
                .putExtra("bundle_json", bundle)
                .putExtra("worker_ips", toCsv(workers));
            lastError = "";
            stopping = false;
            Context app = context.getApplicationContext();
            if (Build.VERSION.SDK_INT >= 26) app.startForegroundService(intent);
            else app.startService(intent);

            long deadline = System.currentTimeMillis() + 50000L;
            while (System.currentTimeMillis() < deadline) {
                if (taskActive) return "OK";
                if (!lastError.isEmpty()) return "ERROR:" + lastError;
                Thread.sleep(150L);
            }
            return "ERROR:Cloudflare WARP 在 50 秒内未能建立 MASQUE 隧道";
        } catch (SecurityException denied) {
            return "VPN_PERMISSION_REQUIRED";
        } catch (Throwable error) {
            Log.e(TAG, "Could not start Cloudflare WARP task during: " + stage, error);
            return "ERROR【" + stage + "】："
                + (error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage());
        }
    }

    /** Stop immediately after the account API request completes or fails. */
    public static synchronized String stopForTask(Context context) {
        try {
            Intent stop = new Intent(context.getApplicationContext(), AdminAccountVpnService.class)
                .setAction(ACTION_STOP);
            context.getApplicationContext().startService(stop);
            long deadline = System.currentTimeMillis() + 9000L;
            while (System.currentTimeMillis() < deadline) {
                if (!taskActive) return "OK";
                Thread.sleep(80L);
            }
            return "ERROR:Cloudflare WARP 关闭确认超时";
        } catch (Throwable error) {
            return "ERROR:" + error.getClass().getSimpleName();
        }
    }

    private static boolean isAllowedHost(String host) {
        return host != null && host.length() > 12 && host.length() <= 253
            && host.toLowerCase(java.util.Locale.ROOT).endsWith(".workers.dev")
            && host.matches("[A-Za-z0-9.-]+")
            && !host.startsWith(".") && !host.endsWith(".") && !host.contains("..");
    }

    private static boolean isPublicAddress(InetAddress address) {
        if (address.isAnyLocalAddress() || address.isLoopbackAddress()
            || address.isLinkLocalAddress() || address.isSiteLocalAddress()
            || address.isMulticastAddress()) return false;
        if (address instanceof Inet4Address) {
            byte[] b = address.getAddress();
            int a = b[0] & 255, second = b[1] & 255;
            return a != 0 && a != 10 && a != 127 && a < 224
                && !(a == 100 && second >= 64 && second <= 127)
                && !(a == 169 && second == 254)
                && !(a == 172 && second >= 16 && second <= 31)
                && !(a == 192 && second == 168)
                && !(a == 192 && second == 0)
                && !(a == 198 && (second == 18 || second == 19 || second == 51))
                && !(a == 203 && second == 0 && (b[2] & 255) == 113);
        }
        if (address instanceof Inet6Address) {
            byte[] b = address.getAddress();
            return (b[0] & 0xfe) != 0xfc;
        }
        return false;
    }

    private static List<InetAddress> resolveWorkerAddresses(String host) throws Exception {
        List<InetAddress> addresses = new ArrayList<>();
        for (InetAddress address : InetAddress.getAllByName(host)) {
            if (isPublicAddress(address) && !addresses.contains(address)) addresses.add(address);
            if (addresses.size() >= 16) break;
        }
        return addresses;
    }

    private static String toCsv(List<InetAddress> addresses) {
        StringBuilder result = new StringBuilder();
        for (InetAddress address : addresses) {
            if (result.length() > 0) result.append(',');
            result.append(address.getHostAddress());
        }
        return result.toString();
    }

    private static void addCidrAddress(Builder builder, String cidr) throws Exception {
        String[] parts = cidr.split("/", 2);
        InetAddress address = InetAddress.getByName(parts[0]);
        int defaultPrefix = address instanceof Inet4Address ? 32 : 128;
        int prefix = parts.length == 2 ? Integer.parseInt(parts[1]) : defaultPrefix;
        if (prefix < 1 || prefix > defaultPrefix) throw new IllegalArgumentException("WARP tunnel address prefix is invalid");
        builder.addAddress(address, prefix);
    }

    private static java.util.Set<String> endpointIpSet(String endpoints) throws Exception {
        java.util.HashSet<String> values = new java.util.HashSet<>();
        for (String raw : endpoints.split(";")) {
            String item = raw.trim();
            int scheme = item.indexOf("://");
            if (scheme <= 0) throw new IllegalArgumentException("MASQUE endpoint scheme is missing");
            String hostPort = item.substring(scheme + 3);
            String host;
            if (hostPort.startsWith("[")) {
                int close = hostPort.indexOf(']');
                if (close <= 1) throw new IllegalArgumentException("MASQUE IPv6 endpoint is invalid");
                host = hostPort.substring(1, close);
                if (close + 1 >= hostPort.length() || hostPort.charAt(close + 1) != ':') {
                    throw new IllegalArgumentException("MASQUE endpoint port is missing");
                }
            } else {
                int colon = hostPort.lastIndexOf(':');
                if (colon <= 0) throw new IllegalArgumentException("MASQUE endpoint port is missing");
                host = hostPort.substring(0, colon);
            }
            InetAddress address = InetAddress.getByName(host);
            if (!isPublicAddress(address)) throw new IllegalArgumentException("MASQUE endpoint is not a public IP");
            values.add(address.getHostAddress());
        }
        if (values.isEmpty()) throw new IllegalArgumentException("Cloudflare supplied no MASQUE endpoint IPs");
        return values;
    }

    private void startTunnel(String host, String bundle, String ipCsv) {
        ParcelFileDescriptor established = null;
        int detachedFd = -1;
        try {
            if (!isAllowedHost(host) || bundle == null || bundle.isEmpty()) {
                throw new IllegalArgumentException("VPN task configuration is invalid");
            }
            JSONObject root = new JSONObject(bundle);
            JSONObject cfg = new JSONObject(root.getString("config_json"));
            String endpointList = root.getString("endpoints");
            if (endpointList.isEmpty() || root.getString("sni").isEmpty()) {
                throw new IllegalArgumentException("Cloudflare MASQUE endpoint configuration is incomplete");
            }

            java.util.Set<String> masqueEndpointIps = endpointIpSet(endpointList);
            Builder builder = new Builder()
                .setSession("EffectCraft Cloudflare WARP account task")
                .setMtu(1280)
                .addAllowedApplication(APP_ID);
            addCidrAddress(builder, cfg.getString("ipv4"));
            String ipv6 = cfg.optString("ipv6", "");
            if (!ipv6.isEmpty()) addCidrAddress(builder, ipv6);

            int routes = 0;
            for (String value : (ipCsv == null ? "" : ipCsv).split(",")) {
                String ipText = value.trim();
                if (ipText.isEmpty()) continue;
                InetAddress ip = InetAddress.getByName(ipText);
                if (!isPublicAddress(ip)) continue;
                if (ip instanceof Inet6Address && ipv6.isEmpty()) continue;
                if (masqueEndpointIps.contains(ip.getHostAddress())) {
                    throw new IllegalStateException("Worker IP overlaps a MASQUE endpoint; refused to create a VPN route loop");
                }
                builder.addRoute(ip, ip instanceof Inet4Address ? 32 : 128);
                routes++;
            }
            if (routes == 0) throw new IllegalStateException("No public Worker routes could be installed");

            established = builder.establish();
            if (established == null) throw new IllegalStateException("Android did not create the VPN TUN interface");
            tunInterface = established;
            detachedFd = established.detachFd();
            tunInterface = null;

            callWarp("startTunnel",
                new Class<?>[]{String.class, long.class, String.class, String.class},
                cfg.toString(), (long) detachedFd, endpointList, root.getString("sni"));
            detachedFd = -1; // Go owns and closes the detached descriptor.

            long deadline = System.currentTimeMillis() + 45000L;
            String tunnelState = "connecting";
            while (System.currentTimeMillis() < deadline && !stopping) {
                tunnelState = bridgeString("state");
                if ("connected".equals(tunnelState)) {
                    taskActive = true;
                    Log.i(TAG, "Cloudflare MASQUE tunnel connected; account API task may proceed");
                    return;
                }
                Thread.sleep(200L);
            }
            String detail = bridgeString("lastError");
            throw new IllegalStateException("Cloudflare MASQUE did not connect (state=" + tunnelState + ")"
                + (detail.isEmpty() ? "" : ": " + detail));
        } catch (Throwable error) {
            lastError = error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage();
            Log.e(TAG, "Cloudflare MASQUE startup failed", error);
            bridgeStop();
            if (detachedFd >= 0) {
                try { ParcelFileDescriptor.adoptFd(detachedFd).close(); } catch (Exception ignored) {}
            }
            if (established != null) {
                try { established.close(); } catch (Exception ignored) {}
            }
            if (tunInterface != null) {
                try { tunInterface.close(); } catch (Exception ignored) {}
                tunInterface = null;
            }
            taskActive = false;
            stopForeground(true);
            stopSelf();
        }
    }

    private static SecretKey getOrCreateEncryptionKey() throws Exception {
        KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
        keyStore.load(null);
        if (keyStore.containsAlias(KEY_ALIAS)) {
            return ((java.security.KeyStore.SecretKeyEntry) keyStore.getEntry(KEY_ALIAS, null)).getSecretKey();
        }
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(
            KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true)
            .setKeySize(256)
            .build());
        return generator.generateKey();
    }

    private static String loadEncryptedBundle(Context context) {
        try {
            SharedPreferences prefs = context.getApplicationContext().getSharedPreferences(PREFS, MODE_PRIVATE);
            String encoded = prefs.getString(BUNDLE_KEY, null);
            if (encoded == null || encoded.isEmpty()) return null;
            byte[] payload = Base64.decode(encoded, Base64.NO_WRAP);
            ByteBuffer buffer = ByteBuffer.wrap(payload);
            int ivLength = buffer.getInt();
            if (ivLength < 12 || ivLength > 16 || ivLength > buffer.remaining()) throw new IllegalStateException("Encrypted WARP data is malformed");
            byte[] iv = new byte[ivLength];
            buffer.get(iv);
            byte[] ciphertext = new byte[buffer.remaining()];
            buffer.get(ciphertext);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, getOrCreateEncryptionKey(), new GCMParameterSpec(128, iv));
            return new String(cipher.doFinal(ciphertext), StandardCharsets.UTF_8);
        } catch (Throwable error) {
            Log.w(TAG, "Stored WARP identity could not be decrypted; a new device registration will be created", error);
            context.getApplicationContext().getSharedPreferences(PREFS, MODE_PRIVATE).edit().remove(BUNDLE_KEY).apply();
            return null;
        }
    }

    private static void saveEncryptedBundle(Context context, String bundle) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateEncryptionKey());
        byte[] iv = cipher.getIV();
        byte[] encrypted = cipher.doFinal(bundle.getBytes(StandardCharsets.UTF_8));
        ByteBuffer payload = ByteBuffer.allocate(4 + iv.length + encrypted.length);
        payload.putInt(iv.length);
        payload.put(iv);
        payload.put(encrypted);
        String encoded = Base64.encodeToString(payload.array(), Base64.NO_WRAP);
        SharedPreferences prefs = context.getApplicationContext().getSharedPreferences(PREFS, MODE_PRIVATE);
        if (!prefs.edit().putString(BUNDLE_KEY, encoded).commit()) {
            throw new IllegalStateException("Encrypted WARP device identity could not be saved");
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
                    startForeground(NOTIFICATION_ID, buildNotification(),
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_SYSTEM_EXEMPTED);
                } else {
                    startForeground(NOTIFICATION_ID, buildNotification());
                }
            } catch (Throwable error) {
                lastError = "Android 拒绝启动 WARP VPN 前台服务：" + error.getClass().getSimpleName();
                Log.e(TAG, lastError, error);
                stopSelf(startId);
                return START_NOT_STICKY;
            }
            String host = intent.getStringExtra("worker_host");
            String bundle = intent.getStringExtra("bundle_json");
            String ips = intent.getStringExtra("worker_ips");
            if (startThread == null || !startThread.isAlive()) {
                startThread = new Thread(() -> startTunnel(host, bundle, ips), "EffectCraft-Cloudflare-WARP");
                startThread.start();
            }
        }
        return START_NOT_STICKY;
    }

    private void stopTunnel() {
        stopping = true;
        bridgeStop();
        taskActive = false;
        if (tunInterface != null) {
            try { tunInterface.close(); } catch (Exception ignored) {}
            tunInterface = null;
        }
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
                CHANNEL_ID, "EffectCraft Cloudflare WARP", NotificationManager.IMPORTANCE_LOW);
            channel.setDescription("短时连接 Cloudflare WARP，仅在账号请求期间启用");
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
            .setContentTitle("EffectCraft Cloudflare WARP")
            .setContentText("正在建立账号专用加密隧道")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build();
    }
}
