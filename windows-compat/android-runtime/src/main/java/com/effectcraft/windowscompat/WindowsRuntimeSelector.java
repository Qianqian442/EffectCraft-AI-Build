package com.effectcraft.windowscompat;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;

/**
 * Chooses a Wine/Proton container and isolated AEX host worker from PE machine type.
 *
 * This is a planning layer only: a returned candidate must still pass runtime
 * smoke tests before EffectCraft marks the corresponding backend as supported.
 * Deliberately contains no RAM limit, heap budget, rlimit or cgroup setting.
 */
public final class WindowsRuntimeSelector {
    public static final int IMAGE_FILE_MACHINE_I386 = 0x014c;
    public static final int IMAGE_FILE_MACHINE_AMD64 = 0x8664;
    public static final int IMAGE_FILE_MACHINE_ARM64 = 0xaa64;
    public static final int IMAGE_FILE_MACHINE_ARM64EC = 0xa641;
    public static final int IMAGE_FILE_MACHINE_ARM64X = 0xa64e;

    public enum Preference {
        AUTO,
        BOX64_FIRST,
        FEXCORE_FIRST,
        WOWBOX64_FIRST
    }

    public enum Confidence {
        CANDIDATE_NOT_YET_RUNTIME_TESTED,
        HOST_WORKER_COMPILED_RUNTIME_UNTESTED,
        MANUAL_ABI_REVIEW_REQUIRED,
        UNSUPPORTED_WITH_CURRENT_AEX_HOSTS
    }

    public static final class LaunchPlan {
        public final String backendId;
        public final String wineRuntimeId;
        public final String containerPatternAsset;
        public final String launcher;
        public final String hostWorker;
        public final String hodll;
        public final Confidence confidence;
        public final List<String> components;

        private LaunchPlan(
                String backendId,
                String wineRuntimeId,
                String containerPatternAsset,
                String launcher,
                String hostWorker,
                String hodll,
                Confidence confidence,
                List<String> components) {
            this.backendId = Objects.requireNonNull(backendId);
            this.wineRuntimeId = Objects.requireNonNull(wineRuntimeId);
            this.containerPatternAsset = Objects.requireNonNull(containerPatternAsset);
            this.launcher = Objects.requireNonNull(launcher);
            this.hostWorker = Objects.requireNonNull(hostWorker);
            this.hodll = hodll;
            this.confidence = Objects.requireNonNull(confidence);
            this.components = Collections.unmodifiableList(new ArrayList<>(components));
        }

        @Override
        public String toString() {
            return backendId + " [" + wineRuntimeId + ", worker=" + hostWorker
                    + ", confidence=" + confidence + "]";
        }
    }

    private WindowsRuntimeSelector() {}

    /**
     * Returns candidate execution paths in preference order.
     * x86-64 AEX uses an x64 aexlo worker; x86 AEX uses the separately built
     * i686 worker. ARM64EC/ARM64X PE files require a matching host ABI that is
     * not yet provided by the current aexlo builds.
     */
    public static List<LaunchPlan> candidates(int peMachine, Preference preference) {
        List<LaunchPlan> plans = new ArrayList<>();
        switch (peMachine) {
            case IMAGE_FILE_MACHINE_AMD64:
                addX64(plans);
                addArm64EcFex(plans, "effectcraft-aex-host-x64.exe",
                        Confidence.CANDIDATE_NOT_YET_RUNTIME_TESTED);
                break;
            case IMAGE_FILE_MACHINE_I386:
                addArm64EcFex(plans, "effectcraft-aex-host-x86.exe",
                        Confidence.HOST_WORKER_COMPILED_RUNTIME_UNTESTED);
                addArm64EcWow(plans, "effectcraft-aex-host-x86.exe",
                        Confidence.HOST_WORKER_BUILD_CONFIRMED);
                addBox64Box32(plans, "effectcraft-aex-host-x86.exe");
                break;
            case IMAGE_FILE_MACHINE_ARM64EC:
                plans.add(new LaunchPlan(
                        "arm64ec-native-host-required",
                        "proton-9.0-arm64ec",
                        "proton-9.0-arm64ec_container_pattern.tzst",
                        "ARM64EC Proton/Wine direct launcher",
                        "No ARM64EC aexlo worker is built yet",
                        "libwow64fex.dll or wowbox64.dll (not a substitute for an ARM64EC AEX host)",
                        Confidence.MANUAL_ABI_REVIEW_REQUIRED,
                        List.of("Proton 9.0 ARM64EC", "FEXCore or WowBox64")));
                break;
            case IMAGE_FILE_MACHINE_ARM64X:
                plans.add(new LaunchPlan(
                        "arm64x-manual-review",
                        "proton-9.0-arm64ec",
                        "proton-9.0-arm64ec_container_pattern.tzst",
                        "No automatic launcher",
                        "ARM64X-capable AEX host required",
                        null,
                        Confidence.MANUAL_ABI_REVIEW_REQUIRED,
                        List.of("ARM64X PE loader and matching host ABI")));
                break;
            case IMAGE_FILE_MACHINE_ARM64:
                plans.add(new LaunchPlan(
                        "arm64-native-host-required",
                        "proton-9.0-arm64ec",
                        "proton-9.0-arm64ec_container_pattern.tzst",
                        "Native ARM64 process only if the plug-in is a valid ARM64 Windows PE",
                        "No native ARM64 aexlo Windows worker is built yet",
                        null,
                        Confidence.UNSUPPORTED_WITH_CURRENT_AEX_HOSTS,
                        List.of("ARM64 Windows PE loader", "ARM64 AEX host")));
                break;
            default:
                break;
        }
        orderByPreference(plans, preference);
        return Collections.unmodifiableList(plans);
    }

