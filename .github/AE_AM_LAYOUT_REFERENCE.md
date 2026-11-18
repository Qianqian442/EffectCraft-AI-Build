# Ae / AM layout baseline and mobile editing requirements

This document records the user's screenshot references and corrects the layout baseline. It is a product requirement, not a claim that every item below is already implemented.

## Correct baseline

"Old Ae version" means the earlier Ae interface previously customized for this project and shown in the user's third reference screenshot. It does **not** mean the untouched upstream EffectCraft UI. Recover the earlier project-specific layout from the pre-AM project history and the supplied screenshot; do not reset the product to vanilla upstream styling.

The pre-AM history boundary is commit `6c9f7c2178466b09a51874aae82a8a91f8417b30`, immediately before the first AM workspace patch (`4fe25ba5fd2b775e3f560a805c7096a1cede2e12`). Later features must be preserved while restoring only the relevant Ae workspace presentation.

## Ae mode — third screenshot is the visual reference

- Keep the classic desktop-style Ae composition workspace, including the menu bar and one single-row horizontal tools bar.
- Main panel layout: Project / Effect Controls at left; Composition / Layer in the middle with Timeline / Render Queue below; Preview at upper right; Properties / Align / Audio / Effects & Presets at lower right.
- Preserve the old project's visible project/media controls, plugin import, unified project import and export actions in the toolbar.
- No additional second layout-selector row, no duplicated toolbar, no squeezed header, and no AM-only mobile controls in Ae mode.
- Keep the original workspace selector/menu as the Ae/AM switching entry; layout switching must not change the active project, incoming-project auto-import, export, or other existing behavior.
- Restore the previous customized proportions and responsive behavior from the project's pre-AM version / third screenshot. Do not replace these proportions with arbitrary fixed widths or a new generic upstream layout.

## AM portrait mode — first and second screenshots are the references

- First screenshot is the independent portrait editing page; second screenshot is its project/home page.
- AM mode owns its own portrait top bar, project actions, composition preview, transport controls, multi-layer clip timeline, and bottom tool navigation. Do not leave Ae's long horizontal toolbar at the top and call it AM.
- Add dedicated AM-layout access to vector drawing and Puppet Pin editing, including Pen/vector path creation and Puppet Pin / Bend / Starch / Overlap tools. They belong in AM's bottom tool navigation, Add/Draw/Puppet drawers, or contextual editing controls—not in Ae's top tool strip.
- Keyframes and curves must get an AM-style mobile interaction surface: select a layer/property, add/move/delete keyframes, edit interpolation/easing and curves using touch-friendly controls. Do not merely open Ae's desktop Timeline panel and label it AM keyframes.
- The Effects browser and parameter drawers must scroll vertically by finger swipe. Effect rows should respond to taps without hijacking vertical swipes; sliders, curve handles and drag controls must keep their own gestures.
- Keep Ae and AM presentations independent while sharing the project model, rendering/effect engine and core edit commands where appropriate.

## Preservation and acceptance

- Keep all prior Ae functionality, effects, plugins, AI functions, project import/export, sharing, autosave, export progress and launch-time automatic project import.
- Switching Ae -> AM -> Ae must preserve the open project and unsaved state. Switching layout must not duplicate project imports or Activity launches.
- Verify the Ae workspace against the third screenshot and AM workspace against the first two screenshots on an Android handset-sized viewport.
- Test AM effect-list scrolling with finger swipes, effect tap application, parameter-list scrolling, slider adjustment, vector drawing, Puppet Pin placement and keyframe/curve editing.
- A build or source-marker check alone does not count as visual or interaction verification. Report what was built and what was actually tested separately.
