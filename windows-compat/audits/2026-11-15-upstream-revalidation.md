# Android ARM64 Windows PE runtime — upstream revalidation (2026-11-15)

## Executive decision

Keep the primary design as **ARM64-native Bionic Wine/Hangover + a single PE emulator DLL at the WoW64/ARM64EC boundary**. Do not run the whole x86_64 Wine userspace under Linux Box64 for the primary route. Keep Box64 BOX32 and QEMU linux-user as isolated diagnostic/fallback experiments, not stacked into the primary path.

This is an upstream source revalidation and build-plan decision. It is not proof of Android PE execution.

## Exact upstream revisions checked

| Project | Revision checked | Finding |
|---|---|---|
| AndreRH/Hangover master | `56e385b7ff490edd281b288f420677093563560b` (2026-08-28) | Current README still documents ARM64-native Wine, ARM64EC + FEX for x86_64 PE, and FEX/Box64 PE DLL choices for x86 |
| Hangover Wine submodule | `3ea3a14941b6a122b892c84141ce9662c008081e` (2026-08-23) | Wine ARM64EC branch pinned by current Hangover tree |
| Hangover FEX submodule | `fa556167d5a64ec7adb5503c2aa15b169c292cac` (2026-08-09) | AndreRH/FEX ARM64EC branch pinned by current Hangover tree |
| Hangover Box64 submodule | `2f130fab1d6e1a4ee8a71dc60cfdfcc839ad192a` (2026-08-02) | AndreRH/box64 wow64 branch pinned by current Hangover tree |
| FEX upstream main | `ea43314f040633c76fb5891ff31d8a7c3dc533b8` (2026-11-14) | Contains PE targets `Source/Windows/ARM64EC` and `Source/Windows/WOW64`, with `libarm64ecfex.def` and `libwow64fex.def` |
| Box64 upstream main | `085b7cb8136495f807267523d31f6775790dacfa` (2026-11-14) | Contains `wine/wow64/wowbox64.c`, the 32-bit x86 Windows WoW64 CPU DLL path |
| Termux packages master | `8eb3169dbd10d71ef26e2847191f9ae2a452ab2e` (2026-11-14) | Current `x11-packages/hangover-wine/build.sh` is byte-for-byte identical to the EffectCraft workflow's audited Termux pin `e0ce77d242bb9f9adb48cc38dca4d69b3b6d0af9` |

Primary links:
- https://github.com/AndreRH/hangover/commit/56e385b7ff490edd281b288f420677093563560b
- https://github.com/AndreRH/hangover/blob/master/README.md
- https://github.com/AndreRH/hangover/blob/master/docs/COMPILE.md
- https://github.com/termux/termux-packages/blob/master/x11-packages/hangover-wine/build.sh
- https://github.com/FEX-Emu/FEX/commit/ea43314f040633c76fb5891ff31d8a7c3dc533b8
- https://github.com/ptitSeb/box64/commit/085b7cb8136495f807267523d31f6775790dacfa

## Architecture findings

### Hangover remains the best-fit primary architecture

Hangover runs the Wine/Windows API implementation natively on ARM64 and emulates only the Windows guest code at the PE/WoW64 boundary. Its README identifies:
- `HODLL64=libarm64ecfex.dll` for x86_64 PE via FEX/ARM64EC;
- `HODLL=libwow64fex.dll` for x86 PE via FEX;
- `HODLL=wowbox64.dll` as an alternative x86 PE emulator.

Its build guide explicitly says one emulator is sufficient for a use case, except the x86_64 FEX ARM64EC DLL is required for x86_64 emulation. This supports avoiding a stack of full Linux emulation layers.

### Do not conflate the two Box64 routes

- `wowbox64.dll` is a Windows PE/WoW64 CPU emulator DLL for 32-bit x86 code inside ARM64 Wine.
- Box64 `BOX32=ON` adds 32-bit x86 **Linux ELF** support to an ARM64 Box64 process. It does not itself load Windows PE or implement Win32 APIs.
- The earlier Box64 + Bionic Proton whole-Wine route failed with unresolved `__libc_init` and SIGSEGV; do not re-promote that exact route as the primary design.

### Newer upstream FEX is not automatically ABI-compatible

FEX upstream main (2026-11-14) has active ARM64EC and WoW64 PE targets and is newer than the Hangover-pinned AndreRH/FEX branch from 2026-08-09. This is a promising refresh candidate, but its PE exports, Wine CPU interface, ARM64EC ABI, exception/context hand-off and Wine 11.16 compatibility must be tested together before replacing the release-matched emulator DLLs. Do not simply substitute the newer DLLs into the older Wine package.

## Current Termux/Bionic recipe facts

The latest Termux repository HEAD still has Hangover Wine package version 11.16 and the same recipe bytes as the pinned revision used in the current CI reproduction.

The recipe:
- builds Wine against the Termux/Bionic toolchain;
- enables `i386,aarch64,arm64ec`;
- enables OpenGL, Vulkan, PulseAudio, SDL and X11/XCB-related components;
- disables OpenCL and several desktop/Linux services not provided by the Android environment;
- uses `ac_cv_header_linux_userfaultfd_h=no` for Android kernels without userfaultfd support;
- links `libandroid-spawn` and uses `--rosegment`;
- declares package metadata license `LGPL-2.1`;
- pulls the Hangover 11.16 release payload and emulator DLL packages with pinned SHA-256 hashes.

