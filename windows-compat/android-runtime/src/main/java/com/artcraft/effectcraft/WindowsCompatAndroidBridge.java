package com.artcraft.effectcraft;

import android.content.Context;
import android.util.Log;

import com.effectcraft.windowscompat.RuntimeAssetInstaller;
import com.effectcraft.windowscompat.WinlatorBionicRuntimeManager;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.util.Locale;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Narrow Java/JNI facade for the optional Windows compatibility runtime.
 *
 * Runtime installation is explicitly user-triggered. All files remain inside
 * the app's private files directory; downloads are HTTPS and SHA-256 verified,
 * and the bundled Box64 BOX32 binary is pinned to the CI-produced payload.
 */
public final class WindowsCompatAndroidBridge {
    private static final String TAG = "EffectCraftWinCompat";
    private static final String BOX32_ASSET =
            "windows-compat/box64-box32-android-arm64.tar.zst";
    private static final String BOX32_SHA256 =
            "0bfccfc0693c5ec9efc2c85de651704e9d4c279b27185878af228241a1237ae5";

    private static final ConcurrentHashMap<String, String> INSTALL_STATUS = new ConcurrentHashMap<>();
    private static final ExecutorService INSTALL_EXECUTOR = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "EffectCraft-Windows-Runtime-Install");
        thread.setDaemon(true);
        return thread;
    });

    private static volatile Context applicationContext;
    private static volatile WinlatorBionicRuntimeManager runtimeManager;

    private WindowsCompatAndroidBridge() {}

    public static synchronized void initialize(Context context) {
        if (context == null) return;
        Context app = context.getApplicationContext();
        if (applicationContext == app && runtimeManager != null) return;
        applicationContext = app;
        try {
            Path root = app.getFilesDir().toPath().resolve("windows-compat");
            runtimeManager = new WinlatorBionicRuntimeManager(root, RuntimeAssetInstaller.httpFetcher());
            Log.i(TAG, "Windows compatibility runtime bridge initialized in app-private storage.");
        } catch (IOException error) {
            runtimeManager = null;
            Log.e(TAG, "Could not initialize Windows compatibility runtime manager.", error);
        }
    }

    /** Start once from the UI after the user explicitly chooses to prepare the runtime. */
    public static void startRuntimeInstall(String requestId) {
        if (requestId == null || requestId.trim().isEmpty()) return;
        Context context = applicationContext;
        WinlatorBionicRuntimeManager manager = runtimeManager;
        if (context == null || manager == null) {
            INSTALL_STATUS.put(requestId, "ERROR: Windows 兼容运行环境尚未初始化。");
            return;
        }
        String old = INSTALL_STATUS.get(requestId);
        if ("INSTALLING".equals(old)) return;
        INSTALL_STATUS.put(requestId, "INSTALLING");
        INSTALL_EXECUTOR.execute(() -> installRuntime(context, manager, requestId));
    }

    /** Non-destructive polling API. Returns null until the first status is available. */
    public static String pollRuntimeInstall(String requestId) {
        if (requestId == null) return null;
        return INSTALL_STATUS.get(requestId);
    }

    private static void installRuntime(
            Context context,
            WinlatorBionicRuntimeManager manager,
            String requestId) {
        Path archive = null;
        try {
            INSTALL_STATUS.put(requestId, "正在下载并校验 Windows 兼容基础环境…");
            manager.installAllRuntimeComponents();

            INSTALL_STATUS.put(requestId, "正在安装 Android ARM64 的 32 位 x86 兼容 Box64…");
            archive = context.getCacheDir().toPath().resolve("box64-box32-android-arm64.tar.zst");
            copyBundledAsset(context, BOX32_ASSET, archive);
            manager.installBox64Box32Archive(archive, BOX32_SHA256);

            INSTALL_STATUS.put(requestId, "正在准备 ARM64EC / WoW64 容器与 FEXCore…");
            WinlatorBionicRuntimeManager.Container container = manager.createContainer(
                    "effectcraft-aex-arm64ec",
                    WinlatorBionicRuntimeManager.Architecture.ARM64EC);
            manager.installArm64EcEmulator(
                    container,
                    WinlatorBionicRuntimeManager.WoW64Engine.FEXCORE);

            INSTALL_STATUS.put(requestId,
                    "READY:Windows 兼容运行环境已安装。真实 AEX 插件执行仍需逐项验证。");
            Log.i(TAG, "Windows compatibility base, Box64 BOX32 and FEXCore are prepared.");
        } catch (Exception error) {
            String detail = error.getMessage();
            String message = "ERROR: Windows 兼容环境安装失败："
                    + (detail == null || detail.trim().isEmpty()
                    ? error.getClass().getSimpleName() : detail);
            INSTALL_STATUS.put(requestId, message);
            Log.e(TAG, "Windows compatibility runtime installation failed.", error);
        } finally {
            if (archive != null) {
                try { Files.deleteIfExists(archive); } catch (IOException ignored) {}
            }
        }
    }

    private static void copyBundledAsset(Context context, String assetName, Path destination)
            throws IOException {
        Objects.requireNonNull(context, "context");
        Path parent = destination.getParent();
        if (parent == null) throw new IOException("BOX32 cache path has no parent");
        Files.createDirectories(parent);
        Path temporary = destination.resolveSibling(destination.getFileName() + ".part");
        Files.deleteIfExists(temporary);
        try (InputStream input = context.getAssets().open(assetName);
             OutputStream output = Files.newOutputStream(
                     temporary, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
            byte[] buffer = new byte[64 * 1024];
            int read;
            while ((read = input.read(buffer)) != -1) {
                if (read > 0) output.write(buffer, 0, read);
            }
            output.flush();
        } catch (IOException failure) {
            Files.deleteIfExists(temporary);
            throw new IOException("Could not read bundled BOX32 runtime asset: " + assetName, failure);
        }
        try {
            Files.move(temporary, destination,
                    StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } catch (java.nio.file.AtomicMoveNotSupportedException ignored) {
            Files.move(temporary, destination, StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException failure) {
            Files.deleteIfExists(temporary);
            throw failure;
        }
    }
}
