# Desktop After Effects Import — Compatibility Matrix

Status: implementation inventory and work plan. **The current importer is not full-fidelity and must not be described as complete.**

Baseline inspected: EffectCraft source tag `v0.21.1`, `crates/aep`, `crates/engine/src/cmd/aep.rs`, and `docs/aep-import.md`.

## Current route

- Desktop Adobe project import is a dedicated `.aep/.aepx` route (`file.importAepDesktop`) that delegates to the existing After Effects importer.
- `.aep` and XML `.aepx` are parsed by the same typed reader.
- Import performs a dry-run report before the project is changed. The user must explicitly consent to a partial import when the report contains losses or known reader limitations.
- Imported data is added into a new project folder; the source file is read, not edited.
- This route remains separate from Ae's own `.ecproj/.ecprojx` files and from Adobe's mobile-app project format.

## Existing importer coverage (baseline, not a claim of universal fidelity)

| Area | Current baseline |
|---|---|
| Project tree | Folders, compositions, solids, footage items |
| Composition | Dimensions, frame rate, duration, work area, background, pixel aspect, motion-blur settings, shutter, renderer |
| Layer types | Solid, null, adjustment, footage, precomposition, text, shape, camera, supported light types |
| Layer relationships | Parent links, supported track mattes, layer order, several visibility/audio/3D switches |
| Transform and timing | Anchor Point, Position, Scale, Rotation, Opacity, X/Y Rotation, Orientation, in/out/start, stretch, time remapping |
| Animation | Keyframe time/value, supported linear/Bezier/hold sides, temporal ease and supported spatial tangents; expressions are retained on supported properties |
| Text | Source Text and many character/paragraph attributes, text animators and supported range selectors |
| Shapes and masks | Shape groups, paths, fills, strokes and several operators; supported masks and mask path animation |
| Effects and styles | A defined set of native effects, expression controls and nine common layer styles, with parameters and supported keyframes |
| Other | Layer/composition markers, image sequences, missing-footage placeholders, missing-font diagnostics, selected project colour/time settings |

The authoritative item-by-item list and its test notes live in the pinned source's `docs/aep-import.md`. A feature listed there may still have renderer differences or a documented approximation.

## Known gaps that block a full-import claim

### Data not currently decoded or not imported

- Frame blending, 3D material options and audio levels. Guide-layer state is decoded by the current importer and must not be counted as an unsupported field.
- Additional mask attributes such as mask colour, lock, feather falloff, mask motion blur and RotoBezier state.
- Per-character 3D text, text-on-a-path data and several unrecognised text style slots.
- Source Text keyframes and unsupported text animator selectors/properties, including wiggly/expression selectors and additional character controls.
- Effects outside the supported table, including documented examples such as Lumetri, EXtractoR and Stroke.
- Environment lights and some 3D/transform variants, including separated dimensions.
- Layer-style features such as layer-style gradients and Pattern Overlay.
- Mesh Warp Bezier handles moved independently.
- Certain footage interpretation and audio-related metadata.

### Imported with known approximation or renderer differences

- Some keyframe interpolation/ease forms (including documented Orientation and mask-path cases); an AE Bezier Orientation side can arrive as linear and is reported.
- **Curves:** the five curve channels/points are imported, but Ae uses monotone interpolation rather than AE's natural spline; the recorded render comparison differs by up to about 6 levels in the sampled fixture.
- **Mesh Warp:** rows, columns, quality and vertex offsets are imported, but Ae's bilinear mesh rendering differs from AE; the sampled comparison showed a small region around the moved vertex with differences above 2 levels. Independently moved Bezier handles are not yet imported.
- **Selected effects:** CC Radial Blur and Channel Blur matched in the documented fixtures; Directional Blur was within 5/255, while Venetian Blinds, Radial Blur, Black & White, Tritone, Luma Key, Matte Choker and Transform showed renderer differences in the recorded comparisons.
- **Layer styles:** Drop Shadow, Inner Shadow, Satin, Color Overlay and Stroke were close in the documented samples; Glow and Bevel intensities and Gradient Overlay direction differed.
- **Shape operators:** Repeater copy opacity and Offset Paths outline behavior have documented renderer differences.
- These are imported controls with a known visual-fidelity caveat, not exact AE equivalents. The UI preflight should make these documented differences visible alongside unimported fields.

These must remain visible in the preflight report until the relevant reader, model mapping and renderer behavior are verified.

## Required implementation sequence

1. **Inventory and preservation:** classify every source item as exact, converted, missing/relink-required, unsupported-but-retained, or rejected as damaged. Never silently skip a source object.
2. **Source-backed unsupported records:** preserve plug-in/effect identifiers, version strings and raw readable parameter values as revisitable metadata when the target does not yet have an equivalent. A placeholder is not a working effect and must be labeled as such.
3. **Media and fonts:** resolve relative paths, keep missing-media placeholders, support relinking and collection, preserve image-sequence numbering/rate, and report substitutions.
4. **Animation and text:** extend verified readers for separated dimensions, Source Text keyframes, additional text selectors, mask properties and time/ease forms.
5. **Audio and layer switches:** decode and map audio levels/channel metadata, frame blending, additional layer flags and 3D material properties. Guide-layer state is already decoded by the current importer.
6. **Effects and plug-ins:** extend the standard-effect table with verified parameter schemas; inventory third-party plug-ins and map only when an equivalent has matching controls and behavior. Do not execute desktop `.aex` binaries on mobile.
7. **Visual parity:** compare source/target renders and editable project structure at representative frames and times.

### Android media relinking boundary

- The Android folder-based relinker searches recursively only under the device's **primary shared storage** (main/internal shared storage) and requires the app's on-demand **All files access** permission for filesystem scanning. The Android document-tree bridge intentionally rejects non-primary storage volumes; footage stored on an external SD card must first be copied into primary shared storage. The folder picker and path checks reject locations that cannot be written/accessed.
- The relinker matches exact, unique filenames and checks media kind, dimensions, audio/video properties, codec and (for video/audio) compatible frame-rate/duration metadata. Duplicate names, unsupported source types, incomplete sequences and incompatible media remain unresolved for manual review. A dry-run report is available before applying changes.

## Build and validation gates

- Unit/fixture tests for both `.aep` and `.aepx`, damaged inputs, all supported property/effect types and every newly decoded field.
- Import-report tests proving every unsupported source item is counted and identified.
- Round-trip application tests: import, save Ae project, close, reopen, and verify media links and editable objects remain.
- Reference-render comparisons against the same source project in After Effects, covering timing, keyframes, transforms, text, masks, effects, styles, 3D, audio and nested compositions.
- Real-world project fixtures from the user (with permission), including media and fonts or a reproducible relink package.

**Completion rule:** do not mark a category fully supported merely because the file parsed or a layer appeared. It is complete only when its source data is accounted for, its Ae controls remain editable, and structural/timing/render validation passes. Unknown plug-ins and unsupported source records must never be silently discarded.
