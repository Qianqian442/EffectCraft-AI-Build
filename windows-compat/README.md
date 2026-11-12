# EffectCraft Windows Plug-in Compatibility Runtime

This branch is an isolated compatibility experiment. It does not change the production `main` branch or the active main-APK build.

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
- x86-64 PE: try the standard Wine + Box64 container; allow the Arm64EC/FEXCore container as a separately tested alternate.
- x86 PE: try a validated Box86/WoW64 path; use FEXCore or WowBox64 only when the selected Wine/Proton container supports that ABI.
- ARM64/ARM64EC PE: route to the matching native/Arm64EC container only after checking the actual ABI and imported DLLs.
- Record backend failures and allow fallback between separate clean Wine prefixes/containers. Do not mix emulator DLLs from different backends in one Wine prefix without validation.

This is an important improvement over a Box64-only proposal. It still does not implement Adobe's AE plug-in host API, and it does not mean every AEX binary works.

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

A separate Android NDK CI build now compiles this optional variant with `BOX32=ON` and `BOX32_BINFMT=OFF`. The latter avoids trying to install Linux `binfmt_misc` rules on Android. It is an additional runtime artifact; it does not replace the standard Box64 build or FEXCore's Arm64EC/WoW64 path.

Upstream source and CMake options: https://github.com/ptitSeb/box64

### QEMU linux-user as a third CPU backend

Pinned source reference: https://www.qemu.org/docs/master/user/

- QEMU user-mode can run an executable built for another CPU architecture while using the host operating system's kernel interfaces.
- Termux's official Android package recipe explicitly builds the `x86_64-linux-user` target for Android/ARM64, packages it as `qemu-user-x86-64`, and links Android-specific shmem/log support.
- Termux recipe: https://github.com/termux/termux-packages/blob/master/packages/qemu-system-x86-64-headless/build.sh
- QEMU source release in the inspected recipe: 11.1.3, GPL-2.0.

EffectCraft fallback chain:
1. Primary: Winlator Bionic standard x86-64 Wine container + Box64.
2. Alternate: Arm64EC Wine/Proton container + FEXCore/WowBox64.
3. Diagnostic/compatibility fallback: Android QEMU `qemu-x86_64` + x86-64 Linux Wine rootfs.

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

This branch currently improves native plug-in inspection and routing. It does not yet contain a working Wine/Box64 runtime, an AE host implementation, or proof that arbitrary `.aex` files run. A successful Python/Rust syntax check is not an end-to-end compatibility result.
