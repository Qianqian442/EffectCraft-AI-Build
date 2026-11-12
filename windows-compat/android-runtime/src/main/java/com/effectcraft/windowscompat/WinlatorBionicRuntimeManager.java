package com.effectcraft.windowscompat;

import java.io.BufferedReader;
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
        private volatile Integer exitCode;

        private GuestProcess(Process process, Consumer<String> logCallback, Consumer<Integer> exitCallback) {
            this.process = process;
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
    private volatile boolean closed;

    public WinlatorBionicRuntimeManager(Path privateRoot, RuntimeAssetInstaller.AssetFetcher fetcher)
            throws IOException {
        this.privateRoot = Objects.requireNonNull(privateRoot, "private root").toAbsolutePath().normalize();
        Files.createDirectories(this.privateRoot);
        if (Files.isSymbolicLink(this.privateRoot)) {
            throw new IOException("runtime root must not be a symlink");
        }
        this.imageFsRoot = this.privateRoot.resolve("imagefs");
        this.containersRoot = this.privateRoot.resolve("containers");
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
        Files.createDirectories(destination.getParent());
        Path archive = assets.downloadVerified(spec);
        extractor.extractTarXz(archive, destination);
    }

    private void installBox64() throws IOException {
        RuntimeAssetInstaller.AssetSpec spec = WinlatorBionicAssetCatalog.box64();
        contentPackages.install(spec, imageFsRoot,
                imageFsRoot.resolve("containers/not-used/system32"),
                imageFsRoot.resolve("containers/not-used/syswow64"));
    }

    public synchronized Container createContainer(String id, Architecture architecture) throws IOException {
        ensureOpen();
        if (id == null || !id.matches("[A-Za-z0-9._-]{1,80}")) {
            throw new IOException("invalid runtime container id");
        }
        Path root = containersRoot.resolve(id).normalize();
        if (!root.startsWith(containersRoot)) throw new IOException("container path escapes private runtime root");
        deleteTree(root);
        Files.createDirectories(root);

        RuntimeAssetInstaller.AssetSpec pattern = architecture == Architecture.X86_64
                ? WinlatorBionicAssetCatalog.x64ContainerPattern()
                : WinlatorBionicAssetCatalog.arm64EcContainerPattern();
        Path archive = assets.downloadVerified(pattern);
        extractor.extractTarZstd(archive, root);

        Path wineRoot = architecture == Architecture.X86_64
                ? imageFsRoot.resolve("opt/proton-9.0-x86_64")
                : imageFsRoot.resolve("opt/proton-9.0-arm64ec");
        Container container = new Container(id, architecture, root, wineRoot);
        Files.createDirectories(container.system32);
        Files.createDirectories(container.syswow64);
        installCommonWindowsDlls(container);
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
        List<String> command = new ArrayList<>();
        Map<String, String> environment = baseWineEnvironment(container);

        if (container.architecture == Architecture.X86_64) {
            Path box64 = imageFsRoot.resolve("usr/bin/box64");
            if (!Files.isRegularFile(box64)) throw new IOException("Box64 binary is missing");
            ensureExecutable(box64);
            command.add(box64.toString());
            environment.put("BOX64_DYNAREC", "1");
            environment.put("BOX64_NOBANNER", "1");
            environment.put("BOX64_NORCFILES", "1");
            environment.put("BOX64_X11GLX", "1");
            environment.put("BOX64_PATH", imageFsRoot.resolve("usr/bin").toString());
            environment.put("BOX64_LD_LIBRARY_PATH", guestLibraryPath());
        } else {
            // FEXCore or WowBox64 DLL selection is controlled by HODLL.
            if (!Files.exists(container.system32.resolve("libwow64fex.dll"))
                    && !Files.exists(container.system32.resolve("wowbox64.dll"))) {
                throw new IOException("ARM64EC container has no FEXCore or WowBox64 WoW64 DLL");
            }
            environment.put("HODLL", Files.exists(container.system32.resolve("libwow64fex.dll"))
                    ? "libwow64fex.dll" : "wowbox64.dll");
        }

        command.add(wine64.toString());
        command.add(toWinePath(host));
        command.add(toWinePath(plugin));

        ProcessBuilder builder = new ProcessBuilder(command);
        builder.directory(imageFsRoot.toFile());
        builder.environment().putAll(environment);
        builder.redirectErrorStream(false);
        Process process = builder.start();
        return new GuestProcess(process, logCallback, exitCallback);
    }

    private Map<String, String> baseWineEnvironment(Container container) {
        Map<String, String> env = new HashMap<>();
        String root = imageFsRoot.toString();
        String winePath = container.wineRoot.resolve("bin").toString();
        env.put("HOME", root + "/home/xuser");
        env.put("USER", "xuser");
        env.put("TMPDIR", root + "/usr/tmp");
        env.put("XDG_DATA_DIRS", root + "/usr/share");
        env.put("XDG_CONFIG_DIRS", root + "/usr/etc/xdg");
        env.put("LD_LIBRARY_PATH", root + "/usr/lib:/system/lib64");
        env.put("PATH", winePath + ":" + root + "/usr/bin");
        env.put("PREFIX", root + "/usr");
        env.put("WINEPREFIX", container.winePrefix.toString());
        env.put("WINE_NO_DUPLICATE_EXPLORER", "1");
        env.put("WINEDEBUG", "-all");
        env.put("DISPLAY", ":0");
        env.put("FONTCONFIG_PATH", root + "/usr/etc/fonts");
        env.put("SSL_CERT_FILE", root + "/usr/etc/tls/cert.pem");
        env.put("SSL_CERT_DIR", root + "/usr/etc/tls/certs");
        env.put("GST_PLUGIN_PATH", root + "/usr/lib/gstreamer-1.0");
        return env;
    }

    private String guestLibraryPath() {
        return imageFsRoot.resolve("lib/x86_64-linux-gnu") + ":"
                + imageFsRoot.resolve("usr/lib/x86_64-linux-gnu") + ":"
                + imageFsRoot.resolve("usr/lib");
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
