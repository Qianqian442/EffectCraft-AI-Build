package com.effectcraft.windowscompat;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

/** Host-side tests for the experimental native-Bionic Hangover launch profile. */
public final class HangoverBionicLaunchProfileSelfTest {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static void touch(Path path) throws IOException {
        Files.createDirectories(path.getParent());
        Files.write(path, new byte[] { 0x7f, 'E', 'L', 'F' });
    }

    public static void main(String[] args) throws Exception {
        Path root = Files.createTempDirectory("effectcraft-hangover-profile");
        try {
            Path prefix = root.resolve("runtime");
            Path winePrefix = root.resolve("prefixes/x86_64");
            Path x86Prefix = root.resolve("prefixes/x86");
            Path guest = root.resolve("host/effectcraft-aex-host-x64.exe");

            Files.createDirectories(winePrefix);
            Files.createDirectories(x86Prefix);
            Files.createDirectories(root.resolve("home"));
            Files.createDirectories(root.resolve("tmp"));
            Files.createDirectories(prefix.resolve("lib"));
            Files.createDirectories(prefix.resolve("bin"));
            Files.createDirectories(prefix.resolve("opt/hangover-wine/bin"));
            Files.createDirectories(prefix.resolve(HangoverBionicLaunchProfile.WINE_UNIX_LIB_RELATIVE));
            Path windowsLib = prefix.resolve(HangoverBionicLaunchProfile.WINE_WINDOWS_LIB_RELATIVE);
            Files.createDirectories(windowsLib);

            touch(prefix.resolve(HangoverBionicLaunchProfile.WINE_RELATIVE));
            touch(prefix.resolve(HangoverBionicLaunchProfile.WINESERVER_RELATIVE));
            touch(prefix.resolve(HangoverBionicLaunchProfile.TERMUX_EXEC_RELATIVE));
            touch(windowsLib.resolve(HangoverBionicLaunchProfile.ARM64EC_DLL));
            touch(windowsLib.resolve(HangoverBionicLaunchProfile.WOW64_DLL));
            touch(windowsLib.resolve(HangoverBionicLaunchProfile.WOWBOX64_DLL));
            touch(guest);

            HangoverBionicLaunchProfile.LaunchSpec x64 = HangoverBionicLaunchProfile.create(
                    root, prefix, winePrefix, HangoverBionicLaunchProfile.GuestArchitecture.X86_64,
                    guest, List.of("--plugin", "Z:\\data\\sample.aex"));

            List<String> command = x64.command();
            check(command.size() == 5, "linker64 command must preserve guest executable and arguments");
            check(command.get(0).equals("/system/bin/linker64"), "Wine Bionic ELF must be entered through linker64");
            check(command.get(1).endsWith("/opt/hangover-wine/bin/wine64"), "Wine64 must be the Bionic host executable");
            check(command.get(2).equals(HangoverBionicLaunchProfile.toWineDosPath(guest)),
                    "Android private guest path must map to Wine Z: drive");
            check(command.get(3).equals("--plugin") && command.get(4).equals("Z:\\data\\sample.aex"),
                    "AEX worker arguments must remain unchanged");

            Map<String, String> env = x64.environment();
            check(env.get("WINEARCH").equals("win64"), "32-bit guests must use the 64-bit WoW64 prefix too");
            check(env.get("HODLL64").equals(HangoverBionicLaunchProfile.ARM64EC_DLL),
                    "ARM64EC x64 PE emulator must be explicitly selected");
            check(env.get("HODLL").equals(HangoverBionicLaunchProfile.WOW64_DLL),
                    "WoW64 x86 PE emulator must be explicitly selected");
            check(env.get("LD_PRELOAD").endsWith("/lib/libtermux-exec-ld-preload.so"),
                    "Termux exec bridge must handle Wine child exec calls");
            check(env.get("LD_LIBRARY_PATH").contains(prefix.resolve("lib").toString()),
                    "Bionic prefix libraries must be visible to the Wine host");
            check(env.get("LD_LIBRARY_PATH").contains("/system/lib64"),
                    "Android system Bionic libraries must remain visible");
            check(!env.get("LD_LIBRARY_PATH").contains("glibc"),
                    "glibc guest libraries must never enter the Bionic host loader path");
            check(x64.winePrefix().equals(winePrefix.toRealPath()), "x64 prefix must be isolated");

            HangoverBionicLaunchProfile.LaunchSpec x86 = HangoverBionicLaunchProfile.create(
                    root, prefix, x86Prefix, HangoverBionicLaunchProfile.GuestArchitecture.X86,
                    guest, List.of());
            check(x86.guestArchitecture() == HangoverBionicLaunchProfile.GuestArchitecture.X86,
                    "x86 guest architecture must be preserved");
            check(x86.winePrefix().equals(x86Prefix.toRealPath()), "x86 prefix must be separate from x64 prefix");

            boolean rejectedRelative = false;
            try {
                HangoverBionicLaunchProfile.toWineDosPath(Path.of("relative.exe"));
            } catch (IllegalArgumentException expected) {
                rejectedRelative = true;
            }
            check(rejectedRelative, "relative guest paths must be rejected");

            Path outside = Files.createTempFile("effectcraft-outside", ".exe");
            try {
                boolean rejectedOutside = false;
                try {
                    HangoverBionicLaunchProfile.create(root, prefix, winePrefix,
                            HangoverBionicLaunchProfile.GuestArchitecture.X86_64, outside, List.of());
                } catch (IOException expected) {
                    rejectedOutside = expected.getMessage().contains("escapes EffectCraft private storage");
                }
                check(rejectedOutside, "guest executable outside private storage must be rejected");
            } finally {
                Files.deleteIfExists(outside);
            }
            System.out.println("Hangover Bionic launch profile tests passed (configuration only; no PE execution).");
        } finally {
            try (Stream<Path> paths = Files.walk(root)) {
                paths.sorted(java.util.Comparator.reverseOrder()).forEach(path -> {
                    try { Files.deleteIfExists(path); } catch (IOException ignored) {}
                });
            }
        }
    }
}
