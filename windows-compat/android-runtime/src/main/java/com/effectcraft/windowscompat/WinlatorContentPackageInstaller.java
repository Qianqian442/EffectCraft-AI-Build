package com.effectcraft.windowscompat;

import com.google.gson.Gson;
import com.google.gson.JsonParseException;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermission;
import java.util.ArrayList;
import java.util.Collections;
import java.util.EnumSet;
import java.util.List;
import java.util.Locale;
import java.util.Objects;

/**
 * Installs Winlator Bionic .tzst content packages using their profile.json
 * mapping. Only audited Box64/FEXCore/WowBox64 profiles and target paths are
 * accepted. The compressed package is checksum-verified before extraction.
 *
 * This implements the small, relevant subset of Winlator ContentsManager;
 * it deliberately does not accept arbitrary external path templates.
 */
public final class WinlatorContentPackageInstaller {
    private static final int BUFFER_SIZE = 64 * 1024;

    private static final class Profile {
        String type;
        String versionName;
        int versionCode;
        String description;
        List<ProfileFile> files;
    }

    private static final class ProfileFile {
        String source;
        String target;
    }

    public static final class InstallResult {
        public final String type;
        public final String versionName;
        public final int versionCode;
        public final List<Path> installedFiles;

        private InstallResult(String type, String versionName, int versionCode, List<Path> installedFiles) {
            this.type = type;
            this.versionName = versionName;
            this.versionCode = versionCode;
            this.installedFiles = Collections.unmodifiableList(new ArrayList<>(installedFiles));
        }
    }

    private final RuntimeAssetInstaller assets;
    private final SafeRuntimeArchiveExtractor extractor;
    private final Gson gson = new Gson();

    public WinlatorContentPackageInstaller(
            RuntimeAssetInstaller assets,
            SafeRuntimeArchiveExtractor extractor) {
        this.assets = Objects.requireNonNull(assets, "asset installer");
        this.extractor = Objects.requireNonNull(extractor, "archive extractor");
    }

    public InstallResult install(
            RuntimeAssetInstaller.AssetSpec packageSpec,
            Path imageFsRoot,
            Path containerSystem32,
            Path containerSysWow64) throws IOException {
        Objects.requireNonNull(packageSpec, "package spec");
        Path root = assets.getPrivateRoot().toAbsolutePath().normalize();
        Path imageFs = imageFsRoot.toAbsolutePath().normalize();
        Path system32 = containerSystem32.toAbsolutePath().normalize();
        Path syswow64 = containerSysWow64.toAbsolutePath().normalize();
        if (!imageFs.startsWith(root) || !system32.startsWith(root) || !syswow64.startsWith(root)) {
            throw new IOException("content package destinations must be within the private runtime root");
        }

        Path archive = assets.downloadVerified(packageSpec);
        Path staging = root.resolve("staging").resolve(safeId(packageSpec.id)).normalize();
        if (!staging.startsWith(root)) throw new IOException("unsafe package staging directory");
        deleteRecursively(staging);
        Files.createDirectories(staging);

        try {
            extractor.extractTarZstd(archive, staging);
            Path profileFile = staging.resolve("profile.json").normalize();
            if (!profileFile.startsWith(staging) || !Files.isRegularFile(profileFile, LinkOption.NOFOLLOW_LINKS)
                    || Files.isSymbolicLink(profileFile)) {
                throw new IOException("Winlator package does not contain a safe profile.json");
            }
            Profile profile;
            try {
                profile = gson.fromJson(
                        new String(Files.readAllBytes(profileFile), java.nio.charset.StandardCharsets.UTF_8),
                        Profile.class);
            } catch (JsonParseException error) {
                throw new IOException("invalid Winlator content profile", error);
            }
            validateProfile(profile);

            List<Path> destinations = new ArrayList<>();
            for (ProfileFile file : profile.files) {
                Path source = resolveSource(staging, file.source);
                Path destination = resolveTarget(
                        profile.type, file.target, imageFs, system32, syswow64);
                installOne(source, destination, root, profile.type.equalsIgnoreCase("Box64"));
                destinations.add(destination);
            }
            return new InstallResult(profile.type, profile.versionName, profile.versionCode, destinations);
        } finally {
            deleteRecursively(staging);
        }
    }

    private static void validateProfile(Profile profile) throws IOException {
        if (profile == null || profile.type == null || profile.versionName == null
                || profile.versionName.trim().isEmpty() || profile.files == null || profile.files.isEmpty()) {
            throw new IOException("Winlator content profile is missing required fields");
        }
        if (!profile.type.equalsIgnoreCase("Box64")
                && !profile.type.equalsIgnoreCase("FEXCore")
                && !profile.type.equalsIgnoreCase("WOWBox64")) {
            throw new IOException("unapproved Winlator content type: " + profile.type);
        }
        if (profile.files.size() > 16) {
            throw new IOException("unexpected number of files in the small emulator package profile");
        }
    }

    private static Path resolveSource(Path staging, String rawSource) throws IOException {
        if (rawSource == null || rawSource.trim().isEmpty()) throw new IOException("empty package source path");
        Path relative = java.nio.file.Paths.get(rawSource.replace('\\', '/'));
        if (relative.isAbsolute()) throw new IOException("absolute package source path");
        Path source = staging.resolve(relative).normalize();
        if (!source.startsWith(staging) || Files.isSymbolicLink(source)
                || !Files.isRegularFile(source, LinkOption.NOFOLLOW_LINKS)) {
            throw new IOException("package source is missing or unsafe: " + rawSource);
        }
        rejectSymlinkParents(staging, source.getParent());
        return source;
    }

