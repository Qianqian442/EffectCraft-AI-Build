#!/usr/bin/env python3
"""Harden the Android export-button path so setup failures become visible errors, not app exits."""
from __future__ import annotations

import os
import re
from pathlib import Path


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    header_path = root / "crates/ui-egui/src/header.rs"
    header = header_path.read_text(encoding="utf-8")

    # Convert synchronous engine panics into ordinary UI errors.
    guard = r'''/// EFFECTCRAFT_ANDROID_EXPORT_COMMAND_PANIC_GUARD_V1
/// Convert synchronous export-command panics into ordinary UI errors.
fn effectcraft_run_export_command(
    app: &mut EffectcraftApp,
    ctx: &egui::Context,
    command: &str,
    params: serde_json::Value,
) -> Result<serde_json::Value, String> {
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        crate::menus::invoke(app, ctx, command, params)
    }))
    .unwrap_or_else(|_| Err(format!("执行导出操作 {command} 时发生内部异常，已阻止编辑器继续崩溃。")))
}
'''
    if "EFFECTCRAFT_ANDROID_EXPORT_COMMAND_PANIC_GUARD_V1" not in header:
        header = header.rstrip() + "\n\n" + guard.strip() + "\n"

    header, add_count = re.subn(
        r'match crate::menus::invoke\(app,\s*&ctx,\s*"renderQueue\.add",\s*params\) \{',
        'match effectcraft_run_export_command(app, &ctx, "renderQueue.add", params) {',
        header,
        count=1,
    )
    if add_count != 1 and 'match effectcraft_run_export_command(app, &ctx, "renderQueue.add", params) {' not in header:
        raise SystemExit("Export button renderQueue.add call was not guarded.")

    header, output_count = re.subn(
        r'match crate::menus::invoke\(\s*app,\s*&ctx,\s*"renderQueue\.setOutput",',
        'match effectcraft_run_export_command(app, &ctx, "renderQueue.setOutput",',
        header,
        count=1,
    )
    # The current Android export deliberately keeps the Render Queue's own output path.
    # Do not require a setOutput command when no such override exists; that old check
    # contradicted the direct-render path and blocked builds even though no call was present.
    if output_count != 1:
        has_guarded_output = 'effectcraft_run_export_command(app, &ctx, "renderQueue.setOutput",' in header
        has_unguarded_output = re.search(
            r'crate::menus::invoke\(\\s*app,\\s*&ctx,\\s*"renderQueue\\.setOutput"', header
        ) is not None
        if has_unguarded_output and not has_guarded_output:
            raise SystemExit("A renderQueue.setOutput override exists but is not panic-guarded.")
        if not has_guarded_output:
            print("No renderQueue.setOutput override exists; native Render Queue output remains unchanged.")

    header, set_render_count = re.subn(
        r'crate::menus::invoke\(\s*app,\s*&ctx,\s*"renderQueue\.setRender",',
        'effectcraft_run_export_command(app, &ctx, "renderQueue.setRender",',
        header,
    )
    if set_render_count == 0 and 'effectcraft_run_export_command(app, &ctx, "renderQueue.setRender",' not in header:
        raise SystemExit("renderQueue.setRender recovery calls were not guarded.")

    # Guard the Android MediaStore JNI bridge at completion as well.
    old_start = 'match crate::android_gallery::start_publish(&path, &gallery_request) {'
    new_start = r'''let gallery_start_result = std::panic::catch_unwind(
                std::panic::AssertUnwindSafe(|| crate::android_gallery::start_publish(&path, &gallery_request)),
            ).unwrap_or_else(|_| Err("启动 Android 相册保存接口时发生内部异常。".to_string()));
            match gallery_start_result {'''
    if old_start in header:
        header = header.replace(old_start, new_start, 1)

    old_poll = 'match crate::android_gallery::poll_publish(&gallery_request) {'
    new_poll = r'''let gallery_poll_result = std::panic::catch_unwind(
            std::panic::AssertUnwindSafe(|| crate::android_gallery::poll_publish(&gallery_request)),
        ).unwrap_or_else(|_| Err("查询 Android 相册保存状态时发生内部异常。".to_string()));
        match gallery_poll_result {'''
    if old_poll in header:
        header = header.replace(old_poll, new_poll, 1)

    required = (
        "EFFECTCRAFT_ANDROID_EXPORT_COMMAND_PANIC_GUARD_V1",
        'match effectcraft_run_export_command(app, &ctx, "renderQueue.add", params) {',
        'effectcraft_run_export_command(app, &ctx, "renderQueue.setRender",',
    )
    missing = [item for item in required if item not in header]
    if missing:
        raise SystemExit("Export crash guard incomplete: " + "; ".join(missing))
    if "effectcraft_android_video_staging_path" in header:
        raise SystemExit("Quick video export must not override the Render Queue output with a staging path.")

    # The previous preflight allowed a 1080p export with only about 472 MiB
    # reported as available RAM. Complex compositions need much more headroom
    # for decoded footage, layer buffers, compositing and encoder staging.
    preflight_marker = "EFFECTCRAFT_ANDROID_EXPORT_DEVICE_PREFLIGHT_V2"
    if preflight_marker in header:
        old_memory = """        let mut min_total = if pixels >= 7_000_000 { 6 * GIB }
            else if pixels >= 3_000_000 { 4 * GIB }
            else if pixels >= 1_500_000 { 3 * GIB }
            else { 2 * GIB };
        if ai_interpolation || ai_upscale {
            min_total = min_total.saturating_add(512 * MIB);
        }
        let bytes_per_pixel = if ai_upscale { 40 } else if ai_interpolation { 28 } else { 12 };
        let fps_reserve = if fps >= 240.0 { 384 * MIB }
            else if fps >= 120.0 { 256 * MIB }
            else if fps >= 60.0 { 128 * MIB }
            else { 64 * MIB };
        let required_available = 384 * MIB + pixels.saturating_mul(bytes_per_pixel) + fps_reserve;"""
        new_memory = """        let mut min_total = if pixels >= 7_000_000 { 8 * GIB }
            else if pixels >= 3_000_000 { 6 * GIB }
            else if pixels >= 1_500_000 { 4 * GIB }
            else { 3 * GIB };
        if ai_interpolation || ai_upscale {
            min_total = min_total.saturating_add(GIB);
        }
        let bytes_per_pixel = if ai_upscale { 160 } else if ai_interpolation { 112 } else { 64 };
        let fps_reserve = if fps >= 240.0 { 512 * MIB }
            else if fps >= 120.0 { 384 * MIB }
            else if fps >= 60.0 { 256 * MIB }
            else { 128 * MIB };
        let required_available = GIB + pixels.saturating_mul(bytes_per_pixel) + fps_reserve;"""
        if old_memory in header:
            header = header.replace(old_memory, new_memory, 1)
        elif new_memory not in header:
            raise SystemExit("Export memory preflight did not match the expected V2 implementation; refusing an unsafe partial patch.")
    else:
        raise SystemExit("Expected Android export preflight helper was not generated before crash hardening.")

    required_runtime = (
        "let required_available = GIB + pixels.saturating_mul(bytes_per_pixel) + fps_reserve;",
        "let bytes_per_pixel = if ai_upscale { 160 } else if ai_interpolation { 112 } else { 64 };",
    )
    missing_runtime = [item for item in required_runtime if item not in header]
    if missing_runtime:
        raise SystemExit("Export memory preflight hardening incomplete: " + "; ".join(missing_runtime))

    header_path.write_text(header, encoding="utf-8")

    # EFFECTCRAFT_ANDROID_AI_EXPORT_CHECKPOINT_V1
    # AI inference is synchronous inside each frame. Make AI exports commit progress and
    # observe Render Queue cancellation after each completed frame, not after a large batch.
    pipeline_path = root / "crates/export/src/pipeline.rs"
    pipeline = pipeline_path.read_text(encoding="utf-8")
    if "EFFECTCRAFT_ANDROID_AI_EXPORT_CHECKPOINT_V1" not in pipeline:
        helper = r"""
/// EFFECTCRAFT_ANDROID_AI_EXPORT_CHECKPOINT_V1
/// AI frames are expensive and cancellation must be observed between individual inferences.
pub(crate) fn ai_batch_size(default: u64, android: bool, ai_enabled: bool) -> u64 {
    if android && ai_enabled { 1 } else { default.max(1) }
}
"""
        impl_anchor = "impl<'a> Cx<'a> {\n"
        if pipeline.count(impl_anchor) != 1:
            raise SystemExit("Could not find the single export context implementation for AI checkpoints.")
        pipeline = pipeline.replace(impl_anchor, helper + "\n" + impl_anchor, 1)
        method_anchor = "impl<'a> Cx<'a> {\n"
        method = r"""impl<'a> Cx<'a> {
    /// Return a batch size which lets Android AI exports report progress and accept cancel
    /// after every completed output frame. Ordinary exports retain the upstream batch size.
    pub fn batch_size(&self) -> u64 {
        ai_batch_size(
            crate::batch_size(),
            cfg!(target_os = "android"),
            self.job.output.ai_frame_interpolation || self.job.output.ai_upscale,
        )
    }
"""
        pipeline = pipeline.replace(method_anchor, method, 1)
        test_module = r"""

#[cfg(test)]
mod android_ai_export_checkpoint_tests {
    use super::ai_batch_size;

    #[test]
    fn android_ai_export_checks_cancellation_after_each_processed_frame() {
        assert_eq!(ai_batch_size(12, true, true), 1);
        assert_eq!(ai_batch_size(2, true, true), 1);
        assert_eq!(ai_batch_size(12, true, false), 12);
        assert_eq!(ai_batch_size(12, false, true), 12);
        assert_eq!(ai_batch_size(0, false, false), 1);
    }
}
"""
        pipeline = pipeline.rstrip() + test_module + "\n"
        pipeline_path.write_text(pipeline, encoding="utf-8")

    # Route every native movie/sequence exporter through the job-aware batch policy.
    export_paths = (
        (root / "crates/export/src/lib.rs", ("cx.batch_size()", "job.batch_size()")),
        (root / "crates/export/src/encode.rs", ("job.batch_size()",)),
        (root / "crates/export/src/webm.rs", ("job.batch_size()",)),
    )
    for export_path, replacements in export_paths:
        source = export_path.read_text(encoding="utf-8")
        old = "let batch = batch_size();"
        count = source.count(old)
        if count == 0:
            if "let batch = cx.batch_size();" in source or "let batch = job.batch_size();" in source:
                continue
            raise SystemExit(f"Could not find export batch-size call in {export_path.name}.")
        if export_path.name == "lib.rs":
            if count != 2:
                raise SystemExit(f"Expected two native export batch sites in lib.rs, found {count}.")
            source = source.replace(old, "let batch = cx.batch_size();", 1)
            source = source.replace(old, "let batch = job.batch_size();", 1)
        else:
            if count != 1:
                raise SystemExit(f"Expected one native export batch site in {export_path.name}, found {count}.")
            source = source.replace(old, "let batch = job.batch_size();", 1)
        export_path.write_text(source, encoding="utf-8")

    # The previous final gate incorrectly rejected renderQueue.setOutput. The quick-export
    # dialog must set the queue item's output path: Android's save hook returns a private
    # staging file, and MediaStore publication copies that completed queue output to Gallery.
    verifier_path = Path(__file__).with_name("verify_android_source_patches.py")
    verifier = verifier_path.read_text(encoding="utf-8")
    old_gate = """    if "effectcraft_android_video_staging_path" in quick_export or '"renderQueue.setOutput"' in quick_export:
        raise SystemExit("Quick video export must use the Render Queue's resolved output path without a staging override.")
    if "EFFECTCRAFT_ANDROID_EXPORT_START_PANIC_GUARD_V1" not in quick_export:
        raise SystemExit("Synchronous Render Queue startup must remain panic guarded.")
    print("Verified video export writes directly through the Render Queue; Gallery publication is only post-render.")"""
    new_gate = """    if "effectcraft_android_video_staging_path" in quick_export:
        raise SystemExit("Quick video export must not use the obsolete staging-path override.")
    required_output_route = (
        'crate::android_gallery::staging_path(&default_output)',
        '"renderQueue.setOutput"',
        'json!({"item": item_id, "path": output_path})',
        '"renderQueue.render"',
        "EFFECTCRAFT_ANDROID_EXPORT_START_PANIC_GUARD_V1",
    )
    missing_output_route = [token for token in required_output_route if token not in quick_export]
    if missing_output_route:
        raise SystemExit("Quick video export is not fully connected to the native Render Queue output path: " + "; ".join(missing_output_route))

    builder_root = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    build_common = (builder_root / "lib/build-common.sh").read_text(encoding="utf-8")
    for token in ("fn saf_video_gallery_stage_path(", "effectcraft_ui_egui::android_gallery::staging_path(name)", "saf_video_gallery_stage_path(&default)"):
        if token not in build_common:
            raise SystemExit("Android video output is not routed through its private Gallery staging file: " + token)

    saf_activity = (builder_root / "templates/android/SafActivity.java").read_text(encoding="utf-8")
    gallery_required = (
        "EFFECTCRAFT_ANDROID_MEDIASTORE_GALLERY_V1",
        "createGalleryStagingPath",
        "startGalleryPublish",
        "pollGalleryPublish",
        "MediaStore.Video.Media.RELATIVE_PATH",
        "MediaStore.Video.Media.IS_PENDING",
        'Environment.DIRECTORY_DCIM + "/EffectCraft"',
        'galleryPublishResults.put(requestId, "OK")',
    )
    missing_gallery = [token for token in gallery_required if token not in saf_activity]
    if missing_gallery:
        raise SystemExit("Android MediaStore publication is incomplete: " + "; ".join(missing_gallery))

    for token in ("EFFECTCRAFT_ANDROID_GALLERY_SUCCESS_POPUP_V1", "android_gallery::start_publish", "android_gallery::poll_publish"):
        if token not in header_source:
            raise SystemExit("The export completion UI is not waiting for confirmed Gallery publication: " + token)
    print("Verified Render Queue output assignment, private video staging, MediaStore publication, and success-after-confirmation.")"""
    if new_gate not in verifier:
        if old_gate not in verifier:
            raise SystemExit("Could not locate the contradictory quick-export validation gate.")
        verifier = verifier.replace(old_gate, new_gate, 1)

    old_required = '''        "android_export_defaults_to_one_in_flight_frame_without_overriding_explicit_settings",
    )'''
    new_required = '''        "android_export_defaults_to_one_in_flight_frame_without_overriding_explicit_settings",
        "EFFECTCRAFT_ANDROID_AI_EXPORT_CHECKPOINT_V1",
        "pub(crate) fn ai_batch_size(default: u64, android: bool, ai_enabled: bool) -> u64",
        "android_ai_export_checks_cancellation_after_each_processed_frame",
        "self.job.output.ai_frame_interpolation || self.job.output.ai_upscale",
    )'''
    if new_required not in verifier:
        if old_required not in verifier:
            raise SystemExit("Could not extend the final gate with AI export checkpoint assertions.")
        verifier = verifier.replace(old_required, new_required, 1)

    verifier_path.write_text(verifier, encoding="utf-8")
    print("Reworked Android export checkpoints: AI progress/cancel is observed per output frame.")
    print("Corrected the final source gate to validate the real staging -> Render Queue -> MediaStore path.")


if __name__ == "__main__":
    main()
