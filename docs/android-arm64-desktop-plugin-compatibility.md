# Android ARM64 desktop plug-in binary compatibility

**Status: engineering workstream; not a shipped translator.** This document records the selected open-source stack and the implementation boundary for running desktop plug-ins on Android ARM64. The source importer may identify the CPU architecture and report a candidate route, but that must never be presented as successful translation or execution.

## Goal

Accept a desktop plug-in package on an Android phone, identify its operating-system format and CPU architecture, preserve the original binary, and—where a compatible runtime and host adapter exist—run it through a sandboxed compatibility worker and expose its effect controls/rendering to Ae.

The phone target is **Android ARM64 (arm64-v8a / AArch64)**. "x86 to ARM64 translation" here means **dynamic translation at runtime**. The original x86/x86-64 plug-in is not rewritten into a new ARM64 .aex/.ofx file. Box64/Box86 translate guest CPU instructions as the plug-in executes.

## Open-source components selected

Pinned references are recorded for reproducible integration. Update them only through a reviewed dependency update.

| Component | Upstream / pinned revision | License | Role |
|---|---|---|---|
| Box64 | [ptitSeb/box64](https://github.com/ptitSeb/box64) — 3e5a0b5988435843a9a28534c08e97a2d34ed698 | MIT | x86-64 Linux guest execution and ARM64 dynamic recompiler |
| Box86 | [ptitSeb/box86](https://github.com/ptitSeb/box86) — bb716a2a6576cc06da811bf55e31e2f6f03b7596 | MIT | 32-bit x86 Linux guest support when a 32-bit ARM guest userspace is available |
| Wine | [wine-mirror/wine](https://github.com/wine-mirror/wine) — 76f8e9479548cbc5bdb8b3bd499e4768e7c25078 | LGPL-2.1-or-later | Windows PE loader and Windows API compatibility; it is not a CPU translator |
| OpenFX | [AcademySoftwareFoundation/openfx](https://github.com/AcademySoftwareFoundation/openfx) — 4249fe1b590a7e65caf4b1e4693b6b53220703f5 | BSD-3-Clause | First host API target for compatible OFX effects |
| FEX (fallback/reference) | [FEX-Emu/FEX](https://github.com/FEX-Emu/FEX) — 031d6d1edeb68ea1a224f1c4aebac0c0b342f438 | MIT | Alternative x86/x86-64-on-AArch64 Linux user-mode translator; not the primary Android integration |
| Remill (analysis only) | [lifting-bits/remill](https://github.com/lifting-bits/remill) | Apache-2.0 | Static instruction lifting to LLVM bitcode for research/analysis, not a drop-in general PE recompiler |

The Android packaging model is informed by [Winlator](https://github.com/winebox64/winlator), which demonstrates Wine plus Box86/Box64 on Android. Box64 upstream also documents Wine64 use, the need for Box86 for many 32-bit components, an experimental Wine WOW64 alternative, and Android/Termux/Winlator-glibc build profiles. These are upstream capabilities, not evidence that Ae has already bundled or validated the runtime.

## Execution routes

| Input | Candidate route | Important remaining requirement |
|---|---|---|
| Windows PE x86-64 (.aex, Windows .ofx, .dll) | Wine64 loads PE code inside an x86-64 guest; Box64 translates x86-64 instructions to ARM64 | Windows API, guest root filesystem, plug-in host ABI, graphics/runtime dependencies |
| Windows PE x86 (32-bit) | Wine32 + Box86 with a 32-bit ARM guest userspace; alternatively Wine WOW64 + Box64/Box32 only after compatibility testing | 32-bit guest libraries and host ABI; Box32/WOW64 path is experimental |
| Linux ELF x86-64 | Box64 | glibc guest environment, shared-library dependencies, plug-in host ABI |
| Linux ELF x86 | Box86 | 32-bit guest userspace and plug-in host ABI |
| ARM64 PE/ELF | Native ARM64 CPU path where the OS loader/ABI supports it | Windows/Linux ABI and plug-in host ABI still need adaptation |
| macOS Mach-O | No automatic Android execution route | Requires source-based port or a clean reimplementation; macOS frameworks cannot be assumed available on Android |

The translator and Windows compatibility layer are separate responsibilities:
- **Box64/Box86 translate guest CPU instructions.**
- **Wine loads Windows PE binaries and implements Windows APIs.**
- **The plug-in host adapter implements the application-specific ABI expected by the plug-in.**
All three are needed for a Windows desktop plug-in to become usable in Ae.

## Host integration strategy

### First target: OpenFX

OpenFX is a C-based plug-in API with an open BSD-3-Clause specification and headers. Its C ABI makes it a much more realistic first host bridge than a proprietary C++ plug-in interface.

Implement a separate x86-64 Wine-side OFX host worker which:
1. discovers an OFX binary and calls its standard plug-in entry points;
2. implements the minimum required OFX property, image-effect, parameter, memory, message and image suites;
3. exposes only the supported CPU render context at first;
4. exchanges bounded image buffers and parameter values with the native ARM64 Ae process over a versioned IPC/shared-memory protocol;
5. maps OFX parameters to Ae effect controls and keyframes through Ae's normal property system.

Start with a small test plug-in built from the upstream OpenFX examples. Do not claim arbitrary OFX compatibility until the plug-in passes discovery, instance creation, parameter round-trip, preview render, final render, cancellation, and teardown tests.

### Separate, later target: Adobe After Effects .aex

An .aex is not an OFX plug-in. It expects Adobe After Effects SDK suites, selectors, parameter semantics, and other host services. Box64 plus Wine can address CPU and Windows API compatibility but **cannot create the Adobe host API**.

AEX support therefore requires a separately designed, clean-room Adobe host compatibility layer, built only against legally available interface documentation/SDK materials. It must not copy proprietary Adobe implementation code. Start with a narrow set of effects and host callbacks; unknown suites or GPU-only effects must be reported as unsupported rather than silently ignored.

Generic Windows .dll, Photoshop .8bf, and Premiere .prm files each need their own host/API adapter. A DLL filename alone does not tell Ae how to call it.

## Ae integration contract

- Keep original desktop binaries unchanged in Plug-ins/Desktop-Originals/.
- Keep WASM/WAT and JavaScript plug-ins on their existing native Ae import/load paths. Do not route them through Wine.
- Record detected file format, architecture, selected CPU translator, target ABI, host adapter requirement, and runtime status in the import report.
- Current metadata status must remain translation_executed = false until the runtime and host worker actually execute and pass tests.
- Never load an untrusted desktop binary into the Ae Android process. Run it in an isolated worker with a private guest filesystem, no network by default, strict memory/CPU limits, bounded shared-memory buffers, request timeouts, and a force-stop path.
- Reject malformed binaries and archives before handing them to any loader. Keep existing archive size/entry limits.
- Do not treat a filename/string match to a built-in effect as binary translation. Such a match is an Android compatibility recreation, not the original desktop plug-in.

## Implementation phases and acceptance gates

1. **Architecture-aware intake (current code change):** recognize PE/ELF architecture, assign an explicit Box64/Box86 candidate route, identify the required plug-in host adapter, preserve the source, and show that execution is not yet active.
2. **ARM64 x86-64 runtime proof:** build/pin Box64 for the selected Android guest environment; package a minimal glibc/guest userspace and Wine64 as a separate optional runtime component; test a known x86-64 Windows test executable on at least one Android ARM64 device. This is not yet a plug-in test.
3. **OFX host proof:** load an OpenFX sample through Wine + Box64 in the isolated worker, render a known frame, round-trip parameters, and verify cancellation/teardown. Only then enable import as a runnable OFX plug-in.
4. **32-bit x86:** add Box86/Wine32 with a verified 32-bit guest userspace, or evaluate Box64 + Wine WOW64/Box32 separately. Do not advertise it before real tests.
5. **AEX host compatibility:** implement and test Adobe-specific host callbacks separately; expand effect coverage in measured increments.
6. **GPU/advanced effects:** add GPU bridges, temporal frames, multiple image inputs, tracking and other host capabilities only when an effect requires them and they pass regression tests.

## License and distribution checks

Ship each third-party license and notices with the corresponding optional runtime. Wine is LGPL-2.1-or-later; source and modification notices must be supplied as required. Preserve the MIT notices for Box64/Box86 and the BSD-3-Clause notice for OpenFX. Record exact source revisions and build flags in every runtime release. The plug-in binary itself remains the user's supplied software; Ae must not bypass plug-in activation/licensing checks.

## References

- [Box64 README](https://github.com/ptitSeb/box64/blob/main/README.md)
- [Box64 Wine guide](https://github.com/ptitSeb/box64/blob/main/docs/WINE.md)
- [Box64 Android/Termux/Winlator-glibc build options](https://github.com/ptitSeb/box64/blob/main/docs/COMPILE.md)
- [Box86 README](https://github.com/ptitSeb/box86/blob/master/docs/README.md)
- [Winlator for Android](https://github.com/winebox64/winlator)
- [Wine README and license](https://github.com/wine-mirror/wine)
- [OpenFX API and license](https://github.com/AcademySoftwareFoundation/openfx)
- [Remill machine-code lifting](https://github.com/lifting-bits/remill)
