# Termux Hangover 11.16 / Android Bionic audit

Audit date: 2026-11-14

## Decision

Promote the official Termux `hangover-wine` 11.16 package recipe to the **preferred next Android-native execution candidate**. Keep the existing Winlator/Proton route as a separate comparison/fallback. This is a source/package audit only: it is not yet integrated into EffectCraft and has not been executed on an EffectCraft Android app UID or device.

The key architectural advantage is that Wine itself is built for Android Bionic/ARM64. Hangover's emulator DLLs translate only Windows guest code at the WoW64/ARM64EC boundary. This avoids the failed design of putting the entire Bionic Wine host under Linux Box64.

## Pinned upstream evidence

| Component | Verified source state |
|---|---|
| Termux package recipe | `termux/termux-packages@e0ce77d242bb9f9adb48cc38dca4d69b3b6d0af9`, 2026-11-13 |
| Package path/version | `x11-packages/hangover-wine/build.sh`, version `11.16` |
| Wine source tag | `AndreRH/wine:hangover-11.16`, commit `628d1aeb09803d3fa9170023e7203060e955bfe8` |
| Wine source archive SHA-256 | `21e4dd77a9d1d4897194d5751e03a5fc6cdec4390889ad6a652b87d05aa0bb4d` |
| Hangover release | `AndreRH/hangover:hangover-11.16`, published 2026-08-30 |
| Release Wine submodule | `3ea3a14941b6a122b892c84141ce9662c008081e` |
| Release FEX submodule | `fa556167d5a64ec7adb5503c2aa15b169c292cac` |
| Release Box64 submodule | `2f130fab1d6e1a4ee8a71dc60cfdfcc839ad192a` |
| Ubuntu ARM64 helper asset | `hangover_11.16_ubuntu2204_jammy_arm64.tar`, 312,883,200 bytes |
| Helper asset SHA-256 | `ecde5846b2f1b23d394fede04a52cbf31853076b85e98d53a391d9e758345488` |

The Termux recipe downloads the Wine source archive and the Hangover 11.16 release helper tar. It extracts the three emulator DLL packages from that helper tar and installs their PE DLLs into the Bionic Wine prefix.

## Architecture actually selected by Hangover

- **Windows x86_64 PE:** ARM64EC Wine plus `HODLL64=libarm64ecfex.dll` (FEX PE emulator).
- **Windows x86 PE:** ARM64 WoW64 Wine plus `HODLL=libwow64fex.dll` (FEX WoW64 PE emulator).
- **Alternative x86 PE path:** `wowbox64.dll` (Box64-based Hangover PE emulator).
- Wine configure enables `i386,aarch64,arm64ec`.
- Hangover breaks out of emulation at Wine/Win32 syscall boundaries; the Unix host and Wine system calls remain native ARM64. Its README says this design does not require a separate 32-bit Unix userspace.

This means the successful EffectCraft Box64 `BOX32=ON` build is useful as an optional classic Box64/Linux-Wine fallback, but it is **not a prerequisite** for the preferred Hangover FEX WoW64 route. BOX32 build success still does not prove x86 Windows PE execution.

## Android/Bionic recipe details

The pinned Termux recipe:

- builds Wine from source with the Termux Android toolchain and LLVM-MinGW;
- enables `i386,aarch64,arm64ec`;
- links `libandroid-spawn` and uses `-Wl,--rosegment`;
- disables the `userfaultfd` header because it is unavailable on older Android releases;
- disables unsupported/unused host integrations including OpenCL, ALSA, DBus, GStreamer, FFmpeg, USB, V4L2 and several desktop services;
- enables OpenGL, Vulkan, PulseAudio, SDL, X11-related libraries and font support.

Termux carries three Wine patches:

1. `0001-fix-paths.patch`: Termux prefix paths for certificates, libraries, debug symbols, wineserver temporary sockets, Wine prefix drive mapping and desktop helpers.
2. `0002-no-pthread_mutexattr_setprotocol.patch`: avoids a robust priority-protocol call unavailable on older Android APIs.
3. `0003-fix-socket-ipx.patch`: disables unsupported IPX socket support on Android.

The package metadata declares LGPL-2.1 for the Wine/Hangover package. The FEX DLL package carries FEX's MIT license; the WowBox64 package carries Box64's MIT license. The runtime also depends on packages such as `libandroid-spawn`, PulseAudio, Vulkan loader, SDL, OpenGL and X11 libraries. A complete dependency SBOM and license/NOTICE review is still required before redistribution inside an APK.