    private static void addX64(List<LaunchPlan> plans) {
        plans.add(new LaunchPlan(
                "x86_64-proton-box64",
                "proton-9.0-x86_64",
                "proton-9.0-x86_64_container_pattern.tzst",
                "/usr/bin/box64 <proton-bin>/<guest-executable>",
                "effectcraft-aex-host-x64.exe",
                null,
                Confidence.CANDIDATE_NOT_YET_RUNTIME_TESTED,
                List.of("ImageFS", "Proton 9.0 x86_64", "Box64 Android ARM64")));
    }

    private static void addArm64EcFex(
            List<LaunchPlan> plans, String worker, Confidence confidence) {
        plans.add(new LaunchPlan(
                "arm64ec-proton-fexcore",
                "proton-9.0-arm64ec",
                "proton-9.0-arm64ec_container_pattern.tzst",
                "<proton-bin>/<guest-executable> (direct ARM64EC Wine/Proton launch)",
                worker,
                "libwow64fex.dll",
                confidence,
                List.of("ImageFS", "Proton 9.0 ARM64EC", "FEXCore ARM64EC", "FEXCore WoW64")));
    }

    private static void addArm64EcWow(
            List<LaunchPlan> plans, String worker, Confidence confidence) {
        plans.add(new LaunchPlan(
                "arm64ec-proton-wowbox64",
                "proton-9.0-arm64ec",
                "proton-9.0-arm64ec_container_pattern.tzst",
                "<proton-bin>/<guest-executable> (direct ARM64EC Wine/Proton launch)",
                worker,
                "wowbox64.dll",
                confidence,
                List.of("ImageFS", "Proton 9.0 ARM64EC", "WowBox64")));
    }

    private static void addBox64Box32(List<LaunchPlan> plans, String worker) {
        plans.add(new LaunchPlan(
                "x86_64-proton-box64-box32",
                "proton-9.0-x86_64",
                "proton-9.0-x86_64_container_pattern.tzst",
                "/usr/bin/box64 (BOX32=ON) <proton-bin>/<guest-executable>",
                worker,
                null,
                Confidence.CANDIDATE_NOT_YET_RUNTIME_TESTED,
                List.of("ImageFS", "Proton 9.0 x86_64", "Box64 BOX32", "32-bit Wine/WoW64 libraries")));
    }

    private static void orderByPreference(List<LaunchPlan> plans, Preference preference) {
        if (preference == null || preference == Preference.AUTO || plans.size() < 2) return;
        String first = preference == Preference.BOX64_FIRST
                ? "box64"
                : preference == Preference.FEXCORE_FIRST
                    ? "fexcore"
                    : "wowbox64";
        plans.sort((left, right) -> Boolean.compare(
                !left.backendId.contains(first), !right.backendId.contains(first)));
    }
}
