package com.effectcraft.windowscompat;

import org.apache.commons.compress.archivers.tar.TarArchiveEntry;
import org.apache.commons.compress.archivers.tar.TarArchiveOutputStream;
import org.apache.commons.compress.archivers.tar.TarConstants;
import org.apache.commons.compress.compressors.xz.XZCompressorOutputStream;
import org.apache.commons.compress.compressors.zstandard.ZstdCompressorOutputStream;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;

/** End-to-end tests of streaming XZ/Zstandard TAR extraction and archive safety. */
public final class SafeRuntimeArchiveExtractorSelfTest {
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void addDirectory(TarArchiveOutputStream tar, String path) throws IOException {
        TarArchiveEntry entry = new TarArchiveEntry(path.endsWith("/") ? path : path + "/");
        entry.setMode(0755);
        tar.putArchiveEntry(entry);
        tar.closeArchiveEntry();
    }

    private static void addFile(TarArchiveOutputStream tar, String path, byte[] data) throws IOException {
        TarArchiveEntry entry = new TarArchiveEntry(path);
        entry.setSize(data.length);
        entry.setMode(0755);
        tar.putArchiveEntry(entry);
        tar.write(data);
        tar.closeArchiveEntry();
    }

    private static void addAbsoluteGuestSymlink(TarArchiveOutputStream tar, String path, String target)
            throws IOException {
        TarArchiveEntry entry = new TarArchiveEntry(path, TarConstants.LF_SYMLINK);
        entry.setLinkName(target);
        tar.putArchiveEntry(entry);
        tar.closeArchiveEntry();
    }

    private static void makeXzTar(Path output, boolean traversal) throws IOException {
        try (OutputStream file = Files.newOutputStream(output);
             XZCompressorOutputStream xz = new XZCompressorOutputStream(file);
             TarArchiveOutputStream tar = new TarArchiveOutputStream(xz)) {
            addDirectory(tar, "usr/bin");
            addFile(tar, "usr/bin/wine64", "wine-runtime".getBytes(StandardCharsets.UTF_8));
            addAbsoluteGuestSymlink(tar, "bin", "/usr/bin");
            if (traversal) {
                addFile(tar, "../outside.txt", "must-not-escape".getBytes(StandardCharsets.UTF_8));
            }
        }
    }

    private static void makeZstdTar(Path output) throws IOException {
        try (OutputStream file = Files.newOutputStream(output);
             ZstdCompressorOutputStream zstd = new ZstdCompressorOutputStream(file);
             TarArchiveOutputStream tar = new TarArchiveOutputStream(zstd)) {
            addDirectory(tar, "opt/proton");
            addFile(tar, "opt/proton/proton", "proton-binary".getBytes(StandardCharsets.UTF_8));
        }
    }

    public static void main(String[] args) throws Exception {
        Path base = Files.createTempDirectory("effectcraft-runtime-extractor-test");
        try {
            SafeRuntimeArchiveExtractor extractor = new SafeRuntimeArchiveExtractor();
            Path xz = base.resolve("rootfs.txz");
            Path xzRoot = base.resolve("imagefs");
            makeXzTar(xz, false);
            extractor.extractTarXz(xz, xzRoot);

            check(Files.readString(xzRoot.resolve("usr/bin/wine64")).equals("wine-runtime"),
                    "XZ TAR file contents must be extracted");
            check(Files.isSymbolicLink(xzRoot.resolve("bin")),
                    "guest-root absolute symlink must be materialized");
            Path target = Files.readSymbolicLink(xzRoot.resolve("bin"));
            check(target.toString().equals("usr/bin"),
                    "absolute guest symlink must be rewritten to an in-root relative link");

            Path zstd = base.resolve("container.tzst");
            Path zstdRoot = base.resolve("container");
            makeZstdTar(zstd);
            extractor.extractTarZstd(zstd, zstdRoot);
            check(Files.readString(zstdRoot.resolve("opt/proton/proton")).equals("proton-binary"),
                    "Zstandard TAR file contents must be extracted");

            Path badArchive = base.resolve("traversal.txz");
            makeXzTar(badArchive, true);
            boolean rejected = false;
            try {
                extractor.extractTarXz(badArchive, base.resolve("bad-root"));
            } catch (IOException expected) {
                rejected = true;
            }
            check(rejected, "TAR path traversal must be rejected");
            check(!Files.exists(base.resolve("outside.txt")),
                    "path traversal must not write outside the private root");

            System.out.println("Safe runtime archive extraction tests passed.");
        } finally {
            try (var paths = Files.walk(base)) {
                paths.sorted(Comparator.reverseOrder()).forEach(path -> {
                    try {
                        Files.deleteIfExists(path);
                    } catch (IOException ignored) {}
                });
            }
        }
    }
}
