# Android ARM64 Windows PE runtime — upstream revalidation (2026-11-15)

## Architecture decision

Keep the primary design as **ARM64-native Bionic Wine/Hangover + one PE emulator DLL at the WoW64/ARM64EC boundary**. Do not run the entire x86_64 Wine userspace under Linux Box64 for the primary route. Keep Box64 BOX32 and QEMU linux-user as isolated diagnostic/fallback experiments, not stacked into the primary path.

This is an upstream source revalidation and build-plan decision, not proof of Android PE execution.

## Exact upstream revisions checked

| Project | Revision checked | Finding |
|---|---|---|
| AndreRH/Hangover master | `56e385b7ff490edd281b288f420677093563560b` (2026-08-28) | ARM64-native Wine, ARM64EC + FEX for x86_64 PE, FEX/Box64 PE DLL choices for x86 |
| Hangover Wine submodule | `3ea3a14941b6a122b892c84141ce9662c008081e` (2026-08-23) | Wine ARM64EC branch pinned by Hangover |
| Hangover FEX submodule | `fa556167d5a64ec7adb5503c2aa15b169c292cac` (2026-08-09) | AndreRH/FEX ARM64EC branch pinned by Hangover |
| Hangover Box64 submodule | `2f130fab1d6e1a4ee8a71dc60cfdfcc839ad192a` (2026-08-02) | AndreRH/Box64 WoW64 branch pinned by Hangover |
| FEX upstream main | `ea43314f040633c76fb5891ff31d8a7c3dc533b8` (2026-11-14) | Has PE targets `Source/Windows/ARM64EC` and `Source/Windows/WOW64`, including `libarm64ecfex.def` and `libwow64fex.def` |
| Box64 upstream main | `085b7cb8136495f807267523d31f6775790dacfa` (2026-11-14) | Has `wine/wow64/wowbox64.c`, the 32-bit x86 Windows WoW64 CPU DLL path |
| Termux packages master | `8eb3169dbd10d71ef26e2847191f9ae2a452ab2e` (2026-11-14) | Current Hangover recipe is byte-for-byte identical to EffectCraft's pinned Termux revision `e0ce77d242bb9f9adb48cc38dca4d69b3b6d0af9` |

Primary links:
- https://github.com/AndreRH/hangover/commit/56e385b7ff490edd281b288f420677093563560b
- https://github.com/AndreRH/hangover/blob/master/README.md
- https://github.com/AndreRH/hangover/blob/master/docs/COMPILE.md
- https://github.com/termux/termux-packages/blob/master/x11-packages/hangover-wine/build.sh
- https://github.com/FEX-Emu/FEX/commit/ea43314f040633c76fb5891ff31d8a7c3dc533b8
- https://github.com/ptitSeb/box64/commit/085b7cb8136495f807267523d31f6775790dacfa

## Architecture findings

### Hangover is the best-fit primary architecture

Hangover runs Wine/Windows APIs natively on ARM64 and emulates only Windows guest code at the PE/WoW64 boundary. Its README documents:
- `HODLL64=libarm64ecfex.dll` for x86_64 PE via FEX/ARM64EC;
- `HODLL=libwow64fex.dll` for x86 PE via FEX;
- `HODLL=wowbox64.dll` as an alternative x86 PE emulator.

Its build guide says one emulator is sufficient for a use case, except the x86_64 FEX ARM64EC DLL is required for x86_64 emulation. This supports avoiding a stack of full Linux emulation layers.

### Do not conflate the two Box64 routes

- `wowbox64.dll` is a Windows PE/WoW64 CPU emulator DLL for 32-bit x86 code inside ARM64 Wine.
- Box64 `BOX32=ON` adds 32-bit x86 **Linux ELF** support to an ARM64 Box64 process. It does not itself load Windows PE or implement Win32 APIs.
- The earlier Box64 + Bionic Proton whole-Wine route failed with unresolved `__libc_init` and SIGSEGV; do not re-promote that exact route as primary.

### Newer FEX is not automatically ABI-compatible

FEX upstream main (2026-11-14) is newer than Hangover's pinned AndreRH/FEX branch (2026-08-09) and has ARM64EC/WoW64 PE targets. It is a refresh candidate, but its PE exports, Wine CPU interface, ARM64EC ABI, exception/context hand-off and Wine 11.16 compatibility must be tested together before replacing release-matched emulator DLLs.

## Current Termux/Bionic recipe

The latest Termux repository HEAD still has Hangover Wine 11.16 and the same recipe bytes as the pinned revision used in EffectCraft's CI reproduction.

The recipe:
- builds Wine against the Termux/Bionic toolchain;
- enables `i386,aarch64,arm64ec`;
- enables OpenGL, Vulkan, PulseAudio, SDL and X11/XCB components;
- disables OpenCL and several desktop/Linux services;
- sets `ac_cv_header_linux_userfaultfd_h=no` for Android kernels without userfaultfd support;
- links `libandroid-spawn` and uses `--rosegment`;
- declares package metadata license `LGPL-2.1`;
- downloads pinned Hangover 11.16 Wine and emulator payloads with SHA-256 checks.

