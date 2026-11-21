package com.artcraft.effectcraft;

import android.graphics.Bitmap;
import org.json.JSONObject;
import android.content.Context;
import android.util.Log;
import android.os.Build;
import android.os.Process;

import com.effectcraft.windowscompat.RuntimeAssetInstaller;
import com.effectcraft.windowscompat.WinlatorBionicRuntimeManager;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;
import java.util.Arrays;
import java.util.UUID;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
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
    private static final String FEXCORE_ASSET = "windows-compat/fexcore-arm64ec-wow64.tar.zst";
    private static final String FEXCORE_ASSET_SHA256 = "0000000000000000000000000000000000000000000000000000000000000000";
    private static final String BOX86_ASSET = "windows-compat/box86-android-armv7.tar.zst";
    private static final String BOX86_ASSET_SHA256 = "0000000000000000000000000000000000000000000000000000000000000000";
    private static final String QEMU_ASSET = "windows-compat/qemu-x86_64-linux-user-android-arm64.tar.zst";
    private static final String QEMU_ASSET_SHA256 = "0000000000000000000000000000000000000000000000000000000000000000";
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
    private static volatile com.effectcraft.windowscompat.AndroidArm64Capabilities arm64Capabilities;
    private static volatile WinlatorBionicRuntimeManager.Container arm64EcContainer;
    private static volatile WinlatorBionicRuntimeManager.Container box64Container;

    private WindowsCompatAndroidBridge() {}

    private static native long[] nativeProbeArm64();

    /** Returns the hardware and page-size facts needed to select ARM64EC/FEX. */
    public static com.effectcraft.windowscompat.AndroidArm64Capabilities getArm64Capabilities() {
        com.effectcraft.windowscompat.AndroidArm64Capabilities cached = arm64Capabilities;
        if (cached != null) return cached;
        synchronized (WindowsCompatAndroidBridge.class) {
            cached = arm64Capabilities;
            if (cached != null) return cached;
            if (!Process.is64Bit() || !Arrays.asList(Build.SUPPORTED_ABIS).contains("arm64-v8a")) {
                cached = com.effectcraft.windowscompat.AndroidArm64Capabilities.unavailable(
                        "current process is not arm64-v8a");
            } else {
                try {
                    System.loadLibrary("effectcraft-exec");
                    cached = com.effectcraft.windowscompat.AndroidArm64Capabilities
                            .fromNativeProbe(nativeProbeArm64());
                } catch (UnsatisfiedLinkError | SecurityException error) {
                    cached = com.effectcraft.windowscompat.AndroidArm64Capabilities.unavailable(
                            "libeffectcraft-exec.so is not packaged or could not be loaded: "
                                    + error.getMessage());
                }
            }
            arm64Capabilities = cached;
            return cached;
        }
    }

    public static synchronized void initialize(Context context) {
        if (context == null) return;
        Context app = context.getApplicationContext();
        if (applicationContext == app && runtimeManager != null) return;
        applicationContext = app;
        com.effectcraft.windowscompat.AndroidArm64Capabilities capabilities = getArm64Capabilities();
        Log.i(TAG, capabilities.describe());
        try {
            Path root = app.getFilesDir().toPath().resolve("windows-compat");
            Path execBridge = Paths.get(app.getApplicationInfo().nativeLibraryDir)
                    .resolve("libeffectcraft-exec.so");
            runtimeManager = new WinlatorBionicRuntimeManager(
                    root, RuntimeAssetInstaller.httpFetcher(), execBridge);
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
        Path fexArchive = null;
        Path box86Archive = null;
        Path qemuArchive = null;
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
            arm64EcContainer = container;

            String fexStatus = "FEXCore 源码构建包未安装。";
            try {
                fexArchive = context.getCacheDir().toPath().resolve("fexcore-arm64ec-wow64.tar.zst");
                copyBundledAsset(context, FEXCORE_ASSET, fexArchive);
                manager.installFexCoreArchive(container, fexArchive, FEXCORE_ASSET_SHA256);
                fexStatus = "源码构建的 FEXCore ARM64EC + WoW64 两套后端已校验并安装。";
            } catch (Exception fexError) {
                fexStatus = "源码构建 FEXCore 安装失败：" + safeMessage(fexError);
                Log.w(TAG, fexStatus, fexError);
            }

            String box64Status = "Box64/BOX32 x86-64 Proton 容器未准备。";
            try {
                INSTALL_STATUS.put(requestId, "正在准备 x86-64 Proton + Box64/BOX32 独立容器…");
                WinlatorBionicRuntimeManager.Container x64 = manager.createContainer(
                        "effectcraft-aex-x86_64",
                        WinlatorBionicRuntimeManager.Architecture.X86_64);
                box64Container = x64;
                box64Status = "独立 x86-64 Proton + Box64/BOX32 容器已准备；尚需 AEX 实测。";
            } catch (Exception box64Error) {
                box64Container = null;
                box64Status = "Box64 x86-64 容器准备失败：" + safeMessage(box64Error);
                Log.w(TAG, box64Status, box64Error);
            }

            String box86Status = "Box86 ARMv7 后备未随包提供。";
            if (!BOX86_ASSET_SHA256.matches("0{64}")) {
                try {
                    INSTALL_STATUS.put(requestId, "正在校验并安装可选 Box86 ARMv7 引擎…");
                    box86Archive = context.getCacheDir().toPath().resolve("box86-android-armv7.tar.zst");
                    copyBundledAsset(context, BOX86_ASSET, box86Archive);
                    manager.installBox86Archive(box86Archive, BOX86_ASSET_SHA256);
                    boolean hasArm32Linker = Build.SUPPORTED_32_BIT_ABIS != null
                            && Build.SUPPORTED_32_BIT_ABIS.length > 0
                            && Files.isExecutable(Paths.get("/system/bin/linker"));
                    box86Status = hasArm32Linker
                            ? "Box86 ARMv7 已安装；仍需独立 i386 Wine 根文件系统。"
                            : "Box86 ARMv7 已安装，但设备没有 32 位 Bionic linker，当前设备禁用该路线。";
                } catch (Exception box86Error) {
                    box86Status = "Box86 ARMv7 安装失败：" + safeMessage(box86Error);
                    Log.w(TAG, box86Status, box86Error);
                }
            }

            String qemuStatus = "QEMU x86-64 Linux-user 后备未随包提供。";
            if (!QEMU_ASSET_SHA256.matches("0{64}")) {
                try {
                    INSTALL_STATUS.put(requestId, "正在安装可选 QEMU x86-64 Linux-user 引擎…");
                    qemuArchive = context.getCacheDir().toPath().resolve("qemu-x86_64-linux-user-android-arm64.tar.zst");
                    copyBundledAsset(context, QEMU_ASSET, qemuArchive);
                    manager.installQemuUserArchive(qemuArchive, QEMU_ASSET_SHA256);
                    qemuStatus = "QEMU ARM64 引擎已安装；仍需独立 x86-64 Wine/glibc 根文件系统才能运行 Windows AEX。";
                } catch (Exception qemuError) {
                    qemuStatus = "QEMU Linux-user 安装失败：" + safeMessage(qemuError);
                    Log.w(TAG, qemuStatus, qemuError);
                }
            }

            boolean fexReady = Files.isRegularFile(container.system32.resolve("libarm64ecfex.dll"))
                    && Files.isRegularFile(container.system32.resolve("libwow64fex.dll"));
            if (!fexReady && box64Container == null) {
                throw new IOException("FEXCore 和 Box64 两条核心后端均未准备成功。");
            }
            INSTALL_STATUS.put(requestId, "正在校验并安装 Windows x64 / x86 AEX 宿主…");
            Path hostDirectory = context.getFilesDir().toPath().resolve("windows-compat/hosts");
            installVerifiedPeHost(context, AEX_HOST_X64_ASSET, AEX_HOST_X64_SHA256,
                    hostDirectory.resolve("effectcraft-aex-host-x64.exe"), 0x8664);
            installVerifiedPeHost(context, AEX_HOST_X86_ASSET, AEX_HOST_X86_SHA256,
                    hostDirectory.resolve("effectcraft-aex-host-x86.exe"), 0x014c);

            INSTALL_STATUS.put(requestId,
                    "READY:Windows 兼容环境基础文件与 x86/x64 AEX 宿主已准备。"
                    + fexStatus + box64Status + box86Status + qemuStatus
                    + "导入 AEX 后会先试 FEXCore，再回退测试 Box64；Box86/QEMU 只有满足各自 Wine 客体根文件系统条件后才可执行。");
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
            if (fexArchive != null) {
                try { Files.deleteIfExists(fexArchive); } catch (IOException ignored) {}
            }
            if (box86Archive != null) {
                try { Files.deleteIfExists(box86Archive); } catch (IOException ignored) {}
            }
            if (qemuArchive != null) {
                try { Files.deleteIfExists(qemuArchive); } catch (IOException ignored) {}
            }
            ACTIVE_REQUESTS.remove(requestId);
        }
    }

    private static String safeMessage(Exception error) {
        String message = error.getMessage();
        return message == null || message.trim().isEmpty()
                ? error.getClass().getSimpleName() : message;
    }

    /** Starts a user-requested, isolated test of the first AEX found in a file or ZIP. */
    public static void startAexPluginTest(String requestId, String sourcePath) {
        if (requestId == null || requestId.trim().isEmpty()
                || sourcePath == null || sourcePath.trim().isEmpty()) return;
        Context context = applicationContext;
        WinlatorBionicRuntimeManager manager = runtimeManager;
        WinlatorBionicRuntimeManager.Container fexContainer = arm64EcContainer;
        WinlatorBionicRuntimeManager.Container box64 = box64Container;
        if (context == null || manager == null || (fexContainer == null && box64 == null)) {
            INSTALL_STATUS.put(requestId, "ERROR: 请先安装 Windows 兼容运行环境。");
            return;
        }
        if (!ACTIVE_REQUESTS.add(requestId)) return;
        INSTALL_STATUS.put(requestId, "RUNNING: 正在提取 AEX 并按 FEXCore、Box64 顺序测试后端…");
        INSTALL_EXECUTOR.execute(() -> runAexPluginTest(
                context, manager, fexContainer, box64, requestId, sourcePath));
    }

    private static final class AexTrialResult {
        final String backendName;
        final int score;
        final int parameterCount;
        final int roundTrippedParameters;
        final long loadMillis;
        final long renderMillis;
        final boolean repeatedFrameStable;
        final String outputSha256;
        final int width;
        final int height;

        AexTrialResult(
                String backendName, int score, int parameterCount,
                int roundTrippedParameters, long loadMillis, long renderMillis,
                boolean repeatedFrameStable, String outputSha256, int width, int height) {
            this.backendName = backendName;
            this.score = score;
            this.parameterCount = parameterCount;
            this.roundTrippedParameters = roundTrippedParameters;
            this.loadMillis = loadMillis;
            this.renderMillis = renderMillis;
            this.repeatedFrameStable = repeatedFrameStable;
            this.outputSha256 = outputSha256;
            this.width = width;
            this.height = height;
        }

        String summary() {
            return backendName + "：得分 " + score + "/100；参数 " + parameterCount
                    + "；成功往返参数 " + roundTrippedParameters
                    + "；加载 " + loadMillis + " ms；两次渲染 " + renderMillis + " ms；输出 "
                    + width + "x" + height + "；同帧重复 "
                    + (repeatedFrameStable ? "一致" : "不一致")
                    + "；SHA-256 " + outputSha256;
        }
    }

    private static void runAexPluginTest(
            Context context,
            WinlatorBionicRuntimeManager manager,
            WinlatorBionicRuntimeManager.Container fexContainer,
            WinlatorBionicRuntimeManager.Container box64Container,
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

            Path inputPng = plugin.getParent().resolve("input.png");
            writeSmokeTestImage(inputPng, 320, 240);
            String[] backendNames = {"ARM64EC Wine + source-built FEXCore", "x86-64 Wine + Box64/BOX32"};
            WinlatorBionicRuntimeManager.Container[] containers = {fexContainer, box64Container};
            java.util.List<AexTrialResult> passedTrials = new java.util.ArrayList<>();
            StringBuilder attemptLog = new StringBuilder();

            // Do not stop at the first working backend. Run every available candidate
            // against the same plug-in, input image, frame and parameter values.
            for (int index = 0; index < containers.length; index++) {
                WinlatorBionicRuntimeManager.Container candidate = containers[index];
                if (candidate == null) {
                    attemptLog.append(backendNames[index]).append("：运行环境未安装，跳过。\n");
                    continue;
                }
                Path routeOutput = plugin.getParent().resolve(
                        index == 0 ? "output-fexcore.png" : "output-box64.png");
                INSTALL_STATUS.put(requestId, String.format(Locale.ROOT,
                        "RUNNING: PE 架构 0x%04x；正在完整测试候选后端 %s…", machine, backendNames[index]));
                try {
                    AexTrialResult trial = runAexSmokeTest(
                            manager, candidate, host, plugin, inputPng, routeOutput,
                            machine, requestId, backendNames[index]);
                    passedTrials.add(trial);
                    attemptLog.append("通过：").append(trial.summary()).append('\n');
                } catch (Exception backendError) {
                    String detail = backendError.getMessage();
                    attemptLog.append("未通过：").append(backendNames[index]).append("：")
                            .append(detail == null ? backendError.getClass().getSimpleName() : detail)
                            .append('\n');
                    Log.w(TAG, "AEX sample failed on " + backendNames[index], backendError);
                }
            }

            if (passedTrials.isEmpty()) {
                throw new IOException("所有已安装的 AEX 候选后端均未通过加载、参数往返、重复渲染和正常退出测试。\n"
                        + attemptLog
                        + "Box86 需要 i386 Wine 根文件系统；QEMU 需要 x86-64 Wine/glibc 根文件系统，未具备时不会冒充可运行。");
            }

            // Rank only routes that completed every mandatory smoke-test gate.
            // Prefer the highest measured score, then the faster two-frame render.
            AexTrialResult best = passedTrials.stream()
                    .sorted(java.util.Comparator
                            .comparingInt((AexTrialResult value) -> value.score).reversed()
                            .thenComparingLong(value -> value.renderMillis))
                    .findFirst().orElseThrow(() -> new IOException("没有可选的通过路线。"));

            StringBuilder finalStatus = new StringBuilder();
            finalStatus.append("EXIT:0\n当前插件样本已完成所有可用后端的隔离试跑。")
                    .append("\n自动优选：").append(best.backendName)
                    .append("（").append(best.score).append("/100）")
                    .append("\n优选依据：参数往返、两次真实 CPU 帧渲染、重复帧稳定性、正常退出和实测耗时。")
                    .append("\n逐路线测试记录：\n").append(attemptLog)
                    .append("\n注意：这是当前插件样本的一帧 CPU 宿主兼容性试跑，不代表全部 Adobe SDK/A E G P 套件、GPU、时间历史、多输入或其他插件均已兼容。");
            INSTALL_STATUS.put(requestId, finalStatus.toString());
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

    private static AexTrialResult runAexSmokeTest(
            WinlatorBionicRuntimeManager manager,
            WinlatorBionicRuntimeManager.Container container,
            Path host,
            Path plugin,
            Path inputPng,
            Path outputPng,
            int machine,
            String requestId,
            String backendName) throws Exception {
        StringBuilder output = new StringBuilder();
        WinlatorBionicRuntimeManager.GuestProcess guest = manager.launchAexHost(
                container, host, plugin,
                line -> appendRuntimeLog(requestId, output, line),
                code -> appendRuntimeLog(requestId, output, "宿主退出码：" + code));
        Path repeatedOutput = outputPng.resolveSibling(outputPng.getFileName().toString() + ".repeat.png");
        try {
            long loadStarted = System.nanoTime();
            String metadataLine = guest.readStdoutLine(45,
                    java.util.concurrent.TimeUnit.SECONDS);
            if (metadataLine == null) {
                throw new IOException("AEX 宿主未在 45 秒内返回插件加载信息。");
            }
            JSONObject metadata = new JSONObject(metadataLine);
            if (!metadata.optBoolean("ok", false)) {
                throw new IOException("AEX 插件加载失败：" + metadata.optString("error", metadataLine));
            }
            long loadMillis = java.util.concurrent.TimeUnit.NANOSECONDS
                    .toMillis(System.nanoTime() - loadStarted);
            int parameterCount = metadata.optInt("param_count", -1);
            org.json.JSONArray parameters = metadata.optJSONArray("parameters");
            if (parameterCount < 0 || parameters == null) {
                throw new IOException("AEX 宿主没有返回有效的参数元数据。");
            }

            // Round-trip every parameter value understood by the isolated host.
            // Unsupported custom UI objects are counted as unsupported, never faked.
            org.json.JSONArray roundTrip = new org.json.JSONArray();
            for (int index = 0; index < parameters.length(); index++) {
                JSONObject item = parameters.optJSONObject(index);
                if (item == null) continue;
                JSONObject value = item.optJSONObject("value");
                if (value == null || "unsupported".equals(value.optString("type"))) continue;
                JSONObject entry = new JSONObject();
                entry.put("index", item.optInt("index", -1));
                entry.put("value", value);
                if (entry.optInt("index", -1) < 0) {
                    throw new IOException("AEX 参数元数据包含无效索引。");
                }
                roundTrip.put(entry);
            }

            Files.deleteIfExists(outputPng);
            Files.deleteIfExists(repeatedOutput);
            JSONObject firstRequest = new JSONObject();
            firstRequest.put("cmd", "render");
            firstRequest.put("input_png", inputPng.toString());
            firstRequest.put("output_png", outputPng.toString());
            firstRequest.put("frame", 0);
            firstRequest.put("fps", 30);
            firstRequest.put("params", roundTrip);

            long renderStarted = System.nanoTime();
            guest.sendLine(firstRequest.toString());
            JSONObject firstRender = readSuccessfulRender(guest, 90, "首次 AEX CPU 帧渲染");
            if (!validPngOutput(outputPng)) {
                throw new IOException("AEX 宿主报告渲染成功，但没有生成有效 PNG 输出。");
            }

            JSONObject repeatRequest = new JSONObject(firstRequest.toString());
            repeatRequest.put("output_png", repeatedOutput.toString());
            guest.sendLine(repeatRequest.toString());
            JSONObject repeatedRender = readSuccessfulRender(guest, 90, "同一帧重复渲染");
            if (!validPngOutput(repeatedOutput)) {
                throw new IOException("AEX 宿主第二次报告渲染成功，但没有生成有效 PNG 输出。");
            }
            long renderMillis = java.util.concurrent.TimeUnit.NANOSECONDS
                    .toMillis(System.nanoTime() - renderStarted);

            int width = firstRender.optInt("width", 0);
            int height = firstRender.optInt("height", 0);
            if (width <= 0 || height <= 0
                    || repeatedRender.optInt("width", 0) != width
                    || repeatedRender.optInt("height", 0) != height) {
                throw new IOException("AEX 两次渲染的输出尺寸无效或不一致。");
            }
            String firstHash = sha256File(outputPng);
            String repeatedHash = sha256File(repeatedOutput);
            boolean stable = firstHash.equals(repeatedHash);

            guest.sendLine(new JSONObject().put("cmd", "quit").toString());
            long deadline = System.nanoTime()
                    + java.util.concurrent.TimeUnit.SECONDS.toNanos(20);
            while (guest.isAlive() && System.nanoTime() < deadline) Thread.sleep(100);
            if (guest.isAlive()) {
                throw new IOException("AEX 宿主完成渲染后未能正常退出。");
            }
            long exitDeadline = System.nanoTime()
                    + java.util.concurrent.TimeUnit.SECONDS.toNanos(2);
            while (guest.getExitCode() == null && System.nanoTime() < exitDeadline) Thread.sleep(50);
            Integer exitCode = guest.getExitCode();
            if (exitCode == null || exitCode != 0) {
                throw new IOException("AEX 宿主渲染完成后的退出码异常：" + exitCode);
            }

            // Scores are calculated from observed work only. No desktop visual-fidelity
            // percentage is invented because this sample run has no AE reference image.
            int performancePoints = Math.max(0, 5 - (int) Math.min(5, renderMillis / 1000));
            int score = 15 /* loaded */
                    + 15 /* parameter metadata */
                    + 20 /* supported parameters round-tripped */
                    + 25 /* two real frame renders */
                    + (stable ? 10 : 0)
                    + 10 /* clean worker exit */
                    + performancePoints;
            return new AexTrialResult(
                    backendName, score, parameterCount, roundTrip.length(),
                    loadMillis, renderMillis, stable, firstHash, width, height);
        } finally {
            Files.deleteIfExists(repeatedOutput);
            if (guest.isAlive()) {
                guest.terminate();
                long terminateDeadline = System.nanoTime()
                        + java.util.concurrent.TimeUnit.SECONDS.toNanos(1);
                while (guest.isAlive() && System.nanoTime() < terminateDeadline) Thread.sleep(50);
                if (guest.isAlive()) guest.kill();
            }
        }
    }

    private static JSONObject readSuccessfulRender(
            WinlatorBionicRuntimeManager.GuestProcess guest,
            long timeoutSeconds,
            String stage) throws Exception {
        String line = guest.readStdoutLine(timeoutSeconds,
                java.util.concurrent.TimeUnit.SECONDS);
        if (line == null) {
            throw new IOException(stage + "超时，宿主未返回结果。");
        }
        JSONObject result = new JSONObject(line);
        if (!result.optBoolean("ok", false)) {
            throw new IOException(stage + "失败：" + result.optString("error", line));
        }
        return result;
    }

    private static boolean validPngOutput(Path path) throws IOException {
        if (!Files.isRegularFile(path, java.nio.file.LinkOption.NOFOLLOW_LINKS)
                || Files.isSymbolicLink(path) || Files.size(path) < 64) return false;
        try (InputStream input = Files.newInputStream(path)) {
            byte[] signature = new byte[8];
            int offset = 0;
            while (offset < signature.length) {
                int count = input.read(signature, offset, signature.length - offset);
                if (count < 0) return false;
                offset += count;
            }
            byte[] expected = {(byte) 0x89, 'P', 'N', 'G', 13, 10, 26, 10};
            return Arrays.equals(signature, expected);
        }
    }

    private static String sha256File(Path path) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = Files.newInputStream(path)) {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (count > 0) digest.update(buffer, 0, count);
            }
        }
        StringBuilder result = new StringBuilder(64);
        for (byte value : digest.digest()) {
            result.append(String.format(Locale.ROOT, "%02x", value & 0xff));
        }
        return result.toString();
    }

    private static void writeSmokeTestImage(Path path, int width, int height) throws IOException {
        Bitmap bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        try {
            int[] pixels = new int[width * height];
            for (int y = 0; y < height; y++) {
                for (int x = 0; x < width; x++) {
                    int red = (x * 255) / Math.max(1, width - 1);
                    int green = (y * 255) / Math.max(1, height - 1);
                    int blue = ((x + y) * 255) / Math.max(1, width + height - 2);
                    pixels[y * width + x] = android.graphics.Color.argb(255, red, green, blue);
                }
            }
            bitmap.setPixels(pixels, 0, width, 0, 0, width, height);
            try (OutputStream output = Files.newOutputStream(path,
                    StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
                if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)) {
                    throw new IOException("Could not create AEX smoke-test input PNG.");
                }
                output.flush();
            }
        } finally {
            bitmap.recycle();
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
