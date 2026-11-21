#!/usr/bin/env python3
"""Add a real, user-triggered Android Windows runtime install and AEX smoke-test UI."""
from __future__ import annotations
import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_WINDOWS_RUNTIME_SETUP_UI_V2"

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
        "    Confirm { path: String, native_count: usize, mode: MigrationMode },\n",
        "    Confirm { path: String, native_count: usize, mode: MigrationMode },\n"
        "    // " + MARKER + "\n"
        "    RuntimeSetup { path: String, native_count: usize, mode: MigrationMode, request_id: String, status: String },\n",
        "runtime setup state",
    )
    source = once(
        source,
        "        Start(String, MigrationMode),\n        Cancel,\n",
        "        Start(String, MigrationMode),\n"
        "        PrepareRuntime(String, usize, MigrationMode),\n"
        "        TestAexPlugin(String),\n"
        "        BackToConfirm(String, usize, MigrationMode),\n"
        "        Cancel,\n",
        "runtime UI actions",
    )
    source = once(
        source,
        "                let mut start = false;\n                let mut cancel = false;\n",
        "                let mut start = false;\n"
        "                let mut cancel = false;\n"
        "                let mut prepare_runtime = false;\n",
        "runtime setup button state",
    )
    source = once(
        source,
        """                        ui.horizontal(|ui| {
                            if ui.button("取消").clicked() { cancel = true; }
                            if ui.button("按此方式开始").clicked() { start = true; }
                        });
""",
        """                        ui.horizontal(|ui| {
                            if ui.button("取消").clicked() { cancel = true; }
                            if ui.button("按此方式开始").clicked() { start = true; }
                        });
                        ui.add_space(6.0);
                        if ui.button("安装 Windows 兼容运行环境").clicked() {
                            prepare_runtime = true;
                        }
                        ui.small("首次安装会准备 Wine/Proton、Box64/BOX32、源码构建 FEXCore，以及设备架构适用时的 Box86 和 QEMU Linux-user；运行组件保存在 Ae 私有目录。");
""",
        "runtime setup button",
    )
    source = once(
        source,
        '                if start { action = Some(Action::Start(path.clone(), *mode)); }\n                else if cancel || !open { action = Some(Action::Cancel); }',
        '                if start { action = Some(Action::Start(path.clone(), *mode)); }\n'
        '                else if prepare_runtime { action = Some(Action::PrepareRuntime(path.clone(), *native_count, *mode)); }\n'
        '                else if cancel || !open { action = Some(Action::Cancel); }',
        "runtime setup action dispatch from confirmation",
    )

    poll_anchor = "    let mut action: Option<Action> = None;\n\n    if let Some(state) = app.plugin_import.as_mut() {\n"
    poll_code = """    let mut action: Option<Action> = None;

    // Poll the real Java-side runtime installer/host worker without blocking the egui frame.
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
    source = once(source, poll_anchor, poll_code, "Windows runtime status polling")

    running_anchor = "            ImportState::Running { path, mode, progress, receiver } => {\n"
    runtime_arm = """            ImportState::RuntimeSetup { path, native_count, mode, request_id: _, status } => {
                let mut open = true;
                let mut test_plugin = false;
                let mut back = false;
                let ready = status.starts_with("READY:");
                let finished = ready || status.starts_with("EXIT:") || status.starts_with("ERROR:");
                let screen = ctx.content_rect();
                egui::Window::new("Windows x86/x64 兼容运行环境")
                    .id(Id::new("effectcraft-windows-runtime-setup"))
                    .order(Order::Foreground)
                    .movable(true)
                    .collapsible(false)
                    .resizable(false)
                    .default_width(350.0)
                    .default_pos(pos2(screen.center().x - 175.0, screen.center().y - 100.0))
                    .open(&mut open)
                    .show(ctx, |ui| {
                        if !finished {
                            ui.horizontal(|ui| {
                                ui.spinner();
                                ui.label("正在安装或测试 Windows 兼容运行环境…");
                            });
                        } else if ready {
                            ui.heading("Windows 兼容运行环境已安装");
                        } else if status.starts_with("EXIT:0") {
                            ui.heading("AEX 样本运行与帧渲染通过");
                        } else {
                            ui.heading("运行环境或 AEX 测试未通过");
                        }
                        ui.add_space(4.0);
                        egui::ScrollArea::vertical().max_height(180.0).show(ui, |ui| {
                            ui.label(status.as_str());
                        });
                        if ready {
                            ui.add_space(6.0);
                            ui.label(format!("当前导入包检测到 {native_count} 个原生插件文件。"));
                            ui.small("测试会提取首个 AEX 文件，在独立 Wine/Proton 宿主进程中读取参数并执行一次 CPU PNG 帧渲染。通过只证明该样本测试通过。");
                            if ui.button("测试当前导入包中的第一个 AEX 插件").clicked() {
                                test_plugin = true;
                            }
                        }
                        ui.add_space(8.0);
                        if ui.button("返回移植方式选择").clicked() { back = true; }
                    });
                if test_plugin {
                    action = Some(Action::TestAexPlugin(path.clone()));
                } else if back || !open {
                    action = Some(Action::BackToConfirm(path.clone(), *native_count, *mode));
                } else if !finished {
                    ctx.request_repaint_after(Duration::from_millis(250));
                }
            }
