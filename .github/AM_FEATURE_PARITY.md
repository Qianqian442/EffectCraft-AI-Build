# Alight Motion compatibility and feature-parity register

This register is the acceptance checklist for the separate **AM 竖屏** editing mode.
It is deliberately stricter than a visual resemblance check: a feature is complete only
when its editing controls, saved project data, renderer/export path, and regression tests
all work in the AM workspace without removing the original Ae workspace.

## UI separation requirement (hard gate)

Switching to **AM 竖屏** must route directly to a separate mobile editing application surface,
not resize, rotate, recolour, relabel, or rearrange the Ae screen.

The AM workspace must own its own:
- editing top bar, project actions, preview controls, playback/transport bar and bottom tool navigation;
- multi-track layer timeline, layer operations, keyframe controls and AM-style clip-edge gestures;
- Add Layer browser, effect browser, effect parameter editor, transform/property editor and project/media browser;
- AM-specific drawers, sheets, dialogs, touch gestures and contextual menus.

The AM surface must **not** use Ae's `DockArea`, Ae toolbar, or Ae Timeline as its
primary editing layout. The restored AM page owns the top bar, preview placement, transport,
clip timeline and bottom tool navigation. To avoid removing existing capabilities, selected
native panels are available only as contextual drawers: Effects & Presets, Effect Controls,
Properties, Project, and the native Timeline panel for detailed keyframe/curve editing. These
drawers are auxiliary editing surfaces, not the AM page's main layout.

Permitted shared internals include the project/session model, command engine, compositor and
rendering backend, media/audio decoding, effect implementations, undo history, encoders and
serialization. AM uses its own preview placement and touch-oriented clip timeline while calling
the shared composition renderer. The native Pen and Puppet tools remain selectable from its
Add Layer drawer.

The restored in-tree `am_editor.rs` page recreates the earlier AM-style mobile editing layout.
It is a first-pass AM-inspired editor, not the official Alight Motion application and not a claim
of complete feature parity. The selected AbsentMotion v5.1.1 source remains a separate future
integration candidate; it has not been compiled into the current Ae APK.

## Package size policy

There is no arbitrary product-imposed APK size target or 1 GB cap. A 2 GB distribution target is
acceptable when needed for local models, effect resources, media codecs or other complete
functionality. Do not remove features, models, effects or assets just to meet an artificial size
budget. Build and delivery must still account for actual Android packaging, filesystem, signing,
download and artifact-host limits; report those constraints if they become relevant rather than
silently reducing the application.

## Legal and source boundary

The official Alight Motion application source is not publicly available as an open-source
editor repository. Do not copy, decompile, or extract proprietary application code. Use only
source code the project owner is authorized to provide, or third-party components whose
licenses permit modification and redistribution. Open Motion is an MIT-licensed prototype;
the AM project parser/player libraries are MIT/Apache-2.0 components. Neither is a complete
replacement for the Alight Motion application.

A full independent open-source editor has now been selected as the AM-layout base:
[AbsentMotion](https://github.com/Comett1225/AbsentMotion), release v5.1.1, pinned commit
`f350576485c42ff7aefa5c2f205b9f1b8ad873f7`. It is a GPL-3.0 Android editor and supports
Alight Motion project import, but it is an alternative editor, **not** the official Alight
Motion source and not proof of exact AM feature parity. The integration must use its own
Compose editing surface and native renderer as a separate module; it must not be reduced to
a portrait version of the Ae screen. Preserve its GPL-3.0 notices and provide corresponding
source when distributing modified binaries.

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
