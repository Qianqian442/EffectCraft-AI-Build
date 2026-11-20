# Desktop plug-in to Android ARM64: sequential trials and aggressive compatibility

**Status: route planning is implemented in the import analysis; execution backends and plug-in host workers are not yet integrated.** Every route is currently recorded as not_run_runtime_not_integrated. This is deliberate: CPU architecture detection or a filename match is not proof of a working port.

## Goal

When a user imports a desktop plug-in on Android, Ae should:
1. Preserve the original binary unchanged.
2. Identify OS format, CPU architecture, plug-in format and host ABI.
3. Build the applicable route list and try those routes one by one, not all at once.
4. Run every candidate against the same test project, footage, parameter values and reference frames in an isolated copy.
5. Compare load/feature/render completeness, visual fidelity, stability and performance.
6. Import the highest-scoring candidate only if it passes mandatory correctness and stability gates. If none passes, retain the original and report the best partial result without marking it runnable.

The target phone architecture is Android ARM64 / arm64-v8a. CPU translation is normally dynamic at runtime; it does not rewrite the desktop plug-in into an ARM64 .aex/.ofx file.

## Open-source routes to compare

| Route | Guest format | Proposed role | Caveats |
|---|---|---|---|
| [Box64](https://github.com/ptitSeb/box64) | x86-64 Linux userland | Main Android x86-64 dynamic translation candidate | Needs compatible guest libraries and host ABI; not a Windows loader |
| [Box86](https://github.com/ptitSeb/box86) | 32-bit x86 Linux userland | 32-bit x86 candidate where a matching 32-bit guest userland is available | Not a substitute for Wine or a plug-in host |
| [Wine](https://github.com/wine-mirror/wine) | Windows PE / Windows API | Loads Windows plug-ins and implements Windows APIs | Does not translate CPU instructions; pair with a compatible translator |
| [FEX](https://github.com/FEX-Emu/FEX) | 32/64-bit x86 Linux userland | Alternative translator to compare against Box64/Box86 | Requires an appropriate Linux guest rootfs; upstream documents a Linux ARM64 environment and kernel prerequisites |
| [QEMU user-mode](https://www.qemu.org/docs/master/user/) | Linux user-mode x86/i386 | Slow reference/compatibility candidate and diagnostic cross-check | Runs foreign-architecture Linux user programs; it is not a direct Windows PE loader |
| [Winlator](https://github.com/winebox64/winlator) | Android + Wine + Box86/Box64 | Reference for packaging the Android guest runtime | Demonstrates general Windows applications on Android, not Ae plug-in host compatibility |
| [OpenFX](https://github.com/AcademySoftwareFoundation/openfx) | OFX plug-in ABI | First plug-in host API to implement in the worker | OFX host implementation is still required |
| [Capstone](https://github.com/capstone-engine/capstone) | x86/x86-64 and ARM64 instruction decoding | Lightweight native Android disassembly to inspect instruction families and build a static triage report | Disassembles instructions; does not itself translate or port a plug-in |
| [Ghidra](https://github.com/NationalSecurityAgency/ghidra) | PE/ELF/Mach-O analysis | Deep static disassembly, decompilation, import/export analysis and control-flow recovery | Large developer/offline analysis tool, not an automatic on-device converter |
| [Remill](https://github.com/lifting-bits/remill) | x86/amd64 machine code | Lift instructions to LLVM IR to assist deeper binary analysis/reimplementation | Building a complete binary translator still needs ABI, OS and runtime work |

### Ae migration choices

The desktop plug-in import flow offers five selectable strategies:

1. **Automatic best route:** compare every applicable runtime route and select the highest measured completeness score among candidates that pass all mandatory gates.
2. **CPU translation first:** prioritize the compatible Box64/Box86, FEX or QEMU path for the detected architecture.
3. **Forced compatibility:** test optional host/API shims, runtime versions, pixel-format adaptation, CPU feature fallback and CPU/serial render fallback.
4. **Aggressive port / reconstruction:** rebuild from source for ARM64 when possible; otherwise analyze and reconstruct the effect under legally usable interfaces.
5. **Manual route review:** show every applicable backend for every detected native plug-in, its prerequisites, current measured status and any failed gates. The user can inspect and specify a preferred route; no route is presented as runnable until its worker and host adapter are integrated and its tests pass.

The migration result page must show **all** applicable candidates for **all** detected plug-ins; it must not truncate the candidate list to a short preview. After scanning, Ae opens a route-selection window: each detected native plug-in has its own **automatic best-route** choice plus a radio choice for every applicable backend (Box64/Box86, FEX, QEMU, Wine combinations, or native ARM64 path). Every route shows its prerequisites, notes, and measured status/score where available. The same window lists every forced-compatibility/aggressive-port sub-profile. Users may choose automatic selection or manually prefer any listed route for each plug-in; no route is mandatory and there is no fixed preference for Box64. Manual selections are reported as preferences only until an executable worker and host adapter exist.

AI model/plugin ZIP import and model downloads are handled exclusively from **模型管理**. The general **导入插件** menu is reserved for effects and desktop plug-ins and must not contain an AI import item.

## Ordered trial policy

The route planner records the following order; a route may run only when its exact prerequisites are available.

| Input file | Ordered candidate execution routes |
|---|---|
| Windows PE x86-64 (.aex, Windows .ofx, .dll) | Wine64 + Box64 → Wine64 + FEX (Linux guest / kernel prerequisites) → Wine64 + QEMU x86_64-user (slow reference) |
| Windows PE x86 (32-bit) | Wine32 + Box86 → Wine WOW64 + Box64 (experimental) → Wine32 + FEX i386 → Wine32 + QEMU i386-user |
| Linux ELF x86-64 | Box64 → FEX → QEMU x86_64-user |
| Linux ELF x86 | Box86 → FEX i386 → QEMU i386-user |
| Windows/Linux ARM64 | Native ARM64 loader path, subject to OS and plug-in ABI |
| macOS Mach-O | No direct Android execution route; static analysis + source rebuild or clean reimplementation |

For Windows plug-ins, FEX/QEMU candidates mean running a Wine guest in a compatible Linux guest environment—not passing the PE file directly to a Linux user-mode emulator. QEMU user-mode is mainly a slow reference route. A route is skipped, not failed, when its kernel, rootfs, guest libraries or ABI prerequisites are missing.

## Sequential trial harness and result comparison

Each route must run in its own disposable guest snapshot and must not share writable plug-in state with the next candidate. Use no network by default, a private rootfs, bounded memory/CPU, timeouts, restricted filesystem access, bounded IPC buffers, and force-stop cleanup.

Every candidate receives identical deterministic tests:

1. Binary and dependency load; plug-in entry point discovery.
2. Instance creation, required host API suite discovery and clean teardown.
3. Parameter count, IDs, defaults, ranges, UI controls and animated parameter round-trip.
4. Preview and final render on the same image frames and settings.
5. Alpha, color space, channel order, row stride, bit depth, edge modes and multi-input behavior.
6. Keyframes, frame-time behavior, temporal history and random-access frames where supported.
7. Cancellation, repeated renders, memory growth, crash isolation and recovery.
8. Output comparison against desktop reference renders at identical resolution, time and settings.
9. Render time and peak memory on the target device.

Suggested score (0–100):

| Dimension | Weight |
|---|---:|
| Required host/API coverage and successful discovery | 20 |
| Parameter/control coverage and animation | 15 |
| Preview + final render correctness | 20 |
| Feature completeness (multi-input, temporal, GPU where applicable) | 15 |
| Visual fidelity against desktop reference | 15 |
| Stability, cancellation, repeatability and cleanup | 10 |
| Performance and peak memory | 5 |

The score is reported only when the candidate has real measured results. Unknown or untested capabilities are unknown, not treated as supported. A candidate cannot win by producing an attractive single frame if it lacks required effects, parameter controls, temporal behavior or stable final export.

Hard gates before automatic import:
- no crash or memory corruption in the test suite;
- all required host APIs for the claimed feature set are implemented;
- parameter and keyframe behavior round-trips;
- final render and cancellation pass;
- no silent substitution of missing required APIs;
- plugin authorization and license checks are not bypassed.

If every route fails a hard gate, Ae preserves the source and exposes only the analysis report or an explicitly labeled compatibility recreation.

## Aggressive port / forced compatibility mode

This is a deeper fallback after ordinary routes fail. It is not permission to blindly execute unknown code or lie to the plug-in about required APIs.

### Compatibility profiles to test, one at a time

- **Legacy OS/runtime profile:** test supported Windows API levels and install only legally redistributable VC runtime / .NET dependencies.
- **Host API profile:** negotiate optional suites; provide clearly bounded shims only for optional callbacks. Missing required callbacks are a failure.
- **Pixel format profile:** try RGBA/BGRA, supported bit depths, premultiplied/straight alpha and row-stride conversion.
- **Render profile:** try CPU fallback, GPU forwarding disabled, serial rendering, and ordered frame calls when the plug-in's threading behavior is incompatible.
- **CPU profile:** mask unsupported optional CPU extensions and test lower feature levels; never pretend unavailable instructions are supported.
- **Source rebuild:** when source is provided or available under valid terms, recompile for Android ARM64 with NDK/Clang and replace platform-specific APIs.
- **On-device triage:** use Capstone's native Android library to disassemble x86/x86-64 instructions and record unsupported instruction families, imports and call targets. Capstone is a disassembler, not an emulator or translator.
- **Deep binary reconstruction:** use Ghidra during engineering/offline analysis to inspect imports/exports, resources, strings, control flow and parameter metadata. Remill may lift supported machine instructions into LLVM IR for further analysis. Reimplement the effect algorithm as native ARM64 or a sandboxed WASM module, then compare it against reference frames. Ghidra is not intended to be bundled into the normal phone APK.

"Force compatibility" must not disable security checks, bypass activation/licensing/DRM, silently stub required host APIs, or import a binary that has not passed the render tests. A compatibility recreation must be labeled as an Android recreation, not the original vendor plug-in.

## Host API work is separate from CPU translation

- **OFX:** first target because the OpenFX API has a C ABI and public specification. Build a separate Wine-side OFX host worker and bridge its parameters/images to Ae through versioned IPC/shared memory.
- **Adobe AEX:** not OFX. It requires a separate Adobe After Effects SDK host adapter for suites, selectors, parameter semantics and callbacks. Box64 + Wine alone cannot provide Adobe's host.
- **Photoshop .8bf / Premiere .prm / arbitrary DLL:** each needs its own host adapter; a DLL is not a plug-in standard by itself.

The worker must never load arbitrary desktop plug-in binaries inside Ae's main Android process.

## Current source implementation status

The importer now:
- detects Windows PE and Linux ELF architecture;
- assigns format-specific candidate routes in deterministic order;
- exposes automatic-best, CPU-translation, forced-compatibility, aggressive-port and manual-review strategy choices in Ae;
- lists every candidate route for every detected native plug-in in the migration report;
- records each route as not_run_runtime_not_integrated with translation_executed=false;
- records proposed aggressive compatibility profiles;
- preserves native desktop plug-ins separately from runnable WASM/WAT/script modules;
- reports that architecture analysis and a proposed route are not a successful port.

Not yet implemented:
- packaging Box64/Box86/FEX/QEMU and Wine guest runtimes in Ae;
- per-route isolated workers and actual sequential execution;
- the real score calculation from measured results;
- OpenFX host worker and Adobe AEX host compatibility;
- phone hardware validation.

## License / redistribution

Preserve upstream notices. Box64/Box86/FEX use MIT-style permissive terms; Wine is LGPL-2.1-or-later; QEMU is GPL-2.0 with per-file exceptions; OpenFX and Capstone use BSD licenses; Ghidra and Remill use Apache-2.0. Before shipping, audit the exact pinned source revision, all transitive libraries, modified-source publication obligations and notices. Do not bundle a binary without verifying its license.

## Sources

- Box64: https://github.com/ptitSeb/box64
- Box86: https://github.com/ptitSeb/box86
- Wine: https://github.com/wine-mirror/wine
- FEX: https://github.com/FEX-Emu/FEX
- QEMU user-mode docs: https://www.qemu.org/docs/master/user/
- Winlator Android integration reference: https://github.com/winebox64/winlator
- OpenFX: https://github.com/AcademySoftwareFoundation/openfx
- Ghidra: https://github.com/NationalSecurityAgency/ghidra
- Capstone: https://github.com/capstone-engine/capstone
- Remill: https://github.com/lifting-bits/remill
