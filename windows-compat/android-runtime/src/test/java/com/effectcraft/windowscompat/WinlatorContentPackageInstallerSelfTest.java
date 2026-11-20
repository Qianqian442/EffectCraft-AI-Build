package com.effectcraft.windowscompat;

import org.apache.commons.compress.archivers.tar.TarArchiveEntry;
import org.apache.commons.compress.archivers.tar.TarArchiveOutputStream;
import org.apache.commons.compress.compressors.zstandard.ZstdCompressorOutputStream;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** Tests safe installation of Winlator Box64/FEXCore/WoWBox64 content profiles. */
public final class WinlatorContentPackageInstallerSelfTest {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static String gitBlobSha1(byte[] data) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-1");
        digest.update(("blob " + data.length + "\0").getBytes(StandardCharsets.US_ASCII));
        digest.update(data);
        StringBuilder result = new StringBuilder();
        for (byte value : digest.digest()) result.append(String.format(Locale.ROOT, "%02x", value & 0xff));
        return result.toString();
    }

    private static byte[] makePackage(String type, String source, String target, byte[] binary)
            throws IOException {
        String json = "{"
                + "\"type\":\"" + type + "\","
                + "\"versionName\":\"fixture-1\","
                + "\"versionCode\":1,"
                + "\"description\":\"fixture package\","
                + "\"files\":[{\"source\":\"" + source + "\",\"target\":\"" + target + "\"}]"
                + "}";
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (OutputStream zstd = new ZstdCompressorOutputStream(bytes);
             TarArchiveOutputStream tar = new TarArchiveOutputStream(zstd)) {
            byte[] profile = json.getBytes(StandardCharsets.UTF_8);
            TarArchiveEntry profileEntry = new TarArchiveEntry("profile.json");
            profileEntry.setSize(profile.length);
            profileEntry.setMode(0644);
            tar.putArchiveEntry(profileEntry);
            tar.write(profile);
            tar.closeArchiveEntry();

            TarArchiveEntry binaryEntry = new TarArchiveEntry(source);
            binaryEntry.setSize(binary.length);
            binaryEntry.setMode(0755);
            tar.putArchiveEntry(binaryEntry);
            tar.write(binary);
            tar.closeArchiveEntry();
        }
        return bytes.toByteArray();
    }

    public static void main(String[] args) throws Exception {
        Path root = Files.createTempDirectory("effectcraft-content-package-test");
        try {
            byte[] box64 = "box64-arm64-binary".getBytes(StandardCharsets.UTF_8);
            byte[] packageBytes = makePackage("Box64", "box64", "${bindir}/box64", box64);
            URI packageUrl = URI.create("https://unit.test/box64.tzst");
            Map<URI, byte[]> payloads = new HashMap<>();
            payloads.put(packageUrl, packageBytes);

            RuntimeAssetInstaller assets = new RuntimeAssetInstaller(root, uri -> {
                byte[] data = payloads.get(uri);
                if (data == null) throw new IOException("missing fixture URI: " + uri);
                return new ByteArrayInputStream(data);
            });
            SafeRuntimeArchiveExtractor extractor = new SafeRuntimeArchiveExtractor();
            WinlatorContentPackageInstaller packages =
                    new WinlatorContentPackageInstaller(assets, extractor);

            RuntimeAssetInstaller.AssetSpec boxSpec = new RuntimeAssetInstaller.AssetSpec(
                    "fixture-box64", List.of(packageUrl), null,
                    RuntimeAssetInstaller.DigestKind.GIT_BLOB_SHA1,
                    gitBlobSha1(packageBytes), packageBytes.length,
                    java.nio.file.Paths.get("downloads/fixture-box64.tzst"));
            Path imageFs = root.resolve("imagefs");
            Path prefixSystem32 = root.resolve("containers/arm64ec/drive_c/windows/system32");
            Path prefixSyswow64 = root.resolve("containers/arm64ec/drive_c/windows/syswow64");
            Files.createDirectories(prefixSystem32);
            Files.createDirectories(prefixSyswow64);

            var result = packages.install(boxSpec, imageFs, prefixSystem32, prefixSyswow64);
            Path installed = imageFs.resolve("usr/bin/box64");
            check(result.type.equals("Box64"), "profile type must be parsed");
            check(Files.readAllBytes(installed).length == box64.length,
                    "Box64 WCP source must be installed to ${bindir}/box64");
            check(Files.isExecutable(installed), "Box64 binary must retain executable permissions");

            byte[] malicious = makePackage("Box64", "box64", "${bindir}/../../escape", box64);
            URI maliciousUrl = URI.create("https://unit.test/malicious.tzst");
            payloads.put(maliciousUrl, malicious);
            RuntimeAssetInstaller.AssetSpec maliciousSpec = new RuntimeAssetInstaller.AssetSpec(
                    "fixture-box64-malicious", List.of(maliciousUrl), null,
                    RuntimeAssetInstaller.DigestKind.GIT_BLOB_SHA1,
                    gitBlobSha1(malicious), malicious.length,
                    java.nio.file.Paths.get("downloads/fixture-box64-malicious.tzst"));
            boolean rejected = false;
            try {
                packages.install(maliciousSpec, imageFs, prefixSystem32, prefixSyswow64);
            } catch (IOException expected) {
                rejected = true;
            }
            check(rejected, "untrusted target template must be rejected");
            check(!Files.exists(root.resolve("escape")), "profile path traversal must not escape root");

            System.out.println("Winlator content package installer tests passed.");
        } finally {
            try (var paths = Files.walk(root)) {
                paths.sorted(java.util.Comparator.reverseOrder()).forEach(path -> {
                    try {
                        Files.deleteIfExists(path);
                    } catch (IOException ignored) {}
                });
            }
        }
    }
}
