# Adobe After Effects Plugin Compatibility for Android Ae

## Scope

The compatibility target is Adobe After Effects (desktop), not the EffectCraft extension system. The Android application must preserve its existing editing, import/export, AI, and Windows-runtime features. Adobe plugin support is an additive subsystem.

## Verified extension families

| Family | Desktop package/file | Desktop purpose | Android implementation target |
|---|---|---|---|
| Native AE effect plug-ins | Windows `.aex` (native SDK binary) | New image effects with AE parameter, pixel-buffer, render, and UI callbacks | Native ABI/SDK adapter and isolated x86-64 Windows guest; do not mark compatible until a real effect renders |
| ExtendScript scripts | `.jsx`; compiled `.jsxbin` exists in the ecosystem | Automation, project/layer operations, commands | ExtendScript-compatible interpreter/DOM subset; compiled JSXBIN needs a compatible bytecode runtime or vendor source |
| CEP panels | Usually `.zxp` package or unpacked extension directory with `CSXS/manifest.xml` | HTML/JS panel plus ExtendScript bridge | CEP-compatible panel runtime plus AE DOM bridge; package extraction alone is not execution |
| UXP plugins | `.ccx` package, unpacked folder with `manifest.json` | Commands and persistent panels using UXP and AE-specific APIs | UXP-compatible JS/API/runtime subset; inspect host manifest and declared permissions |
| Animation presets | `.ffx` | Reusable layer/effect/keyframe/expression settings | Parser/translator into Android Ae layer/effect/keyframe model; not a native executable plugin |
| Projects (not plugins) | `.aep`, `.aepx` | Project files | Keep in project import flow, never classify as plugins |

## Important platform constraints

- A Windows `.aex` is a native plug-in binary. CPU translation alone is insufficient: the host must implement the After Effects SDK callback/suite ABI, pixel formats, parameter lifecycle, render lifecycle, threading, and UI expectations. Android ARM64 cannot load a Windows x86-64 DLL directly.
- Box64/Wine/FEX/QEMU can be investigated as guest-runtime components, but none by itself supplies the AE host SDK. A route is not supported until it loads a test plug-in and renders known output in the app.
- CEP and UXP are different extension runtimes. Do not conflate `.zxp` with `.ccx`; do not treat either ZIP container as proof that a panel can execute.
- `.ffx` is an animation preset, not a native effect binary. It should be translated into native layer/effect/keyframe operations when its contents are understood.
- Never execute imported packages automatically. Validate manifests, paths, size limits, signatures/permissions where applicable, and isolate untrusted code.

## Delivery stages

1. **Inventory and safe intake**: recognize `.aex`, `.jsx`, `.jsxbin`, `.zxp`, `.ccx`, `.ffx`, and project formats separately; inspect package manifests; preserve the original directory tree and resource paths; reject path traversal.
2. **Preset route**: build a read-only `.ffx` inspector and compatibility report, then implement a translator for supported preset constructs.
3. **Script route**: implement a restricted ExtendScript-compatible execution layer against the Android Ae project/layer/effect model. Unsupported APIs must be reported, not silently ignored.
4. **Panel route**: prototype CEP and UXP separately, starting with manifest validation and a minimal panel that can call a small safe set of Ae operations.
5. **Native effect route**: define the AE SDK host adapter and a real render test harness. Only after the host ABI is implemented should the x86-64 guest runtime be connected.
6. **Regression and release**: preserve all existing features; build APK; validate signature, package integrity, import flows, and real runtime behavior. Report each route as implemented, partial, or unsupported based on tests.

## Acceptance criteria

- An import result distinguishes: file recognized, package extracted, manifest validated, runtime initialized, host API calls available, effect/panel/script executed, and render/operation verified.
- No route may be reported as successful based solely on file extension, architecture detection, static strings, or archive extraction.
- Failed or unsupported imports leave the original package available for retry and show a specific reason.
- Existing app features and Windows compatibility controls remain available and separate from the Adobe AE plug-in routes.

## Official Adobe references

- After Effects developer portal: https://developer.adobe.com/after-effects/
- After Effects UXP documentation: https://developer.adobe.com/after-effects/uxp/
- UXP package format (.ccx) and CEP (.zxp) distinction: https://developer.adobe.com/uxp/guides/how-to/distribution/package/
- UXP support matrix: https://developer.adobe.com/uxp/uxp-api/versions
- Animation presets (.ffx): https://helpx.adobe.com/after-effects/desktop/apply-effects-and-animation-presets/effects-and-presets-overview.html
