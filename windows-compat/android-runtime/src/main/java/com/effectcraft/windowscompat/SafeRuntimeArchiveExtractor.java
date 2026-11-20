package com.effectcraft.windowscompat;

import org.apache.commons.compress.archivers.ArchiveEntry;
import org.apache.commons.compress.archivers.tar.TarArchiveEntry;
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream;
import org.apache.commons.compress.compressors.xz.XZCompressorInputStream;
import org.apache.commons.compress.compressors.zstandard.ZstdCompressorInputStream;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermission;
import java.util.EnumSet;
import java.util.Set;

/**
 * Streaming TAR.XZ/TAR.Zstandard extractor for a private runtime root.
 *
 * There is no total archive-size, entry-count, uncompressed-size or RAM budget.
 * Bytes are streamed using a fixed-size transfer buffer. Safety checks prevent
 * archive path traversal and symlinks/hardlinks that resolve outside the
 * selected private root. Guest-root absolute symlinks such as /usr/bin/python
 * are rewritten as relative links rooted inside the private filesystem.
 *
 * Special device nodes, sockets and FIFOs are skipped; Android apps cannot
 * create them in ordinary private storage without privileged support.
 */
public final class SafeRuntimeArchiveExtractor implements RuntimeAssetInstaller.ArchiveExtractor {
    private static final int BUFFER_SIZE = 64 * 1024;

    @Override
    public void extractTarXz(Path archive, Path privateTarget) throws IOException {
        try (InputStream file = new BufferedInputStream(Files.newInputStream(archive));
             InputStream xz = new XZCompressorInputStream(file, true)) {
            extractTar(xz, privateTarget);
        }
    }

    @Override
    public void extractTarZstd(Path archive, Path privateTarget) throws IOException {
        try (InputStream file = new BufferedInputStream(Files.newInputStream(archive));
             InputStream zstd = new ZstdCompressorInputStream(file)) {
            extractTar(zstd, privateTarget);
        }
    }

    private void extractTar(InputStream compressedTar, Path privateTarget) throws IOException {
        Path root = privateTarget.toAbsolutePath().normalize();
        Files.createDirectories(root);
        if (Files.isSymbolicLink(root)) {
            throw new IOException("private extraction root cannot be a symbolic link");
        }

        try (TarArchiveInputStream tar = new TarArchiveInputStream(
                new BufferedInputStream(compressedTar), "UTF-8")) {
            TarArchiveEntry entry;
            byte[] buffer = new byte[BUFFER_SIZE];
            while ((entry = tar.getNextTarEntry()) != null) {
                if (!tar.canReadEntryData(entry)) {
                    throw new IOException("unsupported TAR entry encoding: " + entry.getName());
                }

                Path output = resolveEntry(root, entry.getName());
                if (entry.isDirectory()) {
                    createDirectoriesNoSymlink(root, output);
                } else if (entry.isSymbolicLink()) {
                    createSymbolicLink(root, output, entry.getLinkName());
                } else if (entry.isLink()) {
                    createHardLink(root, output, entry.getLinkName());
                } else if (entry.isFile()) {
                    extractRegularFile(root, output, entry, tar, buffer);
                } else {
                    // Character/block devices, sockets and FIFOs are not materialized.
                    // Their parent directories still exist in the guest filesystem.
                }
            }
        }
    }

    private static Path resolveEntry(Path root, String rawName) throws IOException {
        if (rawName == null || rawName.isEmpty()) {
            throw new IOException("empty TAR entry path");
        }
        String portable = rawName.replace('\\', '/');
        while (portable.startsWith("./")) portable = portable.substring(2);
        // An absolute name in a rootfs archive is interpreted relative to that
        // rootfs, never as an Android host absolute path.
        while (portable.startsWith("/")) portable = portable.substring(1);
        if (portable.isEmpty()) return root;
        if (portable.matches("(?i)^[a-z]:.*")) {
            throw new IOException("Windows drive path in TAR entry: " + rawName);
        }
        Path relative = Paths.get(portable);
        if (relative.isAbsolute()) throw new IOException("absolute TAR entry rejected: " + rawName);
        Path output = root.resolve(relative).normalize();
        if (!output.startsWith(root)) {
            throw new IOException("TAR entry escapes private root: " + rawName);
        }
        return output;
    }

    private static void createDirectoriesNoSymlink(Path root, Path output) throws IOException {
        ensureInside(root, output);
        Path current = root;
        Path relative = root.relativize(output);
        for (Path part : relative) {
            current = current.resolve(part);
            if (Files.exists(current, LinkOption.NOFOLLOW_LINKS)) {
                if (Files.isSymbolicLink(current)) {
                    throw new IOException("TAR directory path crosses a symlink: " + current);
                }
                if (!Files.isDirectory(current, LinkOption.NOFOLLOW_LINKS)) {
                    throw new IOException("TAR directory conflicts with a file: " + current);
                }
            } else {
                Files.createDirectory(current);
            }
        }
    }

