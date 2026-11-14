#!/usr/bin/env python3
"""Show exactly four project-format export buttons and one generic share action."""
from __future__ import annotations

import os
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    header = root / "crates/ui-egui/src/header.rs"
    source = header.read_text(encoding="utf-8")

    old_state = """    let mut save_project_copy = false;
    let mut collect_project_files = false;
    let mut export_alight_motion = false;
    let mut export_nodevideo = false;
    let mut export_capcut = false;"""
    new_state = """    let mut export_aep = false;
    let mut export_alight_motion = false;
    let mut export_nodevideo = false;
    let mut export_capcut = false;
    let mut share_project_package = false;"""
    source = replace_once(source, old_state, new_state, "project export action state")

    old_buttons = """            ui.label("工程分享");
            if ui.button("完整导出工程（包含素材）").clicked() {
                collect_project_files = true;
            }
            if ui.button("只导出工程文件（.ecproj）").clicked() {
                save_project_copy = true;
            }
            if ui.button("导出 AM 工程（.xml）").clicked() {
                export_alight_motion = true;
            }
            if ui.button("导出 NodeVideo 工程包（.zip）").clicked() {
                export_nodevideo = true;
            }
            if ui.button("导出 CapCut 桌面工程包（.zip）").clicked() {
                export_capcut = true;
            }
            ui.small("QQ 分享建议：完整导出后压缩整个文件夹；接收方解压后导入其中的 .ecproj。");"""
    new_buttons = """            ui.label("工程导出");
            if ui.button("Ae 工程导出（.aep）").clicked() {
                export_aep = true;
            }
            if ui.button("AM 工程导出（.xml）").clicked() {
                export_alight_motion = true;
            }
            if ui.button("NV 工程导出（.zip）").clicked() {
                export_nodevideo = true;
            }
            if ui.button("CapCut 工程导出（.zip）").clicked() {
                export_capcut = true;
            }
            ui.small("以上四个按钮分别生成对应软件的工程格式；目标软件不支持的项目内容会在导出报告中说明。");
            if ui.button("打包并分享到QQ").clicked() {
                share_project_package = true;
            }
            ui.small("自动收集工程文件和引用素材，优先发送到QQ；未安装QQ时提供系统分享方式。");"""
    source = replace_once(source, old_buttons, new_buttons, "four project export buttons and share action")

    old_project_actions = """    if collect_project_files {
        match crate::menus::invoke(app, ui.ctx(), "file.collectFiles", json!({})) {
            Ok(_) => open = false,
            Err(error) => app.ui.status = error,
        }
    }
    if save_project_copy {
        match crate::menus::invoke(app, ui.ctx(), "file.saveCopy", json!({})) {
            Ok(_) => open = false,
            Err(error) => app.ui.status = error,
        }
    }
"""
    new_project_actions = """    if share_project_package {
        match crate::menus::invoke(app, ui.ctx(), "file.collectFiles", json!({})) {
            Ok(export) => {
                if let Some(project_path) = export.get("project").and_then(|value| value.as_str()) {
                    match crate::android_gallery::share_project_package(project_path) {
                        Ok(()) => {
                            app.ui.status = "工程及引用素材正在打包；随后选择手机中的分享应用。".into();
                            open = false;
                        }
                        Err(error) => app.ui.status = format!("工程分享失败：{error}"),
                    }
                } else {
                    app.ui.status = "工程已收集，但没有取得工程文件路径，无法分享。".into();
                }
            }
            Err(error) => app.ui.status = format!("收集工程素材失败：{error}"),
        }
    }
"""
    source = replace_once(source, old_project_actions, new_project_actions, "generic project share action")

    aep_anchor = """    if export_alight_motion {
        match crate::menus::invoke(app, ui.ctx(), "file.exportAlightMotion", json!({})) {"""
    aep_addition = """    if export_aep {
        match crate::menus::invoke(app, ui.ctx(), "file.exportAep", json!({})) {
            Ok(_) => open = false,
            Err(error) => app.ui.status = error,
        }
    }
"""
    source = replace_once(source, aep_anchor, aep_addition + aep_anchor, "AE project export command dispatch")

    if source.count('ui.button("Ae 工程导出（.aep）")') != 1:
        raise SystemExit("Ae project export button was not installed exactly once")
    for label in ["AM 工程导出（.xml）", "NV 工程导出（.zip）", "CapCut 工程导出（.zip）"]:
        if source.count(f'ui.button("{label}")') != 1:
            raise SystemExit(f"Expected exactly one export button: {label}")
    if "file.exportAep" not in source or "share_project_package(project_path)" not in source:
        raise SystemExit("The AE export or project share action is not connected")

    header.write_text(source, encoding="utf-8")
    print("Installed four separate project export controls: AE, AM, NV and CapCut.")
    print("Added a separate generic package-and-share action through the Android Sharesheet.")


if __name__ == "__main__":
    main()
