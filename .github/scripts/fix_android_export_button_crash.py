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

    # Do not cross JNI while processing the Export button. Use the same app-private
    # temporary directory already used by the Android SAF video-save bridge.
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
}'''\n\n    # Convert synchronous engine panics into ordinary UI errors.\n    guard = r'''/// EFFECTCRAFT_ANDROID_EXPORT_COMMAND_PANIC_GUARD_V1
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
    if "std::env::temp_dir()" in header:
        raise SystemExit("Export staging must use Android's app-private cache bridge, not /data/local/tmp.")

    header_path.write_text(header, encoding="utf-8")
    print("Guarded export queue setup and staged videos in Android's app-private cache.")


if __name__ == "__main__":
    main()
