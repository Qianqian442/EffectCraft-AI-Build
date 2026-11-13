# EffectCraft Windows Plug-in Compatibility Runtime

This branch is an isolated compatibility experiment and is not merged into `main`. Since 2026-11-13, the main Android APK workflow is also triggered on this branch so the current export and app-integration patches can be type-checked and packaged independently.

## What is being combined

### Primary Android execution path

Use the Android execution architecture already demonstrated by Winlator:

1. Winlator Android app patterns for private rootfs installation, guest process lifecycle, environment variables, and ARM64 native launcher integration.
2. Wine as the Windows API and PE/DLL compatibility layer.
3. Box64 for x86-64 Linux user-space instruction translation on ARM64. Wine's x86-64 Linux runtime runs under Box64 and loads Windows PE programs/DLLs.
4. Box86 or Wine WoW64 only as a separate 32-bit compatibility path, selected according to the actual Wine build and device ABI.
5. Optional Vulkan/OpenGL translation backends only where the selected plug-in host actually needs them.

Useful upstream sources:

- Winlator Android source: https://github.com/brunodev85/winlator-app
- Wine: https://gitlab.winehq.org/wine/wine
- Box64: https://github.com/ptitSeb/box64
- Box86: https://github.com/ptitSeb/box86

Winlator's source includes a rootfs installer, Box64 asset handling, a Wine environment, and a guest process launcher. It is a much more complete Android reference than embedding Box64 alone.

### Alternative execution path

Keep Hangover as an alternative backend to evaluate, not something to blindly link into the primary Wine/Box64 process:

- https://github.com/AndreRH/hangover

Hangover is designed to run x86/x86-64 Windows applications on AArch64 Wine using emulator DLLs such as FEX or Box64. It is an ARM64 Linux route and still needs Android-specific integration and testing.

### Android-native Hangover Bionic candidate

A more directly Android-focused build has also been audited:
- Source: https://github.com/Piperella/Piperella-Hangover-Bionic
- Pinned source revision: cd0d2b48da092a6a662a10d0b0b1ce189bbd3981
- Release: hangover-bionic-11.9-build19 (2026-07-14)
- Asset: hangover-bionic-aarch64.tar, 339,589,120 bytes; SHA-256 09cc7c2f43a1607d64b5f79e916939d0fefc8e1d094d09aee923abc4b8608793
- It builds Wine 11.9/Hangover against Android Bionic, includes fresh FEX-2607 ARM64EC and WoW64 backends plus WowBox64, adds Wine Wayland and PulseAudio drivers, and patches wineserver paths, NLS lookup, W^X executable mappings, and removal of wine-preloader for Android linker64 launch.
- The project documents the Android API 29+ app-data execution restriction and uses /system/bin/linker64 to load Bionic ELFs.

This is a strong Android-specific alternative to the current Winlator Proton 9.0 package. It is not automatically the primary backend: the release is several months older than the currently audited FEXCore 2611.1 package, its GUI path expects a Wayland compositor, the runtime bundle is about 340 MB, and it has not yet been tested with EffectCraft's aexlo host on an Android ARM64 device. Keep it as a separately audited fallback until its runtime, license/SBOM, and rendering tests pass.

## Important distinction: executing a DLL is not hosting an AE plug-in

An `.aex` file is normally a Windows PE DLL. Wine/Box64 can help with PE loading and CPU execution, but an AE effect plug-in expects an After Effects host process and its plug-in ABI. The host has to implement the relevant entry-point commands, parameter suites, memory suites, image worlds, render callbacks, UI callbacks, SmartFX/AEGP behavior, and any other suites the plug-in uses.

Therefore the full EffectCraft design needs two separate layers:

- **Windows execution backend:** Wine + Box64/Box86, with Hangover evaluated as an alternative.
- **Effect plug-in host ABI:** an EffectCraft-owned host/shim based on the public SDK contract, with explicit feature coverage and per-plug-in compatibility tests.

OpenFX remains a separate plug-in standard. An OpenFX host can run OpenFX plug-ins; it does not automatically turn an AE `.aex` into an OpenFX plug-in.

Adobe documents that third-party hosts do not support SmartFX or AEGP completely and states that Adobe does not support or recommend creating Adobe-compatible third-party hosts:
https://ae-plugins.docsforadobe.dev/intro/third-party-plug-in-hosts/
https://ae-plugins.docsforadobe.dev/ppro/other-hosts/

