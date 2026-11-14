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
            if ui.button("Ae 手机版工程导出（.ecproj）").clicked() {
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
            ui.small("电脑版 After Effects 使用 .aep；手机端保存为 EffectCraft .ecproj 工程，可由手机版 EffectCraft 再次打开。");
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
        match crate::menus::invoke(app, ui.ctx(), "file.saveCopy", json!({})) {
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
    if source.count('ui.button("Ae 手机版工程导出（.ecproj）")') != 1:
        raise SystemExit("Mobile EffectCraft project export button was not installed exactly once")
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

    # file.saveCopy is EffectCraft's native mobile project format (.ecproj). Emit the
    # same completion event only after write_output has successfully written the file.
    project_engine = root / "crates/engine/src/cmd/file_more.rs"
    engine_source = project_engine.read_text(encoding="utf-8")
    write_anchor = "    s.write_output(path, json.as_bytes())?;"
    write_event = write_anchor + '\n    s.events.push(crate::Event::Frontend { command: "effectcraft.projectExported".into(), params: json!({"path": path, "format": "Ae 手机版（EffectCraft）"}) });'
    if write_event not in engine_source:
        if engine_source.count(write_anchor) != 1:
            raise SystemExit("Could not safely hook the native .ecproj export completion event")
        engine_source = engine_source.replace(write_anchor, write_event, 1)
        project_engine.write_text(engine_source, encoding="utf-8")
    if "file.saveCopy" not in engine_source or "Ae 手机版（EffectCraft）" not in engine_source:
        raise SystemExit("The mobile EffectCraft project export success event is not connected")
    if '"file.saveCopy" => ("path", Ask::Save(project_as(" copy", "ecproj"))),' not in front_source:
        raise SystemExit("The native EffectCraft .ecproj save picker is missing")

    header.write_text(source, encoding="utf-8")
    print("Installed five project export controls: desktop Ae, mobile EffectCraft .ecproj, AM, NV and CapCut.")
    print("QQ sharing remains hidden until one of those five project exports succeeds.")
    print("The share action sends the exact last exported project file; it does not claim to bundle source media.")


if __name__ == "__main__":
    main()
