# Adobe After Effects Plugin Compatibility for Android Ae

## Scope

The compatibility target is Adobe After Effects (desktop), not EffectCraft or another host. Adobe plug-in support is additive. **Do not remove or replace any existing Ae feature, Windows compatibility feature, plug-in import control, translation backend, aggressive-port option, force-compatibility option, manual backend selection, or progress/report UI.** New Adobe-specific routes must be added alongside them.

## Verified Adobe extension families

Adobe's current SDK distinguishes effect plug-ins, general plug-ins (AEGPs), and input/output plug-ins (AEIOs). Effects add renderable image operations; AEGPs can add commands, panels, project operations and render-queue workflows; AEIOs add media-format support. Do not collapse all native .aex files into image effects.


| Family | Desktop package/file | Desktop purpose | Android implementation target |
|---|---|---|---|
| Native After Effects plug-in modules | Windows `.aex`, `.pbk`, `.pbg` | Effect plug-ins, general host extensions and I/O modules; the actual role is determined by Adobe SDK module/entry points, not only the suffix | Accept the files and retain originals; `.aex` can enter the isolated AEX host trial. `.pbk/.pbg` require their own module-specific host validation and are not treated as AEX effects automatically |
| Legacy Photoshop-format plug-ins/filters | `.8bi` (historic After Effects compatibility format) | Legacy Photoshop-format filters; Adobe marks the old filter API family as deprecated and recommends modern AE I/O approaches for new work | Accept, identify and preserve; use a separate legacy Photoshop-format host adapter. Do not send these through the AEX host |
| Windows native modules and dependencies | `.dll` | Windows PE module format; a DLL may be a plug-in, helper or dependency and is not an AE plug-in type by itself | Inspect PE architecture/imports and retain. Execute only when a matching AE plug-in family and host ABI have been established |
| macOS plug-in bundles | `.plugin` / `.bundle` directories; may contain Mach-O executables and `.dylib` components | macOS native plug-in package and resources | Accept as a ZIP-preserved bundle tree so relative resources remain intact; macOS Mach-O is not directly executable on Android and needs source-based port/reimplementation |
| ExtendScript scripts | `.jsx`; compiled `.jsxbin` | Automation, project/layer/effect operations and commands | `.jsx` remains on the script route. `.jsxbin` is accepted and preserved, but needs a compatible bytecode runtime or vendor source before execution |
| CEP panels | `.zxp` package or unpacked extension directory containing `CSXS/manifest.xml` | HTML/JS panel and ExtendScript bridge | Accept and inspect the package/manifest; execution requires a CEP-compatible panel runtime and AE DOM bridge |
| UXP plug-ins | `.ccx` package or unpacked extension directory with `manifest.json` | Commands and persistent panels using UXP and AE APIs | Accept and inspect the package/manifest; execution requires an After Effects-compatible UXP runtime and the APIs exposed by the target AE version |
| Animation presets (not plug-ins) | `.ffx` | Reusable effects, properties, keyframes and animation settings | Accept and preserve; translate only supported preset constructs into Android Ae effects/properties/keyframes. Do not report a preset as an executable plug-in |
| Projects (not plug-ins) | `.aep`, `.aepx` | Project files | Keep in the existing project-import route, never misclassify as plug-ins |

Adobe documents that After Effects plug-ins include more than image effects: AEGPs can integrate menus/panels and manipulate project elements, while AEIO plug-ins add media-format support. The importer and compatibility report must preserve these distinct plug-in roles. The SDK also exposes legacy Photoshop-format filters and older extension points such as Artisans/BlitHook; these do not all define a separate portable filename suffix, so the importer must identify the module family and host ABI from metadata/SDK entry points rather than guess from a `.dll` name. A `.zip` is only a safe transport container, not an AE plug-in format. `.8bf` may be accepted as an additional compatibility candidate, but is not being claimed here as an Adobe-documented After Effects suffix. include more than image effects: AEGPs can integrate menus/panels and manipulate project elements, while AEIO plug-ins add media-format support. The importer and compatibility report must preserve these distinct plug-in roles.

## Existing migration and compatibility controls — MUST REMAIN

Keep every existing route and its separate user-selectable action:

1. **Automatic comparison / best route** — inspect applicable routes, compare verified functional completeness and choose only a route that passes the required tests.
2. **CPU instruction translation** — preserve Box64, Box86, FEXCore and QEMU candidate/installed routes and their architecture-specific handling.
3. **Force compatibility** — preserve the existing runtime, API, graphics, pixel-format, CPU-feature and serial-render fallback experiments.
4. **Aggressive port / reconstruction** — preserve PE parsing, import/export inspection, x86/x64 instruction decoding, control-flow/basic-block reconstruction, intermediate-representation output, source-assisted recompilation where source and license permit, and isolated runtime trials.
5. **Manual backend selection** — preserve the ability to inspect and choose among applicable backends.
6. **Windows runtime installation and isolated testing** — preserve Wine/Proton, Box64/BOX32, FEXCore and the separate Box86/QEMU experiments and their progress/results UI.
7. **Migration progress, detailed report, retry and original-package retention** — keep these capabilities.

Do not merge these choices into one opaque button or silently remove any option. Adobe-specific adapters are additional routes, not replacements for the existing migration modes. Where a route is not yet executable, retain the option and clearly show its actual status and prerequisites.

## Platform constraints and honest status