This is a technical limitation, not a reason to delete EffectCraft's desktop plug-in import feature. The existing migration/reimplementation path remains necessary for unsupported plug-ins.

## Improved hybrid backend selection

A newer and more suitable reference has been verified: the Winlator Bionic family (the inspected source is the MIT-licensed `EmuProto/Winlator-Ludashi` branch).

- Source: https://github.com/EmuProto/Winlator-Ludashi/tree/winlator_bionic
- Inspected revision: `95224ca7db27ae133dbb1578e004b94b86ef8894`
- Its Android launcher switches between normal x86_64 Wine/Proton containers using Box64/Box86 and Arm64EC containers using FEXCore, with optional WowBox64 for the 32-bit WoW64 path.
- FEXCore source: https://github.com/FEX-Emu/FEX (MIT; inspected revision `ab135df091d005cc98dfddc56c3dc9c9e4bd501d`).

EffectCraft should adapt this **backend orchestration**, not copy the Winlator UI:
- x86-64 PE: prefer ARM64EC Wine/Proton + FEXCore (HODLL64=libarm64ecfex.dll); keep Box64 and WowBox64 as separate 64-bit fallback candidates.
- x86 PE: prefer ARM64EC Wine/Proton + FEXCore WoW64 (HODLL=libwow64fex.dll). Do not offer WowBox64 as the x86 backend; it is the separate 64-bit backend.
- ARM64/ARM64EC PE: route to the matching native/Arm64EC container only after checking the actual ABI and imported DLLs.
- Record backend failures and allow fallback between separate clean Wine prefixes/containers. Do not mix emulator DLLs from different backends in one Wine prefix without validation.

The hybrid path is still experimental. The current Bionic Proton x86_64 binary failed under Box64 with unresolved __libc_init, so that exact pair is not considered working. The runtime does not implement Adobe's full AE plug-in host API, and it does not mean every AEX binary works.

## PE architecture routing metadata

The static PE analyser records machine type, imported DLLs, exported symbols and candidate AE entry points. It also marks ARM64EC (`0xA641`) and ARM64X (`0xA64E`) explicitly so the runtime manager can choose an appropriate container. Architecture hints are diagnostic only until a specific Wine prefix + emulator combination passes real plug-in tests.

## New AE plug-in host breakthrough: aexlo

A particularly relevant MIT-licensed upstream was found and pinned:

- Repository: https://github.com/potistudio/aexlo
- Revision: `32c3fe399bc7d2deb3e5f9a02c627db50d8e7ff9`
- It is a Rust reimplementation of the After Effects plug-in runtime, not merely a PE loader. It can load a Windows `.aex`/DLL, perform setup, inspect parameters, and render frames outside Adobe After Effects.
- Its README reports approximately 89% of its listed Effect API suites implemented, but only approximately 11% of AEGP. It is under heavy development; sequence data, masks, camera, text, composite and several project-level suites are absent or partial.
- Its documented plug-in target is Windows x64 (plus macOS arm64); it does not support Linux. Therefore the intended Android architecture is to compile an x64 Windows worker and run it inside the selected Wine + Box64 or Arm64EC Wine/Proton + FEXCore container.
- Upstream source: https://github.com/potistudio/aexlo

This is a substantial bridge for ordinary AE effect plug-ins:
1. Android runtime starts the selected Wine/Box64 or FEXCore backend.
2. The backend starts the isolated Windows x64 `effectcraft-aex-host.exe`.
3. The worker loads the AEX file through aexlo and returns parameter metadata.
4. EffectCraft sends frame images, time and parameter updates to the worker and receives rendered frames.
5. Each plugin runs in its own supervised worker process. A crash should not bring down the Android main process.

The experimental bridge source is in `windows-compat/aexlo-host/`. It exposes a JSON-lines worker protocol with inspection and frame render operations. A separate CI job builds it for Windows x64; it is not yet connected to the production Android launcher.

GPU path: the first integration should force aexlo's CPU rendering path unless a supported CUDA/driver translation path is proven. AEX-only plug-ins that rely on unsupported GPU callbacks or AEGP suites may not render. OpenFX remains a separate ABI and host.

## Additional open-source fallbacks found

### Box64 BOX32 for 32-bit x86 Linux userland

