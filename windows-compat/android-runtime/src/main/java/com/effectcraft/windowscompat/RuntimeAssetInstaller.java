package com.effectcraft.windowscompat;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Streaming installer for the optional Winlator Bionic runtime assets.
 *
 * This helper has no fixed file-size limit and no memory/RAM budget. It streams
 * all downloads to app-private storage, validates SHA-256 sidecars or pinned
 * Git object IDs, and only then atomically publishes the file.
 *
 * Archive extraction is deliberately delegated to a separate implementation
 * that must reject absolute paths, ".." traversal, symlinks escaping the target
 * directory, and archive entries that overwrite application files.
 */
public final class RuntimeAssetInstaller {
    private static final int BUFFER_SIZE = 64 * 1024;
    private static final Pattern SHA256_TOKEN = Pattern.compile("(?i)\\b([0-9a-f]{64})\\b");

    public enum DigestKind {
        SHA256_SIDECAR,
        GIT_BLOB_SHA1
    }

    public interface AssetFetcher {
        InputStream open(URI uri) throws IOException;
    }

    public interface ArchiveExtractor {
        void extractTarXz(Path archive, Path privateTarget) throws IOException;
        void extractTarZstd(Path archive, Path privateTarget) throws IOException;
    }

    public static final class AssetSpec {
        public final String id;
        public final List<URI> sourceParts;
        public final URI checksumSidecar;
        public final DigestKind digestKind;
        public final String expectedDigest;
        public final long expectedSize;
        public final Path destinationRelative;

        public AssetSpec(
                String id,
                List<URI> sourceParts,
                URI checksumSidecar,
                DigestKind digestKind,
                String expectedDigest,
                long expectedSize,
                Path destinationRelative) {
            this.id = requireText(id, "asset id");
            if (sourceParts == null || sourceParts.isEmpty()) {
                throw new IllegalArgumentException("asset requires at least one source URI");
            }
            List<URI> checked = new ArrayList<>();
            for (URI uri : sourceParts) {
                checked.add(requireHttps(uri));
            }
            this.sourceParts = Collections.unmodifiableList(checked);
            this.checksumSidecar = checksumSidecar == null ? null : requireHttps(checksumSidecar);
            this.digestKind = Objects.requireNonNull(digestKind, "digest kind");
            this.expectedDigest = expectedDigest == null ? null : expectedDigest.toLowerCase(Locale.ROOT);
            if (this.expectedDigest != null) {
                String pattern = digestKind == DigestKind.SHA256_SIDECAR ? "(?i)[0-9a-f]{64}" : "(?i)[0-9a-f]{40}";
                if (!this.expectedDigest.matches(pattern)) {
                    throw new IllegalArgumentException("pinned digest has the wrong length or format");
                }
            }
            this.expectedSize = expectedSize;
            this.destinationRelative = Objects.requireNonNull(destinationRelative, "destination");
            if (destinationRelative.isAbsolute() || destinationRelative.normalize().startsWith("..")) {
                throw new IllegalArgumentException("asset destination must be a safe relative path");
            }
            if (digestKind == DigestKind.SHA256_SIDECAR
                    && checksumSidecar == null && expectedDigest == null) {
                throw new IllegalArgumentException("SHA-256 asset requires a sidecar or pinned digest");
            }
            if (digestKind == DigestKind.GIT_BLOB_SHA1
                    && (expectedDigest == null || !expectedDigest.matches("(?i)[0-9a-f]{40}"))) {
                throw new IllegalArgumentException("Git blob asset requires a 40-character SHA-1");
            }
            if (expectedSize < -1) {
                throw new IllegalArgumentException("invalid expected size");
            }
        }
    }

    private final Path privateRoot;
    private final AssetFetcher fetcher;

    public RuntimeAssetInstaller(Path privateRoot, AssetFetcher fetcher) throws IOException {
        this.privateRoot = Objects.requireNonNull(privateRoot, "private root").toAbsolutePath().normalize();
        this.fetcher = Objects.requireNonNull(fetcher, "asset fetcher");
        Files.createDirectories(this.privateRoot);
    }

    public static AssetFetcher httpFetcher() {
        return uri -> {
            HttpURLConnection connection = (HttpURLConnection) uri.toURL().openConnection();
            connection.setConnectTimeout(20_000);
            connection.setReadTimeout(60_000);
            connection.setUseCaches(false);
            connection.setInstanceFollowRedirects(true);
            connection.setRequestProperty("User-Agent", "EffectCraft-Windows-Compat-Runtime/1");
            int status = connection.getResponseCode();
            if (!"https".equalsIgnoreCase(connection.getURL().getProtocol())) {
                connection.disconnect();
                throw new IOException("refusing insecure HTTP redirect for " + uri);
            }
            if (status < 200 || status >= 300) {
                connection.disconnect();
                throw new IOException("HTTP " + status + " downloading " + uri);
            }
            return new java.io.FilterInputStream(connection.getInputStream()) {
                @Override
                public void close() throws IOException {
                    try {
                        super.close();
                    } finally {
                        connection.disconnect();
                    }
                }
            };
        };
    }

