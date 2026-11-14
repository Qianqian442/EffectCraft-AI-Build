# Simplified Chinese interface audit

## Scope

This audit targets the Android build's Simplified Chinese interface (`zh-hans`), not merely the operating-system language. It covers:

- Main menu and context menus
- Home screen, workspace and panel titles
- Project, Timeline, Composition, Effects and Presets panels
- Every Settings page, field, choice, tooltip and help label
- Import/export, overwrite, confirmation, progress and completion dialogs
- Effect names and categories
- Engine-generated status, warning and error messages

User-created names, file paths, external brand names, plug-in names and source text are not translated.

## Existing coverage found in the EffectCraft v0.21.1 localization source

The upstream `docs/localization-parity.md` describes Simplified Chinese as partial, not complete. Its measured baseline is approximately 1,936 of an estimated 4,200 user-visible strings (about 46%):

- 630 fixed menu labels
- 998 panel/dialog catalog sources
- 308 effect names and 21 effect categories
- Effect parameter names (approximately 1,650) are not comprehensively translated
- Home-screen literals, engine-generated tooltips, status and error text still include unwrapped English strings
- Help content is not fully localized, and the baseline has not had a complete native-speaker review

The panel catalog has many Settings and dialog labels, but catalog counts do not prove that every setting value, option, dialog branch or runtime error is covered. Missing catalog entries fall back to English.

## Automated audit added to PR #26

The integration validation now runs:

```sh
cargo test -p effectcraft-ui-egui --lib missing_translations_report -- --nocapture
```

This reports untranslated fixed menu and panel/dialog source strings for each catalog language, including Simplified Chinese. It is a report, not a zero-missing gate: the upstream test intentionally does not fail the build for missing translations. Its output must be reviewed before claiming full localization.

The validation workflow also runs `.github/scripts/audit_zh_hans_uncatalogued.py`. It scans direct UI literals, dialog/window titles, and common engine error/toast/status call sites that are not necessarily wired into the translation catalog. Its output is a **manual-review candidate list**, not a proof that every line is user-visible or untranslated; it must be reviewed in context.

The Android build patch also keeps Simplified Chinese as the default language for new installs and resolves a stored `system` preference to Simplified Chinese on Android. An explicit language selected by the user remains unchanged.

## After Effects desktop versus mobile EffectCraft

Adobe After Effects project export remains the desktop `.aep` format. The complete mobile package added here is EffectCraft's own `.ecproj` format plus its referenced media; it is not an Adobe After Effects mobile project. A different mobile application's project format requires that target application's name and a sample project so its real import/export schema can be verified.

## Acceptance criteria for calling the interface fully Chinese

1. The missing-string report has no untranslated, app-owned Simplified Chinese UI strings, apart from intentional technical names and user/content data.
2. All 21 effect categories and all registered effect names remain covered; effect parameter labels, units, enum choices and tooltips are also translated.
3. Every Settings page, field label, option, explanatory sentence and nested dialog branch is reviewed.
4. Home screen, menus, panel chrome, empty states, onboarding, import/export dialogs, progress UI, confirmations, warnings, status messages and errors are reviewed.
5. Engine-generated messages that reach the UI are routed through the same translation catalog (or have reviewed Chinese source messages).
6. Placeholder counts and formatting are preserved; UI tests and Android/Rust compilation pass.
7. Remaining English text is limited to user-entered content, paths, file extensions, API identifiers, external brand/plugin names and other technical proper nouns.

## Complete mobile project transfer

The new mobile EffectCraft export is intended to produce a self-contained project folder containing the `.ecproj` file and copied referenced footage under `(Footage)/`. Paths inside the project are relative to the exported project. The Android QQ share bridge packages that folder as one ZIP attachment. If any referenced footage is missing or cannot be copied, the export must fail rather than show a successful complete-package state.

On the receiving phone, the ZIP is selected through the unified project import entry (`文件 → 导入 → 导入am/NV/Ae/capcut工程`). The importer safely extracts the archive, locates the contained `.ecproj`, and hands it to EffectCraft's native project importer so the relative footage paths resolve next to the project.

The package includes project-referenced image, video, audio and image-sequence footage. It does not automatically embed external fonts, separately installed plug-ins, licensed assets or other software dependencies; those may need to be installed on the receiving device too.
