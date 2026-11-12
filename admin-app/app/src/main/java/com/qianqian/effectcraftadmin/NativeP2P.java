package com.qianqian.effectcraftadmin;

import android.content.Context;
import android.net.wifi.WifiManager;

final class NativeP2P {
    private static final boolean AVAILABLE;
    private static WifiManager.MulticastLock multicastLock;

    static {
        boolean loaded;
        try {
            System.loadLibrary("effectcraft_p2p");
            loaded = true;
        } catch (UnsatisfiedLinkError | SecurityException error) {
            loaded = false;
        }
        AVAILABLE = loaded;
    }

    private NativeP2P() {}

    private static native String nativeStartAdmin(String filesDirectory);
    private static native String nativeStopAdmin();
    private static native String nativeStatus();

    static synchronized String start(Context context) {
        if (!AVAILABLE) return "ERROR:P2P原生组件未加载";
        try {
            WifiManager wifi = (WifiManager) context.getApplicationContext()
                .getSystemService(Context.WIFI_SERVICE);
            if (wifi != null && (multicastLock == null || !multicastLock.isHeld())) {
                multicastLock = wifi.createMulticastLock("EffectCraft-P2P-mDNS");
                multicastLock.setReferenceCounted(false);
                multicastLock.acquire();
            }
            return nativeStartAdmin(context.getFilesDir().getAbsolutePath());
        } catch (UnsatisfiedLinkError | SecurityException error) {
            return "ERROR:" + error.getMessage();
        }
    }

    static synchronized void stop() {
        if (AVAILABLE) {
            try { nativeStopAdmin(); } catch (Throwable ignored) {}
        }
        if (multicastLock != null && multicastLock.isHeld()) {
            try { multicastLock.release(); } catch (RuntimeException ignored) {}
        }
        multicastLock = null;
    }

    static String status() {
        if (!AVAILABLE) return "{\"started\":false,\"status\":\"native_library_missing\"}";
        try {
            return nativeStatus();
        } catch (UnsatisfiedLinkError error) {
            return "{\"started\":false,\"status\":\"native_status_error\"}";
        }
    }

    static boolean isAvailable() {
        return AVAILABLE;
    }
}
