package com.effectcraft.windowscompat;

/** Plain-Java smoke tests; run with java -ea after compiling the selector. */
public final class WindowsRuntimeSelectorSelfTest {
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        var x64 = WindowsRuntimeSelector.candidates(
                WindowsRuntimeSelector.IMAGE_FILE_MACHINE_AMD64,
                WindowsRuntimeSelector.Preference.AUTO);
        check(x64.size() == 2, "x64 must have Box64 and ARM64EC/FEX candidates");
        check(x64.get(0).hostWorker.equals("effectcraft-aex-host-x64.exe"),
                "x64 must select x64 AEX host");
        check(x64.get(0).backendId.equals("x86_64-proton-box64"),
                "Box64 is the default x64 path");

        var x86 = WindowsRuntimeSelector.candidates(
                WindowsRuntimeSelector.IMAGE_FILE_MACHINE_I386,
                WindowsRuntimeSelector.Preference.AUTO);
        check(x86.size() == 3, "x86 must have FEX, WowBox64 and Box64-BOX32 paths");
        check(x86.get(0).hostWorker.equals("effectcraft-aex-host-x86.exe"),
                "x86 must select x86 AEX host");
        check(x86.get(0).hodll.equals("libwow64fex.dll"),
                "FEXCore WoW64 path must select the correct HODLL");

        var preferred = WindowsRuntimeSelector.candidates(
                WindowsRuntimeSelector.IMAGE_FILE_MACHINE_I386,
                WindowsRuntimeSelector.Preference.WOWBOX64_FIRST);
        check(preferred.get(0).backendId.equals("arm64ec-proton-wowbox64"),
                "preference must move WowBox64 path first");

        var arm64ec = WindowsRuntimeSelector.candidates(
                WindowsRuntimeSelector.IMAGE_FILE_MACHINE_ARM64EC,
                WindowsRuntimeSelector.Preference.AUTO);
        check(arm64ec.get(0).confidence
                == WindowsRuntimeSelector.Confidence.MANUAL_ABI_REVIEW_REQUIRED,
                "ARM64EC AEX must not be marked supported without a matching host");

        var unknown = WindowsRuntimeSelector.candidates(0x9999,
                WindowsRuntimeSelector.Preference.AUTO);
        check(unknown.isEmpty(), "unknown PE types must not be auto executed");

        System.out.println("WindowsRuntimeSelector checks passed.");
    }
}
