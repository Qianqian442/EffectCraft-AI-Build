# Android Bionic Hangover audit — 2026-11-14

## Decision

Promote the current Termux hangover-wine 11.16 package recipe to the preferred Bionic-native integration target for Windows PE execution. Keep the existing Winlator/Proton containers as a separate fallback/test path. Do not run the complete x86_64 Wine process through Linux Box64 for the primary PE route.

Hangover runs Wine natively on ARM64 and emulates only the Windows application code at the WoW64/ARM64EC boundary. Its upstream build guide explicitly says one emulator is sufficient for a use case, with libarm64ecfex.dll required for x86_64. This avoids stacking a Linux x86_64 Wine binary, Box64, and another PE emulator in one primary path.

This is an audited candidate, not yet integrated into EffectCraft and not yet tested on an Android device.

## Current Termux source of truth

- Repository: https://github.com/termux/termux-packages
- Audited repository revision: e0ce77d242bb9f9adb48cc38dca4d69b3b6d0af9 (2026-11-13)
- Package recipe: https://github.com/termux/termux-packages/tree/master/x11-packages/hangover-wine
- Package version: 11.16
- Version bump commit: https://github.com/termux/termux-packages/commit/f28d0cbacde34399f0c95ec085972be23da952b9 (2026-09-01)
- Latest recipe path maintenance commit: https://github.com/termux/termux-packages/commit/41ab946b57c6e9d17e7c51199c6a4a21daee921b (2026-10-28)

The current recipe downloads two pinned inputs:

| Input | SHA-256 |
|---|---|
| AndreRH/wine tag hangover-11.16 source archive | 21e4dd77a9d1d4897194d5751e03a5fc6cdec4390889ad6a652b87d05aa0bb4d |
| Hangover release asset hangover_11.16_ubuntu2204_jammy_arm64.tar | ecde5846b2f1b23d394fede04a52cbf31853076b85e98d53a391d9e758345488 |

The Hangover release asset is 312,883,200 bytes. The Termux-built hangover-wine_11.16_aarch64.deb is approximately 250.5 MiB; the separate emulator DLL packages are much smaller.

### Bionic build configuration

The Termux recipe builds Wine against the Termux/Bionic toolchain and enables:

- --enable-archs=i386,aarch64,arm64ec
- --with-opengl, --with-vulkan, --with-pulse, --with-sdl
- --without-opencl, --without-alsa, --without-dbus
- ac_cv_header_linux_userfaultfd_h=no because userfaultfd is not available on older Android targets
- -landroid-spawn and -Wl,--rosegment
- Android-specific path and pthread_mutexattr_setprotocol compatibility patches

Dependencies include fontconfig, freetype, krb5, libandroid-spawn, libc++, gmp, gnutls, XCB/X11 libraries, OpenGL, PulseAudio, SDL2, Vulkan loader, and XRandR.

This is direct evidence that a Bionic-native Wine build is maintainable in the Termux package ecosystem. It is not a prebuilt generic glibc Wine binary.

## PE execution architecture

| Windows guest | ARM64 Wine host path | Emulator DLL |
|---|---|---|
| x86_64 PE | ARM64EC/WoW64 Wine path | libarm64ecfex.dll (FEX) |
| x86 PE | 32-bit WoW64 path | libwow64fex.dll (FEX), or wowbox64.dll (Box64 alternative) |
| ARM64 PE | Native ARM64 Windows PE path, if its imports/host ABI match | No x86 translator |
| ARM64EC / ARM64X PE | Requires exact hybrid ABI and loader checks | Never infer compatibility from filename alone |

Termux splits the Hangover payload into the base Wine package plus hangover-libarm64ecfex, hangover-libwow64fex, and hangover-wowbox64. Install/verify the complete compatible set, then create a clean Wine prefix. Do not assume the base Wine package alone is enough.

The Termux package source uses the AndreRH/wine tag hangover-11.16 (commit 628d1aeb09803d3fa9170023e7203060e955bfe8). The Hangover release tag's submodule tree records a different Wine submodule commit (3ea3a14941b6a122b892c84141ce9662c008081e); the former reverts a page-size warning change. Record this source mismatch and verify the resulting PE DLL/Wine ABI at runtime rather than claiming byte-for-byte source identity.