Box64 itself has a `BOX32=ON` build option that adds 32-bit x86 ELF support inside the 64-bit ARM64 Box64 process. This is different from 32-bit Windows PE support: it can run the 32-bit Linux/Wine side of a WoW64 configuration, but Wine must still provide the Windows PE loader and 32-bit Windows API implementation.

A dedicated Android NDK r26b build with `BOX32=ON` and `BOX32_BINFMT=OFF` now compiles and links successfully.

- Run: https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43392590850
- Source commit: `92cda7aeee5fc793083af51dd7d4f17f7515bec3`
- Artifact: `EffectCraft-Box64-BOX32-Android-ARM64`
- Artifact ID: `14021596892`
- Payload: `box64-box32-android-arm64.tar.zst` (5,841,155 bytes)
- Payload SHA-256: `0bfccfc0693c5ec9efc2c85de651704e9d4c279b27185878af228241a1237ae5`
- The payload was independently downloaded, decompressed and checked; the binary is an Android API 31 AArch64 ELF64 PIE with `/system/bin/linker64` as its interpreter.
- The build compiled 658 objects, including the Android-specific `box32_alloc_bionic.c` allocator bridge; packaging and checksum generation succeeded.

The previous Bionic resolver/netdb compile errors and unresolved `box32_*` final-link symbols are resolved for this pinned Box64 source/build configuration. This is a **build/package milestone only**. Still required before claiming 32-bit execution support: run a 32-bit x86 Linux ELF fixture through the resulting ARM64 Box64 binary, validate matching 32-bit Wine/WoW64 process startup, run a 32-bit Windows PE/AEX host fixture, and test on OPPO/Qualcomm and Huawei/Mali Android devices. BOX32 alone handles 32-bit Linux ELF userland; it does not load Windows PE files or supply Windows APIs without Wine/WoW64.

Upstream source and CMake options: https://github.com/ptitSeb/box64

### Boxedwine as a 16/32-bit Windows fallback candidate

Another useful open-source fallback has been inspected:

- Repository: https://github.com/danoon2/Boxedwine
- License: GPL-2.0 (the upstream README says GPL v2; source headers use GPL-2.0-or-later in some newer files, so perform file-level license review).
- It combines an x86 CPU emulator/JIT, emulated Linux kernel interfaces and a 32-bit Wine environment.
- Its upstream README reports 16/32-bit Windows program support and native ARMv8 JIT; its CPU emulation documentation describes the portable interpreter and ARMv8 JIT.
- The tree includes SDL2's Android support code, but the Boxedwine application itself currently documents Windows, macOS, Linux and Emscripten build targets; there is no ready-made Android application build target in the upstream build guide.

Why it may help EffectCraft:
- It is a second independent x86 execution stack for legacy 32-bit Windows plug-ins.
- It brings an x86 Linux/Wine environment instead of requiring Android to provide an x86 Linux userspace.
- It may help test older 32-bit PE modules that do not work in a selected Wine/Box64/WoW64 container.

Why it is not the primary path:
- It is aimed at 16/32-bit applications, not 64-bit AEX.
- It still needs the same AE plug-in host ABI; it does not replace aexlo.
- The app needs an Android SDL2/NDK port and private rootfs integration; this is not yet done.
- GPL-2.0 has copyleft/source-distribution implications. Keep it in a developer-only experiment until license and distribution consequences are reviewed.

Conclusion: retain Boxedwine as an independent 32-bit compatibility experiment, not as a replacement for the Winlator Bionic Proton + Box64/FEXCore architecture.

### QEMU linux-user as a third CPU backend

Pinned source reference: https://www.qemu.org/docs/master/user/

- QEMU user-mode can run an executable built for another CPU architecture while using the host operating system's kernel interfaces.
- Termux's official Android package recipe explicitly builds the `x86_64-linux-user` target for Android/ARM64, packages it as `qemu-user-x86-64`, and links Android-specific shmem/log support.
- Termux recipe: https://github.com/termux/termux-packages/blob/master/packages/qemu-system-x86-64-headless/build.sh
- QEMU source release in the inspected recipe: 11.1.3, GPL-2.0.

