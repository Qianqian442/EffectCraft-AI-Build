package com.effectcraft.windowscompat;

import androidx.test.ext.junit.runners.AndroidJUnit4;

import org.junit.Test;
import org.junit.runner.RunWith;

/**
 * Runs archive operations on Android so the Zstandard JNI bundled in the AAR
 * is loaded for the actual device ABI, not the Linux host JVM.
 */
@RunWith(AndroidJUnit4.class)
public final class WindowsCompatRuntimeInstrumentedTests {
    @Test
    public void extractsXzAndZstandardArchivesSafelyOnAndroid() throws Exception {
        SafeRuntimeArchiveExtractorSelfTest.main(new String[0]);
    }

    @Test
    public void installsVerifiedWinlatorContentPackagesOnAndroid() throws Exception {
        WinlatorContentPackageInstallerSelfTest.main(new String[0]);
    }
}