## FEX freshness

Hangover 11.16 was published on 2026-08-30 and reports FEX 2608 plus Box64 v0.4.4. Its pinned FEX ARM64EC branch is older than current FEX upstream.

Current official FEX source was checked on 2026-11-14:

- FEX current main commit: ea43314f040633c76fb5891ff31d8a7c3dc533b8
- Stable FEX 2611.1 tag commit: 4f9c1f1e36443d22d7655477e34f51b95b685bf1
- Current main contains Source/Windows/ARM64EC and Source/Windows/WOW64 PE targets, including libarm64ecfex.dll and libwow64fex.dll export definition files.

A separate EffectCraft CI build is being updated to build both PE DLLs from the current upstream FEX main commit and validate the PE machine values and Wine CPU exports. Even if that build passes, it proves only PE DLL compilation/structure; it does not prove compatibility with Wine 11.16 or successful Android execution. Keep the Termux release DLLs as the baseline until the new pair passes Wine/Android tests.

## Prior failures and what they mean

- The earlier Linux Box64 + Bionic Proton x86_64 test failed with unresolved __libc_init and SIGSEGV. Do not use that exact combination as the primary route.
- Box64 BOX32 now compiles and packages successfully after Bionic-specific resolver, netdb, spawn, signal/thread and allocation patches. Run 43392590850, artifact EffectCraft-Box64-BOX32-Android-ARM64, package SHA-256 0bfccfc0693c5ec9efc2c85de651704e9d4c279b27185878af228241a1237ae5. The 658-object link and archive checksum passed. This is not yet a 32-bit x86 ELF execution test, and it does not by itself load Windows PE.
- FEX ARM64EC and WoW64 PE DLLs were previously built successfully from the older pinned FEX source in run 43366222539, artifact EffectCraft-FEXCore-Arm64EC-WoW64.
- The Windows x64 aexlo host and Noise sample AEX built and rendered on Windows CI, but the separate attempt to run the x64 Wine binary through Linux Box64 on ARM64 failed before reaching the AEX host.

Termux issue #27663 (https://github.com/termux/termux-packages/issues/27663) recorded x86/x64 startup failures and an x64 missing-libarm64ecfex.dll condition. The issue was closed as completed on 2026-03-21 after the reporter installed all Hangover packages and regenerated the Wine prefix. Treat this as a packaging/prefix warning and a historical user report, not as proof that every app or plugin works.

## Android integration plan

1. Build a reproducible ARM64 Bionic runtime bundle from the pinned Termux package inputs; verify package metadata/signatures and SHA-256 before extraction.
2. Extract into EffectCraft private app storage; relocate Termux prefix paths, library paths, wineserver sockets, registry/prefix directories, and drive mappings. Never rely on a user's shared storage being executable.
3. Start only Bionic ARM64 ELF host binaries through /system/bin/linker64 (the existing AndroidBionicProcessLauncher path). Windows PE executables and DLLs are loaded by Wine, not by Android's ELF linker.
4. Install the complete Hangover emulator DLL set into the matching Wine system directories and generate a fresh isolated prefix for each backend/version.
5. First run minimal Win32 console and GUI PE samples, then x86_64 PE, then x86 PE; test DLL loading, TLS, exceptions, threads, virtual memory, file I/O, registry, process creation and clean shutdown.
6. Run the aexlo x64 worker under this Bionic Hangover prefix; only then load a real x64 sample AEX and compare parameters and CPU-render output.
7. Build a headless/offscreen or Android-Surface-backed render path. The Termux recipe's X11/PulseAudio desktop dependencies are not an Android Surface integration.
8. Test OPPO/Qualcomm Android 12 first, then Huawei/Mali-class devices. Record kernel, Android API, page size, Vulkan/OpenGL driver and exact package hashes.

## Known gaps and distribution constraints

