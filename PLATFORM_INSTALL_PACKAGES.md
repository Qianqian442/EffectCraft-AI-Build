# Ae Platform-Specific Install Packages

Status: approved release architecture. Separate native targets are required; builds and device validation remain separate work.

## Required install packages

| Platform | Deliverable | Notes |
| --- | --- | --- |
| Android phones/tablets | APK (or split APK set only if technically required) | Keep the current Android application target, package ID, signing identity, and update path stable. |
| HarmonyOS 5.0 and later | Native HAP module(s), packaged as a signed App Pack (.app) for distribution | Build with HarmonyOS SDK/DevEco toolchain; do not present an Android APK or compatibility-container app as the native HarmonyOS release. |
| iPhone/iPad | Native iOS IPA | Build with the supported Apple toolchain and valid Apple signing/provisioning. Distribution may use TestFlight, App Store, or an appropriate authorized in-house/ad-hoc channel. |

## Non-negotiable feature-parity rule

- These are separate OS-specific installation packages, not one universal package and not a single APK with renamed extensions.
- Preserve Ae's user-visible features, workflows, parameter ranges, project compatibility, and output behavior across all platform targets. Do not remove, hide, silently disable, or replace features with no-op controls to make a build pass.
- Platform-specific UI conventions and system APIs may differ where required by the OS, but user capabilities and results must remain equivalent.
- Shared engine code, Rust/C/C++ algorithms, media processing, project schemas, model assets, and network protocols should be reused where compatible.
- Platform-specific adapters must be maintained separately for application lifecycle, rendering/surface hosting, file/folder access, media-library publishing, share sheets, permissions, local inference, background work, and networking.
- If an OS policy or technical restriction blocks a requested behavior, record it as an explicit release blocker and explain the constraint. Do not claim full compatibility until a compliant equivalent with matching user capability is implemented and validated.

## Shared feature acceptance baseline

- Editing canvas, compositions, layers, effects, transforms, animation and keyframes.
- Timeline touch editing, including direct dragging of a clip's right edge to extend/shorten duration and live updates to duration, end time, timeline range, and related animation/keyframes.
- Curve editor, presets, playhead/selected-keyframe targeting, interpolation and expression behavior.
- Puppet pins and connected rigs; Chroma Key; RSMB-style motion blur; Looks-style grading; undo/redo.
- Existing EffectCraft effects, WASM plug-in loading/import, built-in effect packs, plug-in parameters, desktop AE plug-in package inspection/migration and script import paths, subject to each OS's supported secure execution model.
- Separate project import paths for Ae mobile-native projects (.ecproj/.ecprojx and supported project ZIPs), Adobe After Effects mobile projects only when the actual Adobe-exported format is verified, desktop After Effects .aep/.aepx, Alight Motion, NodeVideo and CapCut.
- Project export to a user-selected folder, with required media collected and relative paths preserved; system share-sheet support where available.
- Video export with manual format, resolution, frame-rate and bitrate selection; 240 FPS maximum selectable rate; actual render progress; resource preflight/warnings; completed video saved to the platform media library without forcing a folder picker.
- Draggable AI launcher and chat UI, image attachment/recognition, in-app DeepSeek local-model management and offline inference, RIFE interpolation, and Real-ESRGAN quality enhancement.
- Account registration/login, QQ-or-WeChat one-of contact requirement, avatar photo selection, offline registration queue and sync, on-demand session validation, administrator account counts, independent ban/unban controls, and authenticated encrypted connectivity.

## Platform build and validation gates

### Android
- Generate the APK from the existing Android pipeline.
- Verify package ID and persistent signing certificate to preserve compatible in-place updates.
- Verify APK ZIP integrity, manifest, ABI/native libraries, embedded assets and signature.
- Do not claim installation testing unless a real device installation test was performed.

### HarmonyOS
- Build a genuine HarmonyOS-native application using ArkTS/ArkUI and HarmonyOS SDK/NDK.
- Reuse compatible shared native code through supported HarmonyOS native interfaces; implement native rendering, storage, media, sharing, permission, lifecycle and networking adapters.
- Produce signed HAP module(s) and the signed .app distribution package.
- Validate on real HarmonyOS 5+ hardware against the shared feature acceptance baseline.

### iOS
- Build a genuine iOS/iPadOS application target, not an Android compatibility build.
- Reuse portable engine and Rust/C/C++ code where compatible; implement iOS-native lifecycle, Metal/rendering, file/folder picker, Photos library publishing, share sheet, permissions, local model storage/inference and networking adapters.
- Keep local AI model import/model management in-app; do not require an unrelated companion APK.
- Review plug-in/WASM delivery and execution against current Apple platform security and App Review rules. Do not silently remove plugin features; implement a compliant equivalent or track the limitation as a release blocker.
- Produce a signed IPA with valid Apple signing/provisioning, then distribute through an appropriate authorized channel such as TestFlight or App Store.
- Validate on real iPhone/iPad hardware against the shared feature acceptance baseline.

## Cross-platform project compatibility

- Keep the Ae mobile-native project format and media-reference schema shared wherever possible so projects can move between Android, HarmonyOS and iOS without lossy conversion.
- Test project export/import in both directions for every supported platform pair.
- Keep account IDs, backend protocols, model-package schema and effect/project identifiers stable unless a versioned migration is explicitly implemented.

## Release naming and disclosure

- Publish separate, clearly named releases: Ae Android APK; Ae HarmonyOS HAP/App Pack; Ae iOS IPA.
- Never label a source archive, build log, HAP, or IPA as an APK.
- For every release, state the OS/version and device architecture requirements, signing/distribution method, build verification results, and any outstanding feature-parity blockers.
- No platform build is declared feature-complete until the relevant feature checklist has passed. No install test is claimed unless performed.