The upstream Termux recipe has an interactive `make ... -k || bash` fallback. EffectCraft CI patches this to fail closed rather than silently opening a shell.

This package is not an Android Surface integration. X11/PulseAudio/SDL/OpenGL/Vulkan are reference plumbing; EffectCraft still needs explicit Android Surface/input/audio bridging and verified GPU feature mapping.

## Build/test evidence updated in this run

### Windows PE fixtures

Successful cross-build:
https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43670962887

- Commit: `82638e8deac633902366fb40a8449053641351ad`.
- Artifact: `EffectCraft-Windows-PE-Smoke-Fixtures`, artifact ID `14144440841`, uploaded 2026-11-15.
- Pinned llvm-mingw 20250319 successfully built x86 and x86_64 EXE/DLL pairs.
- PE audit passed for all four images: I386/AMD64 machine type, DLL flag, base relocations and static TLS directories.
- CI printed `x86: machine, DLL dependency fixture, TLS and relocations verified` and the same for `x86_64`.

This is cross-build + PE metadata evidence only. The fixtures have not yet been executed on Android.

### App-private linker/exec bridge

Host tests now pass for `execve`, `execveat` and `fexecve`, verifying that an app-private native ELF is redirected through a linker shim and argv is preserved:
https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43671001896

The first Android NDK test exposed that Bionic headers do not declare an `execveat()` libc prototype. The test now resolves the bridge's exported symbol with `dlsym` rather than directly linking to a non-public libc symbol. `-ldl` was added to both host and NDK fixture link commands.

The first bridge build completed successfully:
https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43671001896

A second build including explicit `-ldl` linkage also completed successfully:
https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43671169573

Both host-test and Android ARM64 NDK jobs passed. The artifact contains an AArch64 ELF64 shared library and ARM64 ELF fixtures whose PT_INTERP is `/system/bin/linker64`; it is a reproducible build artifact, not an Android-device execution result. No Android-device execution is claimed.

### Termux Hangover package reproduction

The pinned Termux Bionic build remains in progress:
https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43668930730

The latest available log tail shows dependency packages (including Xorg protocol packages) installing into the EffectCraft private prefix. It has not yet reached a verified final Hangover package set. Do not claim Wine build completion until package inspection, Bionic ELF interpreter checks, emulator DLL checks and artifact checksums all pass.

## Remaining Android-specific gaps

1. **App-private execution:** EffectCraft must own and validate its linker64/exec bridge for all child-process paths, including spawn, direct exec, helper processes and wineserver. Raw direct syscalls can bypass LD_PRELOAD symbol interposition and need source-level audit.
2. **Relocation:** Termux paths must be relocated to EffectCraft's private root. Prove Wine loader, wineserver, DLL search, registry/prefix, sockets, symlinks and helper binaries work under `/data/data/com.artcraft.effectcraft/files/windows-compat`.
3. **Memory/page size:** test 4K/16K page devices, mmap reservations, executable-memory transitions, W^X, address-space layout, shared mappings, signals/exceptions and JIT cache invalidation.
4. **CPU features:** detect ARMv8 and required FP/CRC32 capabilities before selecting FEX; record actual CPU flags and avoid advertising unavailable x86 guest extensions.
5. **Graphics:** Wine X11/Wayland/DXVK requires a compositor or direct Android Surface path. DXVK needs Vulkan 1.3 plus specific features/extensions; driver version alone is insufficient.
6. **Audio/input:** map PulseAudio/SDL device handling, focus, touch/mouse/keyboard, clipboard and lifecycle to Android.
7. **AE host ABI:** PE execution is not full After Effects compatibility. AEX plug-ins require host suites, callbacks, parameters, pixel formats, threading/lifecycle and render API. The current aexlo host is experimental and CPU-first; AEGP/SmartFX/GPU callback coverage remains incomplete.

## License and redistribution gate

The Termux recipe labels the Wine package LGPL-2.1; Hangover is LGPL-2.1; FEX and Box64 carry their own license notices, but the final bundle also contains many transitive libraries and package-specific copyright files. Before APK redistribution, generate a complete package-level SBOM, preserve notices, provide corresponding source and comply with each license's relinking/source obligations. DRM, account, activation, anti-cheat and hardware-authorization bypass are out of scope.

## Milestone state (2026-11-15)

| Milestone | Status |
|---|---|
| M0 source/build/license audit | Upstream revisions and Termux recipe rechecked; full transitive SBOM incomplete |
| M1 minimal Win32 PE on Android ARM64 | Not demonstrated |
| M2 x86_64 PE with DLL/thread/TLS/memory/exception/I/O | x86/x64 fixtures cross-built and PE metadata audited; Android execution not demonstrated |
| M3 graphics/audio/input/device matrix | Not demonstrated |
| M4 EffectCraft APK integration/install validation | Not demonstrated |
| M5 real third-party/AE AEX load, parameters, render and stability | Not demonstrated |

No architecture breakthrough is claimed. The next proof gate is: finish Bionic package build -> install privately in EffectCraft -> run minimal x86_64 and x86 PE fixtures on Android ARM64 -> capture exact device/kernel/page size and logs -> then load the AEX worker and real plug-in samples.
