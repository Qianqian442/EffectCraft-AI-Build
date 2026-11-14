#!/usr/bin/env python3
"""Configure five project exporters and reveal QQ sharing only after a successful export."""
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
    let mut export_mobile_effectcraft_project = false;
    let mut export_alight_motion = false;
    let mut export_nodevideo = false;
    let mut export_capcut = false;
    let mut share_exported_project: Option<String> = None;"""
    source = replace_once(source, old_state, new_state, "project export action state")

    source = replace_once(
        source,
        '    let comp_rate = app.session.active_comp().map(|c| c.frame_rate.as_f64());\n',
        '    let comp_rate = app.session.active_comp().map(|c| c.frame_rate.as_f64());\n'
        '    let export_path_id = egui::Id::new("effectcraft-last-successful-project-export");\n'
        '    let last_exported_path: Option<String> = ui.ctx().data(|d| d.get_temp(export_path_id));\n',
        "last successfully exported project path state",
    )

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
            if ui.button("Ae 手机版完整工程导出（含素材）").clicked() {
                export_mobile_effectcraft_project = true;
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
            ui.small("电脑版 After Effects 使用 .aep；手机版完整工程会收集 .ecproj、图片、视频、音频和序列素材。");
            ui.small("完整工程分享时自动压缩成 ZIP；接收方在文件→导入中选择 ZIP 即可导入。");
            ui.small("AM、NV、CapCut 分别导出；不支持转换的项目内容会在导出报告中说明。");
            if let Some(path) = last_exported_path.as_ref() {
                ui.separator();
                ui.label("工程已成功导出");
                if ui.button("分享到QQ").clicked() {
                    share_exported_project = Some(path.clone());
                }
            }"""
    source = replace_once(source, old_buttons, new_buttons, "four project export buttons and conditional QQ share button")

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
    new_project_actions = """    if let Some(export_path) = share_exported_project.as_deref() {
        match crate::android_gallery::share_exported_project(export_path) {
            Ok(()) => app.ui.status = "正在将刚刚导出的工程文件发送到 QQ；如不可用会打开系统分享面板。".into(),
            Err(error) => app.ui.status = format!("分享到 QQ 失败：{error}"),
        }
    }
"""
    source = replace_once(source, old_project_actions, new_project_actions, "share the exact exported project file")

    # Remove stale successful-export state before starting any new format export. The
    # engine only sets it again after the chosen save path has actually been written.
    aep_anchor = """    if export_alight_motion {
        match crate::menus::invoke(app, ui.ctx(), "file.exportAlightMotion", json!({})) {"""
    aep_addition = """    if export_aep {
        ui.ctx().data_mut(|d| { d.remove_temp::<String>(export_path_id); });
        match crate::menus::invoke(app, ui.ctx(), "file.exportAep", json!({})) {
            Ok(_) => {},
            Err(error) => app.ui.status = error,
        }
    }
"""
    mobile_addition = """    if export_mobile_effectcraft_project {
        ui.ctx().data_mut(|d| { d.remove_temp::<String>(export_path_id); });
        match crate::menus::invoke(app, ui.ctx(), "file.collectFiles", json!({})) {
            Ok(_) => {},
            Err(error) => app.ui.status = error,
        }
    }
"""
    source = replace_once(source, aep_anchor, aep_addition + mobile_addition + aep_anchor, "desktop and mobile Ae project export command dispatch")

    for variable, command, label in [
        ("export_alight_motion", "file.exportAlightMotion", "AM"),
        ("export_nodevideo", "file.exportNodeVideo", "NV"),
        ("export_capcut", "file.exportCapCut", "CapCut"),
    ]:
        old = f"""    if {variable} {{
        match crate::menus::invoke(app, ui.ctx(), "{command}", json!({{}})) {{
            Ok(_) => open = false,
            Err(error) => app.ui.status = error,
        }}
    }}"""
        new = f"""    if {variable} {{
        ui.ctx().data_mut(|d| {{ d.remove_temp::<String>(export_path_id); }});
        match crate::menus::invoke(app, ui.ctx(), "{command}", json!({{}})) {{
            Ok(_) => {{}},
            Err(error) => app.ui.status = error,
        }}
    }}"""
        source = replace_once(source, old, new, f"{label} export asynchronous save action")

    # The Android picker answers asynchronously, so the engine emits this frontend event
    # only after its export function successfully writes the selected destination.
    frontend = root / "crates/ui-egui/src/menus/frontend.rs"
    front_source = frontend.read_text(encoding="utf-8")
    front_source = replace_once(
        front_source,
        '        "mediaBrowser.copySourcePath" => {\n',
        """        "effectcraft.projectExported" => {
            let path = p.get("path").and_then(Value::as_str)
                .filter(|path| !path.trim().is_empty())
                .ok_or("project export notification has no output path")?;
            let export_path_id = egui::Id::new("effectcraft-last-successful-project-export");
            ctx.data_mut(|data| data.insert_temp(export_path_id, path.to_string()));
            app.ui.status = format!("工程已成功导出：{}", std::path::Path::new(path).file_name().and_then(|name| name.to_str()).unwrap_or(path));
            ctx.request_repaint();
            Value::Null
        }
        "mediaBrowser.copySourcePath" => {
""",
        "project export success event handler",
    )
    front_source = replace_once(
        front_source,
        '        "file.exportLottie" => ("path", Ask::Save("Animation.json".into())),\n',
        '        "file.exportLottie" => ("path", Ask::Save("Animation.json".into())),\n'
        '        "file.exportAep" => ("path", Ask::Save("Project.aep".into())),\n'
        '        "file.exportAlightMotion" => ("path", Ask::Save("AlightMotion.xml".into())),\n'
        '        "file.exportNodeVideo" => ("path", Ask::Save("NodeVideo.zip".into())),\n'
        '        "file.exportCapCut" => ("path", Ask::Save("CapCut.zip".into())),\n',
        "save pickers for the four project export formats",
    )
    frontend.write_text(front_source, encoding="utf-8")

    if source.count('ui.button("Ae 工程导出（.aep）")') != 1:
        raise SystemExit("Desktop Ae project export button was not installed exactly once")
    if source.count('ui.button("Ae 手机版完整工程导出（含素材）")') != 1:
        raise SystemExit("Complete mobile EffectCraft project export button was not installed exactly once")
    for label in ["AM 工程导出（.xml）", "NV 工程导出（.zip）", "CapCut 工程导出（.zip）"]:
        if source.count(f'ui.button("{label}")') != 1:
            raise SystemExit(f"Expected exactly one export button: {label}")
    if 'ui.button("分享到QQ")' not in source or "share_exported_project(export_path)" not in source:
        raise SystemExit("Conditional QQ share action is not connected")
    for command in ["file.exportAep", "file.exportAlightMotion", "file.exportNodeVideo", "file.exportCapCut"]:
        if command not in front_source:
            raise SystemExit(f"Missing save picker for {command}")
    if "effectcraft.projectExported" not in front_source:
        raise SystemExit("Project export completion event handler is missing")

    # Collect Files copies all referenced source footage into (Footage), rewrites paths
    # relative to the exported .ecproj, and returns only after the collection has completed.
    project_engine = root / "crates/engine/src/cmd/file_more.rs"
    engine_source = project_engine.read_text(encoding="utf-8")
    engine_source = replace_once(
        engine_source,
        "    let mut plan: Vec<(ItemId, Vec<(String, String)>)> = vec![];",
        "    let mut errors: Vec<String> = Vec::new();\n    let mut plan: Vec<(ItemId, Vec<(String, String, String)>)> = vec![];",
        "complete mobile project collection plan",
    )
    engine_source = replace_once(
        engine_source,
        """        if f.path.is_empty() {
            continue;
        }""",
        """        if f.missing || f.path.is_empty() {
            errors.push(format!("{}：源素材缺失，无法制作完整工程包", it.name));
            continue;
        }""",
        "refuse missing source footage in a full mobile project package",
    )
    engine_source = replace_once(
        engine_source,
        '            let dst = format!("{folder}/(Footage)/{name}");',
        '            let relative = format!("(Footage)/{name}");\n            let dst = format!("{folder}/{relative}");',
        "relative media paths for portable mobile project packages",
    )
    engine_source = replace_once(
        engine_source,
        "            pairs.push((src.clone(), dst));",
        "            pairs.push((src.clone(), dst, relative));",
        "store relative and physical media paths separately",
    )
    engine_source = replace_once(
        engine_source,
        "        for (src, dst) in &pairs {",
        "        for (src, dst, relative) in &pairs {",
        "collect all source media into the package folder",
    )
    engine_source = replace_once(
        engine_source,
        "            new_paths.push(dst.clone());",
        "            new_paths.push(relative.clone());",
        "write portable relative source-media paths into .ecproj",
    )
    engine_source = replace_once(
        engine_source,
        "    let mut copied = 0;\n    let mut errors = vec![];\n    for (id, pairs) in plan {",
        "    let mut copied = 0;\n    for (id, pairs) in plan {",
        "reuse the preflight error accumulator",
    )
    engine_source = replace_once(
        engine_source,
        '    s.write_output_with(&protected, &out, proj.to_json().as_bytes())?;',
        '''    if !errors.is_empty() {
        return Err(EngineError::Other(format!(
            "工程素材收集不完整，未生成可分享的完整工程包：{}",
            errors.join("；")
        )));
    }
    s.write_output_with(&protected, &out, proj.to_json().as_bytes())?;
    s.events.push(crate::Event::Frontend {
        command: "effectcraft.projectExported".into(),
        params: json!({"path": out, "format": "Ae 手机版完整工程（含素材）"}),
    });''',
        "only reveal QQ sharing after every project asset has been saved",
    )
    if '"file.collectFiles" => ("folder", Ask::Folder),' not in front_source:
        raise SystemExit("The complete mobile project export must use the Android folder picker")
    if "effectcraft.projectExported" not in engine_source:
        raise SystemExit("The complete mobile project export success notification is missing")
    if "工程素材收集不完整" not in engine_source or "new_paths.push(relative.clone())" not in engine_source:
        raise SystemExit("Full-project packaging must refuse missing media and use portable relative footage paths")

    header.write_text(source, encoding="utf-8")
    print("Installed five project export controls: desktop Ae, complete mobile EffectCraft project, AM, NV and CapCut.")
    print("The mobile export collects image, video, audio and sequence footage, and saves portable relative paths.")
    print("QQ sharing is revealed only after the complete project folder is written successfully.")


if __name__ == "__main__":
    main()