EffectCraft fallback chain:
1. Preferred candidate: ARM64EC Wine/Proton + FEXCore (64-bit PE via HODLL64, 32-bit PE via HODLL).
2. Separate 64-bit fallback candidates: Box64 + ABI-compatible x86_64 Linux Wine, or ARM64EC Wine/Proton + WowBox64.
3. Diagnostic fallback: Android QEMU qemu-x86_64 + x86_64 Linux Wine rootfs.
4. Legacy 32-bit fallback: Box64 BOX32 after its Bionic build issue is fixed, or a separately ported Boxedwine.

QEMU does **not** load Windows PE DLLs by itself. It translates the x86-64 Linux Wine process; Wine remains responsible for Windows PE and API compatibility. This backend is expected to be slower than Box64/FEX and is an alternate path for compatibility/debugging, not a promise of higher performance.

### Android root filesystem and process-launcher model

Use Winlator's Android implementation as the primary reference rather than assuming a full PRoot container is required:

- Winlator's `RootFS` and `RootFSInstaller` extract a compressed Ubuntu/Wine root filesystem into the app's private files directory.
- Its `GuestProgramLauncherComponent` starts the Android/Bionic Box64 binary with environment variables such as `LD_LIBRARY_PATH` and `BOX64_LD_LIBRARY_PATH`, pointing at the matching native and x86-64 rootfs libraries.
- Its Java `ProcessHelper` uses Android `ProcessBuilder` and process lifecycle control; no root permission is required for the basic launcher pattern.
- Sources: https://github.com/brunodev85/winlator-app

PRoot remains an optional helper when a chroot-like path view or cross-architecture rootfs management is useful:
- https://github.com/termux/proot
- https://github.com/termux/proot-distro

PRoot-Distro documents rootless Android rootfs use and QEMU user-mode integration. It uses ptrace syscall interception and filesystem path rewriting; Android/SELinux compatibility must be verified on target devices before using it in the main APK:
https://github.com/termux/proot-distro

### Optional OpenCL acceleration: CLVK

- Project: https://github.com/kpet/clvk
- License: Apache-2.0.
- Implements OpenCL 3.0 on top of Vulkan using clspv.
- The upstream README provides an Android NDK build path; Khronos' Vulkan documentation also describes using clvk on Android.
- Android build reference: https://github.khronos.org/Vulkan-Site/tutorial/latest/Advanced_Vulkan_Compute/12_Mobile_and_Embedded_Compute/02_android_compute.html

Potential use: provide an Android ARM64 OpenCL 3 implementation to a compatible Wine/Arm64EC OpenCL bridge, so some plug-ins using portable OpenCL kernels may execute on a Vulkan-capable GPU.

Limitations:
- A build with compiler support disabled only accepts precompiled SPIR-V paths and is **not** sufficient for arbitrary plug-ins that call `clCreateProgramWithSource` at runtime.
- A full runtime compiler requires clspv/LLVM components and is a much heavier build.
- Wine's OpenCL ICD/Unix bridge must be tested to ensure an Arm64EC/native Wine process can call the Android ARM64 `libOpenCL.so`.
- OpenCL interoperability extensions and GPU sharing with the host compositor are not guaranteed.
- CLVK does not implement CUDA. CUDA-dependent AE plug-ins remain a separate unresolved compatibility class.

### Deep reverse-engineering fallback: Ghidra

- Project: https://github.com/NationalSecurityAgency/ghidra
- License: Apache-2.0.
- Supports x86/x86-64 and ARM/AArch64 disassembly, decompilation, call graphs, symbol analysis and scripted analysis of Windows PE programs.
- Use it in the developer workflow when a closed-source `.aex` cannot be mapped from imports/exports and embedded strings alone: identify its entry point, inspect API calls, follow effect parameter handling, locate CPU/GPU render routines, and export a structured analyst report.
- This is not an Android runtime and does not automatically recover original source or recreate a plug-in's algorithm. Dynamic testing still needs a compatible Wine/Box64/FEX execution container and the AE host shim.

Ghidra's official project overview and license:
https://github.com/NationalSecurityAgency/ghidra

### Static and dynamic PE analysis helpers

Use these as analysis tools, not as the production runtime:

