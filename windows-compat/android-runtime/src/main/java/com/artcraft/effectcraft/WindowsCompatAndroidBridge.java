package com.artcraft.effectcraft;

import android.content.Context;
import android.util.Log;

import com.effectcraft.windowscompat.RuntimeAssetInstaller;
import com.effectcraft.windowscompat.WinlatorBionicRuntimeManager;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;
import java.util.UUID;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
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
    private static final String AEX_HOST_X64_ASSET = "windows-compat/aex-host-x64.exe";
    private static final String AEX_HOST_X64_SHA256 = "ed8875e9346f117cb4f61a766dd271a746fecab2db315e6e9fd753b90101511f";
    private static final String AEX_HOST_X86_ASSET = "windows-compat/aex-host-x86.exe";
    private static final String AEX_HOST_X86_SHA256 = "d067d8e9e7cf02ab11026dde0b8d6ca5975ecf04cc9e634dac4d0dcf261a1131";

    private static final ConcurrentHashMap<String, String> INSTALL_STATUS = new ConcurrentHashMap<>();
    private static final java.util.Set<String> ACTIVE_REQUESTS = ConcurrentHashMap.newKeySet();
    private static final ExecutorService INSTALL_EXECUTOR = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "EffectCraft-Windows-Runtime-Install");
        thread.setDaemon(true);
        return thread;
    });

    private static volatile Context applicationContext;
    private static volatile WinlatorBionicRuntimeManager runtimeManager;
    private static volatile WinlatorBionicRuntimeManager.Container arm64EcContainer;

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
        if (!ACTIVE_REQUESTS.add(requestId)) return;
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

            arm64EcContainer = container;
            INSTALL_STATUS.put(requestId, "正在校验并安装 Windows x64 / x86 AEX 宿主…");
            Path hostDirectory = context.getFilesDir().toPath().resolve("windows-compat/hosts");
            installVerifiedPeHost(context, AEX_HOST_X64_ASSET, AEX_HOST_X64_SHA256,
                    hostDirectory.resolve("effectcraft-aex-host-x64.exe"), 0x8664);
            installVerifiedPeHost(context, AEX_HOST_X86_ASSET, AEX_HOST_X86_SHA256,
                    hostDirectory.resolve("effectcraft-aex-host-x86.exe"), 0x014c);

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
            ACTIVE_REQUESTS.remove(requestId);
        }
    }

    /** Starts a user-requested, isolated test of the first AEX found in a file or ZIP. */
    public static void startAexPluginTest(String requestId, String sourcePath) {
        if (requestId == null || requestId.trim().isEmpty()
                || sourcePath == null || sourcePath.trim().isEmpty()) return;
        Context context = applicationContext;
        WinlatorBionicRuntimeManager manager = runtimeManager;
        WinlatorBionicRuntimeManager.Container container = arm64EcContainer;
        if (context == null || manager == null || container == null) {
            INSTALL_STATUS.put(requestId, "ERROR: 请先安装 Windows 兼容运行环境。");
            return;
        }
        if (!ACTIVE_REQUESTS.add(requestId)) return;
        INSTALL_STATUS.put(requestId, "RUNNING: 正在提取并检查 AEX 插件…");
        INSTALL_EXECUTOR.execute(() -> runAexPluginTest(
                context, manager, container, requestId, sourcePath));
    }

    private static void runAexPluginTest(
            Context context,
            WinlatorBionicRuntimeManager manager,
            WinlatorBionicRuntimeManager.Container container,
            String requestId,
            String sourcePath) {
        Path plugin = null;
        try {
            Path root = context.getFilesDir().toPath().resolve("windows-compat");
            Path pluginDirectory = root.resolve("plugins").resolve(UUID.randomUUID().toString());
            Files.createDirectories(pluginDirectory);
            plugin = extractFirstAex(Paths.get(sourcePath), pluginDirectory);
            int machine = readPeMachine(plugin);
            Path hostDirectory = root.resolve("hosts");
            Path host;
            if (machine == 0x8664) {
                host = hostDirectory.resolve("effectcraft-aex-host-x64.exe");
            } else if (machine == 0x014c) {
                host = hostDirectory.resolve("effectcraft-aex-host-x86.exe");
            } else {
                throw new IOException(String.format(Locale.ROOT,
                        "AEX PE 架构 0x%04x 暂不支持；当前宿主只提供 x86 和 x64。", machine));
            }
            if (!Files.isRegularFile(host, java.nio.file.LinkOption.NOFOLLOW_LINKS)
                    || Files.isSymbolicLink(host)) {
                throw new IOException("匹配的 Windows AEX 宿主未安装：" + host.getFileName());
            }

            INSTALL_STATUS.put(requestId, String.format(Locale.ROOT,
                    "RUNNING: 已识别 PE 架构 0x%04x，正在启动隔离 AEX 宿主…", machine));
            StringBuilder output = new StringBuilder();
            WinlatorBionicRuntimeManager.GuestProcess guest = manager.launchAexHost(
                    container, host, plugin,
                    line -> appendRuntimeLog(requestId, output, line),
                    code -> appendRuntimeLog(requestId, output, "宿主退出码：" + code));
            long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(120);
            while (guest.isAlive() && System.nanoTime() < deadline) {
                Thread.sleep(200);
            }
            if (guest.isAlive()) {
                guest.terminate();
                Thread.sleep(1000);
                if (guest.isAlive()) guest.kill();
                INSTALL_STATUS.put(requestId,
                        "ERROR: AEX 宿主运行超过 120 秒，已终止。\n" + output);
            } else {
                Integer exitCode = guest.getExitCode();
                INSTALL_STATUS.put(requestId,
                        "EXIT:" + (exitCode == null ? "unknown" : exitCode)
                                + "\nAEX 宿主进程已结束。退出码只代表进程结果，不代表所有插件功能、参数和渲染均兼容。\n"
                                + output);
            }
        } catch (Exception error) {
            String detail = error.getMessage();
            INSTALL_STATUS.put(requestId, "ERROR: AEX 测试失败："
                    + (detail == null || detail.trim().isEmpty()
                    ? error.getClass().getSimpleName() : detail));
            Log.e(TAG, "AEX plug-in test failed.", error);
        } finally {
            if (plugin != null) {
                try { deletePrivateTree(plugin.getParent()); } catch (IOException ignored) {}
            }
            ACTIVE_REQUESTS.remove(requestId);
        }
    }

    private static void appendRuntimeLog(String requestId, StringBuilder output, String line) {
        synchronized (output) {
            if (output.length() < 12_000) {
                output.append(line).append('\n');
                if (output.length() > 12_000) output.setLength(12_000);
            }
            INSTALL_STATUS.put(requestId, "RUNNING:\n" + output);
        }
    }

    /** Extracts exactly one .aex into a fixed private filename; ZIP paths are never reused. */
    private static Path extractFirstAex(Path source, Path destination) throws IOException {
        if (source == null || !Files.isRegularFile(source, java.nio.file.LinkOption.NOFOLLOW_LINKS)
                || Files.isSymbolicLink(source)) {
            throw new IOException("导入的插件文件不存在或不安全。");
        }
        String lower = source.getFileName().toString().toLowerCase(Locale.ROOT);
        Path target = destination.resolve("plugin.aex");
        if (lower.endsWith(".aex")) {
            copyFile(source, target);
            return target;
        }
        if (!lower.endsWith(".zip")) {
            throw new IOException("当前测试只支持单个 .aex 文件或 ZIP 插件包。");
        }
        try (ZipFile zip = new ZipFile(source.toFile())) {
            java.util.Enumeration<? extends ZipEntry> entries = zip.entries();
            int checked = 0;
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                if (++checked > 1024) {
                    throw new IOException("ZIP 文件条目超过 1024 个安全上限。");
                }
                if (entry.isDirectory()
                        || !entry.getName().toLowerCase(Locale.ROOT).endsWith(".aex")) continue;
                if (entry.getSize() < 64 || entry.getSize() > 64L * 1024 * 1024) {
                    throw new IOException("AEX 文件大小超出 64 MB 安全范围。");
                }
                try (InputStream input = zip.getInputStream(entry);
                     OutputStream output = Files.newOutputStream(target,
                             StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
                    byte[] buffer = new byte[64 * 1024];
                    int count;
                    long total = 0;
                    while ((count = input.read(buffer)) != -1) {
                        if (count == 0) continue;
                        total += count;
                        if (total > 64L * 1024 * 1024) {
                            throw new IOException("实际 AEX 数据超过 64 MB 安全上限。");
                        }
                        output.write(buffer, 0, count);
                    }
                }
                return target;
            }
        }
        throw new IOException("ZIP 插件包中没有找到 .aex 文件。");
    }

    /** Reads IMAGE_FILE_HEADER.Machine after validating the DOS and PE signatures. */
    private static int readPeMachine(Path peFile) throws IOException {
        try (RandomAccessFile file = new RandomAccessFile(peFile.toFile(), "r")) {
            if (file.length() < 64 || file.readUnsignedByte() != 'M'
                    || file.readUnsignedByte() != 'Z') {
                throw new IOException("AEX 文件不是有效的 Windows PE 文件（缺少 MZ 头）。");
            }
            file.seek(0x3c);
            long peOffset = readLe32(file);
            if (peOffset < 64 || peOffset > file.length() - 6) {
                throw new IOException("AEX PE 头偏移无效。");
            }
            file.seek(peOffset);
            if (file.readUnsignedByte() != 'P' || file.readUnsignedByte() != 'E'
                    || file.readUnsignedByte() != 0 || file.readUnsignedByte() != 0) {
                throw new IOException("AEX 文件 PE 签名无效。");
            }
            return file.readUnsignedByte() | (file.readUnsignedByte() << 8);
        }
    }

    private static long readLe32(RandomAccessFile file) throws IOException {
        long b0 = file.readUnsignedByte();
        long b1 = file.readUnsignedByte();
        long b2 = file.readUnsignedByte();
        long b3 = file.readUnsignedByte();
        return b0 | (b1 << 8) | (b2 << 16) | (b3 << 24);
    }

    private static void installVerifiedPeHost(
            Context context, String asset, String expectedSha256,
            Path destination, int expectedMachine) throws IOException {
        if (Files.isRegularFile(destination, java.nio.file.LinkOption.NOFOLLOW_LINKS)
                && !Files.isSymbolicLink(destination)
                && expectedSha256.equalsIgnoreCase(sha256(destination))) {
            verifyPeMachine(destination, expectedMachine);
            return;
        }
        Path parent = destination.getParent();
        if (parent == null) throw new IOException("AEX host destination has no parent");
        Files.createDirectories(parent);
        Path temporary = destination.resolveSibling(destination.getFileName() + ".installing");
        Files.deleteIfExists(temporary);
        MessageDigest digest;
        try {
            digest = MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("Android must provide SHA-256", impossible);
        }
        try (InputStream input = context.getAssets().open(asset);
             OutputStream output = Files.newOutputStream(temporary,
                     StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (count == 0) continue;
                digest.update(buffer, 0, count);
                output.write(buffer, 0, count);
            }
            output.flush();
        } catch (IOException failure) {
            Files.deleteIfExists(temporary);
            throw new IOException("Could not install bundled AEX host: " + asset, failure);
        }
        StringBuilder hex = new StringBuilder(64);
        for (byte value : digest.digest()) {
            hex.append(String.format(Locale.ROOT, "%02x", value & 0xff));
        }
        if (!expectedSha256.equalsIgnoreCase(hex.toString())) {
            Files.deleteIfExists(temporary);
            throw new IOException("AEX host SHA-256 mismatch for " + asset);
        }
        verifyPeMachine(temporary, expectedMachine);
        try {
            Files.move(temporary, destination,
                    StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } catch (java.nio.file.AtomicMoveNotSupportedException ignored) {
            Files.move(temporary, destination, StandardCopyOption.REPLACE_EXISTING);
        }
    }

    private static void verifyPeMachine(Path path, int expectedMachine) throws IOException {
        int actual = readPeMachine(path);
        if (actual != expectedMachine) {
            throw new IOException(String.format(Locale.ROOT,
                    "AEX host PE machine mismatch: expected 0x%04x, received 0x%04x",
                    expectedMachine, actual));
        }
    }

    private static String sha256(Path file) throws IOException {
        MessageDigest digest;
        try {
            digest = MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("Android must provide SHA-256", impossible);
        }
        try (InputStream input = Files.newInputStream(file)) {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (count > 0) digest.update(buffer, 0, count);
            }
        }
        StringBuilder hex = new StringBuilder(64);
        for (byte value : digest.digest()) {
            hex.append(String.format(Locale.ROOT, "%02x", value & 0xff));
        }
        return hex.toString();
    }

    private static void copyFile(Path source, Path destination) throws IOException {
        try (InputStream input = Files.newInputStream(source);
             OutputStream output = Files.newOutputStream(destination,
                     StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (count > 0) output.write(buffer, 0, count);
            }
        }
    }

    private static void deletePrivateTree(Path path) throws IOException {
        if (path == null || !Files.exists(path, java.nio.file.LinkOption.NOFOLLOW_LINKS)) return;
        if (Files.isDirectory(path, java.nio.file.LinkOption.NOFOLLOW_LINKS)
                && !Files.isSymbolicLink(path)) {
            try (java.util.stream.Stream<Path> children = Files.list(path)) {
                for (Path child : (Iterable<Path>) children::iterator) deletePrivateTree(child);
            }
        }
        Files.deleteIfExists(path);
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
