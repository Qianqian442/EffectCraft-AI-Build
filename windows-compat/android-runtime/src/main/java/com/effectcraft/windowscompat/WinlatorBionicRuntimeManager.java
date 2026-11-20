package com.effectcraft.windowscompat;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.OutputStreamWriter;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.TimeUnit;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;

/**
 * EffectCraft-specific installer and launcher for the pinned Winlator Bionic runtime.
 *
 * The manager uses app-private ImageFS and separate Wine prefixes. It adds no
 * application RAM cap, rlimit, cgroup limit or Box64/FEX guest memory budget.
 * Process output is drained asynchronously so guest logs cannot block a worker.
 *
 * This manager is still an experimental integration layer: the chosen Wine
 * worker/host combination must pass a real Android emulator/device smoke test
 * before EffectCraft marks that PE architecture as supported.
 */
public final class WinlatorBionicRuntimeManager implements AutoCloseable {
    public enum Architecture {
        X86_64,
        ARM64EC
    }

    public enum WoW64Engine {
        FEXCORE,
        WOWBOX64
    }

    public static final class Container {
        public final String id;
        public final Architecture architecture;
        public final Path root;
        public final Path winePrefix;
        public final Path system32;
        public final Path syswow64;
        public final Path wineRoot;

        private Container(String id, Architecture architecture, Path root, Path wineRoot) {
            this.id = id;
            this.architecture = architecture;
            this.root = root;
            this.winePrefix = root.resolve(".wine");
            this.system32 = winePrefix.resolve("drive_c/windows/system32");
            this.syswow64 = winePrefix.resolve("drive_c/windows/syswow64");
            this.wineRoot = wineRoot;
        }
    }

    public final class GuestProcess {
        private final Process process;
        private final ExecutorService outputReaders;
        private final BlockingQueue<String> stdoutLines = new ArrayBlockingQueue<>(64);
        private final BufferedWriter stdin;
        private final Object stdinLock = new Object();
        private volatile Integer exitCode;

        private GuestProcess(Process process, Consumer<String> logCallback, Consumer<Integer> exitCallback) {
            this.process = process;
            this.stdin = new BufferedWriter(new OutputStreamWriter(process.getOutputStream(), StandardCharsets.UTF_8));
            this.outputReaders = Executors.newFixedThreadPool(2, runnable -> {
                Thread thread = new Thread(runnable, "EffectCraft-Wine-Log");
                thread.setDaemon(true);
                return thread;
            });
            outputReaders.execute(() -> drain(process.getInputStream(), "stdout", logCallback));
            outputReaders.execute(() -> drain(process.getErrorStream(), "stderr", logCallback));
            Thread waiter = new Thread(() -> {
                int status;
                try {
                    status = process.waitFor();
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    status = -1;
                }
                exitCode = status;
                outputReaders.shutdown();
                if (exitCallback != null) exitCallback.accept(status);
            }, "EffectCraft-Wine-Wait");
            waiter.setDaemon(true);
            waiter.start();
        }

        /** Send one JSON-line command to the isolated AEX worker. */
        public void sendLine(String line) throws IOException {
            if (!process.isAlive()) throw new IOException("AEX worker is no longer running");
            synchronized (stdinLock) {
                stdin.write(line);
                stdin.newLine();
                stdin.flush();
            }
        }

        /** Read the next worker response line without blocking the Android UI thread. */
        public String readStdoutLine(long timeout, TimeUnit unit) throws InterruptedException {
            return stdoutLines.poll(timeout, unit);
        }

        public boolean isAlive() {
            return process.isAlive();
        }

        public Integer getExitCode() {
            return exitCode;
        }

        public void terminate() {
            process.destroy();
        }

        public void kill() {
            process.destroyForcibly();
        }

