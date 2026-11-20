package com.effectcraft.windowscompat;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Builds a native-Bionic Hangover launch profile.
 *
 * Wine itself is a Bionic ARM64 ELF and is entered through Android linker64.
 * Hangover then loads Windows PE guests through ARM64EC/FEX and WoW64/FEX.
 * This deliberately does not wrap Bionic Wine in Box64 or mix glibc guest
 * libraries into the Bionic host loader path.
 *
 * The profile is experimental until a package installed under the EffectCraft
 * UID has passed on-device Win32 and x86_64 PE smoke tests.
 */
public final class HangoverBionicLaunchProfile {
    public enum GuestArchitecture {
        X86,
        X86_64
    }

    public static final String WINE_RELATIVE = "opt/hangover-wine/bin/wine64";
    public static final String WINESERVER_RELATIVE = "opt/hangover-wine/bin/wineserver";
    public static final String TERMUX_EXEC_RELATIVE = "lib/libtermux-exec-ld-preload.so";
    public static final String WINE_UNIX_LIB_RELATIVE = "opt/hangover-wine/lib/wine/aarch64-unix";
    public static final String WINE_WINDOWS_LIB_RELATIVE = "opt/hangover-wine/lib/wine/aarch64-windows";
    public static final String ARM64EC_DLL = "libarm64ecfex.dll";
    public static final String WOW64_DLL = "libwow64fex.dll";
    public static final String WOWBOX64_DLL = "wowbox64.dll";

    private HangoverBionicLaunchProfile() {}

    public static final class LaunchSpec {
        private final List<String> command;
        private final Map<String, String> environment;
        private final Path winePrefix;
        private final GuestArchitecture guestArchitecture;

        private LaunchSpec(List<String> command, Map<String, String> environment,
                           Path winePrefix, GuestArchitecture guestArchitecture) {
            this.command = Collections.unmodifiableList(new ArrayList<>(command));
            this.environment = Collections.unmodifiableMap(new LinkedHashMap<>(environment));
            this.winePrefix = winePrefix;
            this.guestArchitecture = guestArchitecture;
        }

        public List<String> command() { return command; }
        public Map<String, String> environment() { return environment; }
        public Path winePrefix() { return winePrefix; }
        public GuestArchitecture guestArchitecture() { return guestArchitecture; }
    }

