package com.artcraft.effectcraft;

import android.content.Context;
import android.net.wifi.WifiManager;
import android.util.Log;

/** Starts the same encrypted libp2p node used by the administrator app. */
final class NativeP2P {
    private static final String TAG = "EffectCraftP2P";
    private static WifiManager.MulticastLock multicastLock;

    static {
        System.loadLibrary("effectcraft_p2p");
    }

    private NativeP2P() {}

    private static native String nativeStartClient(String filesDirectory);
    private static native String nativeStatus();

    static synchronized void start(Context context) {
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
