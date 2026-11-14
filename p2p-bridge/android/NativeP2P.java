package com.artcraft.effectcraft;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.net.wifi.WifiManager;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.lang.ref.WeakReference;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;

/** Starts the same encrypted libp2p node used by the administrator app. */
final class NativeP2P {
    private static final String TAG = "EffectCraftP2P";
    private static WifiManager.MulticastLock multicastLock;
    private static final Handler watchdogHandler = new Handler(Looper.getMainLooper());
    private static volatile Context applicationContext;
    private static boolean watchdogScheduled;
    private static boolean vpnCommandServerStarted;
    private static volatile WeakReference<Activity> launcherActivity = new WeakReference<>(null);

    private static final Runnable nodeWatchdog = new Runnable() {
        @Override public void run() {
            Context context = applicationContext;
            if (context != null) {
                try {
                    String snapshot = nativeStatus();
                    boolean stopped = snapshot == null
                        || snapshot.contains("\"started\":false")
                        || snapshot.contains("\"status\":\"transport_error\"")
                        || snapshot.contains("\"status\":\"runtime_error\"")
                        || snapshot.contains("\"status\":\"thread_error\"")
                        || snapshot.contains("\"status\":\"rpc_proxy_error\"")
                        || snapshot.contains("\"status\":\"command_channel_closed\"");
                    if (stopped) {
                        String result = nativeStartClient(context.getFilesDir().getAbsolutePath());
                        Log.w(TAG, "P2P automatic recovery: " + result + " · previous status: " + snapshot);
                    }
                } catch (Throwable error) {
                    Log.e(TAG, "P2P watchdog recovery failed", error);
                }
            }
            watchdogHandler.postDelayed(this, 8000L);
        }
    };

    static {
        System.loadLibrary("effectcraft_p2p");
    }

    private NativeP2P() {}

    private static native String nativeStartClient(String filesDirectory);
    private static native String nativeStatus();
    private static native String nativeConfigureVpnProxy(String workerHost, String workerIpsCsv, String secret);
    private static native void nativeClearVpnProxyConfig();

    static synchronized void start(Context context) {
        applicationContext = context.getApplicationContext();
        if (context instanceof Activity) launcherActivity = new WeakReference<>((Activity) context);
        try {
            WifiManager wifi = (WifiManager) context.getApplicationContext()
                .getSystemService(Context.WIFI_SERVICE);
            if (wifi != null && (multicastLock == null || !multicastLock.isHeld())) {
                multicastLock = wifi.createMulticastLock("EffectCraft-P2P-mDNS");
                multicastLock.setReferenceCounted(false);
                multicastLock.acquire();
            }

            String result = nativeStartClient(context.getFilesDir().getAbsolutePath());
            Log.i(TAG, "P2P node start: " + result);
            startVpnCommandServer(context.getApplicationContext());
            if (!watchdogScheduled) {
                watchdogScheduled = true;
                watchdogHandler.postDelayed(nodeWatchdog, 8000L);
            }
        } catch (Throwable error) {
            // Network setup must never prevent the editor itself from launching.
            Log.e(TAG, "P2P node unavailable; local editing remains available", error);
        }
    }

    static void clearVpnProxyConfig() {
        try {
            nativeClearVpnProxyConfig();
        } catch (Throwable error) {
            Log.w(TAG, "Could not clear the temporary VPN credentials", error);
        }
    }

    static void launchVpnPermission(Intent permission, int requestCode) {
        Activity activity = launcherActivity.get();
        if (activity != null && !activity.isFinishing()) {
            activity.runOnUiThread(() -> {
                try {
                    if (!activity.isFinishing()) activity.startActivityForResult(permission, requestCode);
                } catch (Throwable error) {
                    Log.e(TAG, "Could not show Android VPN permission dialog", error);
                    EffectCraftVpnService.onPermissionResult(false);
                }
            });
            return;
        }
        Context context = applicationContext;
        if (context != null) {
            try {
                permission.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(permission);
            } catch (Throwable error) {
                Log.e(TAG, "Could not launch Android VPN permission dialog", error);
                EffectCraftVpnService.onPermissionResult(false);
            }
        } else {
            EffectCraftVpnService.onPermissionResult(false);
        }
    }

    static void onVpnPermissionActivityResult(int resultCode) {
        EffectCraftVpnService.onPermissionResult(resultCode == Activity.RESULT_OK);
    }

    static String configureVpnProxy(String workerHost, String workerIpsCsv, String secret) {
        try {
            return nativeConfigureVpnProxy(workerHost, workerIpsCsv, secret);
        } catch (Throwable error) {
            Log.e(TAG, "Could not configure the private account VPN bridge", error);
            return "ERROR:" + error.getClass().getSimpleName();
        }
    }

    static String status() {
        try {
            return nativeStatus();
        } catch (Throwable error) {
            return "{\"started\":false,\"status\":\"unavailable\"}";
        }
    }

    private static synchronized void startVpnCommandServer(Context context) {
        if (vpnCommandServerStarted) return;
        vpnCommandServerStarted = true;
        Thread serverThread = new Thread(() -> {
            while (true) {
                try (ServerSocket server = new ServerSocket(10809, 8, InetAddress.getByName("127.0.0.1"))) {
                    Log.i(TAG, "Local VPN task command bridge listening");
                    while (true) {
                        try (Socket client = server.accept()) {
                            client.setSoTimeout(90000);
                            BufferedReader reader = new BufferedReader(
                                new InputStreamReader(client.getInputStream(), StandardCharsets.UTF_8));
                            PrintWriter writer = new PrintWriter(
                                new OutputStreamWriter(client.getOutputStream(), StandardCharsets.UTF_8), true);
                            String command = reader.readLine();
                            String response;
                            if (command != null && command.startsWith("START ")) {
                                response = EffectCraftVpnService.startForTask(context, command.substring(6).trim());
                            } else if ("STOP".equals(command)) {
                                response = EffectCraftVpnService.stopForTask(context);
                            } else {
                                response = "ERROR:未知的 VPN 任务命令";
                            }
                            writer.println(response);
                        } catch (Throwable error) {
                            Log.w(TAG, "VPN task command failed", error);
                        }
                    }
                } catch (Throwable error) {
                    Log.e(TAG, "VPN command bridge listener failed; retrying", error);
                    try { Thread.sleep(2000L); } catch (InterruptedException interrupted) {
                        Thread.currentThread().interrupt();
                        return;
                    }
                }
            }
        }, "EffectCraft-VPN-command");
        serverThread.setDaemon(true);
        serverThread.start();
    }
}