    public Path downloadVerified(AssetSpec spec) throws IOException {
        Objects.requireNonNull(spec, "asset spec");
        Path destination = privateRoot.resolve(spec.destinationRelative).normalize();
        if (!destination.startsWith(privateRoot)) {
            throw new IOException("asset destination escapes private runtime directory");
        }
        Path parent = destination.getParent();
        if (parent == null) throw new IOException("asset destination has no parent");
        ensureNoSymlinkPath(parent);
        Files.createDirectories(parent);
        ensureNoSymlinkPath(parent);

        String expected = expectedDigest(spec);
        if (Files.isRegularFile(destination) && matches(spec, destination, expected)) {
            return destination;
        }

        Path temporary = destination.resolveSibling(destination.getFileName() + ".part");
        Files.deleteIfExists(temporary);
        MessageDigest digest = newDigest(spec.digestKind == DigestKind.SHA256_SIDECAR ? "SHA-256" : "SHA-1");
        long written = 0;
        try {
            try (OutputStream output = Files.newOutputStream(temporary)) {
                for (URI part : spec.sourceParts) {
                    try (InputStream input = fetcher.open(part)) {
                        byte[] buffer = new byte[BUFFER_SIZE];
                        int count;
                        while ((count = input.read(buffer)) != -1) {
                            if (count == 0) continue;
                            output.write(buffer, 0, count);
                            digest.update(buffer, 0, count);
                            written = Math.addExact(written, count);
                        }
                    }
                }
                output.flush();
            }
            if (spec.expectedSize >= 0 && written != spec.expectedSize) {
                throw new IOException("asset size mismatch for " + spec.id
                        + ": expected " + spec.expectedSize + ", received " + written);
            }
            String actual = hex(digest.digest());
            if (!actual.equalsIgnoreCase(expected)) {
                throw new IOException("asset digest mismatch for " + spec.id
                        + ": expected " + expected + ", received " + actual);
            }
            try {
                Files.move(temporary, destination, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            } catch (AtomicMoveNotSupportedException ignored) {
                Files.move(temporary, destination, StandardCopyOption.REPLACE_EXISTING);
            }
            return destination;
        } catch (ArithmeticException overflow) {
            Files.deleteIfExists(temporary);
            throw new IOException("asset file size overflow for " + spec.id, overflow);
        } catch (IOException | RuntimeException failure) {
            Files.deleteIfExists(temporary);
            throw failure;
        }
    }

    public Path installArchive(
            AssetSpec spec,
            Path relativeTarget,
            ArchiveExtractor extractor,
            boolean zstd) throws IOException {
        Objects.requireNonNull(extractor, "archive extractor");
        Path archive = downloadVerified(spec);
        Path target = privateRoot.resolve(relativeTarget).normalize();
        if (target.equals(privateRoot) || !target.startsWith(privateRoot)) {
            throw new IOException("archive target must be a child of private runtime directory");
        }
        Files.createDirectories(target);
        if (zstd) extractor.extractTarZstd(archive, target);
        else extractor.extractTarXz(archive, target);
        return target;
    }

    private String expectedDigest(AssetSpec spec) throws IOException {
        if (spec.expectedDigest != null) return spec.expectedDigest;
        if (spec.checksumSidecar == null) throw new IOException("missing checksum for " + spec.id);
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (InputStream input = fetcher.open(spec.checksumSidecar)) {
            byte[] buffer = new byte[4096];
            int count;
            while ((count = input.read(buffer)) != -1) {
                bytes.write(buffer, 0, count);
            }
        }
        Matcher matcher = SHA256_TOKEN.matcher(new String(bytes.toByteArray(), StandardCharsets.UTF_8));
        if (!matcher.find()) throw new IOException("invalid SHA-256 sidecar for " + spec.id);
        return matcher.group(1).toLowerCase(Locale.ROOT);
    }

    private boolean matches(AssetSpec spec, Path file, String expected) throws IOException {
        if (spec.expectedSize >= 0 && Files.size(file) != spec.expectedSize) return false;
        String actual = digestFile(file, spec.digestKind);
        return actual.equalsIgnoreCase(expected);
    }

    private static String digestFile(Path path, DigestKind kind) throws IOException {
        MessageDigest digest = newDigest(kind == DigestKind.SHA256_SIDECAR ? "SHA-256" : "SHA-1");
        long size = Files.size(path);
        if (kind == DigestKind.GIT_BLOB_SHA1) {
            digest.update(("blob " + size + "\0").getBytes(StandardCharsets.US_ASCII));
        }
        try (InputStream input = Files.newInputStream(path)) {
            byte[] buffer = new byte[BUFFER_SIZE];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (count > 0) digest.update(buffer, 0, count);
            }
        }
        return hex(digest.digest());
    }

    private static MessageDigest newDigest(String name) {
        try {
            return MessageDigest.getInstance(name);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(name + " is required by the Java runtime", impossible);
        }
    }

    private static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) result.append(String.format(Locale.ROOT, "%02x", value & 0xff));
        return result.toString();
    }

    private static URI requireHttps(URI uri) {
        Objects.requireNonNull(uri, "asset URI");
        if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null) {
            throw new IllegalArgumentException("runtime assets must use HTTPS URLs");
        }
        return uri;
    }

    private void ensureNoSymlinkPath(Path path) throws IOException {
        Path current = privateRoot;
        if (Files.isSymbolicLink(current)) {
            throw new IOException("private runtime root must not be a symbolic link");
        }
        Path relative = privateRoot.relativize(path.toAbsolutePath().normalize());
        for (Path part : relative) {
            current = current.resolve(part);
            if (Files.exists(current) && Files.isSymbolicLink(current)) {
                throw new IOException("symbolic link in private runtime path: " + current);
            }
        }
    }

    private static String requireText(String value, String label) {
        if (value == null || value.trim().isEmpty()) throw new IllegalArgumentException(label + " is empty");
        return value;
    }

    public Path getPrivateRoot() {
        return privateRoot;
    }
}
