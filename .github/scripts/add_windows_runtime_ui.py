#!/usr/bin/env python3
"""Add an explicit, truthful Windows x86/x64 runtime preparation action to the AE import dialog."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_WINDOWS_RUNTIME_SETUP_UI_V1"


def once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/ui-egui/src/plugin_migration.rs"
    if not path.is_file():
        raise SystemExit("plugin_migration.rs must be generated before Windows runtime UI integration.")
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Windows runtime preparation UI already integrated.")
        return

    source = once(
        source,
        "    Confirm { path: String, native_count: usize },\n",
        "    Confirm { path: String, native_count: usize },\n"
        "    // " + MARKER + "\n"
        "    RuntimeSetup { path: String, native_count: usize, request_id: String, status: String },\n",
        "runtime setup state variant",
    )

    action_anchor = """        Start(String),
        Cancel,
"""
    action_replacement = """        Start(String),
        PrepareRuntime(String, usize),
        ReturnToConfirm(String, usize),
        Cancel,
"""
    source = once(source, action_anchor, action_replacement, "runtime UI actions")

    confirm_state_anchor = """                let mut start = false;
                let mut cancel = false;
"""
    confirm_state_replacement = """                let mut start = false;
                let mut cancel = false;
                let mut prepare_runtime = false;
"""
    source = once(source, confirm_state_anchor, confirm_state_replacement, "runtime prepare button state")

    button_anchor = """                        ui.horizontal(|ui| {
                            if ui.button("取消").clicked() { cancel = true; }
                            if ui.button("开始移植").clicked() { start = true; }
                        });
"""
    button_replacement = """                        ui.horizontal(|ui| {
                            if ui.button("取消").clicked() { cancel = true; }
                            if ui.button("开始移植").clicked() { start = true; }
                        });
                        ui.add_space(6.0);
                        if ui.button("准备 Windows x86/x64 兼容环境（实验）").clicked() {
                            prepare_runtime = true;
                        }
                        ui.small("此操作只安装 Windows 兼容运行环境；不代表当前 .aex 插件已经通过 Android 真机执行验证。");
"""
    source = once(source, button_anchor, button_replacement, "runtime prepare button")

    old_claim = '                        ui.label("点击开始后会扫描压缩包、检查安全性，并安装 EffectCraft 能兼容的模块或替代效果。无法兼容的原生插件会保留原件，不会伪装成已移植。 ");'
    new_claim = '                        ui.label("点击开始后会扫描压缩包、检查安全性，并安装当前 EffectCraft 能兼容的模块或替代效果。原生 .aex/.dll/.ofx 还需要通过 Windows 兼容运行环境逐项验证。");'
    source = once(source, old_claim, new_claim, "desktop plugin compatibility claim")

    confirm_action_anchor = """                if start { action = Some(Action::Start(path.clone())); }
                else if cancel || !open { action = Some(Action::Cancel); }
            }
            ImportState::Running"""
    confirm_action_replacement = """                if start { action = Some(Action::Start(path.clone())); }
                else if prepare_runtime { action = Some(Action::PrepareRuntime(path.clone(), *native_count)); }
                else if cancel || !open { action = Some(Action::Cancel); }
            }
            ImportState::RuntimeSetup { path, native_count, request_id, status } => {
                let mut open = true;
                let mut return_to_import = false;
                let ready = status.starts_with("READY:");
                let failed = status.starts_with("ERROR:");
                let screen = ctx.content_rect();
                egui::Window::new("Windows x86/x64 兼容运行环境")
                    .id(Id::new("effectcraft-windows-runtime-setup"))
                    .order(Order::Foreground)
                    .movable(true)
                    .collapsible(false)
                    .resizable(false)
                    .default_width(350.0)
                    .default_pos(pos2(screen.center().x - 175.0, screen.center().y - 95.0))
                    .open(&mut open)
                    .show(ctx, |ui| {
                        if !ready && !failed {
                            ui.horizontal(|ui| {
                                ui.spinner();
                                ui.label("正在准备 Android ARM64 Windows 兼容运行环境…");
                            });
                        } else if ready {
                            ui.heading("兼容运行环境已安装");
                        } else {
                            ui.heading("兼容运行环境安装失败");
                        }
                        ui.label(status.as_str());
                        if ready {
                            ui.add_space(6.0);
                            ui.small("注意：环境安装成功不等于当前 .aex/.dll 已经能够运行。仍需执行架构匹配、宿主加载、参数和渲染测试。");
                        }
                        ui.add_space(8.0);
                        if ui.button("返回插件移植").clicked() { return_to_import = true; }
                    });
                if return_to_import || !open {
                    action = Some(Action::ReturnToConfirm(path.clone(), *native_count));
                } else if !ready && !failed {
                    ctx.request_repaint_after(Duration::from_millis(250));
                }
                let _ = request_id;
            }
            ImportState::Running"""
    source = once(source, confirm_action_anchor, confirm_action_replacement, "runtime setup dialog")

    poll_anchor = """    let mut action: Option<Action> = None;

    if let Some(state) = app.plugin_import.as_mut() {
"""
    poll_replacement = """    let mut action: Option<Action> = None;

    // Poll the Java installer without blocking the egui frame thread.
    let runtime_request = match app.plugin_import.as_ref() {
        Some(ImportState::RuntimeSetup { request_id, .. }) if !request_id.is_empty() => Some(request_id.clone()),
        _ => None,
    };
    if let Some(request_id) = runtime_request {
        match crate::poll_windows_compat_runtime_install(&request_id) {
            Ok(Some(status)) => {
                if let Some(ImportState::RuntimeSetup { status: current, .. }) = app.plugin_import.as_mut() {
                    *current = status;
                }
            }
            Ok(None) => {}
            Err(error) => {
                if let Some(ImportState::RuntimeSetup { status, .. }) = app.plugin_import.as_mut() {
                    *status = format!("ERROR: {error}");
                }
            }
        }
    }

    if let Some(state) = app.plugin_import.as_mut() {
"""
    source = once(source, poll_anchor, poll_replacement, "runtime status polling")

    action_anchor = """    match action {
        Some(Action::Start(path)) => app.plugin_import = Some(spawn_scan(path)),
"""
    action_replacement = """    match action {
        Some(Action::PrepareRuntime(path, native_count)) => {
            match crate::start_windows_compat_runtime_install() {
                Ok(request_id) => {
                    app.plugin_import = Some(ImportState::RuntimeSetup {
                        path, native_count, request_id, status: "INSTALLING".into(),
                    });
                }
                Err(error) => {
                    app.plugin_import = Some(ImportState::RuntimeSetup {
                        path, native_count, request_id: String::new(),
                        status: format!("ERROR: {error}"),
                    });
                }
            }
        }
        Some(Action::ReturnToConfirm(path, native_count)) => {
            app.plugin_import = Some(ImportState::Confirm { path, native_count });
        }
        Some(Action::Start(path)) => app.plugin_import = Some(spawn_scan(path)),
"""
    source = once(source, action_anchor, action_replacement, "runtime UI action dispatch")

    path.write_text(source, encoding="utf-8")
    print("Added a draggable Windows compatibility runtime setup window to the existing AE migration flow.")
    print("The UI polls real installer state and explicitly warns that runtime installation is not proof of AEX execution.")


if __name__ == "__main__":
    main()
