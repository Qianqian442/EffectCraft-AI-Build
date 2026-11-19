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

    # Use Android's app-private cache bridge; convert JNI failures into a visible error.
    stage_pattern = re.compile(
        r"(?s)/// EFFECTCRAFT_ANDROID_DIRECT_GALLERY_OUTPUT_V1_HELPER.*?"
        r"fn effectcraft_android_video_staging_path\(default_output: &str\) -> Result<String, String> \{\n.*?\n\}"
    )
    stage_helper = r'''/// EFFECTCRAFT_ANDROID_DIRECT_GALLERY_OUTPUT_V1_HELPER
/// Ask Android for its real app-private cache path. JNI failures become visible errors,
/// never a panic during export-button handling (the Activity is kept intact from R8).
fn effectcraft_android_video_staging_path(default_output: &str) -> Result<String, String> {
    let name = std::path::Path::new(default_output)
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.trim().is_empty())
        .unwrap_or("Ae.mp4");
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        crate::android_gallery::staging_path(name)
    }))
    .unwrap_or_else(|_| Err("Android 视频暂存接口发生内部异常，已阻止编辑器崩溃。".to_string()))
}'''

    # Replace the unguarded staging helper installed by patch_export_dialog.py.
    # The previous version declared this regex and replacement but never applied them,
    # leaving JNI exceptions outside the panic guard on the Export-button hot path.
    if stage_helper.strip() not in header:
        stage_matches = list(stage_pattern.finditer(header))
        if len(stage_matches) != 1:
            raise SystemExit(
                "Expected exactly one Android video staging helper to harden; "
                f"found {len(stage_matches)}."
            )
        header = stage_pattern.sub(stage_helper, header, count=1)

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
    if output_count != 1 and 'effectcraft_run_export_command(app, &ctx, "renderQueue.setOutput",' not in header:
        raise SystemExit("Export button renderQueue.setOutput call was not guarded.")

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
        "EFFECTCRAFT_ANDROID_DIRECT_GALLERY_OUTPUT_V1_HELPER",
        "crate::android_gallery::staging_path(name)",
        "catch_unwind",
        "EFFECTCRAFT_ANDROID_EXPORT_COMMAND_PANIC_GUARD_V1",
        'match effectcraft_run_export_command(app, &ctx, "renderQueue.add", params) {',
        'effectcraft_run_export_command(app, &ctx, "renderQueue.setOutput",',
        'effectcraft_run_export_command(app, &ctx, "renderQueue.setRender",',
    )
    missing = [item for item in required if item not in header]
    if missing:
        raise SystemExit("Export crash guard incomplete: " + "; ".join(missing))
    stage_start = header.find("fn effectcraft_android_video_staging_path(")
    stage_end = header.find("\n}", stage_start)
    stage_source = header[stage_start:stage_end] if stage_start >= 0 and stage_end >= 0 else ""
    if "std::env::temp_dir()" in stage_source:
        raise SystemExit("Export staging must use Android's app-private cache bridge, not /data/local/tmp.")


    # Prevent the Android render worker from starving the UI thread. This is a
    # scheduling safeguard, not a render-feature or frame-rate cap.
    render_queue_path = root / "crates/engine/src/render_queue.rs"
    render_queue = render_queue_path.read_text(encoding="utf-8")
    priority_helper = r'''/// EFFECTCRAFT_ANDROID_RENDER_WORKER_BACKGROUND_PRIORITY_V1
/// Let Android keep the editor/UI responsive while a CPU-heavy export is running.
#[cfg(target_os = "android")]
fn effectcraft_set_android_render_thread_priority() {
    unsafe extern "C" {
        fn gettid() -> i32;
        fn setpriority(which: i32, who: u32, priority: i32) -> i32;
    }
    let tid = unsafe { gettid() };
    if tid > 0 {
        // PRIO_PROCESS=0; nice=8 yields to the interactive editor without suspending export.
        let result = unsafe { setpriority(0, tid as u32, 8) };
        if result != 0 {
            log::warn!("Could not lower Android render worker priority for tid={tid}.");
        }
    }
}

#[cfg(not(target_os = "android"))]
fn effectcraft_set_android_render_thread_priority() {}
'''
    priority_marker = "EFFECTCRAFT_ANDROID_RENDER_WORKER_BACKGROUND_PRIORITY_V1"
    if priority_marker not in render_queue:
        render_anchor = "pub struct RenderJob {"
        if render_queue.count(render_anchor) != 1:
            raise SystemExit("Expected exactly one RenderJob declaration for Android worker priority patch.")
        render_queue = render_queue.replace(render_anchor, priority_helper + "\n" + render_anchor, 1)
    thread_anchor = '.name("render-queue".into())\n                .spawn(move || {'
    thread_call = thread_anchor + "\n                    effectcraft_set_android_render_thread_priority();"
    if "effectcraft_set_android_render_thread_priority();" not in render_queue:
        if render_queue.count(thread_anchor) != 1:
            raise SystemExit("Expected exactly one native render worker thread spawn.")
        render_queue = render_queue.replace(thread_anchor, thread_call, 1)
    if priority_marker not in render_queue or "effectcraft_set_android_render_thread_priority();" not in render_queue:
        raise SystemExit("Android render worker priority patch is incomplete.")

    render_queue_path.write_text(render_queue, encoding="utf-8")

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
    print("Guarded export setup, lowered Android render-worker scheduling priority, increased export RAM preflight, and staged videos in app-private cache.")


if __name__ == "__main__":
    main()
