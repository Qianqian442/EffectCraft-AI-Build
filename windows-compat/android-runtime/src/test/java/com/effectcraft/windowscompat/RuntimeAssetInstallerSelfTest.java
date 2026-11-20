package com.effectcraft.windowscompat;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** Streaming checksum, multi-part download and safe-path tests. */
public final class RuntimeAssetInstallerSelfTest {
    private static String hex(byte[] value) {
        StringBuilder out = new StringBuilder();
        for (byte b : value) out.append(String.format(Locale.ROOT, "%02x", b & 0xff));
        return out.toString();
    }

    private static String sha256(byte[] data) throws Exception {
        return hex(MessageDigest.getInstance("SHA-256").digest(data));
    }

    private static String gitBlobSha1(byte[] data) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-1");
        md.update(("blob " + data.length + "\0").getBytes(StandardCharsets.US_ASCII));
        md.update(data);
        return hex(md.digest());
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    public static void main(String[] args) throws Exception {
        Path root = Files.createTempDirectory("ec-runtime-installer-test");
        try {
            Map<URI, byte[]> payloads = new HashMap<>();
            URI p0 = URI.create("https://unit.test/image.00");
            URI p1 = URI.create("https://unit.test/image.01");
            URI sum = URI.create("https://unit.test/image.sha256");
            byte[] expected = "multi-part-imagefs-payload".getBytes(StandardCharsets.UTF_8);
            byte[] first = "multi-part-".getBytes(StandardCharsets.UTF_8);
            byte[] second = "imagefs-payload".getBytes(StandardCharsets.UTF_8);
            payloads.put(p0, first);
            payloads.put(p1, second);
            payloads.put(sum, (sha256(expected) + "  image.txz\n").getBytes(StandardCharsets.US_ASCII));

            RuntimeAssetInstaller installer = new RuntimeAssetInstaller(root, uri -> {
                byte[] bytes = payloads.get(uri);
                if (bytes == null) throw new IOException("missing fixture URL " + uri);
                return new ByteArrayInputStream(bytes);
            });
            var image = new RuntimeAssetInstaller.AssetSpec(
                    "test-image",
                    List.of(p0, p1),
                    sum,
                    RuntimeAssetInstaller.DigestKind.SHA256_SIDECAR,
                    null,
                    expected.length,
                    Path.of("downloads/image.txz"));
            Path downloaded = installer.downloadVerified(image);
            check(java.util.Arrays.equals(Files.readAllBytes(downloaded), expected),
                    "multi-part asset must be assembled in order");
            check(installer.downloadVerified(image).equals(downloaded),
                    "verified existing asset should be reused");

            URI gitUri = URI.create("https://unit.test/container.tzst");
            byte[] gitContent = "container skeleton".getBytes(StandardCharsets.UTF_8);
            payloads.put(gitUri, gitContent);
            var gitAsset = new RuntimeAssetInstaller.AssetSpec(
                    "test-git-blob",
                    List.of(gitUri),
                    null,
                    RuntimeAssetInstaller.DigestKind.GIT_BLOB_SHA1,
                    gitBlobSha1(gitContent),
                    gitContent.length,
                    Path.of("downloads/container.tzst"));
            check(java.util.Arrays.equals(Files.readAllBytes(installer.downloadVerified(gitAsset)), gitContent),
                    "pinned Git blob asset must be verified");

            boolean rejected = false;
            try {
                new RuntimeAssetInstaller.AssetSpec(
                        "bad-path", List.of(gitUri), null,
                        RuntimeAssetInstaller.DigestKind.GIT_BLOB_SHA1,
                        gitBlobSha1(gitContent), gitContent.length,
                        Path.of("../outside.bin"));
            } catch (IllegalArgumentException expectedFailure) {
                rejected = true;
            }
            check(rejected, "path traversal destination must be rejected");

            System.out.println("Runtime asset installer tests passed.");
        } finally {
            deleteRecursively(root);
        }
    }

    private static void deleteRecursively(Path path) throws IOException {
        if (Files.isDirectory(path)) {
            try (var stream = Files.list(path)) {
                for (Path child : (Iterable<Path>) stream::iterator) deleteRecursively(child);
            }
        }
        Files.deleteIfExists(path);
    }
}
