package com.effectcraft.windowscompat;

import org.junit.Test;

/** JUnit entry points for the standalone runtime implementation self-tests. */
public final class WindowsCompatRuntimeTests {
    @Test
    public void selectsCpuAndWineBackendsByPeArchitecture() {
        WindowsRuntimeSelectorSelfTest.main(new String[0]);
    }

    @Test
    public void verifiesAndStreamsRuntimeAssets() throws Exception {
        RuntimeAssetInstallerSelfTest.main(new String[0]);
    }

}