- [LIEF](https://github.com/lief-project/LIEF), Apache-2.0: parses and abstracts PE/COFF, imports, exports, sections, symbols and other binary metadata. It can be used as an independent check against EffectCraft's PE importer report.
- [Qiling](https://github.com/qilingframework/qiling), GPL-2.0-or-later: a Unicorn-based multi-architecture Windows PE/Linux/Android emulation and instrumentation framework. It can help inspect API calls and discover missing Windows API dependencies under a controlled development harness. It is Python-based and should stay outside the shipping APK unless its size, performance and GPL distribution obligations are deliberately accepted.
- Qiling is useful for probing dependencies and making compatibility shims; it is not an AE host and cannot make an arbitrary plug-in render correctly without the required AE SDK suites and effect data.

## Graphics/API coverage strategy

Keep multiple graphics paths instead of assuming one translation layer solves every plug-in:

- WineD3D / DXVK for Direct3D 9/10/11 to OpenGL/Vulkan paths.
- VKD3D-Proton for Direct3D 12 to Vulkan paths.
- Mesa Zink / Turnip / VirGL as optional OpenGL/Vulkan driver paths according to GPU and device support.
- CLVK as an experimental OpenCL-on-Vulkan path.
- CUDA remains unimplemented on ordinary Android GPUs; do not report a CUDA plug-in as supported merely because Wine/Box64 loads its DLL.

Winlator's official project page and source list Wine, Box64/Box86, PRoot, Mesa, DXVK and VKD3D as constituent compatibility layers:
https://www.winlator.org/
https://github.com/winebox64/winlator

### Upgrading the emulator components to current November 12 WCP builds

The runtime catalog now prefers the latest pinned Android WCP packages published on November 12, 2026, instead of the older 0.3.7/2508 assets bundled in the original Winlator Bionic source:

| Component | Pinned build | Size | SHA-256 |
|---|---|---:|---|
| Box64 | 0.4.5-4dbba1300 | 2,901,992 bytes | `9e8e6cda22cecf6c975ebc7d4521a2e08565f4287a479e9db53fcd2850883256` |
| FEXCore | 2611-ab135df09 | 1,104,420 bytes | `6a8ad93996147fc23d9dd4c541b84b03c19f11911db431f6d155b5b15f9a9c86` |
| WowBox64 | 0.4.5-4dbba1300 | 910,648 bytes | `6037af9cc15bf036eb77077423806798e043cf81370dea40cc9ae17d60a09d39` |

These assets are from the public [Winlator Nightly WCP releases](https://github.com/Xnick417x/winlator-nightly-wcp/releases). The downloader verifies the exact size and SHA-256 before the WCP profile installer places any file. The old 0.3.7/2508 components remain catalogued as rollback candidates until the newer packages pass the Android AEX render test.

## Full Wine/Proton runtime packaging breakthrough: Winlator Bionic

A deeper source inspection found that Winlator Bionic already solves the missing **Wine runtime + private root filesystem + per-container architecture switch**. This is more useful than assembling only standalone CPU emulators.

Pinned reference:
- Repository: https://github.com/EmuProto/Winlator-Ludashi
- Branch: `winlator_bionic`
- Commit: `95224ca7db27ae133dbb1578e004b94b86ef8894`
- Repository Java/source license: MIT. The bundled Wine/Proton, Ubuntu rootfs, FEX, Box, Mesa, DXVK and VKD3D assets have their own upstream licenses; the repository's MIT license does not relicense those components.

### Actual upstream installer and launcher design

The inspected Winlator Bionic source provides concrete implementation files:

- `ImageFsInstaller.java`: downloads the Ubuntu Bionic ImageFS in four parts, verifies its published SHA-256 sidecar, extracts into app-private `files/imagefs`, installs Wine runtimes into `/opt`, and marks ImageFS version 21.
- `app/build.gradle`: downloads the Wine/Proton 9.0 x86-64 and ARM64EC runtime archives from `winlator3/winlator-extra` and verifies their published SHA-256 sidecars.
- `ContainerManager.extractContainerPatternFile()`: creates separate x86-64 or ARM64EC Wine prefixes, then adds the matching common DLLs to `system32` and the i386 DLL set to `syswow64`.
- `GuestProgramLauncherComponent.java`: performs the actual backend split:
  - x86-64 Proton/Wine container: launch the Windows executable through Android ARM64 `box64`.
  - ARM64EC Proton/Wine container: launch the native Bionic Wine executable; set HODLL64=libarm64ecfex.dll for 64-bit x86 PE and HODLL=libwow64fex.dll for 32-bit x86 PE. WowBox64 is selected separately as HODLL64=wowbox64.dll for its 64-bit route.
  - FEXCore and WowBox64 DLLs are extracted into the container's `C:\\windows\\system32` directory.
- `ProcessHelper.java`: starts and supervises the guest process with Android `ProcessBuilder`; basic launch does not require root.

### Pinned upstream runtime assets

The Winlator Bionic commit contains the following exact component assets:

| Asset | Size | Role |
|---|---:|---|
| `proton-9.0-x86_64_container_pattern.tzst` | 8.70 MB | x86-64 Wine prefix/container skeleton |
| `proton-9.0-arm64ec_container_pattern.tzst` | 10.31 MB | ARM64EC Wine prefix/container skeleton |
| `box64/box64-0.3.7.tzst` | 2.97 MB | Android ARM64 Box64 binary |
| `fexcore/fexcore-2508.tzst` | 3.42 MB | Arm64EC and WoW64 emulator DLLs |
| `wowbox64/wowbox64-0.3.7.tzst` | 1.05 MB | Alternative 32-bit WoW64 emulator DLL |

The Wine/Proton runtime archives and the base ImageFS are separate from these small container skeletons. The source build downloads them from:

- ImageFS: `https://gitlab.com/winlator3/winlator-extra/-/raw/main/imagefs/imagefs.txz`
- ImageFS checksum: `https://gitlab.com/winlator3/winlator-extra/-/raw/main/imagefs/imagefs.txz.sha256sum`
- Proton x86-64: `https://gitlab.com/winlator3/winlator-extra/-/raw/main/proton/proton-9.0-x86_64.txz`
- Proton x86-64 checksum: `https://gitlab.com/winlator3/winlator-extra/-/raw/main/proton/proton-9.0-x86_64.txz.sha256sum`
- Proton ARM64EC: `https://gitlab.com/winlator3/winlator-extra/-/raw/main/proton/proton-9.0-arm64ec.txz`
- Proton ARM64EC checksum: `https://gitlab.com/winlator3/winlator-extra/-/raw/main/proton/proton-9.0-arm64ec.txz.sha256sum`

These upstream checksum sidecars should be downloaded and verified before extraction. EffectCraft should download these optional assets once into its private application storage, not inflate the base APK with a full Linux/Wine runtime. Before redistributing any of the upstream archives, produce a package-level SBOM and preserve every included license/NOTICE/source obligation.

### EffectCraft-specific mapping

EffectCraft should reuse the **runtime orchestration**, not Winlator's gaming UI:

1. Inspect the imported PE architecture, imports and exports.
2. Select a matching Wine/Proton container and a matching aexlo host worker:
   - x86-64 AEX: x64 aexlo worker, ARM64EC Proton/Wine + FEXCore as the preferred candidate; Box64 or WowBox64 remain separate 64-bit fallbacks only after their exact Wine/host ABI passes.
   - x86 AEX: x86 aexlo worker, ARM64EC Proton/Wine + FEXCore WoW64 (HODLL=libwow64fex.dll) as the preferred candidate. Box64 BOX32 and Boxedwine remain unvalidated fallbacks. This remains experimental until the worker loads and renders under a matching Android container.
   - ARM64EC/ARM64X: inspect the module ABI and host requirements; do not assume that PE machine type alone is sufficient.
3. Extract the selected container skeleton into an isolated EffectCraft private prefix.
4. Copy the matching aexlo worker and AEX into the prefix; start one supervised worker process per plugin.
5. Exchange parameter and frame data with the Android app; never load an untrusted Windows plug-in into the EffectCraft main process.

This supplies the previously missing Wine/Proton packaging and launch design. It still does not establish that every AE plug-in works: aexlo's AEGP/SmartFX coverage is incomplete, and device GPU APIs, proprietary codec libraries, plug-in licensing checks, and unsupported Windows APIs must be tested individually.

### No artificial memory budget

EffectCraft will not add a fixed RAM budget, `ulimit`, `RLIMIT_AS`, cgroup memory cap, Box64 guest-memory cap, FEX guest-memory cap, or arbitrary Wine process memory ceiling. Container display/video-memory preferences should use driver defaults unless an individual plugin requires a documented setting. Physical device RAM, Android process management, storage and GPU/driver capabilities remain real system limits.

## Work now implemented on this branch

- Extend the desktop ZIP import patch to inspect PE headers without executing binaries.
- Extract PE architecture, subsystem, DLL flag, imported DLL names, representative imported symbols, exports, and likely AE entry-point names.
- Include that metadata in the saved desktop plug-in import report.
- Route a directly selected `.aex/.dll/.ofx` (and related native plug-in files) through safe archival and static analysis instead of incorrectly handing the PE file to the WASM loader.
- Preserve the original binary as a migration input; the current importer does **not** claim to execute it.

## Integration plan

1. Finish PE metadata parsing and compile validation.
2. Build a separately testable Android runtime payload from audited upstream sources. Download/install it on demand into EffectCraft's private application storage; do not bundle a large Linux rootfs in the base APK.
3. Implement the Wine/Box64 process launcher using the Winlator Android process/environment model, adapted to EffectCraft's generated Android project. Do not copy Winlator's full UI or unrelated game controls.
4. Add a controlled Windows PE test host and validate ordinary EXE/DLL loading before touching any AE plug-in.
5. Implement the smallest documented AE effect-host ABI surface needed for real sample plug-ins, then expand Suites and render behavior based on compatibility tests.
6. Use Hangover/FEX only if it demonstrably improves a failing architecture or compatibility case.
7. Connect the optional runtime back to the existing top-left desktop plug-in import workflow. Keep WASM, JSX/JS, ScriptUI, and current reimplementation support intact.

## Memory policy

There will be no application-defined RAM ceiling for the compatibility runtime: no fixed heap/RSS budget, no `ulimit`/cgroup memory cap, and no Box64 artificial memory ceiling will be introduced. Runtime allocations are allowed to grow as required and as the Android OS/device can provide.

The operating system, available physical memory, storage, thermal limits, and GPU/driver limits still exist. Removing an application-imposed cap cannot create physical RAM or prevent Android from killing a process under system memory pressure.

Archive validation limits are separate security controls against malformed archives and decompression bombs; they are not a runtime RAM budget.

## Licensing and distribution gate

Before shipping any upstream binary or source in an APK, generate a component-level SBOM and preserve the matching notices/source obligations.

Known upstream license starting points:

- Winlator Android app source: LGPL-2.1 (see its LICENSE).
- Wine: LGPL-2.1-or-later.
- Box64: MIT.
- Box86: MIT.
- Hangover: LGPL-2.1.

The Winlator rootfs is a distribution of many packages, not one license. Do not redistribute its compressed rootfs blindly; generate a package/license inventory first. Prefer building the exact needed runtime components from pinned upstream source revisions and publishing the required corresponding source and notices.

## Current verification status

This branch now contains an experimental Android runtime installer/manager, architecture routing, an isolated aexlo worker, and a Bionic launcher command that invokes app-private native executables through /system/bin/linker64. The runtime is not yet proven to execute a Windows PE or AEX plug-in on an Android ARM64 device.

Verified build and audit results:
- Android NDK CI successfully produced a Bionic ARM64 Box64 artifact and FEXCore ARM64EC/WoW64 PE DLL artifacts.
- Windows CI successfully built the x64 aexlo host worker and sample Noise AEX; the sample worker's Windows-native CPU render test passed.
- WCP package size/SHA-256 checks and profile metadata inspection passed for Box64 Bionic, Box64EC, WowBox64, FEXCore 2611.1, and GE-Proton 11.0-7.1 x86_64/ARM64EC packages.
- The WCP profile inspection failure caused by assuming profile.json was at the archive root has been fixed; the new run passed.

Known blockers from actual CI:
- The x86_64 Bionic Proton binary failed under Box64 on ARM64 Linux with unresolved __libc_init and a segmentation fault. This exact Box64 + Bionic Proton pair is not supported by current evidence; the selector now prefers ARM64EC/FEXCore for x86 and x64 PE.
- The Android NDK Box64 BOX32 build failed in libc_net32.c because Bionic exposes struct __res_state as incomplete. BOX32 is not built yet.
- Android archive tests validate safe extraction and WCP installation, not Windows process execution. Actual Wine startup, real PE execution, and AEX parameter/render tests on an Android ARM64 device remain pending.

A successful source build, static PE inspection, or package checksum is not an end-to-end compatibility result. Keep every backend marked experimental until a real Android ARM64 device test has loaded and rendered a real Windows plug-in.
