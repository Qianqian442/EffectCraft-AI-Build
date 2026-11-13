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
        check(x64.size() == 3, "x64 must have FEXCore, Box64 and WowBox64 candidates");
        check(x64.get(0).hostWorker.equals("effectcraft-aex-host-x64.exe"),
                "x64 must select x64 AEX host");
        check(x64.get(0).backendId.equals("arm64ec-proton-fexcore"),
                "ARM64EC/FEXCore is the default x64 path");
        check(x64.get(0).components.contains("HODLL64=libarm64ecfex.dll"),
                "64-bit PE execution must select HODLL64");
        check(x64.get(0).components.contains("HODLL=libwow64fex.dll"),
                "32-bit WoW64 execution must select HODLL");

        var x86 = WindowsRuntimeSelector.candidates(
                WindowsRuntimeSelector.IMAGE_FILE_MACHINE_I386,
                WindowsRuntimeSelector.Preference.AUTO);
        check(x86.size() == 3, "x86 must have FEX, Box64-BOX32 and Boxedwine candidates");
        check(x86.get(0).hostWorker.equals("effectcraft-aex-host-x86.exe"),
                "x86 must select x86 AEX host");
        check(x86.get(0).hodll.equals("libwow64fex.dll"),
                "FEXCore WoW64 path must select the correct HODLL");

        var preferred = WindowsRuntimeSelector.candidates(
                WindowsRuntimeSelector.IMAGE_FILE_MACHINE_AMD64,
                WindowsRuntimeSelector.Preference.WOWBOX64_FIRST);
        check(preferred.get(0).backendId.equals("arm64ec-proton-wowbox64"),
                "preference must move the 64-bit WowBox64 path first");
        var boxedwinePreferred = WindowsRuntimeSelector.candidates(
                WindowsRuntimeSelector.IMAGE_FILE_MACHINE_I386,
                WindowsRuntimeSelector.Preference.BOXEDWINE_FIRST);
        check(boxedwinePreferred.get(0).backendId.equals("boxedwine-x86-32"),
                "Boxedwine must be selectable as a separate legacy x86 fallback");
        check(boxedwinePreferred.get(0).confidence
                == WindowsRuntimeSelector.Confidence.ANDROID_PORT_REQUIRED,
                "Boxedwine must not be marked Android-ready before porting");

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
