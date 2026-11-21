package com.effectcraft.windowscompat;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;

/**
 * Builds commands that load app-private Bionic executables through Android's
 * system linker. Starting an executable directly from app-private storage can
 * be blocked by Android's app execution policy; /system/bin/linker64 is the
 * supported entry point for 64-bit Bionic ELF payloads.
 *
 * This does not make glibc ELF binaries Bionic-compatible. Guest x86 Linux
 * binaries must still be started by their selected emulator (for example Box64).
 */
public final class AndroidBionicProcessLauncher {
    public static final String SYSTEM_LINKER64 = "/system/bin/linker64";
    public static final String SYSTEM_LINKER32 = "/system/bin/linker";

    private AndroidBionicProcessLauncher() {}

    public static List<String> command(Path bionicExecutable, List<String> arguments) {
        Objects.requireNonNull(bionicExecutable, "Bionic executable");
        Objects.requireNonNull(arguments, "arguments");
        if (!bionicExecutable.isAbsolute()) {
            throw new IllegalArgumentException("Bionic executable path must be absolute");
        }
        List<String> command = new ArrayList<>(arguments.size() + 2);
        command.add(SYSTEM_LINKER64);
        command.add(bionicExecutable.normalize().toString());
        for (String argument : arguments) {
            command.add(Objects.requireNonNull(argument, "command argument"));
        }
        return Collections.unmodifiableList(command);
    }

    /** Build a QEMU Linux-user command; guest paths are interpreted inside the supplied rootfs. */
    public static List<String> qemuUserCommand(
            Path qemuExecutable, Path guestRoot, Path guestExecutable, List<String> guestArguments) {
        Objects.requireNonNull(guestRoot, "guest root");
        Objects.requireNonNull(guestExecutable, "guest executable");
        Objects.requireNonNull(guestArguments, "guest arguments");
        List<String> arguments = new ArrayList<>(guestArguments.size() + 3);
        arguments.add("-L");
        arguments.add(guestRoot.toAbsolutePath().normalize().toString());
        arguments.add(guestExecutable.toAbsolutePath().normalize().toString());
        for (String argument : guestArguments) {
            arguments.add(Objects.requireNonNull(argument, "guest argument"));
        }
        return command(qemuExecutable, arguments);
    }

    /** Box86 is a 32-bit Bionic ELF and requires the optional system linker32 ABI. */
    public static List<String> box86Command(Path box86Executable, List<String> guestArguments) {
        Objects.requireNonNull(box86Executable, "Box86 executable");
        Objects.requireNonNull(guestArguments, "guest arguments");
        if (!box86Executable.isAbsolute()) {
            throw new IllegalArgumentException("Box86 executable path must be absolute");
        }
        List<String> command = new ArrayList<>(guestArguments.size() + 2);
        command.add(SYSTEM_LINKER32);
        command.add(box86Executable.normalize().toString());
        for (String argument : guestArguments) {
            command.add(Objects.requireNonNull(argument, "guest argument"));
        }
        return Collections.unmodifiableList(command);
    }

    /**
     * Builds a 32-bit Bionic command for optional ARMv7 engines such as Box86.
     * Callers must first verify that the device actually ships /system/bin/linker
     * and advertises a 32-bit ABI; 64-bit-only Android builds cannot use this path.
     */
    public static List<String> command32(Path bionicExecutable, List<String> arguments) {
        Objects.requireNonNull(bionicExecutable, "Bionic executable");
        Objects.requireNonNull(arguments, "arguments");
        if (!bionicExecutable.isAbsolute()) {
            throw new IllegalArgumentException("Bionic executable path must be absolute");
        }
        List<String> command = new ArrayList<>(arguments.size() + 2);
        command.add(SYSTEM_LINKER32);
        command.add(bionicExecutable.normalize().toString());
        for (String argument : arguments) {
            command.add(Objects.requireNonNull(argument, "command argument"));
        }
        return Collections.unmodifiableList(command);
    }
}
