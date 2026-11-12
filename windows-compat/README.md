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
