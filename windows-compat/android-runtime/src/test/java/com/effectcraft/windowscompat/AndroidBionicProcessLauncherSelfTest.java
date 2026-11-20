package com.effectcraft.windowscompat;

import java.nio.file.Paths;
import java.util.List;

/** Verifies that private Bionic executables are launched through Android's system linker. */
public final class AndroidBionicProcessLauncherSelfTest {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        List<String> command = AndroidBionicProcessLauncher.command(
                Paths.get("/data/user/0/com.effectcraft/files/imagefs/usr/bin/box64"),
                List.of("/data/user/0/com.effectcraft/files/imagefs/opt/wine/bin/wine",
                        "Z:\\tmp\\effectcraft-aex-host.exe",
                        "Z:\\tmp\\sample.aex"));

        check(command.size() == 5, "linker command must preserve every guest argument");
        check(command.get(0).equals("/system/bin/linker64"),
                "Android system linker64 must be the executable entry point");
        check(command.get(1).endsWith("/usr/bin/box64"),
                "the Bionic emulator executable must be loaded by linker64");
        check(command.get(2).endsWith("/bin/wine"),
                "the x86_64 Wine guest must remain an argument to Box64");
        check(command.get(3).endsWith("effectcraft-aex-host.exe"),
                "Windows host argument must be preserved");
        check(command.get(4).endsWith("sample.aex"),
                "AEX plug-in argument must be preserved");

        boolean rejected = false;
        try {
            AndroidBionicProcessLauncher.command(Paths.get("relative/box64"), List.of());
        } catch (IllegalArgumentException expected) {
            rejected = true;
        }
        check(rejected, "relative executable paths must be rejected");
        System.out.println("Android Bionic process launcher tests passed.");
    }
}
