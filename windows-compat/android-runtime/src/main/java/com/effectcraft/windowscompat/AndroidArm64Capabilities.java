package com.effectcraft.windowscompat;

/**
 * Read-only ARM64 capability snapshot used to decide whether an ARM64EC/FEX
 * backend is a plausible candidate on the current Android device.
 *
 * FEX documents ARMv8.0-A with FEAT_FP and FEAT_CRC32 as its minimum host
 * requirement. Wine 10.5 added larger ARM64 page-size support; 4K and 16K
 * are treated as candidates here, while 64K remains unverified for this
 * Android/Bionic integration.
 */
public final class AndroidArm64Capabilities {
    public static final long HWCAP_FP = 1L << 0;
    public static final long HWCAP_ASIMD = 1L << 1;
    public static final long HWCAP_CRC32 = 1L << 7;

    private final long hwcap;
    private final long pageSize;
    private final String probeError;

    private AndroidArm64Capabilities(long hwcap, long pageSize, String probeError) {
        this.hwcap = hwcap;
        this.pageSize = pageSize;
        this.probeError = probeError;
    }

    public static AndroidArm64Capabilities fromNativeProbe(long[] values) {
        if (values == null || values.length < 2) {
            return unavailable("native ARM64 capability probe returned no data");
        }
        return new AndroidArm64Capabilities(values[0], values[1], null);
    }

    public static AndroidArm64Capabilities unavailable(String reason) {
        return new AndroidArm64Capabilities(0, 0,
                reason == null || reason.trim().isEmpty() ? "capability probe unavailable" : reason);
    }

    public long getHwcap() {
        return hwcap;
    }

    public long getPageSize() {
        return pageSize;
    }

    public boolean isProbeAvailable() {
        return probeError == null && pageSize > 0;
    }

    public boolean hasFp() {
        return (hwcap & HWCAP_FP) != 0;
    }

    public boolean hasAsimd() {
        return (hwcap & HWCAP_ASIMD) != 0;
    }

    public boolean hasCrc32() {
        return (hwcap & HWCAP_CRC32) != 0;
    }

    public boolean supportsFexMinimum() {
        return isProbeAvailable() && hasFp() && hasCrc32();
    }

    public boolean hasCandidateWinePageSize() {
        return pageSize == 4096 || pageSize == 16384;
    }

    public boolean supportsArm64EcCandidate() {
        return supportsFexMinimum() && hasCandidateWinePageSize();
    }

    public String describe() {
        if (!isProbeAvailable()) {
            return "ARM64 capability probe unavailable: " + probeError;
        }
        return "ARM64 HWCAP=0x" + Long.toHexString(hwcap)
                + " FP=" + hasFp()
                + " ASIMD=" + hasAsimd()
                + " CRC32=" + hasCrc32()
                + " pageSize=" + pageSize
                + " FEX-minimum=" + supportsFexMinimum()
                + " ARM64EC-candidate=" + supportsArm64EcCandidate()
                + (pageSize == 65536 ? " (64K page size not yet validated)" : "");
    }
}