    /**
     * Create a headless console/worker launch profile. The caller must create
     * separate 64-bit Wine prefixes for x86 and x86_64 guests and pass a guest
     * EXE stored inside EffectCraft's private data directory.
     */
    public static LaunchSpec create(Path privateRoot, Path runtimePrefix, Path winePrefix,
                                    GuestArchitecture guestArchitecture, Path guestExecutable,
                                    List<String> guestArguments) throws IOException {
        Objects.requireNonNull(privateRoot, "privateRoot");
        Objects.requireNonNull(runtimePrefix, "runtimePrefix");
        Objects.requireNonNull(winePrefix, "winePrefix");
        Objects.requireNonNull(guestArchitecture, "guestArchitecture");
        Objects.requireNonNull(guestExecutable, "guestExecutable");
        Objects.requireNonNull(guestArguments, "guestArguments");

        Path root = requireDirectory(privateRoot, "EffectCraft private runtime root");
        Path prefix = requireInside(root, runtimePrefix, "Hangover runtime prefix");
        Path prefixDir = requireDirectory(prefix, "Hangover runtime prefix");
        Path winePrefixDir = requireDirectory(requireInside(root, winePrefix, "Wine prefix"), "Wine prefix");
        Path guestExe = requireFile(requireInside(root, guestExecutable, "Windows guest executable"),
                "Windows guest executable");

        Path wine = requireFile(prefixDir.resolve(WINE_RELATIVE), "Hangover wine64 Bionic ELF");
        Path wineServer = requireFile(prefixDir.resolve(WINESERVER_RELATIVE), "Hangover wineserver Bionic ELF");
        Path execBridge = requireFile(prefixDir.resolve(TERMUX_EXEC_RELATIVE), "Termux exec preload library");
        Path unixLib = requireDirectory(prefixDir.resolve(WINE_UNIX_LIB_RELATIVE), "Wine aarch64-unix libraries");
        Path windowsLib = requireDirectory(prefixDir.resolve(WINE_WINDOWS_LIB_RELATIVE), "Wine aarch64-windows PE libraries");
        requireFile(windowsLib.resolve(ARM64EC_DLL), "Hangover ARM64EC FEX PE emulator");
        requireFile(windowsLib.resolve(WOW64_DLL), "Hangover WoW64 FEX PE emulator");
        requireFile(windowsLib.resolve(WOWBOX64_DLL), "Hangover WowBox64 PE fallback");

        Path home = requireDirectory(root.resolve("home"), "Hangover HOME");
        Path temp = requireDirectory(root.resolve("tmp"), "Hangover TMPDIR");
        Path prefixLib = requireDirectory(prefixDir.resolve("lib"), "Bionic prefix libraries");
        Path wineLib = requireDirectory(prefixDir.resolve("opt/hangover-wine/lib"), "Hangover Wine libraries");
        Path prefixBin = requireDirectory(prefixDir.resolve("bin"), "Termux prefix bin");
        Path wineBin = requireDirectory(prefixDir.resolve("opt/hangover-wine/bin"), "Hangover Wine bin");

        List<String> guestCommand = new ArrayList<>();
        guestCommand.add(toWineDosPath(guestExe));
        for (String argument : guestArguments) {
            guestCommand.add(Objects.requireNonNull(argument, "guest argument"));
        }

        List<String> command = AndroidBionicProcessLauncher.command(wine, guestCommand);
        Map<String, String> environment = new LinkedHashMap<>();
        environment.put("PREFIX", prefixDir.toString());
        environment.put("TERMUX_PREFIX", prefixDir.toString());
        environment.put("HOME", home.toString());
        environment.put("TMPDIR", temp.toString());
        environment.put("XDG_RUNTIME_DIR", temp.toString());
        environment.put("PATH", prefixBin + ":" + wineBin + ":/system/bin");
        environment.put("LD_PRELOAD", execBridge.toString());
        environment.put("LD_LIBRARY_PATH", prefixLib + ":" + wineLib + ":" + unixLib + ":/system/lib64");
        environment.put("WINEPREFIX", winePrefixDir.toString());
        // Hangover's WoW64 mode runs 32-bit PE guests inside a 64-bit Wine prefix.
        environment.put("WINEARCH", "win64");
        environment.put("WINELOADER", wine.toString());
        environment.put("WINESERVER", wineServer.toString());
        environment.put("WINEDLLPATH", windowsLib.toString());
        environment.put("HODLL64", ARM64EC_DLL);
        environment.put("HODLL", WOW64_DLL);
        environment.put("WINEDEBUG", "-all");
        environment.put("EFFECTCRAFT_HANGOVER_GUEST_ARCH",
                guestArchitecture == GuestArchitecture.X86_64 ? "x86_64" : "x86");
        return new LaunchSpec(command, environment, winePrefixDir, guestArchitecture);
    }

    /** Convert an absolute Android path to Wine's default Z: drive mapping. */
    public static String toWineDosPath(Path androidPath) {
        Objects.requireNonNull(androidPath, "androidPath");
        if (!androidPath.isAbsolute()) {
            throw new IllegalArgumentException("Android guest path must be absolute");
        }
        String path = androidPath.normalize().toString().replace('/', '\\');
        if (path.startsWith("\\")) path = path.substring(1);
        return "Z:\\" + path;
    }

    private static Path requireDirectory(Path path, String label) throws IOException {
        Path real = path.toRealPath();
        if (!Files.isDirectory(real)) throw new IOException(label + " is not a directory: " + real);
        return real;
    }

    private static Path requireFile(Path path, String label) throws IOException {
        Path real = path.toRealPath();
        if (!Files.isRegularFile(real)) throw new IOException(label + " is not a regular file: " + real);
        return real;
    }

    private static Path requireInside(Path root, Path child, String label) throws IOException {
        Path realRoot = root.toRealPath();
        Path realChild = child.toRealPath();
        if (!realChild.startsWith(realRoot)) {
            throw new IOException(label + " escapes EffectCraft private storage: " + realChild);
        }
        return realChild;
    }
}