## Proven Termux behavior and its limits

Termux issue [#27663](https://github.com/termux/termux-packages/issues/27663) is useful real-device evidence, but its history is more nuanced than a blanket x86/x64 success. On Android 15 / Samsung SM-A057G, the reporter said x86 worked in rc5 while x64 failed because `libarm64ecfex.dll` was missing from a freshly generated Wine prefix. A later user reported that installing every Hangover package and recreating the prefix fixed their problem, but also warned that x64 programs might freeze shortly after loading. The issue was closed by a maintainer on 2026-03-21 as presumed resolved; it does not contain a reproducible full x64 stability test or AE plug-in test.

The reported environment used:

- `LD_PRELOAD=/data/data/com.termux/files/usr/lib/libtermux-exec-ld-preload.so`;
- the Termux X11 repository and Termux:X11 plug-in;
- ARM64 Termux on a Samsung SM-A057G with Android 15 / kernel 5.15.

Treat this as evidence that the Termux Hangover package family can run x86 on at least one real Android device and that the x64 ARM64EC DLL/prefix installation order is critical. It is not evidence for EffectCraft, OPPO PEMM00, Huawei, or the EffectCraft AEX host.

## Process launching: reuse Termux's proven design

Current upstream `termux-play-store/termux-exec` is Apache-2.0, commit `47633d5df2db3dfea34cef568c6c82a7ba8dcc2e` (2026-02-22). Its README and source show why a small exec wrapper is needed on Android 10+:

- intercepts libc exec-family calls with `LD_PRELOAD`;
- launches app-private Bionic ELF files as `/system/bin/linker64 <absolute-path> ...`;
- handles shebang interpreters and path normalization;
- preserves `LD_PRELOAD` and `LD_LIBRARY_PATH` for private runtime children;
- removes those variables when launching unrelated Android system executables;
- preserves the logical executable path using `TERMUX_EXEC__PROC_SELF_EXE` and hooks `readlink`/`realpath` for `/proc/self/exe`.

Important limits documented upstream: raw `syscall(SYS_execve)` bypasses LD_PRELOAD, statically linked executables are unsupported, and applications that inspect `/proc/self/exe` need the compatibility hook.

EffectCraft's current `libeffectcraft-exec.so` prototype passed its host-side linker-shim test and Android NDK ARM64 build in run [43548375417](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43548375417), but it has not run on an Android device. The runtime manager was then corrected to accept the APK's `nativeLibraryDir/libeffectcraft-exec.so`, set `LD_PRELOAD` and `EFFECTCRAFT_RUNTIME_ROOT` for Wine/Box64 child processes, and fail closed if the bridge library is absent. The manager now keeps Bionic host `LD_LIBRARY_PATH` separate from the glibc guest rootfs: Box64 host gets `/system/lib64`, ARM64EC adds its native Wine `lib` directory, and x86_64 guest libraries remain in `BOX64_LD_LIBRARY_PATH`. A unit test was added for this separation, and the Android library Gradle module now builds/packages the ARM64 CMake library; validation run [43550017062](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43550017062) is still running. This does not yet prove the module is included in the separate production APK workflow or that the bridge works on a real ARM64 phone. Remaining bridge gaps: Termux-equivalent shebang/PATH handling, `/proc/self/exe` hooks, system-executable environment cleanup, `execveat` and raw-syscall audit.

## Build reproducibility work started

A reproducible workflow now builds the pinned Termux package recipe in its own build system. The recipe contains `make -k || bash` as a developer-interactive fallback; the CI copy replaces that with a fail-closed make command. Two infrastructure blockers were found and corrected: the hosted runner already has Docker (installing `docker.io` conflicted with its `containerd.io`), and Termux requires its pinned NDK r30 under the expected `NDK` path. The workflow now invokes Termux's own checksum-verifying `scripts/setup-android-sdk.sh` to install NDK r30. Latest package reproduction run [43550017038](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43550017038) is in progress. It will archive the Hangover .deb packages, inspect Bionic ELF interpreters and PE machine/CHPE metadata, and record checksums. This is a cross-build/package audit only, not Android execution.

## Current EffectCraft evidence (2026-11-14)

- Box64 Android ARM64 with `BOX32=ON`: compile/link/package succeeded again in run [43549637022](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43549637022), artifact 14095870361 (5,808,322 bytes). This is an AArch64 PIE build; no x86 Linux ELF fixture has run on Android.
- Current upstream FEX ARM64EC/WoW64 PE DLLs, Android Box64 and Windows x64 AEX worker: all three build jobs succeeded in run [43549637028](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43549637028). Artifacts: FEX 14095950159 (2,360,749 bytes), Box64 14095796194 (5,258,808 bytes), AEX host 14095414177 (8,155,573 bytes). Build success is not device execution.
- Windows x64 AEX host and Noise sample DLL also built in the same run; the separate ARM64 Linux Wine/Box64/Proton host-execution job remains in progress in run [43549637001](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43549637001). Even if it passes, it is Linux ARM64, not Android Bionic.
- Bionic exec bridge: host interception test and Android NDK ARM64 shared-library/fixture build succeeded in run [43548375417](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43548375417), artifact 14095630837 (19,638 bytes); no Android app UID execution test.
- Runtime manager library-path/LD_PRELOAD corrections and the new unit test are under validation in run [43550017062](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43550017062). The emulator stage is x86_64 and cannot substitute for a real ARM64 phone test.
- Termux Hangover 11.16 Bionic package reproduction is running in [43550017038](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43550017038); no .deb output has been verified yet.
- The fallback build run [43549636997](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43549636997) has CLVK build success and QEMU x86-64 Linux-user build still in progress.
- The main APK build currently fails in an unrelated Rust UI integration step (`open_ai_plugin_import_from_toolbar` unresolved), and no installable APK is produced by that run.

## Next verification order

1. Reproduce the Termux 11.16 Bionic package set from the pinned recipe and archive its four .deb outputs.
2. Relocate the Termux prefix from `/data/data/com.termux/files/usr` to EffectCraft private storage without leaving absolute Termux paths in Wine, wineserver, registry, loader or DLL search paths.
3. Integrate/adapt Termux-exec semantics in the NDK bridge; verify linker64, `LD_PRELOAD`, argv, environment, shebangs, `/proc/self/exe`, exec variants and helper processes.
4. On an ARM64 Android app UID, launch a Bionic Wine console PE fixture, then x86_64 PE and x86 PE fixtures through FEX/ARM64EC and WoW64.
5. Only after those pass, run the x64/x86 aexlo host and a real AEX sample through parameter inspection and CPU frame rendering.
6. Add Android Surface, input, audio and GPU validation separately. Termux:X11/PulseAudio is not itself an EffectCraft Surface integration.

## M0-M5 status

| Milestone | Status |
|---|---|
| M0 source/license/package recipe audit | Partial: Hangover/Termux/exec-wrapper source reviewed; full dependency SBOM pending |
| M1 minimal Win32 PE on Android Bionic | Not passed |
| M2 x86_64 PE + DLL/thread/memory/exception/I/O on Android | Not passed |
| M3 graphics/audio/input on Android | Not passed |
| M4 EffectCraft APK runtime integration | Not passed |
| M5 real third-party/AE plug-in load, parameters and render on Android | Not passed |


## Fresh upstream and CI review (2026-11-15)

### Current upstream heads checked

- [AndreRH/Hangover](https://github.com/AndreRH/hangover) remains on its `master` branch with the latest release `hangover-11.16`, published 2026-08-30. Its current `.gitmodules` still selects Wine `arm64ec`, FEX `arm64ec`, and Box64 `wow64`; these are coordinated PE-emulation branches, not interchangeable with the ordinary Linux ELF FEX/Box64 mainlines.
- Hangover's selected submodule heads were rechecked: Wine `3ea3a14941b6a122b892c84141ce9662c008081e`, FEX `fa556167d5a64ec7adb5503c2aa15b169c292cac`, and Box64 `2f130fab1d6e1a4ee8a71dc60cfdfcc839ad192a`.
- [Termux packages](https://github.com/termux/termux-packages) current master was `8eb3169dbd10d71ef26e2847191f9ae2a452ab2e` (2026-11-14). Its current `x11-packages/hangover-wine/build.sh` still uses 11.16 and the same Wine/helper asset checksums as the pinned reproducible build. No newer Termux Hangover package version was found in this review.
- Official Hangover release: https://github.com/AndreRH/hangover/releases/tag/hangover-11.16
- Official Termux recipe: https://github.com/termux/termux-packages/tree/master/x11-packages/hangover-wine

### New build evidence and exact boundaries

- **Box64 BOX32:** run [43552790576](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43552790576) completed successfully. It produced artifact `EffectCraft-Box64-BOX32-Android-ARM64`, artifact ID `14097046894`, 5,811,231 bytes. This confirms Android NDK compile/link/package of the AArch64 Box64 binary with BOX32 enabled; it does not show that a 32-bit x86 Linux ELF or Windows PE was executed.
- **Current Hangover PE emulator components:** run [43552787304](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43552787304) built the Android Box64 backend, Windows x64 AEX worker, and current FEX ARM64EC/WoW64 PE backends successfully. The FEX job inspected `libarm64ecfex.dll` as PE machine `0x8664`, CHPE version 1, with required exports; `libwow64fex.dll` was PE machine `0xaa64` with required exports. Artifacts: Box64 5,266,328 bytes; FEXCore ARM64EC/WoW64 2,360,748 bytes; AEX host 8,155,573 bytes. These are build and static PE-metadata checks, not Android execution.
- **Invalid Box64+Bionic Wine pairing:** run [43552783748](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43552783748) built the Windows x64 AEX host and sample plug-in, but its Linux ARM64 test of Bionic Proton/Wine under Box64 failed with `Symbol __libc_init not found` and exit 139. Do not use this pairing as the preferred route; the failure is a host-ABI mismatch. The Termux Hangover approach keeps Wine native to Bionic and emulates Windows PE guest code at the Hangover boundary.
- **Termux package build:** run [43553764486](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43553764486) failed during PulseAudio Meson configuration because `sndfile` was unavailable. The app-specific package-ID build cannot consume Termux's prebuilt dependencies through the default `-i` path, and PulseAudio declares `libsndfile` only as a runtime dependency even though its Meson configure requires it. CI now promotes `libsndfile` to a build dependency in a local-only patch; upstream Termux package metadata is not modified. Fix commit: `4e9af7daf6fcfb8dcd270071bfbc3182ada4d7a0`. A fresh build is triggered; result pending.
- **Compatibility validation:** run [43553764420](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43553764420) failed because the validator added a toolbar call to `open_ai_plugin_import_from_toolbar` but did not apply the AI bridge patch that defines it. The validation workflow now applies the same bridge as the APK build, and the bridge script independently guarantees both Android and non-Android definitions. Fix commits: `79fc8f3d4d4741a28f68e70e1f1fcf856ccb6a1e` and `2b58ed4dfefae68deea8ae8aba5fbbe6d2ac6350`. Fresh validation result pending.

### Revised M0-M5 status

| Milestone | Current status |
|---|---|
| M0 source/license/package audit | Partial; current Hangover/Termux branches and build recipes reviewed; full transitive dependency SBOM and redistribution notice bundle still pending |
| M1 minimal Win32 PE on Android Bionic | Not passed; Termux user reports x86 operation on Samsung Android 15, but no EffectCraft app-UID reproduction yet |
| M2 x86_64 PE + DLL/thread/memory/exception/I/O on Android | Not passed; ARM64EC PE DLLs build and CHPE metadata checks pass, but real x64 execution/stability is not established |
| M3 graphics/audio/input on Android | Not passed; PulseAudio package build currently being repaired; no Android Surface/GPU/audio/input test |
| M4 EffectCraft APK integration | Not passed; runtime manager still needs a dedicated native-Bionic Hangover install/launch path and a signed installable APK |
| M5 real third-party/AE plug-in test | Not passed; AEX host builds, but no real AEX has loaded/rendered on Android |

### Next actions

1. Complete the new PulseAudio/libsndfile dependency build and inspect all five expected package outputs, their dependency metadata, ELF interpreter, PE machine/CHPE metadata, and checksums.
2. Build a complete redistributable dependency closure rather than shipping only the four Hangover packages plus termux-exec; relocate all package payloads into EffectCraft's private prefix and audit embedded absolute paths.
3. Add a native-Bionic Hangover installer/launcher to the Android runtime manager. Do not route this Wine host through Box64. Install all emulator DLLs before creating the Wine prefix; create separate clean prefixes for x86 and x86_64.
4. Run console PE smoke tests under the EffectCraft package UID before wiring the AEX worker. Then test x86 and x64 DLL loading, threads, mappings, exceptions, file I/O, and repeatable launch/shutdown.
5. Integrate the Windows x64 and x86 AEX workers only after their respective Wine/PE paths pass. Start with a redistributable sample plug-in and CPU rendering; real third-party plug-ins require separate host-API and license review.
