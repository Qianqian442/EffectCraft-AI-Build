# EffectCraft AE plug-in worker

This worker wraps the MIT-licensed `aexlo` runtime as a standalone Windows x64 process. It is intended to run inside an EffectCraft-managed Wine/Box64 or Arm64EC/FEXCore container, not in the Android process itself.

## Protocol

Start:

```text
effectcraft-aex-host.exe <plugin.aex>
```

The first stdout JSON line reports the plug-in's ABOUT text, declared parameters, available values, slider ranges, popup choices, custom-UI flags and whether the host runtime detects a GPU path.

Then send one JSON object per stdin line:

```json
{"cmd":"render","input_png":"Z:\\effectcraft\\input.png","output_png":"Z:\\effectcraft\\output.png","frame":0,"fps":30,"params":[{"index":1,"value":{"type":"float","value":0.5}}]}
```

The worker returns one JSON line with render status and output dimensions. Use `{"cmd":"info"}` to re-read parameters and `{"cmd":"quit"}` to exit.

The worker loads one plug-in per process and keeps that instance on its owning thread. EffectCraft should launch one worker per plug-in/compatibility container, supervise it, and discard/restart a worker after a crash or timeout. Map EffectCraft's private plug-in/frame directory into the Wine container and use the corresponding Wine drive path (for example `Z:\\effectcraft\\...`).

## Important implementation boundaries

- This is an early host bridge, not a complete After Effects clone.
- The upstream aexlo README reports approximately 89% implementation across its listed Effect suites, but only about 11% across AEGP suites. Several features such as sequence data, masks, camera, text, composite and some project/comp functions are absent or partial.
- GPU handling in aexlo uses Windows CUDA on Windows builds; EffectCraft should initially set `AEXLO_DISABLE_GPU=1` and use CPU fallback. A plug-in that requires unsupported GPU/AEGP features may still fail.
- aexlo documents native plug-ins as in-process native code without a sandbox. EffectCraft must isolate each plug-in in a separate worker process and must not load untrusted plug-ins inside the main Android process.
- The Android app still needs its own native runtime manager to install Wine/Box64 or Arm64EC/FEXCore, map storage, launch the worker, transport frame files, expose parameter controls and report diagnostics.
- No RAM limit is added by this worker. The Android OS and physical device memory remain the upper bounds.