- A Windows `.aex` is native code. CPU translation alone is insufficient: the host must implement the relevant Adobe SDK suites/callback ABI, parameter lifecycle, pixel buffers/color depths, render lifecycle, threading, and any UI or OS integration the plug-in uses. Android ARM64 cannot directly load a Windows x86-64 DLL. The Android migration flow now connects eligible imported AEX packages to the isolated `aexlo` host worker and can trial the installed ARM64EC/FEXCore or x86-64/Box64 route; a passing smoke test covers only the tested plug-in's load, supported parameter round-trip and repeated CPU-frame render, not full AE compatibility.
- Box64/Wine/FEX/QEMU are candidate guest/runtime components; none automatically provides the Adobe After Effects host SDK. Keep instruction translation, OS/API compatibility, and Adobe host-ABI emulation as separate layers.
- Aggressive PE/IR reconstruction, Remill lifting and Ghidra analysis are porting aids, not proof that closed-source plug-ins have been automatically converted into ARM64 code. The Remill/LLVM route is a candidate only until instruction semantics, imports, relocations, Windows APIs and Adobe host callbacks are implemented and a reference render passes. Never label a plugin as ported until the output passes host/API and render tests.
- CEP and UXP are different runtimes. Do not conflate `.zxp` with `.ccx`, and do not treat archive extraction as successful panel execution.
- As of November 22, 2026, After Effects UXP is in public beta (Adobe announced the AE beta on November 17, 2026). The public beta does not yet support native C++ Hybrid plug-ins; do not treat `.ccx` manifest recognition as proof that a UXP extension runs in Ae. CEP remains supported during the transition, is planned to be disabled by default from December 2028, and removed from After Effects in December 2029. Validate the target host/version and exact API surface; standalone ExtendScript scripts remain a separate route.
- `.ffx` is an animation preset, not an executable native plug-in. Translate supported preset constructs into native Ae effects/properties/keyframes; report unsupported constructs explicitly.
- Do not execute imported packages automatically. Validate manifests, permissions, archive paths and size limits; retain the original package and isolate untrusted code.

## Delivery stages

1. **Inventory and safe intake**: separately recognize `.aex`, `.pbk`, `.pbg`, legacy `.8bi`, Windows `.dll` candidates, macOS `.plugin`/`.bundle` package trees, `.jsx`, `.jsxbin`, `.zxp`, `.ccx`, `.ffx`, and project files. `.zip` is treated as a safe transport container; it is not itself a plug-in type. Inspect manifests, keep nested paths/resources, and reject path traversal. The first inventory tool is `.github/scripts/inventory_adobe_ae_plugins.py`; its output is explicitly inventory-only and does not execute code. The aggressive-port path integrates `.github/scripts/integrate_binary_reconstruction.py` and `windows-compat/aex-reconstruction/src/lib.rs` into the migration screen: for selected `.aex`/PE candidates it can recover bounded x86/x64 instruction assembly/operand IR, basic-block candidates, imported DLL/function names, exports and base relocations. This is static reconstruction evidence for a later port; Windows API semantics, the Adobe SDK host ABI, ARM64 recompilation and reference rendering remain separate unimplemented gates. `.ffx` files also have a bounded read-only triage tool at `.github/scripts/inspect_adobe_ffx_preset.py`; it records hashes, headers and readable strings but does not decode or translate the proprietary preset format. `.jsx` source files have a lexical capability scanner at `.github/scripts/inspect_adobe_extendscript.py`; it identifies likely AE DOM, ScriptUI, file, bridge and runtime-global dependencies without executing the script or claiming API compatibility.
2. **Preset route**: inspect `.ffx` structure and build a compatibility report, then implement translation of supported constructs into Ae's model.
3. **Script route**: implement a restricted ExtendScript-compatible runtime and AE scripting DOM mapping. Unsupported APIs must be reported, not silently ignored.
4. **Panel route**: implement CEP and UXP as distinct runtime projects, beginning with manifest validation and a minimal panel that invokes a safe subset of Ae operations.
5. **Native plug-in route**: implement the relevant Adobe SDK host adapter, then connect the existing CPU translation / Windows guest routes and aggressive reconstruction tools. Add real effect and AEIO/AEGP host tests.
6. **Regression and release**: preserve all existing features and migration controls; build APK; validate package integrity, signing, import flows, runtime execution, and actual effect rendering.

## Acceptance criteria

- Import results distinguish: recognized, extracted, manifest validated, runtime initialized, host APIs available, script/panel/effect executed, and output/render verified.
- No route is marked successful solely from extension recognition, architecture detection, static strings, PE reconstruction, or archive extraction.
- Unsupported or failed imports retain the original package for retry and show a specific reason.
- Existing automatic comparison, instruction translation, force compatibility, aggressive port/reconstruction, manual backend selection, Windows runtime install/testing, progress UI and detailed reports remain present.
- No existing editing, project import/export, AI, network, or other app feature is removed.

## Official Adobe references

- After Effects developer portal and plug-in categories: https://developer.adobe.com/after-effects/
- After Effects C++ SDK capabilities and plug-in types: https://ae-plugins.docsforadobe.dev/intro/what-can-i-do/
- After Effects UXP and host API: https://developer.adobe.com/after-effects/uxp/
- After Effects UXP API reference: https://developer.adobe.com/after-effects/uxp/after-effects-api/
- ExtendScript `.jsx` / `.jsxbin` reference: https://ae-scripting.docsforadobe.dev/introduction/overview/
- UXP platform and API references: https://developer.adobe.com/uxp/uxp-api/
- UXP versions and After Effects host support: https://developer.adobe.com/uxp/uxp-api/versions
- Animation and effect overview: https://helpx.adobe.com/after-effects/desktop/apply-effects-and-animation-presets/effects-and-presets-overview.html