- The Termux recipe disables OpenCL. The separately built CLVK artifact in this project has compiler support disabled and only covers precompiled SPIR-V/OpenCL IL paths; the Wine OpenCL ICD bridge remains unverified. It does not provide CUDA.
- Vulkan/DXVK support is conditional on the actual driver and required Vulkan extensions/features. Hangover's upstream README warns that DXVK needs Vulkan 1.3 and hardware may not expose all required features.
- Termux's X11 and PulseAudio stack is a reference path, not a drop-in EffectCraft UI/audio implementation. AEX dialogs, input, clipboard, audio, and GPU presentation need explicit Android bridges.
- AEX compatibility is also bounded by the host ABI. The current aexlo host is incomplete (notably AEGP/SmartFX coverage); a Windows binary running successfully is not equivalent to full After Effects host compatibility.
- Keep all runtime components optional/on-demand; do not add an artificial RAM limit. Android OS memory pressure and device/driver limits still apply.
- Termux metadata labels the Hangover Wine package LGPL-2.1. Hangover/Wine source and notices, FEX MIT notices, Box64 MIT notices, and all transitive dependency licenses must be inventoried. Do not redistribute the packages in an APK until a package-level SBOM, corresponding source, and notice obligations are complete.
- Do not bypass plugin licensing, DRM, sign-in, activation, anti-cheat, or hardware authorization.

## Milestone status

| Milestone | Status |
|---|---|
| M0 source/build/license audit | Termux Bionic Hangover 11.16 recipe audited; full transitive SBOM still pending |
| M1 minimal Win32 PE on Android ARM64 | Not yet demonstrated |
| M2 x86_64 PE with DLL/thread/memory/exception/I/O tests | Not yet demonstrated |
| M3 graphics/audio/input/device matrix | Not yet demonstrated |
| M4 EffectCraft APK integration/install | Not yet demonstrated |
| M5 real third-party/AE AEX load, parameters, render, stability | Not yet demonstrated |


## Critical app-private execution and relocation gap

The Termux package recipe links libandroid-spawn, but the audited source shows that this library implements posix_spawn/posix_spawnp by fork/vfork followed by execve/execvpe. It does not itself bypass Android's app-data executable restriction.

Termux's app separately injects a linker-aware LD_PRELOAD library from https://github.com/termux-play-store/termux-exec. Its linker preload intercepts execve, execv, execvp, execvpe, execl, execlp, execle and fexecve; for native ELF files under the Termux app-data root it rewrites the process launch to /system/bin/linker64 while preserving argv[0]. The current termux-exec package source declares Apache-2.0 for code and MIT for site documentation. The libandroid-spawn package has its own BSD-2-Clause license metadata.

EffectCraft cannot assume the Termux app's LD_PRELOAD or environment exists. A first EffectCraft-owned prototype has been added under windows-compat/android-runtime/exec-bridge:

- libeffectcraft-exec.so intercepts the exec family used by common Wine helpers and posix_spawn implementations.
- It only routes a native-architecture ELF under EFFECTCRAFT_RUNTIME_ROOT through /system/bin/linker64.
- It checks the ELF machine and PT_INTERP before wrapping, and preserves the caller's argv[0].
- A host-side linker-shim test checks argument preservation; a separate NDK job compiles the arm64-v8a shared library and fixtures.

This is only a prototype. It does not yet prove Android execution, does not intercept raw syscall(SYS_execve) call sites, and its fexecve/execveat path needs further audit. Wine/Hangover child-spawn paths must be checked for direct syscalls and all subprocesses must be observed on Android.

A second critical issue is relocation: the Termux build recipe configures Wine with --prefix=$TERMUX_PREFIX/opt/hangover-wine and its wrapper scripts refer to the Termux prefix under /data/data/com.termux/files/usr. EffectCraft cannot access another package's private directory. The package must be rebuilt with relocatable paths or Wine's WINELOADER, WINESERVER, WINEDLLPATH, data paths and helper paths must be proven to work from EffectCraft's own private files directory. Do not copy the Termux .deb files unchanged and claim they are app-ready.
