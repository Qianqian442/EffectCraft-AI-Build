# Adobe After Effects Plugin Compatibility for Android Ae

## Scope

The compatibility target is Adobe After Effects (desktop), not EffectCraft or another host. Adobe plug-in support is additive. **Do not remove or replace any existing Ae feature, Windows compatibility feature, plug-in import control, translation backend, aggressive-port option, force-compatibility option, manual backend selection, or progress/report UI.** New Adobe-specific routes must be added alongside them.

## Verified Adobe extension families

Adobe's current SDK distinguishes effect plug-ins, general plug-ins (AEGPs), and input/output plug-ins (AEIOs). Effects add renderable image operations; AEGPs can add commands, panels, project operations and render-queue workflows; AEIOs add media-format support. Do not collapse all native .aex files into image effects.


| Family | Desktop package/file | Desktop purpose | Android implementation target |
|---|---|---|---|
| Native AE plug-ins | Windows `.aex`; Adobe also documents `.pbk` and `.pbg` modules | Effects, file-format import/export, general host integration | Adobe SDK host adapter plus isolated Windows guest; actual support requires real host callbacks and a successful render/import test |
| ExtendScript scripts | `.jsx`; compiled `.jsxbin` | Automation, project/layer/effect operations, commands | ExtendScript-compatible interpreter and AE scripting DOM; JSXBIN requires compatible bytecode support or vendor source |
| CEP panels | Commonly `.zxp` package or unpacked directory containing `CSXS/manifest.xml` | HTML/JS panel and ExtendScript bridge | CEP-compatible panel runtime and AE DOM bridge |
| UXP plug-ins | Commonly `.ccx` package or unpacked directory with `manifest.json` | Commands and persistent panels using UXP and AE APIs | UXP runtime/API compatibility layer; validate host declaration, entrypoints and permissions |
| Animation presets | `.ffx` | Reusable effects, properties, keyframes and animation settings | Parser/translator into Android Ae's effect/property/keyframe model |
| Projects (not plug-ins) | `.aep`, `.aepx` | Project files | Keep in the existing project-import route, never misclassify as plug-ins |

Adobe documents that After Effects plug-ins include more than image effects: AEGPs can integrate menus/panels and manipulate project elements, while AEIO plug-ins add media-format support. The importer and compatibility report must preserve these distinct plug-in roles.

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
- Aggressive PE/IR reconstruction is a static analysis and porting aid, not proof that closed-source plug-ins have been automatically converted into ARM64 code. Never label a plugin as ported until the output passes host/API and render tests.
- CEP and UXP are different runtimes. Do not conflate `.zxp` with `.ccx`, and do not treat archive extraction as successful panel execution.
- UXP for After Effects is a new, version-sensitive rollout. Adobe's September 24, 2026 announcement describes a phased transition away from CEP; the public beta announcement says CEP plug-ins are expected to be rewritten for UXP while standalone ExtendScript scripts continue. Inspect the actual AE host/version declaration and supported API surface; do not assume UXP support in another Adobe app implies AE support.
- `.ffx` is an animation preset, not an executable native plug-in. Translate supported preset constructs into native Ae effects/properties/keyframes; report unsupported constructs explicitly.
- Do not execute imported packages automatically. Validate manifests, permissions, archive paths and size limits; retain the original package and isolate untrusted code.

## Delivery stages

1. **Inventory and safe intake**: separately recognize `.aex`, `.pbk`, `.pbg`, `.jsx`, `.jsxbin`, `.zxp`, `.ccx`, `.ffx`, and project files. Inspect manifests, keep nested paths/resources, and reject path traversal. The first inventory tool is `.github/scripts/inventory_adobe_ae_plugins.py`; its output is explicitly inventory-only and does not execute code. The aggressive-port path integrates `.github/scripts/integrate_binary_reconstruction.py` and `windows-compat/aex-reconstruction/src/lib.rs` into the migration screen: for selected `.aex`/PE candidates it can recover bounded x86/x64 instruction assembly/operand IR, basic-block candidates, imported DLL/function names, exports and base relocations. This is static reconstruction evidence for a later port; Windows API semantics, the Adobe SDK host ABI, ARM64 recompilation and reference rendering remain separate unimplemented gates. `.ffx` files also have a bounded read-only triage tool at `.github/scripts/inspect_adobe_ffx_preset.py`; it records hashes, headers and readable strings but does not decode or translate the proprietary preset format. `.jsx` source files have a lexical capability scanner at `.github/scripts/inspect_adobe_extendscript.py`; it identifies likely AE DOM, ScriptUI, file, bridge and runtime-global dependencies without executing the script or claiming API compatibility.
2. **Preset route**: inspect `.ffx` structure and build a compatibility report, then implement translation of supported constructs into Ae's model.
3. **Script route**: implement a restricted ExtendScript-compatible runtime and AE scripting DOM mapping. Unsupported APIs must be reported, not silently ignored.
4. **Panel route**: implement CEP and UXP as distinct runtime projects, beginning with manifest validation and a minimal panel that invokes a safe subset of Ae operations.
5. **Native plug-in route**: use the current isolated `aexlo` worker for eligible x86/x64 AEX smoke trials on FEXCore/Box64, then expand the Adobe SDK host adapter coverage. Keep Remill/LLVM lifting, Ghidra reconstruction and other runtime backends as separate candidate routes until implemented. Add real effect and AEIO/AEGP host tests.
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