"""
    source = once(source, running_anchor, runtime_arm + running_anchor, "Windows runtime setup window")

    dispatch_anchor = """        Some(Action::Start(path, mode)) => {
            app.ui.status = "已开始扫描电脑插件；正在识别架构和可用路线…".into();
            app.plugin_import = Some(spawn_scan(path, mode));
        }
"""
    dispatch_replacement = """        Some(Action::PrepareRuntime(path, native_count, mode)) => {
            match crate::start_windows_compat_runtime_install() {
                Ok(request_id) => {
                    app.ui.status = "正在安装 Android ARM64 Windows 兼容运行环境…".into();
                    app.plugin_import = Some(ImportState::RuntimeSetup {
                        path, native_count, mode, request_id, status: "INSTALLING".into(),
                    });
                }
                Err(error) => {
                    app.plugin_import = Some(ImportState::RuntimeSetup {
                        path, native_count, mode, request_id: String::new(),
                        status: format!("ERROR: {error}"),
                    });
                }
            }
        }
        Some(Action::TestAexPlugin(path)) => {
            match crate::start_windows_compat_aex_test(&path) {
                Ok(request_id) => {
                    if let Some(ImportState::RuntimeSetup { request_id: current, status, .. }) =
                        app.plugin_import.as_mut()
                    {
                        *current = request_id;
                        *status = "RUNNING: 正在提取并启动匹配架构的 AEX 宿主…".into();
                    }
                }
                Err(error) => {
                    if let Some(ImportState::RuntimeSetup { status, .. }) = app.plugin_import.as_mut() {
                        *status = format!("ERROR: {error}");
                    }
                }
            }
        }
        Some(Action::BackToConfirm(path, native_count, mode)) => {
            app.plugin_import = Some(ImportState::Confirm { path, native_count, mode });
        }
        Some(Action::Start(path, mode)) => {
            app.ui.status = "已开始扫描电脑插件；正在识别架构和可用路线…".into();
            app.plugin_import = Some(spawn_scan(path, mode));
        }
"""
    source = once(source, dispatch_anchor, dispatch_replacement, "Windows runtime action handling")

    # The migration route report now refers to the real runtime manager and says exactly what was exercised.
    source = source.replace(
        'ui.small("Android 已接入 Bionic + Wine/Proton、Box64/BOX32 和源码构建 FEXCore；Box86 ARMv7 仅在可选构建成功且设备有 32 位 linker 时安装，仍需要 i386 Wine。QEMU 已加入独立 Linux-user 包构建，但需 x86-64 Wine/glibc rootfs，不能直接加载 Windows PE。");',
        'ui.small("Android 已接入 Bionic + Wine/Proton、Box64/BOX32 与 ARM64EC FEXCore 的安装和隔离 AEX 样本测试入口；独立 Box86/QEMU 路线仍为候选，不会冒充已通过测试。");'
    )
    source = source.replace(
        'lines.push("注意：Box64/BOX32 与源码构建的 ARM64EC/WoW64 FEXCore 已进入主 APK 运行时安装链；Box86 需要 32 位 Bionic linker 与 i386 Wine，QEMU 需要 x86-64 Wine/glibc rootfs，均不直接加载 Windows PE。暴力二进制模式会生成静态 x86/x64 指令与 CFG JSON IR；这不是自动 ARM64 语义重编译。".into());',
        'lines.push("注意：Android 运行时现可安装 Wine/Proton、Box64/BOX32 与 ARM64EC FEXCore，并对单个 AEX 样本执行隔离加载和 CPU 帧渲染测试；独立 Box86/QEMU 与自动二进制重建仍需单独验证。".into());'
    )
    source = source.replace(
        'Self::ManualBackend => "分析后展示该插件全部适用的转译后端、所需运行环境和实测状态，供你比较与指定；目前尚未集成可执行后端，指定只记录选择意向，不会谎称已经转译。",',
        'Self::ManualBackend => "分析后展示适用候选、所需运行环境和实测状态；Box64/FEXCore 进入主运行时链，Box86 受 32 位系统与 i386 Wine 限制，QEMU 需要 x86-64 Wine/glibc rootfs。未满足前置条件或未通过 AEX 加载/渲染测试的路线只标记为候选，不会自动执行或谎称成功。",'
    )
    source = source.replace(
        'app.ui.status = "已记录各插件的路线选择；尚未接入的转译执行器不会被标记为已完成。".into();',
        'app.ui.status = "已记录各插件路线；只有隔离 AEX 样本完成加载、帧渲染和正常退出才会显示测试通过。".into();'
    )

    path.write_text(source, encoding="utf-8")
    print("Added user-triggered Wine/Proton + Box64/FEXCore runtime installation and isolated AEX smoke-test UI.")

if __name__ == "__main__":
    main()
