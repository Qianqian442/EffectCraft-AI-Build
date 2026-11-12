package com.qianqian.effectcraftadmin;

import android.content.Context;

final class NativeP2P {
    private static final boolean AVAILABLE;

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

    private static native String nativeStart(String filesDirectory);
    private static native String nativeStatus();

    static String start(Context context) {
        if (!AVAILABLE) return "ERROR:P2P原生组件未加载";
        try {
            return nativeStart(context.getFilesDir().getAbsolutePath());
        } catch (UnsatisfiedLinkError error) {
            return "ERROR:" + error.getMessage();
        }
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