Important CI hardening: upstream Termux recipe's `termux_step_make()` ends with `make ... -k || bash`, which is an interactive developer fallback. The EffectCraft CI reproduction patches this to fail closed rather than silently opening a shell. This is necessary for trustworthy build evidence.

The Termux package is not an Android Surface integration. Its X11/PulseAudio/SDL/OpenGL/Vulkan dependencies are reference plumbing; EffectCraft still needs an explicit Android Surface/input/audio bridge and tested GPU feature mapping.

## Build and test work updated in this run

### PE fixture workflow

The cross-build job exposed two CI-only fixture issues:
1. llvm-mingw's bin directory was added to `GITHUB_PATH`, which affects later workflow steps but not the current shell step. The same step now exports the directory directly into `PATH`.
2. Clang's MinGW target treated `__declspec(thread)` as an unknown attribute under `-Werror`. The fixture now uses the MinGW-compatible `__thread` TLS spelling.

Commits:
- `df3c40faefc5fe06dd2962acfa713490de99815a` — fix same-step llvm-mingw PATH;
- `0c854a8e111d365a6441f0c86c7b0e0ad23ae4e8` — update x86 helper TLS declaration;
- `ab583be00680e39ed3b7fdf284a9e20f60887665` — update x86/x64 main fixture TLS declaration.

Latest PE fixture workflow at the time of this audit:
https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43670646822

The latest job is still running; no fixture build result is claimed here. Once built, fixtures must still be executed on an Android ARM64 device under the Bionic Hangover prefix. Cross-compilation and PE metadata inspection alone are not runtime proof.

### Termux Hangover reproduction

The pinned Termux Bionic build workflow is still running:
https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43668930730

The latest available log tail shows dependency builds (including Xorg protocol packages) installing into the EffectCraft private prefix. It has not yet reached a verified final Hangover package set. Do not claim the Wine build is complete until the job, package inspection, Bionic ELF interpreter checks, emulator DLL checks and artifact checksums all pass.

## Remaining Android-specific gaps

1. **App-private executable launching:** Termux's package recipes use `libandroid-spawn` and Termux-specific linker interception. EffectCraft must own and validate its own linker64/exec bridge for every child process path, including spawn, direct exec, helper processes and wineserver.
2. **Relocation:** Termux packages target Termux paths. EffectCraft must prove Wine loader, wineserver, DLL search, registry/prefix, sockets, symlinks and helper binaries work under its own `/data/data/com.artcraft.effectcraft/files/windows-compat` root.
3. **Memory and page size:** test 4K/16K page devices, mmap reservation, executable memory transitions, W^X, address-space layout, shared mappings, signal/exception handling and JIT cache invalidation. Do not infer device support from a Linux CI build.
4. **CPU feature detection:** check ARMv8 and required FP/CRC32 capabilities before selecting FEX; log actual CPU feature flags and avoid advertising unavailable extensions to x86 guests.
5. **Graphics:** Wine X11/Wayland/DXVK paths need a compositor or a direct Android Surface path. DXVK needs Vulkan 1.3 and specific extensions/features; driver version alone is not enough.
6. **Audio/input:** map PulseAudio/SDL device handling, focus, touch/mouse/keyboard, clipboard and lifecycle to Android.
7. **AE host ABI:** successful PE execution is not full After Effects compatibility. AEX plug-ins require the correct host suites, callbacks, parameter model, pixel formats, threading/lifecycle and render API. Current aexlo host is experimental and CPU-first; AEGP/SmartFX and GPU callback coverage remain incomplete.

## License and redistribution gate

The Termux recipe labels the Wine package LGPL-2.1; Hangover repository is LGPL-2.1; FEX and Box64 carry their own permissive license notices, but the final bundle also contains many transitive libraries and package-specific copyright files. Before APK redistribution, generate a complete package-level SBOM, preserve notices, provide corresponding source and comply with each license's relinking/source obligations. No DRM, account, activation, anti-cheat or hardware-authorization bypass is in scope.

## Milestone state (2026-11-15)

| Milestone | Evidence/status |
|---|---|
| M0 source/build/license audit | Upstream revisions and Termux recipe rechecked; full transitive SBOM still incomplete |
| M1 minimal Win32 PE on Android ARM64 | Not demonstrated |
| M2 x86_64 PE with DLL, threads, TLS, memory, exceptions and I/O | PE fixtures are being cross-built; no Android execution result |
| M3 graphics/audio/input/device matrix | Not demonstrated |
| M4 EffectCraft APK integration and install validation | Not demonstrated |
| M5 real third-party/AE AEX load, parameters, rendering and stability | Not demonstrated |

No architecture breakthrough is claimed. The next proof gate is: complete Bionic package build -> install privately in EffectCraft -> execute minimal x86_64 and x86 PE fixtures on Android ARM64 -> capture exact device/kernel/page size and logs -> only then load the AEX worker and real plug-in samples.
