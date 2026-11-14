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
    public void keepsGlibcGuestLibrariesOutOfBionicHostLoaderPath() throws Exception {
        java.nio.file.Path root = java.nio.file.Files.createTempDirectory("effectcraft-bionic-env-test");
        java.nio.file.Path imageFs = root.resolve("imagefs");
        java.nio.file.Path wineRoot = root.resolve("wine");
        java.nio.file.Path bridge = root.resolve("native/libeffectcraft-exec.so");
        java.nio.file.Path prefix = root.resolve("prefix");
        java.nio.file.Files.createDirectories(imageFs.resolve("usr/lib"));
        java.nio.file.Files.createDirectories(wineRoot.resolve("lib"));
        java.nio.file.Files.createDirectories(bridge.getParent());
        java.nio.file.Files.createDirectories(prefix);
        java.nio.file.Files.write(bridge, new byte[] { 0x7f, 'E', 'L', 'F' });
        try {
            java.util.Map<String, String> x64 = WinlatorBionicRuntimeManager.buildNativeEnvironment(
                    root, imageFs, wineRoot, WinlatorBionicRuntimeManager.Architecture.X86_64, bridge, prefix);
            if (!"/system/lib64".equals(x64.get("LD_LIBRARY_PATH"))) {
                throw new AssertionError("x86_64 Box64 host must use Bionic system libraries only: "
                        + x64.get("LD_LIBRARY_PATH"));
            }
            if (x64.get("LD_LIBRARY_PATH").contains(imageFs.resolve("usr/lib").toString())) {
                throw new AssertionError("glibc guest libraries leaked into Bionic host loader path");
            }
            if (!bridge.toRealPath().toString().equals(x64.get("LD_PRELOAD"))) {
                throw new AssertionError("exec bridge was not set as LD_PRELOAD");
            }
            if (!root.toRealPath().toString().equals(x64.get("EFFECTCRAFT_RUNTIME_ROOT"))) {
                throw new AssertionError("runtime root was not exported to the exec bridge");
            }

            java.util.Map<String, String> arm64ec = WinlatorBionicRuntimeManager.buildNativeEnvironment(
                    root, imageFs, wineRoot, WinlatorBionicRuntimeManager.Architecture.ARM64EC, bridge, prefix);
            String expectedArm64ecPath = wineRoot.resolve("lib") + ":/system/lib64";
            if (!expectedArm64ecPath.equals(arm64ec.get("LD_LIBRARY_PATH"))) {
                throw new AssertionError("ARM64EC host must use Bionic Wine libs and system libs only: "
                        + arm64ec.get("LD_LIBRARY_PATH"));
            }
            if (arm64ec.get("LD_LIBRARY_PATH").contains(imageFs.resolve("usr/lib").toString())) {
                throw new AssertionError("glibc guest libraries leaked into ARM64EC Bionic host loader path");
            }
            if (arm64ec.containsKey("GST_PLUGIN_PATH")) {
                throw new AssertionError("glibc GStreamer plugins must not be exposed to Bionic Wine");
            }
        } finally {
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