        private void drain(InputStream input, String streamName, Consumer<String> callback) {
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if ("stdout".equals(streamName) && !stdoutLines.offer(line)) {
                        stdoutLines.poll();
                        stdoutLines.offer(line);
                    }
                    if (callback != null) callback.accept("[" + streamName + "] " + line);
                }
            } catch (IOException failure) {
                if (callback != null) callback.accept("[" + streamName + "] " + failure.getMessage());
            }
        }
    }

    private final RuntimeAssetInstaller assets;
    private final SafeRuntimeArchiveExtractor extractor;
    private final WinlatorContentPackageInstaller contentPackages;
    private final Path privateRoot;
    private final Path imageFsRoot;
    private final Path containersRoot;
    private final Path execBridgeLibrary;
    private volatile boolean closed;

    public WinlatorBionicRuntimeManager(Path privateRoot, RuntimeAssetInstaller.AssetFetcher fetcher)
            throws IOException {
        this(privateRoot, fetcher, null);
    }

    public WinlatorBionicRuntimeManager(
            Path privateRoot,
            RuntimeAssetInstaller.AssetFetcher fetcher,
            Path execBridgeLibrary) throws IOException {
        this.privateRoot = Objects.requireNonNull(privateRoot, "private root").toAbsolutePath().normalize();
        Files.createDirectories(this.privateRoot);
        if (Files.isSymbolicLink(this.privateRoot)) {
            throw new IOException("runtime root must not be a symlink");
        }
        this.imageFsRoot = this.privateRoot.resolve("imagefs");
        this.containersRoot = this.privateRoot.resolve("containers");
        this.execBridgeLibrary = execBridgeLibrary == null
                ? null : execBridgeLibrary.toAbsolutePath().normalize();
        this.assets = new RuntimeAssetInstaller(this.privateRoot, fetcher);
        this.extractor = new SafeRuntimeArchiveExtractor();
        this.contentPackages = new WinlatorContentPackageInstaller(assets, extractor);
    }

    /**
     * Install the base root filesystem, both Proton runtimes, Box64, and the
     * optional ARM64EC FEXCore/WowBox64 payloads. Assets are downloaded once,
     * checksum-verified, and kept outside the base EffectCraft APK.
     */
    public synchronized void installAllRuntimeComponents() throws IOException {
        ensureOpen();
        Path marker = privateRoot.resolve("runtime-installed-v1");
        if (!Files.isRegularFile(marker, LinkOption.NOFOLLOW_LINKS)) {
            deleteTree(imageFsRoot);
            RuntimeAssetInstaller.AssetSpec image = WinlatorBionicAssetCatalog.imageFs();
            Path imageArchive = assets.downloadVerified(image);
            extractor.extractTarXz(imageArchive, imageFsRoot);
            installProton(Architecture.X86_64);
            installProton(Architecture.ARM64EC);
            installBox64();
            Files.write(marker, "winlator-bionic-proton-9.0-v1\n".getBytes(StandardCharsets.UTF_8),
                    StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
        } else {
            // Still verify all pinned component files are present before use.
            verifyBaseFiles();
        }
    }

    private void verifyBaseFiles() throws IOException {
        Path box64 = imageFsRoot.resolve("usr/bin/box64");
        Path protonX64 = imageFsRoot.resolve("opt/proton-9.0-x86_64");
        Path protonArm = imageFsRoot.resolve("opt/proton-9.0-arm64ec");
        if (!Files.isRegularFile(box64, LinkOption.NOFOLLOW_LINKS)
                || !Files.isDirectory(protonX64, LinkOption.NOFOLLOW_LINKS)
                || !Files.isDirectory(protonArm, LinkOption.NOFOLLOW_LINKS)
                || !Files.isRegularFile(protonX64.resolve("bin/wine64"))
                || !Files.isRegularFile(protonArm.resolve("bin/wine64"))) {
            throw new IOException("runtime install marker exists but required Wine/Box64 files are missing");
        }
    }

    private void installProton(Architecture architecture) throws IOException {
        String name = architecture == Architecture.X86_64 ? "proton-9.0-x86_64" : "proton-9.0-arm64ec";
        RuntimeAssetInstaller.AssetSpec spec = architecture == Architecture.X86_64
                ? WinlatorBionicAssetCatalog.protonX64()
                : WinlatorBionicAssetCatalog.protonArm64Ec();
        Path destination = imageFsRoot.resolve("opt").resolve(name);
        deleteTree(destination);
        createDirectoriesNoSymlink(privateRoot, destination.getParent());
        Path archive = assets.downloadVerified(spec);
        extractor.extractTarXz(archive, destination);
    }

    private void installBox64() throws IOException {
        RuntimeAssetInstaller.AssetSpec spec = WinlatorBionicAssetCatalog.box64();
        contentPackages.install(spec, imageFsRoot,
                imageFsRoot.resolve("containers/not-used/system32"),
                imageFsRoot.resolve("containers/not-used/syswow64"));
    }

    /**
     * Installs the independently built Android/Bionic BOX32 binary over the
     * ordinary Box64 WCP executable. The embedded archive is SHA-256 pinned,
     * safely extracted beneath app-private staging, and checked for an
     * AArch64 Android PIE ELF header before it can replace the live binary.
     */
    public synchronized Path installBox64Box32Archive(Path archive, String expectedSha256)
            throws IOException {
        ensureOpen();
        if (archive == null || !Files.isRegularFile(archive, LinkOption.NOFOLLOW_LINKS)
                || Files.isSymbolicLink(archive)) {
            throw new IOException("BOX32 archive is missing or unsafe");
        }
        if (expectedSha256 == null || !expectedSha256.matches("(?i)[0-9a-f]{64}")) {
            throw new IOException("BOX32 archive requires a pinned SHA-256 digest");
        }
        String actualDigest = sha256(archive);
        if (!actualDigest.equalsIgnoreCase(expectedSha256)) {
            throw new IOException("BOX32 archive SHA-256 mismatch: expected "
                    + expectedSha256.toLowerCase(Locale.ROOT) + ", received " + actualDigest);
        }

        Path staging = privateRoot.resolve("staging/box64-box32");
        deleteTree(staging);
        Files.createDirectories(staging);
        try {
            extractor.extractTarZstd(archive, staging);
            Path candidate = staging.resolve("usr/bin/box64").normalize();
            if (!candidate.startsWith(staging)
                    || !Files.isRegularFile(candidate, LinkOption.NOFOLLOW_LINKS)
                    || Files.isSymbolicLink(candidate)) {
                throw new IOException("BOX32 archive is missing usr/bin/box64");
            }
            verifyAndroidArm64Pie(candidate);

            Path destination = imageFsRoot.resolve("usr/bin/box64").normalize();
            if (!destination.startsWith(imageFsRoot)) {
                throw new IOException("BOX32 destination escapes ImageFS");
            }
            Path parent = destination.getParent();
            if (parent == null) throw new IOException("BOX32 destination has no parent");
            createDirectoriesNoSymlink(privateRoot, parent);
            Path temporary = destination.resolveSibling("box64.box32.installing");
            Files.deleteIfExists(temporary);
            try {
                copyStreamed(candidate, temporary);
                ensureExecutable(temporary);
                Files.move(temporary, destination,
                        StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            } catch (java.nio.file.AtomicMoveNotSupportedException ignored) {
                Files.move(temporary, destination, StandardCopyOption.REPLACE_EXISTING);
            } catch (IOException | RuntimeException failure) {
                Files.deleteIfExists(temporary);
                throw failure;
            }
            Files.write(privateRoot.resolve("box64-box32-installed.sha256"),
                    (actualDigest + "\n").getBytes(StandardCharsets.US_ASCII),
                    StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE);
            return destination;
        } finally {
            deleteTree(staging);
        }
    }

    private static String sha256(Path file) throws IOException {
        final MessageDigest digest;
        try {
            digest = MessageDigest.getInstance("SHA-256");
        } catch (java.security.NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("Android must provide SHA-256", impossible);
        }
        try (InputStream input = Files.newInputStream(file)) {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (count > 0) digest.update(buffer, 0, count);
            }
        }
        StringBuilder result = new StringBuilder(64);
        for (byte value : digest.digest()) result.append(String.format(Locale.ROOT, "%02x", value & 0xff));
        return result.toString();
    }

    private static void verifyAndroidArm64Pie(Path binary) throws IOException {
        byte[] header = new byte[20];
        try (InputStream input = Files.newInputStream(binary)) {
            int offset = 0;
            while (offset < header.length) {
                int count = input.read(header, offset, header.length - offset);
                if (count < 0) throw new IOException("BOX32 executable has a truncated ELF header");
                offset += count;
            }
        }
        boolean valid = (header[0] & 0xff) == 0x7f && header[1] == 'E' && header[2] == 'L' && header[3] == 'F'
                && (header[4] & 0xff) == 2
                && (header[5] & 0xff) == 1
                && readLe16(header, 16) == 3
                && readLe16(header, 18) == 183;
        if (!valid) {
            throw new IOException("BOX32 executable is not an Android-compatible AArch64 ELF64 PIE");
        }
    }

    private static int readLe16(byte[] data, int offset) {
        return (data[offset] & 0xff) | ((data[offset + 1] & 0xff) << 8);
    }

    public synchronized Container createContainer(String id, Architecture architecture) throws IOException {
        ensureOpen();
        if (id == null || !id.matches("[A-Za-z0-9._-]{1,80}")) {
            throw new IOException("invalid runtime container id");
        }
        Path root = containersRoot.resolve(id).normalize();
        if (!root.startsWith(containersRoot)) throw new IOException("container path escapes private runtime root");
        createDirectoriesNoSymlink(privateRoot, containersRoot);
        Path marker = root.resolve(".effectcraft-container-architecture");
        boolean reusable = Files.isRegularFile(marker, LinkOption.NOFOLLOW_LINKS)
                && !Files.isSymbolicLink(marker)
                && new String(Files.readAllBytes(marker), StandardCharsets.UTF_8).trim().equals(architecture.name())
                && Files.isDirectory(root.resolve(".wine"), LinkOption.NOFOLLOW_LINKS);
        if (!reusable) {
            deleteTree(root);
            createDirectoriesNoSymlink(privateRoot, root);
            RuntimeAssetInstaller.AssetSpec pattern = architecture == Architecture.X86_64
                    ? WinlatorBionicAssetCatalog.x64ContainerPattern()
                    : WinlatorBionicAssetCatalog.arm64EcContainerPattern();
            Path archive = assets.downloadVerified(pattern);
            extractor.extractTarZstd(archive, root);
        }

        Path wineRoot = architecture == Architecture.X86_64
                ? imageFsRoot.resolve("opt/proton-9.0-x86_64")
                : imageFsRoot.resolve("opt/proton-9.0-arm64ec");
        Container container = new Container(id, architecture, root, wineRoot);
        createDirectoriesNoSymlink(privateRoot, container.system32);
        createDirectoriesNoSymlink(privateRoot, container.syswow64);
        installCommonWindowsDlls(container);
        Files.write(marker, (architecture.name() + "\n").getBytes(StandardCharsets.US_ASCII),
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE);
        return container;
    }

    private void installCommonWindowsDlls(Container container) throws IOException {
        String systemSource = container.architecture == Architecture.ARM64EC
                ? "aarch64-windows"
                : "x86_64-windows";
        copyCommonDllDirectory(container.wineRoot.resolve("lib/wine").resolve(systemSource),
                container.system32, container.architecture == Architecture.ARM64EC);
        copyCommonDllDirectory(container.wineRoot.resolve("lib/wine/i386-windows"),
                container.syswow64, false);
    }

    private void copyCommonDllDirectory(Path source, Path destination, boolean arm64Ec) throws IOException {
        if (!Files.isDirectory(source, LinkOption.NOFOLLOW_LINKS)) {
            throw new IOException("Wine common DLL source directory is missing: " + source);
        }
        createDirectoriesNoSymlink(privateRoot, destination);
        try (var stream = Files.list(source)) {
            for (Path file : (Iterable<Path>) stream.sorted()::iterator) {
                String name = file.getFileName().toString();
                if (name.equalsIgnoreCase("tabtip.exe") || name.equalsIgnoreCase("icu.dll")) continue;
                Path actual = file;
                if (arm64Ec && name.equalsIgnoreCase("iexplore.exe")) {
                    Path fallback = containerI386Fallback(file);
                    if (Files.isRegularFile(fallback, LinkOption.NOFOLLOW_LINKS)) actual = fallback;
                }
                if (Files.isSymbolicLink(actual)
                        || !Files.isRegularFile(actual, LinkOption.NOFOLLOW_LINKS)) continue;
                Path target = destination.resolve(name);
                if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) continue;
                copyStreamed(actual, target);
            }
        }
    }

    private Path containerI386Fallback(Path armFile) {
        Path libWine = armFile.getParent().getParent();
        return libWine.resolve("i386-windows").resolve(armFile.getFileName());
    }

    private static void copyStreamed(Path source, Path target) throws IOException {
        Path temporary = target.resolveSibling(target.getFileName() + ".copying");
        Files.deleteIfExists(temporary);
        try (InputStream input = Files.newInputStream(source);
             var output = Files.newOutputStream(temporary, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
            byte[] buffer = new byte[64 * 1024];
            int read;
            while ((read = input.read(buffer)) != -1) {
                if (read > 0) output.write(buffer, 0, read);
            }
            output.flush();
        }
        try {
            Files.move(temporary, target, StandardCopyOption.ATOMIC_MOVE);
        } catch (java.nio.file.AtomicMoveNotSupportedException ignored) {
            Files.move(temporary, target, StandardCopyOption.REPLACE_EXISTING);
        }
    }

    public synchronized void installArm64EcEmulator(Container container, WoW64Engine engine) throws IOException {
        ensureContainer(container, Architecture.ARM64EC);
        RuntimeAssetInstaller.AssetSpec spec = engine == WoW64Engine.FEXCORE
                ? WinlatorBionicAssetCatalog.fexCore()
                : WinlatorBionicAssetCatalog.wowBox64();
        contentPackages.install(spec, imageFsRoot, container.system32, container.syswow64);
    }

    public GuestProcess launchAexHost(
            Container container,
            Path windowsHostExe,
            Path aexFile,
            Consumer<String> logCallback,
            Consumer<Integer> exitCallback) throws IOException {
        ensureOpen();
        Objects.requireNonNull(container, "container");
        Path host = windowsHostExe.toAbsolutePath().normalize();
        Path plugin = aexFile.toAbsolutePath().normalize();
        if (!host.startsWith(privateRoot) || !plugin.startsWith(privateRoot)) {
            throw new IOException("AEX host and plug-in must be staged inside private runtime storage");
        }
        if (!Files.isRegularFile(host) || !Files.isRegularFile(plugin)) {
            throw new IOException("AEX host or plug-in file is missing");
        }

        Path wineBin = container.wineRoot.resolve("bin");
        Path wine64 = findWineExecutable(wineBin);
        ensureExecutable(wine64);
        Map<String, String> environment = baseWineEnvironment(container);
        Path bionicHostExecutable;
        List<String> guestArguments = new ArrayList<>();

        if (container.architecture == Architecture.X86_64) {
            Path box64 = imageFsRoot.resolve("usr/bin/box64");
            if (!Files.isRegularFile(box64)) throw new IOException("Box64 binary is missing");
            ensureExecutable(box64);
            bionicHostExecutable = box64;
            // The x86_64 Wine binary is a guest ELF and must be passed to Box64,
            // not directly to Android's Bionic linker.
            guestArguments.add(wine64.toString());
            environment.put("BOX64_DYNAREC", "1");
            environment.put("BOX64_NOBANNER", "1");
            environment.put("BOX64_NORCFILES", "1");
            environment.put("BOX64_X11GLX", "1");
            environment.put("BOX64_PATH", imageFsRoot.resolve("usr/bin").toString());
            environment.put("BOX64_LD_LIBRARY_PATH", guestLibraryPath(container));
        } else {
            // The ARM64EC Wine host is a native Bionic ELF. Select the two
            // distinct Hangover/FEX backends: HODLL64 handles x86_64 PE code,
            // while HODLL handles 32-bit x86 PE code in the WoW64 layer.
            Path fex64 = container.system32.resolve("libarm64ecfex.dll");
            Path fex32 = container.system32.resolve("libwow64fex.dll");
            Path wowBox64 = container.system32.resolve("wowbox64.dll");
            if (Files.isRegularFile(fex64) && Files.isRegularFile(fex32)) {
                environment.put("HODLL64", "libarm64ecfex.dll");
                environment.put("HODLL", "libwow64fex.dll");
            } else if (Files.isRegularFile(wowBox64)) {
                environment.put("HODLL64", "wowbox64.dll");
            } else {
                throw new IOException("ARM64EC container has no complete FEXCore or WowBox64 backend");
            }
            bionicHostExecutable = wine64;
        }

        guestArguments.add(toWinePath(host));
        guestArguments.add(toWinePath(plugin));
        List<String> command = AndroidBionicProcessLauncher.command(bionicHostExecutable, guestArguments);

        ProcessBuilder builder = new ProcessBuilder(command);
        builder.directory(imageFsRoot.toFile());
        builder.environment().putAll(environment);
        builder.redirectErrorStream(false);
        Process process = builder.start();
        return new GuestProcess(process, logCallback, exitCallback);
    }

    private Map<String, String> baseWineEnvironment(Container container) throws IOException {
        return buildNativeEnvironment(
                privateRoot, imageFsRoot, container.wineRoot, container.architecture, execBridgeLibrary,
                container.winePrefix);
    }

    /**
     * Builds the environment for an Android/Bionic host process. Guest glibc
     * libraries must never appear in the host LD_LIBRARY_PATH: Box64 receives
     * those separately through BOX64_LD_LIBRARY_PATH. The exec bridge is
     * mandatory because Android 10+ may reject direct execution of app-private
     * ELF files by Wine/wineserver child processes.
     */
    static Map<String, String> buildNativeEnvironment(
            Path privateRoot,
            Path imageFsRoot,
            Path wineRoot,
            Architecture architecture,
            Path execBridgeLibrary,
            Path winePrefix) throws IOException {
        Path runtimeRoot = privateRoot.toRealPath();
        if (execBridgeLibrary == null
                || Files.isSymbolicLink(execBridgeLibrary)
                || !Files.isRegularFile(execBridgeLibrary, LinkOption.NOFOLLOW_LINKS)) {
            throw new IOException("Bionic exec bridge libeffectcraft-exec.so is not packaged in the APK nativeLibraryDir");
        }
        Path bridge = execBridgeLibrary.toRealPath();
        String root = imageFsRoot.toString();
        String winePath = wineRoot.resolve("bin").toString();

        Map<String, String> env = new HashMap<>();
        env.put("EFFECTCRAFT_RUNTIME_ROOT", runtimeRoot.toString());
        env.put("LD_PRELOAD", bridge.toString());
        env.put("HOME", root + "/home/xuser");
        env.put("USER", "xuser");
        env.put("TMPDIR", root + "/usr/tmp");
        env.put("XDG_DATA_DIRS", root + "/usr/share");
        env.put("XDG_CONFIG_DIRS", root + "/usr/etc/xdg");

        // Only Bionic host libraries belong here. The x86_64 glibc rootfs is
        // supplied to Box64 through BOX64_LD_LIBRARY_PATH, never to linker64.
        String nativeLibraryPath = "/system/lib64";
        if (architecture == Architecture.ARM64EC) {
            nativeLibraryPath = wineRoot.resolve("lib") + ":" + nativeLibraryPath;
        }
        env.put("LD_LIBRARY_PATH", nativeLibraryPath);

        String path = winePath;
        if (architecture == Architecture.X86_64) {
            path += ":" + root + "/usr/bin";
            env.put("GST_PLUGIN_PATH", root + "/usr/lib/gstreamer-1.0");
        }
        env.put("PATH", path);
        env.put("PREFIX", root + "/usr");
        env.put("WINEPREFIX", winePrefix.toString());
        env.put("WINE_NO_DUPLICATE_EXPLORER", "1");
        env.put("WINEDEBUG", "-all");
        env.put("DISPLAY", ":0");
        env.put("FONTCONFIG_PATH", root + "/usr/etc/fonts");
        env.put("SSL_CERT_FILE", root + "/usr/etc/tls/cert.pem");
        env.put("SSL_CERT_DIR", root + "/usr/etc/tls/certs");
        return env;
    }

    private String guestLibraryPath(Container container) {
        return imageFsRoot.resolve("lib/x86_64-linux-gnu") + ":"
                + imageFsRoot.resolve("usr/lib/x86_64-linux-gnu") + ":"
                + imageFsRoot.resolve("usr/lib") + ":"
                + container.wineRoot.resolve("lib/wine/x86_64-unix") + ":"
                + container.wineRoot.resolve("lib");
    }

    private static Path findWineExecutable(Path wineBin) throws IOException {
        Path wine64 = wineBin.resolve("wine64");
        if (Files.isRegularFile(wine64)) return wine64;
        Path wine = wineBin.resolve("wine");
        if (Files.isRegularFile(wine)) return wine;
        throw new IOException("Wine executable not found under " + wineBin);
    }

    private String toWinePath(Path hostPath) {
        String absolute = hostPath.toAbsolutePath().normalize().toString().replace(File.separatorChar, '\\');
        if (absolute.startsWith("\\\\")) return "Z:" + absolute;
        return "Z:" + absolute;
    }

    private static void ensureExecutable(Path file) throws IOException {
        try {
            Files.setPosixFilePermissions(file, java.util.EnumSet.of(
                    java.nio.file.attribute.PosixFilePermission.OWNER_READ,
                    java.nio.file.attribute.PosixFilePermission.OWNER_WRITE,
                    java.nio.file.attribute.PosixFilePermission.OWNER_EXECUTE,
                    java.nio.file.attribute.PosixFilePermission.GROUP_READ,
                    java.nio.file.attribute.PosixFilePermission.GROUP_EXECUTE,
                    java.nio.file.attribute.PosixFilePermission.OTHERS_READ,
                    java.nio.file.attribute.PosixFilePermission.OTHERS_EXECUTE));
        } catch (UnsupportedOperationException ignored) {
            file.toFile().setExecutable(true, false);
        }
    }

    private void ensureContainer(Container container, Architecture expected) throws IOException {
        if (container == null || container.architecture != expected
                || !container.root.toAbsolutePath().normalize().startsWith(containersRoot)) {
            throw new IOException("container architecture/root mismatch");
        }
    }

    private static void createDirectoriesNoSymlink(Path privateRoot, Path path) throws IOException {
        Path root = privateRoot.toAbsolutePath().normalize();
        Path normalized = path.toAbsolutePath().normalize();
        if (!normalized.startsWith(root)) throw new IOException("directory escapes private runtime root");
        if (Files.isSymbolicLink(root)) throw new IOException("private runtime root is a symlink");
        Path current = root;
        for (Path part : root.relativize(normalized)) {
            current = current.resolve(part);
            if (Files.exists(current, LinkOption.NOFOLLOW_LINKS)) {
                if (Files.isSymbolicLink(current) || !Files.isDirectory(current, LinkOption.NOFOLLOW_LINKS)) {
                    throw new IOException("unsafe runtime directory component: " + current);
                }
            } else {
                Files.createDirectory(current);
            }
        }
    }

    private static void deleteTree(Path path) throws IOException {
        if (!Files.exists(path, LinkOption.NOFOLLOW_LINKS)) return;
        if (Files.isSymbolicLink(path) || !Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) {
            Files.deleteIfExists(path);
            return;
        }
        try (var stream = Files.list(path)) {
            for (Path child : (Iterable<Path>) stream.sorted(Comparator.reverseOrder())::iterator) {
                deleteTree(child);
            }
        }
        Files.deleteIfExists(path);
    }

    private void ensureOpen() throws IOException {
        if (closed) throw new IOException("runtime manager is closed");
    }

    public Path getPrivateRoot() {
        return privateRoot;
    }

    public Path getImageFsRoot() {
        return imageFsRoot;
    }

    @Override
    public void close() {
        closed = true;
    }
}
