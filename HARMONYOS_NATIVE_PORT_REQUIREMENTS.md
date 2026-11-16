# Ae HarmonyOS Native Port — Approved Requirements

Status: approved as a separate platform target; implementation and parity validation are not yet complete.

## Non-negotiable release rule

- Add a genuine native HarmonyOS application target for HarmonyOS 5.0 and later. Do not treat the Android APK as a HarmonyOS installation package and do not rely on an Android compatibility container as the product solution.
- Keep the existing Android APK target and its behavior unchanged. HarmonyOS work must be isolated in a separate project/module and build path.
- No feature deletion, silent disabling, or behavior downgrade to make the HarmonyOS build pass. Every existing Ae capability must have a working HarmonyOS implementation with equivalent user-visible behavior before the HarmonyOS version is called feature-complete.
- Reuse shared project formats, editing logic, algorithms, Rust/C/C++ libraries, and model assets where technically compatible. Implement HarmonyOS platform adapters for lifecycle, files, media library, sharing, permissions, networking, and rendering.
- If a feature is blocked by a platform/API limitation, keep it explicitly tracked as a blocker. Do not hide the control, replace it with a no-op, or claim parity until resolved.
- HarmonyOS UI may follow native ArkUI conventions, but the user's editing capabilities, project compatibility, parameter ranges, and results must not be removed or silently changed.

## Proposed technical direction

- Build a genuine HarmonyOS HAP using ArkTS/ArkUI and the HarmonyOS SDK/NDK.
- Reuse the existing engine and compute-heavy Rust/C/C++ components through HarmonyOS-native shared libraries and Node-API where compatible.
- Evaluate XComponent/NativeWindow rendering to host the existing editing canvas and preserve interactive timeline behavior; replace Android-only NativeActivity/winit host integration with a HarmonyOS host adapter.
- Implement HarmonyOS-native file/folder pickers, media-library save/publish, share sheet, app storage, permission flows, lifecycle, and networking adapters.
- Build and validate a HAP for device testing. For public distribution, create the required signed App Pack (.app) containing the HAP module(s), using valid Huawei developer signing material.
- Do not reuse Android package IDs as HarmonyOS bundle identifiers. Keep account IDs, project formats, network protocols, and cross-platform data schemas compatible where applicable.

## Feature-parity acceptance checklist

### Editing and timeline

- Preserve compositions, layers, transforms, effects, animation, keyframes, and project editing.
- Preserve direct touch dragging of a layer clip's right edge to lengthen/shorten its duration, with live updates to end time, displayed duration, timeline range, and keyframes/animation.
- Preserve curve editor and presets, playhead/keyframe targeting, curve application/overwriting, and all interpolation/expression modes.
- Preserve Puppet pins and connected rigs, Chroma Key with presets and color picker, RSMB-style motion blur, Looks-style controls, undo/redo, and existing editing controls.

### Effects and plug-ins

- Preserve original EffectCraft effects and the existing WASM plug-in import/loading path, built-in compatible effect packs, RSMB/Looks modules, and their parameter controls.
- Preserve desktop AE plug-in package inspection/migration and script import workflows. Do not attempt to execute Windows .aex binaries directly; where requested, analyze effect behavior and parameters and provide native equivalents.
- Do not remove plug-in functions or substitute inert UI controls.

### Project import and export

- Preserve separate import routes for Ae mobile-native projects (.ecproj/.ecprojx and supported project ZIPs), After Effects mobile projects (only after confirming Adobe's real exported format), and desktop After Effects .aep/.aepx.
- Preserve Alight Motion, NodeVideo, and CapCut project import/export routes and their supported conversion behavior.
- Preserve project export to a user-selected folder, including the native project and collected media with valid relative paths; preserve system sharing (including QQ when available).
- Do not fabricate an AE desktop writer or pretend an unimplemented format is supported.

### Video export

- Preserve manual format, resolution, frame-rate, and bitrate selection; maximum selectable frame rate remains 240 FPS.
- Preserve actual render progress, device/resource preflight and clear warnings, and successful completion feedback.
- Adapt output publishing to the HarmonyOS media library so completed videos are saved to the user's media library/album without forcing a folder picker, matching the Android workflow.

### Local AI

- Preserve the draggable floating AI entry and chat panel, expand/restore behavior, image attachment and recognition, and knowledge of Ae controls.
- Preserve in-app DeepSeek model management and local/offline inference. The GGUF model is imported as a model ZIP through the in-app model manager; it is not a third APK.
- Preserve RIFE AI frame interpolation and Real-ESRGAN quality enhancement in the export path.

### Accounts and networking

- Preserve registration and login, QQ-or-WeChat one-of contact requirement, avatar selection from the system photo picker, local/offline registration queue and later sync, and on-demand session verification.
- Preserve administrator-side account counts and independent ban/unban controls, with ban reason and duration rules.
- Preserve encrypted peer-to-peer/account connectivity and connection fallback behavior, adapting Android-specific APIs to HarmonyOS APIs without weakening authentication or authorization.

## Validation required before calling HarmonyOS support complete

- Build and sign the native HAP/App Pack with the correct HarmonyOS SDK/API target.
- Install and launch on real HarmonyOS 5+ hardware.
- Exercise the checklist end-to-end, including long video export, local AI/model import, project import/export with media, timeline dragging/curves, plug-ins, login/offline sync, and update/data retention.
- Verify that project files created on Android remain readable and editable on HarmonyOS and vice versa where the shared project format allows it.
- Report any unsupported format or platform-only constraint explicitly; do not claim full parity until every required item passes.