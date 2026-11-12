package com.artcraft.effectcraft;

import android.content.Context;
import android.net.wifi.WifiManager;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

/** Starts the same encrypted libp2p node used by the administrator app. */
final class NativeP2P {
    private static final String TAG = "EffectCraftP2P";
    private static WifiManager.MulticastLock multicastLock;
    private static final Handler watchdogHandler = new Handler(Looper.getMainLooper());
    private static volatile Context applicationContext;
    private static boolean watchdogScheduled;

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

    static synchronized void start(Context context) {
        applicationContext = context.getApplicationContext();
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
            if (!watchdogScheduled) {
                watchdogScheduled = true;
                watchdogHandler.postDelayed(nodeWatchdog, 8000L);
            }
        } catch (Throwable error) {
            // Network setup must never prevent the editor itself from launching.
            Log.e(TAG, "P2P node unavailable; local editing remains available", error);
        }
    }

    static String status() {
        try {
            return nativeStatus();
        } catch (Throwable error) {
            return "{\"started\":false,\"status\":\"unavailable\"}";
        }
    }
}
