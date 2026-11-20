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
    print("Guarded direct Render Queue video export; Android Gallery publication remains a post-render step.")


if __name__ == "__main__":
    main()
