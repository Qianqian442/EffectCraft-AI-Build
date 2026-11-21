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
        List<String> qemu = AndroidBionicProcessLauncher.qemuUserCommand(
                Paths.get("/data/user/0/com.effectcraft/files/windows-compat/usr/bin/qemu-x86_64"),
                Paths.get("/data/user/0/com.effectcraft/files/windows-compat/guest"),
                Paths.get("/data/user/0/com.effectcraft/files/windows-compat/guest/bin/wine"),
                List.of("--version"));
        check(qemu.get(0).equals("/system/bin/linker64"),
                "QEMU Bionic launcher must use system linker64");
        check(qemu.get(1).endsWith("/usr/bin/qemu-x86_64"),
                "QEMU ARM64 binary must be started as a Bionic executable");
        check(qemu.get(2).equals("-L") && qemu.get(3).endsWith("/guest"),
                "QEMU must receive the x86_64 guest rootfs prefix");
        check(qemu.get(4).endsWith("/guest/bin/wine") && qemu.get(5).equals("--version"),
                "QEMU must preserve guest executable and arguments");

        List<String> box86 = AndroidBionicProcessLauncher.box86Command(
                Paths.get("/data/user/0/com.effectcraft/files/windows-compat/engines/box86/usr/bin/box86"),
                List.of("/data/user/0/com.effectcraft/files/windows-compat/i386/usr/bin/wine", "--version"));
        check(box86.get(0).equals("/system/bin/linker"),
                "Box86 ARMv7 Bionic binary must use the 32-bit system linker");
        check(box86.get(1).endsWith("/usr/bin/box86"),
                "Box86 runtime path must be preserved");
        check(box86.get(2).endsWith("/usr/bin/wine") && box86.get(3).equals("--version"),
                "Box86 guest arguments must be preserved");

        System.out.println("Android Bionic process launcher tests passed.");
    }
}
