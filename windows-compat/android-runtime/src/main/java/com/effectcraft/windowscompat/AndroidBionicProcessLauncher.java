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
}
