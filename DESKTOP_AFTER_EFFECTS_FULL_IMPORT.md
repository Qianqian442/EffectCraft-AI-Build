# Ae Desktop After Effects Project — Full-Fidelity Import Requirement

Status: requested and approved target. Current importer exists, but full fidelity is not yet demonstrated. Do not describe the present implementation as complete or lossless.

## Goal

Import Adobe After Effects desktop project files `.aep` and `.aepx` into Ae as editable projects, preserving the original project's structure, timing, appearance, media relationships, and editable controls as closely as technically possible. This is a dedicated desktop-project import route, separate from Ae mobile-native projects and Adobe mobile After Effects exports.

## Non-negotiable rules

- Keep the original `.aep`/`.aepx` file unchanged. Import into a new Ae project and preserve a source backup/reference.
- Never silently discard a layer, effect, property, keyframe, expression, media reference, audio track, mask, shape, camera, light, or project setting.
- Before committing an import, run a dry-run analysis and show an understandable report of items that will import exactly, be converted, need relinking, or cannot yet be reproduced.
- Do not label an import complete when it has unresolved losses. Let the user review the report and choose whether to proceed with a clearly marked partial import.
- Keep the existing import command and loss-confirmation flow. Do not route desktop `.aep`/`.aepx` through the Ae mobile-native `.ecproj` parser.
- Do not directly execute Windows `.aex` binaries, DLLs, or other desktop-native plug-in code on Android, HarmonyOS, or iOS. Analyze plug-in metadata/behavior and implement a compatible native/WASM equivalent where feasible; preserve the original plug-in identity and settings for unresolved effects.
- A successful file parse is not the same as successful project fidelity. Validate the converted project visually and structurally.

## Required project coverage

### Project structure and media

- Project bins/folders, footage items, still images, image sequences, video, audio, solids, nested compositions, composition dimensions, pixel aspect ratio, frame rate, duration, work area, and time display.
- Preserve source paths and footage metadata. Provide a media relink flow for missing/offline files, support collecting/copying referenced media, and retain relative paths in the resulting Ae project package.
- Preserve audio timing, channels, sample-rate metadata where available, layer audio switches, and synchronization.
- Identify fonts used by text layers; preserve font family/style metadata and clearly report missing or substituted fonts rather than silently changing typography.

### Layers and animation

- Preserve layer order, start/end times, in/out points, stretch, source offsets, time remapping, visibility, solo, shy, guide, lock, collapse transformations, motion blur, frame blending, quality, blending modes, opacity, parenting, track mattes, and markers.
- Preserve transform channels and all importable animated properties.
- Preserve keyframe time/value data, hold/linear/Bezier interpolation, temporal ease, spatial tangents, roving behavior, and separated dimensions where represented by the source.
- Preserve expressions exactly when a compatible expression runtime exists. Otherwise preserve the original expression text and dependencies, identify it as unresolved, and offer a documented conversion path; do not silently replace it with a constant.

### Visual features and effects

- Preserve masks, mask modes/feather/expansion/opacity, shape layers and paths, text animators, gradients, strokes, fills, layer styles, adjustment layers, track mattes, cameras, lights, and 2D/3D layer properties.
- Map standard AE effects to Ae-native equivalents with matching parameter ranges, defaults, keyframe behavior, and visual output wherever possible.
- Preserve effect order and every effect parameter, including animated parameters and expressions.
- For third-party effects, detect plug-in name, version, effect identifiers, and parameter data. Map to an equivalent Ae effect where available; otherwise retain an unresolved-effect record and expose a clear report. Do not pretend a different effect is identical.
- Preserve color management, linear-light settings, bit depth, working space, and relevant render/composition settings where represented and supported.

## Import pipeline

1. Parse and inventory the `.aep`/`.aepx` container, project tree, compositions, layer graphs, media references, effects, plug-ins, properties, keyframes, expressions, and settings.
2. Resolve external media and fonts. Offer relinking/collection before final import.
3. Build a conversion map for each source feature to a native Ae object/property/effect, including parameter mapping and keyframe translation.
4. Run a dry-run compatibility report with separate counts for exact imports, converted imports, missing media/fonts, unsupported expressions, unsupported effects, 3D/camera/light limitations, and other unresolved content.
5. Present the loss report before import. Preserve unresolved source data in the imported project metadata so it can be revisited after future compatibility improvements.
6. Import to an editable Ae project without changing the source file.
7. Compare source and imported project structure, timing, keyframes, effect settings, and rendered reference frames.

## Acceptance criteria

- No silent omissions. Every source layer, composition, effect, property, keyframe, expression, asset, and project setting is either imported, converted with a recorded mapping, or explicitly reported as unresolved.
- Common 2D projects with supported effects, fonts, and media should import with editable layers and matching animation/timing.
- Complex projects containing 3D, cameras, lights, expressions, third-party effects, image sequences, audio, or unusual media paths must receive specific diagnostics rather than generic success messages.
- Import preserves the original source and allows the resulting Ae project to be saved, reopened, and exported.
- Regression tests cover both `.aep` and `.aepx`, nested compositions, missing footage/relinking, text/fonts, masks, shape layers, 2D/3D transforms, cameras/lights, animated effects, expressions, audio, time remap, and third-party plug-in metadata.
- Validate with representative real-world projects and compare reference renders. Only mark a feature as fully supported after tests pass.

## Current status disclosure

The existing project has a separate `.aep`/`.aepx` import route and a dry-run loss-confirmation path. Existing patch scripts explicitly acknowledge reporting unsupported effects, 3D conversions, and missing media. That is a useful starting point, not proof of complete import. Full fidelity remains an implementation and validation target.