    private static Path resolveTarget(
            String type, String template, Path imageFs, Path system32, Path syswow64) throws IOException {
        if (template == null || template.indexOf("..") >= 0) {
            throw new IOException("unsafe Winlator content target");
        }
        String normalized = template.replace('\\', '/');
        Path base;
        String suffix;
        if (normalized.startsWith("${bindir}/")) {
            base = imageFs.resolve("usr/bin");
            suffix = normalized.substring("${bindir}/".length());
            if (!type.equalsIgnoreCase("Box64") || !suffix.equals("box64")) {
                throw new IOException("Box64 package attempted an unapproved target");
            }
        } else if (normalized.startsWith("${system32}/")) {
            base = system32;
            suffix = normalized.substring("${system32}/".length());
            if (type.equalsIgnoreCase("FEXCore")) {
                if (!suffix.equals("libarm64ecfex.dll") && !suffix.equals("libwow64fex.dll")) {
                    throw new IOException("FEXCore package attempted an unapproved system32 target");
                }
            } else if (type.equalsIgnoreCase("WOWBox64")) {
                if (!suffix.equals("wowbox64.dll")) {
                    throw new IOException("WowBox64 package attempted an unapproved system32 target");
                }
            } else {
                throw new IOException("Box64 package cannot write to system32");
            }
        } else {
            throw new IOException("unsupported Winlator target template: " + template);
        }
        Path relative = java.nio.file.Paths.get(suffix);
        if (relative.isAbsolute()) throw new IOException("absolute Winlator target");
        Path destination = base.resolve(relative).normalize();
        if (!destination.startsWith(base)) throw new IOException("Winlator target escapes its install directory");
        return destination;
    }

    private static void installOne(Path source, Path destination, Path privateRoot, boolean executable)
            throws IOException {
        if (!destination.toAbsolutePath().normalize().startsWith(privateRoot)) {
            throw new IOException("package destination escapes private runtime storage");
        }
        Path parent = destination.getParent();
        if (parent == null) throw new IOException("package destination has no parent");
        createDirectoriesNoSymlink(privateRoot, parent);
        Path temporary = destination.resolveSibling(destination.getFileName() + ".installing");
        Files.deleteIfExists(temporary);
        try {
            try (InputStream input = Files.newInputStream(source);
                 OutputStream output = Files.newOutputStream(
                         temporary, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
                byte[] buffer = new byte[BUFFER_SIZE];
                int read;
                while ((read = input.read(buffer)) != -1) {
                    if (read > 0) output.write(buffer, 0, read);
                }
                output.flush();
            }
            try {
                Files.move(temporary, destination, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            } catch (AtomicMoveNotSupportedException ignored) {
                Files.move(temporary, destination, StandardCopyOption.REPLACE_EXISTING);
            }
            if (executable) {
                try {
                    Files.setPosixFilePermissions(destination, EnumSet.of(
                            PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE,
                            PosixFilePermission.OWNER_EXECUTE, PosixFilePermission.GROUP_READ,
                            PosixFilePermission.GROUP_EXECUTE, PosixFilePermission.OTHERS_READ,
                            PosixFilePermission.OTHERS_EXECUTE));
                } catch (UnsupportedOperationException ignored) {
                    destination.toFile().setExecutable(true, false);
                }
            }
        } catch (IOException | RuntimeException failure) {
            Files.deleteIfExists(temporary);
            throw failure;
        }
    }

    private static void createDirectoriesNoSymlink(Path root, Path path) throws IOException {
        Path normalizedRoot = root.toAbsolutePath().normalize();
        Path normalized = path.toAbsolutePath().normalize();
        if (!normalized.startsWith(normalizedRoot)) throw new IOException("path escapes private runtime root");
        if (Files.isSymbolicLink(normalizedRoot)) throw new IOException("private runtime root is a symbolic link");
        Path current = normalizedRoot;
        for (Path part : normalizedRoot.relativize(normalized)) {
            current = current.resolve(part);
            if (Files.exists(current, LinkOption.NOFOLLOW_LINKS)) {
                if (Files.isSymbolicLink(current) || !Files.isDirectory(current, LinkOption.NOFOLLOW_LINKS)) {
                    throw new IOException("unsafe package directory component: " + current);
                }
            } else {
                Files.createDirectory(current);
            }
        }
    }

    private static void rejectSymlinkParents(Path root, Path path) throws IOException {
        if (path == null) return;
        Path normalizedRoot = root.toAbsolutePath().normalize();
        Path normalized = path.toAbsolutePath().normalize();
        if (!normalized.startsWith(normalizedRoot)) throw new IOException("path escapes private runtime root");
        Path current = normalizedRoot;
        for (Path part : normalizedRoot.relativize(normalized)) {
            current = current.resolve(part);
            if (Files.isSymbolicLink(current)) throw new IOException("refusing package write through symlink: " + current);
        }
    }

    private static String safeId(String id) throws IOException {
        if (id == null || !id.matches("[A-Za-z0-9._-]{1,100}")) {
            throw new IOException("unsafe Winlator package id");
        }
        return id.toLowerCase(Locale.ROOT);
    }

    private static void deleteRecursively(Path path) throws IOException {
        if (!Files.exists(path, LinkOption.NOFOLLOW_LINKS)) return;
        if (Files.isSymbolicLink(path) || !Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) {
            Files.deleteIfExists(path);
            return;
        }
        try (var stream = Files.list(path)) {
            for (Path child : (Iterable<Path>) stream::iterator) deleteRecursively(child);
        }
        Files.deleteIfExists(path);
    }
}
