package com.effectcraft.windowscompat;

import org.junit.Test;

/** JUnit entry points for the standalone runtime implementation self-tests. */
public final class WindowsCompatRuntimeTests {
    @Test
    public void selectsCpuAndWineBackendsByPeArchitecture() {
        WindowsRuntimeSelectorSelfTest.main(new String[0]);
    }

    @Test
    public void launchesPrivateBionicExecutablesThroughAndroidLinker64() {
        AndroidBionicProcessLauncherSelfTest.main(new String[0]);
    }

    @Test
    public void rejectsUnpinnedOrCorruptEmbeddedBox32Archives() throws Exception {
        java.nio.file.Path root = java.nio.file.Files.createTempDirectory("effectcraft-box32-test");
        java.nio.file.Path archive = root.resolve("bad.tar.zst");
        java.nio.file.Files.write(archive, "not a zstandard archive".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        WinlatorBionicRuntimeManager manager = new WinlatorBionicRuntimeManager(
                root.resolve("private"), uri -> { throw new java.io.IOException("network is not used by this test"); });
        try {
            try {
                manager.installBox64Box32Archive(archive,
                        "0000000000000000000000000000000000000000000000000000000000000000");
                throw new AssertionError("corrupt BOX32 archive was accepted");
            } catch (java.io.IOException expected) {
                if (!expected.getMessage().contains("SHA-256 mismatch")) {
                    throw new AssertionError("wrong BOX32 rejection reason: " + expected.getMessage(), expected);
                }
            }
            if (java.nio.file.Files.exists(manager.getImageFsRoot().resolve("usr/bin/box64"))) {
                throw new AssertionError("corrupt BOX32 archive replaced the live Box64 binary");
            }
        } finally {
            manager.close();
            try (java.util.stream.Stream<java.nio.file.Path> paths = java.nio.file.Files.walk(root)) {
                paths.sorted(java.util.Comparator.reverseOrder()).forEach(path -> {
                    try { java.nio.file.Files.deleteIfExists(path); } catch (java.io.IOException ignored) {}
                });
            }
        }
    }

    @Test
    public void verifiesAndStreamsRuntimeAssets() throws Exception {
        RuntimeAssetInstallerSelfTest.main(new String[0]);
    }

}