    private static void createSymbolicLink(Path root, Path output, String rawTarget) throws IOException {
        ensureInside(root, output);
        if (rawTarget == null || rawTarget.isEmpty()) {
            throw new IOException("empty TAR symlink target at " + output);
        }
        Path parent = output.getParent();
        if (parent == null) throw new IOException("symlink has no parent: " + output);
        createDirectoriesNoSymlink(root, parent);

        String portable = rawTarget.replace('\\', '/');
        Path guestTarget;
        if (portable.startsWith("/")) {
            // In a chroot/PRoot rootfs, /usr/lib is guest-root-relative.
            guestTarget = root.resolve(portable.substring(1)).normalize();
        } else {
            guestTarget = parent.resolve(portable).normalize();
        }
        ensureInside(root, guestTarget);

        Path relativeTarget = parent.relativize(guestTarget);
        if (Files.exists(output, LinkOption.NOFOLLOW_LINKS)) {
            throw new FileAlreadyExistsException(output.toString());
        }
        Files.createSymbolicLink(output, relativeTarget);
    }

    private static void createHardLink(Path root, Path output, String rawTarget) throws IOException {
        ensureInside(root, output);
        String portable = rawTarget.replace('\\', '/');
        while (portable.startsWith("/")) portable = portable.substring(1);
        Path target = root.resolve(portable).normalize();
        ensureInside(root, target);
        Path parent = output.getParent();
        if (parent == null) throw new IOException("hard link has no parent: " + output);
        createDirectoriesNoSymlink(root, parent);
        rejectSymlinkAncestors(root, target);
        if (!Files.isRegularFile(target, LinkOption.NOFOLLOW_LINKS)) {
            throw new IOException("TAR hard-link target is missing or not a regular file: " + target);
        }
        if (Files.exists(output, LinkOption.NOFOLLOW_LINKS)) {
            throw new FileAlreadyExistsException(output.toString());
        }
        try {
            Files.createLink(output, target);
        } catch (UnsupportedOperationException | IOException linkFailure) {
            // A copy fallback preserves the guest file contents if hard-links
            // are not supported by the Android filesystem. No fixed size cap.
            try (InputStream input = Files.newInputStream(target);
                 OutputStream stream = Files.newOutputStream(output, StandardOpenOption.CREATE_NEW)) {
                copy(input, stream, new byte[BUFFER_SIZE]);
            }
        }
    }

    private static void extractRegularFile(
            Path root,
            Path output,
            TarArchiveEntry entry,
            InputStream tar,
            byte[] buffer) throws IOException {
        ensureInside(root, output);
        Path parent = output.getParent();
        if (parent == null) throw new IOException("file entry has no parent: " + output);
        createDirectoriesNoSymlink(root, parent);
        rejectSymlinkAncestors(root, parent);
        if (Files.exists(output, LinkOption.NOFOLLOW_LINKS)) {
            if (Files.isSymbolicLink(output) || Files.isDirectory(output, LinkOption.NOFOLLOW_LINKS)) {
                throw new IOException("TAR file conflicts with existing non-file: " + output);
            }
            Files.delete(output);
        }
        try (OutputStream out = Files.newOutputStream(output, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
            copy(tar, out, buffer);
        }
        applyFileMode(output, entry.getMode());
    }

    private static void copy(InputStream input, OutputStream output, byte[] buffer) throws IOException {
        int read;
        while ((read = input.read(buffer)) != -1) {
            if (read > 0) output.write(buffer, 0, read);
        }
        output.flush();
    }

    private static void applyFileMode(Path file, int mode) {
        try {
            Set<PosixFilePermission> permissions = EnumSet.noneOf(PosixFilePermission.class);
            if ((mode & 0400) != 0) permissions.add(PosixFilePermission.OWNER_READ);
            if ((mode & 0200) != 0) permissions.add(PosixFilePermission.OWNER_WRITE);
            if ((mode & 0100) != 0) permissions.add(PosixFilePermission.OWNER_EXECUTE);
            if ((mode & 0040) != 0) permissions.add(PosixFilePermission.GROUP_READ);
            if ((mode & 0020) != 0) permissions.add(PosixFilePermission.GROUP_WRITE);
            if ((mode & 0010) != 0) permissions.add(PosixFilePermission.GROUP_EXECUTE);
            if ((mode & 0004) != 0) permissions.add(PosixFilePermission.OTHERS_READ);
            if ((mode & 0002) != 0) permissions.add(PosixFilePermission.OTHERS_WRITE);
            if ((mode & 0001) != 0) permissions.add(PosixFilePermission.OTHERS_EXECUTE);
            Files.setPosixFilePermissions(file, permissions);
        } catch (IOException | UnsupportedOperationException ignored) {
            // Android's app-private filesystem or provider may not expose POSIX modes.
            // The launcher can apply executable bits separately to known guest binaries.
        }
    }

    private static void rejectSymlinkAncestors(Path root, Path path) throws IOException {
        ensureInside(root, path);
        Path current = root;
        for (Path part : root.relativize(path)) {
            current = current.resolve(part);
            if (Files.isSymbolicLink(current)) {
                throw new IOException("TAR extraction refuses to write through a symlink: " + current);
            }
        }
    }

    private static void ensureInside(Path root, Path path) throws IOException {
        Path normalized = path.toAbsolutePath().normalize();
        if (!normalized.startsWith(root)) {
            throw new IOException("archive path escapes private root: " + path);
        }
    }
}
