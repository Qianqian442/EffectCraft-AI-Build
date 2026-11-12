package com.effectcraft.windowscompat;

import java.net.URI;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;

/** Immutable source catalog for the pinned Winlator Bionic runtime components. */
public final class WinlatorBionicAssetCatalog {
    private static final String EXTRA = "https://gitlab.com/winlator3/winlator-extra/-/raw/main/";
    private static final String RAW =
            "https://raw.githubusercontent.com/EmuProto/Winlator-Ludashi/95224ca7db27ae133dbb1578e004b94b86ef8894/app/src/main/assets/";

    private WinlatorBionicAssetCatalog() {}

    public static RuntimeAssetInstaller.AssetSpec imageFs() {
        return new RuntimeAssetInstaller.AssetSpec(
                "ubuntu-bionic-imagefs-v21",
                List.of(
                        URI.create(EXTRA + "imagefs/imagefs.txz.00"),
                        URI.create(EXTRA + "imagefs/imagefs.txz.01"),
                        URI.create(EXTRA + "imagefs/imagefs.txz.02"),
                        URI.create(EXTRA + "imagefs/imagefs.txz.03")),
                URI.create(EXTRA + "imagefs/imagefs.txz.sha256sum"),
                RuntimeAssetInstaller.DigestKind.SHA256_SIDECAR,
                null,
                -1,
                Paths.get("downloads/imagefs-v21.txz"));
    }

    public static RuntimeAssetInstaller.AssetSpec protonX64() {
        return sha256Asset("proton-9.0-x86_64",
                EXTRA + "proton/proton-9.0-x86_64.txz",
                EXTRA + "proton/proton-9.0-x86_64.txz.sha256sum",
                "downloads/proton-9.0-x86_64.txz");
    }

    public static RuntimeAssetInstaller.AssetSpec protonArm64Ec() {
        return sha256Asset("proton-9.0-arm64ec",
                EXTRA + "proton/proton-9.0-arm64ec.txz",
                EXTRA + "proton/proton-9.0-arm64ec.txz.sha256sum",
                "downloads/proton-9.0-arm64ec.txz");
    }

    public static RuntimeAssetInstaller.AssetSpec x64ContainerPattern() {
        return gitAsset("proton-9.0-x86_64-container-pattern",
                "proton-9.0-x86_64_container_pattern.tzst",
                "c7a6ed5972f6a357ed033da88b5de0dc5eaaf468",
                8698674,
                "downloads/proton-9.0-x86_64-container-pattern.tzst");
    }

    public static RuntimeAssetInstaller.AssetSpec arm64EcContainerPattern() {
        return gitAsset("proton-9.0-arm64ec-container-pattern",
                "proton-9.0-arm64ec_container_pattern.tzst",
                "6a2fe6f1a7aa2f70d6f15d2c057fc7c6b2246248",
                10309411,
                "downloads/proton-9.0-arm64ec-container-pattern.tzst");
    }

    /** Current pinned Android Box64 WCP (0.4.5, built from ptitSeb/box64@4dbba1300). */
    public static RuntimeAssetInstaller.AssetSpec box64() {
        return wcpAsset("box64-0.4.5-4dbba1300",
                "https://github.com/Xnick417x/winlator-nightly-wcp/releases/download/box64-nightly-0.4.5-4dbba1300/Box64-0.4.5-4dbba1300.wcp",
                "9e8e6cda22cecf6c975ebc7d4521a2e08565f4287a479e9db53fcd2850883256",
                2901992,
                "downloads/box64-0.4.5-4dbba1300.wcp");
    }

    /** Current pinned Android ARM64EC/WoW64 FEXCore WCP (2611). */
    public static RuntimeAssetInstaller.AssetSpec fexCore() {
        return wcpAsset("fexcore-2611-ab135df09",
                "https://github.com/Xnick417x/winlator-nightly-wcp/releases/download/fex-nightly-2611-ab135df09/FEXCore-2611-ab135df09.wcp",
                "6a8ad93996147fc23d9dd4c541b84b03c19f11911db431f6d155b5b15f9a9c86",
                1104420,
                "downloads/fexcore-2611-ab135df09.wcp");
    }

    /** Current pinned Android ARM64EC/WoW64 alternative WCP (0.4.5). */
    public static RuntimeAssetInstaller.AssetSpec wowBox64() {
        return wcpAsset("wowbox64-0.4.5-4dbba1300",
                "https://github.com/Xnick417x/winlator-nightly-wcp/releases/download/wowbox64-nightly-0.4.5-4dbba1300/WOWBox64-0.4.5-4dbba1300.wcp",
                "6037af9cc15bf036eb77077423806798e043cf81370dea40cc9ae17d60a09d39",
                910648,
                "downloads/wowbox64-0.4.5-4dbba1300.wcp");
    }

    /** Older known-good packages retained as fallback during compatibility testing. */
    public static RuntimeAssetInstaller.AssetSpec box64Legacy() {
        return gitAsset("box64-0.3.7",
                "box64/box64-0.3.7.tzst",
                "32c8a016de8368c68090c27e6de91389f927cc04",
                2971992,
                "downloads/box64-0.3.7.tzst");
    }

    public static RuntimeAssetInstaller.AssetSpec fexCoreLegacy() {
        return gitAsset("fexcore-2508",
                "fexcore/fexcore-2508.tzst",
                "9cde1a54074e183ef627c1d1a18a943cff622c86",
                3416724,
                "downloads/fexcore-2508.tzst");
    }

    public static RuntimeAssetInstaller.AssetSpec wowBox64Legacy() {
        return gitAsset("wowbox64-0.3.7",
                "wowbox64/wowbox64-0.3.7.tzst",
                "807702ccb71c7ee5c0983f02e5217517cb3caf95",
                1049978,
                "downloads/wowbox64-0.3.7.tzst");
    }

    private static RuntimeAssetInstaller.AssetSpec wcpAsset(
            String id, String url, String sha256, long size, String destination) {
        return new RuntimeAssetInstaller.AssetSpec(
                id,
                List.of(URI.create(url)),
                null,
                RuntimeAssetInstaller.DigestKind.SHA256_SIDECAR,
                sha256,
                size,
                Paths.get(destination));
    }

    private static RuntimeAssetInstaller.AssetSpec sha256Asset(
            String id, String url, String checksum, String destination) {
        return new RuntimeAssetInstaller.AssetSpec(
                id,
                List.of(URI.create(url)),
                URI.create(checksum),
                RuntimeAssetInstaller.DigestKind.SHA256_SIDECAR,
                null,
                -1,
                Paths.get(destination));
    }

    private static RuntimeAssetInstaller.AssetSpec gitAsset(
            String id, String relativeUrl, String sha1, long size, String destination) {
        return new RuntimeAssetInstaller.AssetSpec(
                id,
                List.of(URI.create(RAW + relativeUrl)),
                null,
                RuntimeAssetInstaller.DigestKind.GIT_BLOB_SHA1,
                sha1,
                size,
                Paths.get(destination));
    }
}
