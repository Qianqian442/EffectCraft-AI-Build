# Ae × AbsentMotion native integration work plan

Pinned upstream: `Comett1225/AbsentMotion` v5.1.1, commit `f350576485c42ff7aefa5c2f205b9f1b8ad873f7` (GPL-3.0).

## Non-negotiable acceptance rule

The existing generated Rust/egui page `crates/ui-egui/src/am_editor.rs` is a temporary prototype only. It is **not** the AM home screen and must never be described or accepted as the completed AM experience. Changing Ae panels, colors, orientation, or labels is not native AM integration.

The completed Ae×am mode must launch the actual pinned AbsentMotion Android/Compose application surfaces and preserve its own UI, navigation, project library, editor, effect browser, timeline, and native rendering engine. Ae's original home/editor remain separate and unchanged.

## Work stages

1. **Vendor and build the upstream source**
   - Bring the complete pinned upstream source into the repository/build (not a screenshot, APK-only wrapper, or copied UI mock).
   - Preserve GPL-3.0 LICENSE, NOTICE, THIRD_PARTY_NOTICES and corresponding source obligations.
   - Integrate its Android Compose code, shared Kotlin code, assets, native C++/Skia engine and required dependencies into the same installable Ae package under a non-conflicting namespace.
   - Keep the launcher/application label as Ae.

2. **Real AM home and editor routing**
   - Ae home remains the default home in Ae mode.
   - Ae×am mode opens the upstream AbsentMotion home/project library and its native editor.
   - The AM home must be the actual upstream HomeScreen/Compose flow, not an Ae home with renamed buttons.
   - Switching back returns to Ae's original home/editor without losing the open project or its unsaved state.

3. **Animated layout transition**
   - Add a short, interrupt-safe cross-fade/slide transition at the mode boundary.
   - Do not animate or rewrite the incoming-project intent/import pipeline.
   - Preserve the existing automatic project import on app launch exactly as it currently works, including when Ae×am was the last selected mode.
   - Do not trigger duplicate Activity launches or duplicate project imports during a switch.

4. **External navigation cleanup**
   - Audit upstream Android, shared Compose, resources, help content, update UI and notification entry points for browser intents, external URLs, social/community links, website/release/changelog links and links that launch another app.
   - Remove user-facing external jump actions and their dead UI affordances.
   - Keep internal app navigation, local help content, project/media file URIs, Android document picker/share handling and required system permission/settings flows.
   - Keep an in-app update/download flow only where it does not open an external browser or another app; remove external-link fallback actions.
   - Add a source audit so newly introduced external navigation cannot silently reappear.

5. **Project and export bridge**
   - Implement explicit project/media conversion and round-trip tests.
   - Do not silently flatten layers or discard unsupported effects, keyframes, masks, curves, audio, or media references.
   - Keep project save/export operations native to the active editor and preserve Ae's existing import/export paths.

## Initial source-audit findings

At the pinned upstream revision:
- `shared/kotlin/app/absentmotion/ui/home/HomeScreen.kt` is the upstream home UI entry to integrate.
- `android/src/main/kotlin/app/absentmotion/MainActivity.kt` owns the native Compose host and lifecycle/import handling.
- `android/src/main/kotlin/app/absentmotion/ui/home/HelpScreen.kt` passes help URLs to `links.openUri`, an external-navigation surface that must be removed or converted to local-only help.
- `android/src/main/kotlin/app/absentmotion/ui/home/UpdateDialog.kt` exposes release/changelog URL actions through `links.openUri`; remove those external actions while preserving safe in-app update behavior where possible.
- `Updater` and update notifications must be audited separately: local download/install flows are not the same as opening a website and should not be removed blindly.

## Completion gates

Do not mark Ae×am native integration complete until:
- the upstream home and editor code are present in the built package and the native renderer loads;
- the app remains one installable package labelled Ae;
- Ae and Ae×am home/editor switching works in both directions;
- transitions are smooth and do not interfere with launch-time automatic project import;
- external-navigation audit passes;
- project save/import/export round-trip tests pass;
- Android build, signing, APK integrity and device compatibility checks pass.

Current status: source audit and integration requirements recorded. Native source vendoring, Compose host integration, home routing, transition implementation, link cleanup, and APK validation remain pending.