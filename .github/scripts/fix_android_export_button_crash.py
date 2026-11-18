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
/// Reserve a private app-cache path without crossing JNI while the Export button is handled.
fn effectcraft_android_video_staging_path(default_output: &str) -> Result<String, String> {
    let name = std::path::Path::new(default_output)
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.trim().is_empty())
        .unwrap_or("Ae.mp4");
    let directory = std::env::temp_dir().join("EffectCraftExports");
    std::fs::create_dir_all(&directory)
        .map_err(|error| format!("无法创建应用私有视频暂存目录：{error}"))?;
    let original = directory.join(name);
    if !original.exists() {
        return Ok(original.to_string_lossy().into_owned());
    }
    let stem = std::path::Path::new(name).file_stem()
        .and_then(|value| value.to_str()).unwrap_or("Ae");
    let extension = std::path::Path::new(name).extension()
        .and_then(|value| value.to_str()).unwrap_or("mp4");
    for suffix in 1..10000 {
        let candidate = directory.join(format!("{stem}_{suffix}.{extension}"));
        if !candidate.exists() {
            return Ok(candidate.to_string_lossy().into_owned());
        }
    }
    Err("视频暂存目录中同名文件过多，请清理后重试。".into())
}'''
    if "crate::android_gallery::staging_path(name)" in header:
        header, count = stage_pattern.subn(stage_helper, header)
        if count != 1:
            raise SystemExit(f"Could not replace JNI staging-path helper (matches={count}).")
    elif "fn effectcraft_android_video_staging_path(" not in header or "std::env::temp_dir()" not in header:
        raise SystemExit("Generated Android video staging helper is missing or unexpected.")

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
        "std::env::temp_dir()",
        "EFFECTCRAFT_ANDROID_EXPORT_COMMAND_PANIC_GUARD_V1",
        'match effectcraft_run_export_command(app, &ctx, "renderQueue.add", params) {',
        'effectcraft_run_export_command(app, &ctx, "renderQueue.setOutput",',
        'effectcraft_run_export_command(app, &ctx, "renderQueue.setRender",',
    )
    missing = [item for item in required if item not in header]
    if missing:
        raise SystemExit("Export crash guard incomplete: " + "; ".join(missing))
    if "crate::android_gallery::staging_path(name)" in header:
        raise SystemExit("Export button still uses JNI for the staging path.")

    header_path.write_text(header, encoding="utf-8")
    print("Guarded export queue setup and moved video staging to the app-private cache without JNI.")


if __name__ == "__main__":
    main()
