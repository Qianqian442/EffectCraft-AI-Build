# Alight Motion compatibility and feature-parity register

This register is the acceptance checklist for the separate **AM 竖屏** editing mode.
It is deliberately stricter than a visual resemblance check: a feature is complete only
when its editing controls, saved project data, renderer/export path, and regression tests
all work in the AM workspace without removing the original Ae workspace.

## Legal and source boundary

The official Alight Motion application source is not publicly available as an open-source
editor repository. Do not copy, decompile, or extract proprietary application code. Use only
source code the project owner is authorized to provide, or third-party components whose
licenses permit modification and redistribution. Open Motion is an MIT-licensed prototype;
the AM project parser/player libraries are MIT/Apache-2.0 components. Neither is a complete
replacement for the Alight Motion application.

## Acceptance checklist

| AM capability | Acceptance requirement | Current status |
|---|---|---|
| Mobile editing surface | Independent AM top bar, preview, transport, layer timeline and bottom tools; no Ae DockArea or Ae timeline renderer | In progress |
| Multi-layer media | Graphics, image, video and audio layers; reorder, select, hide, lock, solo and mute | Partial |
| Vector editing | Shapes, custom vector/freehand paths, Bézier handles, fills, strokes and multi-border | Not complete |
| Effect catalogue | AM effect IDs, every parameter, defaults, ranges, units, enums and presets; no silent drops | Not complete |
| Keyframes | Every supported property can be keyed; keyframe selection, moving, duplication, deletion and interpolation editing | Not complete |
| Easing and curves | AM presets plus custom Bézier, step and other easing curves; import/export round-trip | Not complete |
| Parent/child and rigging | Parenting, nested groups, joint links and transform inheritance | Not complete |
| Camera | Camera pan/zoom, focus blur, fog, animated camera parameters | Not complete |
| Groups and masks | Nested group editing, clipping, mask paths/modes and animated masks | Not complete |
| Colour and compositing | Colour adjustments, blending, opacity, solid/gradient/media fills | Partial |
| Motion blur | Velocity-based motion blur with AM-compatible controls | Not complete |
| Text and fonts | Text styling, alignment, spacing, fonts and imported font resources | Partial |
| Bookmarks and reusable elements | Bookmark editing, saved/reusable elements, copy/paste of whole layers and styles | Not complete |
| Playback | Scrubbing, frame stepping, playback range, audio/video sync and preview fidelity | Partial |
| Export | MP4 H.264/HEVC, GIF, PNG sequence and still image export from AM mode | Partial |
| Project package | Read/write AM project packages with media, fonts, nested scenes and metadata preserved | Partial |
| Ae coexistence | Switching back restores the original Ae layout and all Ae tools; project data remains shared and intact | In progress |
| Regression coverage | Representative AM sample projects, effect-by-effect render comparisons and import/export round-trip tests | Not complete |

## Known importer limitations that must be removed before claiming parity

The existing XML importer is a lossy first pass. It currently warns that AM effects and keyframe curves
are not converted, flattens group containers, simplifies some vector shapes and text styling, and
skips unsupported layer types. Adding the `.amproj` file-picker route only makes the archive
selectable; it does **not** by itself make those contents lossless or fully editable.

## Completion gate

Do not mark AM mode complete until every row above is implemented or has a documented, user-approved
equivalent; every AM effect ID is mapped to a verified implementation; unsupported input is reported
before import rather than silently discarded; representative projects pass import, edit, save,
reopen and render comparisons; and Ae mode regressions remain green.

Reference feature list: https://play.google.com/store/apps/details?id=com.alightcreative.motion
