from pathlib import Path
import os
import re

root = Path(os.environ["EFFECTCRAFT_DIR"])
header_path = root / "crates/ui-egui/src/header.rs"
comp_settings_path = root / "crates/ui-egui/src/panels/comp_settings.rs"
render_queue_path = root / "crates/ui-egui/src/panels/render_queue.rs"
engine_render_queue_path = root / "crates/engine/src/cmd/render_queue.rs"
engine_file_more_path = root / "crates/engine/src/cmd/file_more.rs"
frontend_path = root / "crates/ui-egui/src/menus/frontend.rs"

for path in (header_path, comp_settings_path, render_queue_path, engine_render_queue_path, engine_file_more_path, frontend_path):
    if not path.is_file():
        raise SystemExit(f"Missing expected upstream source file: {path}")

# Guard the original project import/open pathways. This patch must not replace them.
frontend = frontend_path.read_text()
required_import_paths = [
    '"file.open" => ("path", Ask::OpenProject)',
    '"file.importProject" => ("path", Ask::Open(&["ecproj", "ecprojx"]))',
]
missing = [needle for needle in required_import_paths if needle not in frontend]
if missing:
    raise SystemExit("Original project import/open pathways changed; refusing to patch: " + ", ".join(missing))
if "file_dialog_async" not in frontend:
    raise SystemExit("The original asynchronous file-picker pathway is missing; refusing to patch.")

# Collect Files needs a folder URI, not a Save/Create-Document URI. The Android host maps
# FileDialog::Folder to ACTION_OPEN_DOCUMENT_TREE, then the engine makes a project folder.
old_collect = '"file.collectFiles" => ("folder", Ask::Save("Collected Files".into())),'
new_collect = '"file.collectFiles" => ("folder", Ask::Folder),'
if new_collect not in frontend:
    if old_collect not in frontend:
        raise SystemExit("Could not find the Collect Files folder-picker mapping.")
    frontend = frontend.replace(old_collect, new_collect, 1)
    frontend_path.write_text(frontend)

header = header_path.read_text()

# The Export toolbar button opens a centered setup dialog instead of jumping straight to the queue.
old_click = 'if export_response.clicked() {\n        app.show_panel(crate::dock::PanelKind::RenderQueue);\n    }'
new_click = 'if export_response.clicked() {\n        ui.ctx().data_mut(|d| d.insert_temp(egui::Id::new("effectcraft-export-dialog-open"), true));\n    }'
if new_click not in header:
    if old_click not in header:
        raise SystemExit("Could not find the existing Export button click handler.")
    header = header.replace(old_click, new_click, 1)

show_tail = '    right_side(app, ui, &p, rect, x, cy);\n}'
if 'export_dialog(app, ui);' not in header:
    if show_tail not in header:
        raise SystemExit("Could not find the header show() insertion point.")
    header = header.replace(show_tail, '    right_side(app, ui, &p, rect, x, cy);\n    export_dialog(app, ui);\n    export_progress_dialog(app, ui);\n}', 1)
elif 'export_progress_dialog(app, ui);' not in header:
    header = header.replace('    export_dialog(app, ui);\n}', '    export_dialog(app, ui);\n    export_progress_dialog(app, ui);\n}', 1)

dialog_fn = r'''
/// A centered export setup page. The existing Render Queue remains responsible for choosing
/// the Android save destination and running the render job.
fn export_dialog(app: &mut EffectcraftApp, ui: &mut egui::Ui) {
    let open_id = egui::Id::new("effectcraft-export-dialog-open");
    let draft_id = open_id.with("draft");
    let mut open = ui.ctx().data(|d| d.get_temp::<bool>(open_id).unwrap_or(false));
    if !open {
        return;
    }

    let formats = [
        ("h264", "MP4 · H.264"),
        ("hevc", "MP4 · HEVC"),
        ("av1", "AV1"),
        ("webm", "WebM"),
        ("prores", "ProRes MOV"),
    ];
    let (mut format, mut fps, mut resolution) = ui.ctx().data(|d| {
        d.get_temp::<(String, f64, String)>(draft_id)
            .unwrap_or_else(|| ("h264".to_string(), 0.0, "1080".to_string()))
    });
    let comp_name = app.session.active_comp_id().and_then(|id| app.session.project.item(id)).map(|item| item.name.clone());
    let comp_rate = app.session.active_comp().map(|c| c.frame_rate.as_f64());
    let selected_format = formats.iter()
        .find(|(key, _)| *key == format.as_str())
        .map(|(_, label)| *label)
        .unwrap_or("MP4 · H.264");
    let selected_fps = if fps == 0.0 {
        "跟随工程帧率".to_string()
    } else {
        format!("{fps:.0} FPS")
    };
    let selected_resolution = match resolution.as_str() {
        "480" => "480P",
        "720" => "720P",
        "1080" => "1080P",
        "1440" => "2K（1440P）",
        "2160" => "4K（2160P）",
        _ => "跟随工程",
    };
    let mut submit = false;
    let mut cancel = false;
    let mut save_project_copy = false;
    let mut collect_project_files = false;

    egui::Window::new("导出视频")
        .id(open_id.with("window"))
        .order(egui::Order::Foreground)
        .movable(true)
        .default_pos(ui.ctx().content_rect().center() - vec2(160.0, 190.0))
        .collapsible(false)
        .resizable(false)
        .default_width(310.0)
        .open(&mut open)
        .show(ui.ctx(), |ui| {
            ui.label(comp_name.as_deref().unwrap_or("请先打开一个合成工程"));
            if let Some(rate) = comp_rate {
                ui.label(format!("当前工程帧率：{rate:.3} FPS"));
            }
            ui.add_space(6.0);

            ui.label("视频格式");
            egui::ComboBox::from_id_salt("effectcraft-export-format")
                .selected_text(selected_format)
                .width(230.0)
                .show_ui(ui, |ui| {
                    for (key, label) in formats {
                        ui.selectable_value(&mut format, key.to_string(), label);
                    }
                });

            ui.add_space(6.0);
            ui.label("导出分辨率");
            egui::ComboBox::from_id_salt("effectcraft-export-resolution")
                .selected_text(selected_resolution)
                .width(230.0)
                .show_ui(ui, |ui| {
                    for (key, label) in [
                        ("source", "跟随工程"),
                        ("480", "480P"),
                        ("720", "720P"),
                        ("1080", "1080P"),
                        ("1440", "2K（1440P）"),
                        ("2160", "4K（2160P）"),
                    ] {
                        ui.selectable_value(&mut resolution, key.to_string(), label);
                    }
                });

            ui.add_space(6.0);
            ui.label("导出帧率");
            egui::ComboBox::from_id_salt("effectcraft-export-fps")
                .selected_text(selected_fps)
                .width(230.0)
                .show_ui(ui, |ui| {
                    ui.selectable_value(&mut fps, 0.0, "跟随工程帧率");
                    for value in [24.0_f64, 30.0, 60.0, 120.0, 144.0, 240.0] {
                        ui.selectable_value(&mut fps, value, format!("{value:.0} FPS"));
                    }
                });
            ui.add_space(4.0);
            ui.label("最高可选 240 FPS；实际渲染速度取决于工程素材和设备性能。");
            ui.label("确认后进入原有导出队列，再选择视频保存位置。");
            ui.small("编码使用 APK 内置软件编码器；不依赖手机是否具备硬件视频编码器。");
            ui.add_space(8.0);
            ui.separator();
            ui.label("工程分享");
            if ui.button("完整导出工程（包含素材）").clicked() {
                collect_project_files = true;
            }
            if ui.button("只导出工程文件（.ecproj）").clicked() {
                save_project_copy = true;
            }
            ui.small("QQ 分享建议：完整导出后压缩整个文件夹；接收方解压后导入其中的 .ecproj。");
            ui.add_space(8.0);
            ui.horizontal(|ui| {
                if ui.button("取消").clicked() {
                    cancel = true;
                }
                if ui.add_enabled(comp_name.is_some(), egui::Button::new("开始导出")).clicked() {
                    submit = true;
                }
            });
        });

    if cancel {
        open = false;
    }
    if collect_project_files {
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
    if submit {
        if let Some(comp) = app.session.active_comp_id() {
            // Never auto-start old queued jobs together with this new export.
            let has_existing_queued = app.session.project.render_queue.iter().any(|item| item.is_queued());
            let mut params = json!({"comp": comp.0, "format": format});
            if fps > 0.0 {
                params["frameRate"] = json!(fps);
            }
            if resolution != "source" {
                if let Some(active) = app.session.active_comp() {
                    let (width, height) = effectcraft_export_dimensions(active.width, active.height, &resolution);
                    params["resize"] = json!({
                        "enabled": true,
                        "width": width,
                        "height": height,
                        "lockAspect": false,
                        "quality": "high"
                    });
                }
            }
            let ctx = ui.ctx().clone();
            match crate::menus::invoke(app, &ctx, "renderQueue.add", params) {
                Ok(added) => {
                    // The engine returns the newly created queue row as "item", not "id".
                    if let Some(item_id) = added.get("item").and_then(|value| value.as_u64()) {
                        let default_output = app.session.project.render_queue.iter()
                            .find(|item| item.id == item_id)
                            .and_then(|item| app.session.resolve_output(item))
                            .unwrap_or_else(|| "EffectCraft.mp4".to_string());

                        // Use the Android builder's existing SAF Save picker. On Android this
                        // is routed to the app's private staging path, then published to Gallery.
                        match app.hooks.save_dialog(&default_output) {
                            Some(Some(path)) if !path.trim().is_empty() => {
                                match crate::menus::invoke(
                                    app,
                                    &ctx,
                                    "renderQueue.setOutput",
                                    json!({"item": item_id, "path": path}),
                                ) {
                                    Ok(_) => {
                                        open = false;
                                        if has_existing_queued {
                                            app.show_panel(crate::dock::PanelKind::RenderQueue);
                                            app.ui.status = "已选择视频保存位置并加入导出队列。检测到已有排队任务，为避免误导出其他项目，请检查队列后再点击“渲染”。".into();
                                        } else {
                                            ctx.data_mut(|data| {
                                                data.insert_temp(egui::Id::new("effectcraft-export-progress-open"), true);
                                                data.insert_temp(egui::Id::new("effectcraft-export-progress-items"), vec![item_id]);
                                                data.insert_temp(egui::Id::new("effectcraft-export-progress-error"), Option::<String>::None);
                                            });
                                            match crate::menus::invoke(app, &ctx, "renderQueue.render", json!({"wait": false})) {
                                                Ok(result) => {
                                                    let started_ids: Vec<u64> = result.get("items")
                                                        .and_then(|items| items.as_array())
                                                        .map(|items| items.iter()
                                                            .filter_map(|item| item.get("id").and_then(|id| id.as_u64()))
                                                            .collect())
                                                        .unwrap_or_default();
                                                    let ids = if started_ids.is_empty() { vec![item_id] } else { started_ids };
                                                    ctx.data_mut(|data| {
                                                        data.insert_temp(egui::Id::new("effectcraft-export-progress-items"), ids);
                                                    });
                                                }
                                                Err(error) => {
                                                    let _ = crate::menus::invoke(
                                                        app, &ctx, "renderQueue.setRender",
                                                        json!({"item": item_id, "render": false}),
                                                    );
                                                    app.ui.status = error.clone();
                                                    ctx.data_mut(|data| {
                                                        data.insert_temp(egui::Id::new("effectcraft-export-progress-error"), Some(error));
                                                    });
                                                }
                                            }
                                        }
                                    }
                                    Err(error) => {
                                        let _ = crate::menus::invoke(
                                            app, &ctx, "renderQueue.setRender",
                                            json!({"item": item_id, "render": false}),
                                        );
                                        app.ui.status = format!("设置视频保存位置失败：{error}");
                                        open = false;
                                    }
                                }
                            }
                            Some(_) => {
                                let _ = crate::menus::invoke(
                                    app, &ctx, "renderQueue.setRender",
                                    json!({"item": item_id, "render": false}),
                                );
                                app.ui.status = "已取消保存位置选择，视频没有开始导出。".into();
                                open = false;
                            }
                            None => {
                                let _ = crate::menus::invoke(
                                    app, &ctx, "renderQueue.setRender",
                                    json!({"item": item_id, "render": false}),
                                );
                                app.show_panel(crate::dock::PanelKind::RenderQueue);
                                app.ui.status = "当前设备未提供保存位置选择器，导出任务已暂停。请在导出队列的“输出到”中选择保存位置。".into();
                                open = false;
                            }
                        }
                    } else {
                        app.ui.status = "导出任务已创建，但没有取得队列项目编号，未开始渲染。".into();
                        open = false;
                    }
                }
                Err(error) => {
                    app.ui.status = format!("创建导出任务失败：{error}");
                    open = false;
                }
            }
        }
    }

    ui.ctx().data_mut(|d| {
        d.insert_temp(open_id, open);
        d.insert_temp(draft_id, (format, fps, resolution));
    });
}
'''
progress_function = r'''
/// EFFECTCRAFT_ANDROID_EXPORT_PROGRESS_POPUP_V1
/// Centered, draggable live export progress window backed by the original Render Queue job state.
fn export_progress_dialog(app: &mut EffectcraftApp, ui: &mut egui::Ui) {
    let ctx = ui.ctx().clone();
    let visible_id = egui::Id::new("effectcraft-export-progress-open");
    let items_id = egui::Id::new("effectcraft-export-progress-items");
    let error_id = egui::Id::new("effectcraft-export-progress-error");
    if !ctx.data(|data| data.get_temp::<bool>(visible_id).unwrap_or(false)) {
        return;
    }

    let ids: Vec<u64> = ctx.data(|data| data.get_temp::<Vec<u64>>(items_id).unwrap_or_default());
    let start_error: Option<String> = ctx.data(|data| data.get_temp::<Option<String>>(error_id).flatten());
    let rendering = app.session.is_rendering();
    let progress = app.session.render_progress();

    let mut done_items = 0usize;
    let mut failure: Option<String> = start_error;
    let mut stopped = false;
    for id in &ids {
        if let Some(item) = app.session.project.render_queue.iter().find(|item| item.id == *id) {
            match &item.status {
                effectcraft_engine::project::render_queue::RenderStatus::Done => done_items += 1,
                effectcraft_engine::project::render_queue::RenderStatus::Failed(message) => {
                    if failure.is_none() { failure = Some(message.clone()); }
                }
                effectcraft_engine::project::render_queue::RenderStatus::NeedsOutput => {
                    if failure.is_none() { failure = Some("尚未设置视频保存位置，请检查导出队列的输出路径。".to_string()); }
                }
                effectcraft_engine::project::render_queue::RenderStatus::UserStopped => stopped = true,
                _ => {}
            }
        }
    }
    let all_done = !ids.is_empty() && done_items == ids.len();
    let no_job_started = !rendering && progress.is_none() && !all_done && failure.is_none() && !stopped;
    if no_job_started {
        failure = Some("导出未能启动，请检查输出路径和导出格式。".to_string());
    }

    let (done_frames, total_frames, elapsed, remaining, current_name, fraction) =
        if let Some(state) = progress.as_ref() {
            let current_name = state.current
                .and_then(|current| app.session.project.render_queue.iter().find(|item| item.id == current))
                .and_then(|item| app.session.project.item(item.comp))
                .map(|item| item.name.clone())
                .unwrap_or_default();
            let item_fraction = if state.total > 0 {
                (state.done as f64 / state.total as f64).clamp(0.0, 1.0)
            } else { 0.0 };
            let total_fraction = if state.items_total > 0 {
                ((state.items_done as f64 + item_fraction) / state.items_total as f64).clamp(0.0, 1.0)
            } else { item_fraction };
            (
                state.done,
                state.total,
                state.elapsed,
                state.remaining,
                current_name,
                if all_done { 1.0 } else if state.finished && failure.is_none() { 1.0 } else { total_fraction as f32 },
            )
        } else {
            (0, 0, 0.0, None, String::new(), if all_done { 1.0 } else { 0.0 })
        };

    let final_state = !rendering && (all_done || failure.is_some() || stopped);
    if rendering {
        ctx.request_repaint_after(std::time::Duration::from_millis(400));
    }

    let format_time = |seconds: f64| {
        let total = if seconds.is_finite() { seconds.max(0.0).round() as u64 } else { 0 };
        format!("{:02}:{:02}:{:02}", total / 3600, (total / 60) % 60, total % 60)
    };
    let mut stop_requested = false;
    let mut close_requested = false;

    egui::Window::new("导出进度")
        .id(visible_id.with("window"))
        .order(egui::Order::Foreground)
        .movable(true)
        .collapsible(false)
        .resizable(false)
        .default_pos(ctx.content_rect().center() - vec2(175.0, 105.0))
        .default_width(350.0)
        .show(&ctx, |window_ui| {
            if all_done {
                window_ui.heading("导出完成");
            } else if let Some(message) = &failure {
                window_ui.heading("导出失败");
                window_ui.label(message);
            } else if stopped {
                window_ui.heading("导出已停止");
            } else if rendering {
                window_ui.heading("正在导出视频");
            } else {
                window_ui.heading("正在准备导出");
            }

            if !current_name.is_empty() {
                window_ui.label(format!("当前项目：{current_name}"));
            }
            window_ui.add_space(8.0);
            window_ui.add(egui::ProgressBar::new(fraction.clamp(0.0, 1.0)).desired_width(320.0).show_percentage());
            if total_frames > 0 {
                window_ui.label(format!("当前任务：{done_frames} / {total_frames} 帧"));
            }
            if let Some(state) = progress.as_ref() {
                if state.items_total > 0 {
                    window_ui.label(format!("队列进度：{} / {} 项", state.items_done.min(state.items_total), state.items_total));
                }
                window_ui.label(format!("已用时间：{}", format_time(elapsed)));
                if let Some(seconds) = remaining {
                    window_ui.label(format!("预计当前任务剩余：{}", format_time(seconds)));
                }
            }
            window_ui.add_space(10.0);
            window_ui.horizontal(|actions| {
                if rendering && actions.button("停止导出").clicked() {
                    stop_requested = true;
                }
                if final_state && actions.button("完成").clicked() {
                    close_requested = true;
                }
            });
            window_ui.small("此窗口可拖动；进度来自 EffectCraft 实际渲染帧数。");
        });

    if stop_requested {
        if let Err(error) = crate::menus::invoke(app, &ctx, "renderQueue.stop", json!({})) {
            app.ui.status = error;
        }
    }
    if close_requested {
        ctx.data_mut(|data| {
            data.insert_temp(visible_id, false);
            data.remove::<Vec<u64>>(items_id);
            data.remove::<Option<String>>(error_id);
        });
    }
}
'''

# Show the actual render-queue progress in a centered, draggable popup.
if "fn export_progress_dialog(app: &mut EffectcraftApp" not in header:
    header = header.rstrip() + "\n\n" + progress_function.strip() + "\n"

if "fn export_dialog(app: &mut EffectcraftApp" not in header:
    header = header.rstrip() + "\n\n" + dialog_fn.strip() + "\n"

# Supply the resolution-scaling helper used by the export dialog. Keep the source aspect ratio,
# target the selected short edge (1080P landscape => 1920x1080; portrait => 1080x1920),
# and round the derived long edge up to an even number for common video encoders.
dimension_helper = r"""
/// EFFECTCRAFT_ANDROID_EXPORT_DIMENSIONS_V1
fn effectcraft_export_dimensions(source_width: u32, source_height: u32, resolution: &str) -> (u32, u32) {
    let target_short_side = match resolution {
        "480" => 480_u32,
        "720" => 720_u32,
        "1080" => 1080_u32,
        "1440" => 1440_u32,
        "2160" => 2160_u32,
        _ => return (source_width, source_height),
    };

    if source_width == 0 || source_height == 0 {
        return (source_width.max(2), source_height.max(2));
    }

    let even_dimension = |value: f64| -> u32 {
        let rounded = value.round().max(2.0) as u32;
        rounded.saturating_add(rounded % 2)
    };

    if source_width >= source_height {
        let height = target_short_side;
        let width = even_dimension(height as f64 * source_width as f64 / source_height as f64);
        (width, height)
    } else {
        let width = target_short_side;
        let height = even_dimension(width as f64 * source_height as f64 / source_width as f64);
        (width, height)
    }
}
"""

if "fn effectcraft_export_dimensions(" not in header:
    header = header.rstrip() + "\n\n" + dimension_helper.strip() + "\n"

header_path.write_text(header)

# Cap the quick-select menus at 240 FPS. Do not expose the former 480/999 FPS choices.
for path in (comp_settings_path, render_queue_path):
    source = path.read_text()
    source, count_480 = re.subn(r',\s*480\.0', '', source)
    source, count_999 = re.subn(r',\s*999\.0', '', source)
    if "240.0" not in source:
        if path == render_queue_path:
            marker = "for fps in [12.0, 15.0, 23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 60.0"
            if marker not in source:
                raise SystemExit("Could not find Render Queue frame-rate menu.")
            source = source.replace(marker, marker + ", 120.0, 144.0, 240.0", 1)
        else:
            marker = "const FRAME_RATES: &[f64] = &["
            idx = source.find(marker)
            if idx < 0:
                raise SystemExit("Could not find composition frame-rate presets.")
            end = source.find("];", idx)
            if end < 0:
                raise SystemExit("Could not parse composition frame-rate presets.")
            line = source[idx:end]
            if "120.0" not in line:
                line += ", 120.0, 144.0, 240.0"
            else:
                line += ", 240.0"
            source = source[:idx] + line + source[end:]
    path.write_text(source)

# Make Collect Files portable: footage paths in the copied .ecproj must be relative
# to that project file, not absolute paths on the sender's phone. The folder structure is:
#   <chosen-folder>/<Project>.ecproj
#   <chosen-folder>/(Footage)/<media files>
file_more = engine_file_more_path.read_text()
old_media_path = "            new_paths.push(dst.clone());"
new_media_path = """            let filename = std::path::Path::new(dst).file_name().map(|name| name.to_string_lossy()).unwrap_or_else(|| "footage".into());
            new_paths.push(format!("(Footage)/{filename}"));"""
if new_media_path not in file_more:
    if old_media_path not in file_more:
        raise SystemExit("Could not find Collect Files media-path rewrite point.")
    file_more = file_more.replace(old_media_path, new_media_path, 1)
old_project_write = '    s.write_output_with(&protected, &out, proj.to_json().as_bytes())?;'
new_project_write = """    if !errors.is_empty() {
        let details = errors.iter().take(5).cloned().collect::<Vec<_>>().join("; ");
        return Err(EngineError::Other(format!(
            "Nothing was collected because {} media file(s) could not be copied: {details}",
            errors.len()
        )));
    }
    s.write_output_with(&protected, &out, proj.to_json().as_bytes())?;"""
if new_project_write not in file_more:
    if old_project_write not in file_more:
        raise SystemExit("Could not find the final Collect Files project-write point.")
    file_more = file_more.replace(old_project_write, new_project_write, 1)

engine_file_more_path.write_text(file_more)

# Fix Android's synchronous multi-file picker: pick_files must request multiple=true.
rfd_android = root.parents[1] / "vendor/rfd/src/backend/android.rs"
if not rfd_android.is_file():
    raise SystemExit("Could not find Android rfd backend.")
rfd_text = rfd_android.read_text()
old_pick_files = """    fn pick_files(self) -> Option<Vec<PathBuf>> {
        crate::artcraft_saf::pick_sync(crate::artcraft_saf::Kind::Open { multiple: false })
    }"""
new_pick_files = """    fn pick_files(self) -> Option<Vec<PathBuf>> {
        crate::artcraft_saf::pick_sync(crate::artcraft_saf::Kind::Open { multiple: true })
    }"""
if new_pick_files not in rfd_text:
    if old_pick_files not in rfd_text:
        raise SystemExit("Could not find Android synchronous pick_files implementation.")
    rfd_android.write_text(rfd_text.replace(old_pick_files, new_pick_files, 1))


# Keep an imported .ecproj beside its media folder when Android can resolve it to shared storage.
# SAF private staging relocates the project file and breaks its relative (Footage)/ references.
saf_template = root.parents[1] / "templates/android/SafActivity.java"
if not saf_template.is_file():
    raise SystemExit("Could not find Android SAF Activity template.")
saf_text = saf_template.read_text()
direct_helper = """    private boolean hasDirectSharedStorageAccess() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                return Environment.isExternalStorageManager();
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                return checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED;
            }
            return true;
        } catch (Exception error) {
            Log.w(TAG, "Could not verify shared-storage access", error);
            return false;
        }
    }

    private File directSharedProject(Uri uri) {
        try {
            if (uri == null || !hasDirectSharedStorageAccess()
                    || !DocumentsContract.isDocumentUri(this, uri)) return null;
            String documentId = DocumentsContract.getDocumentId(uri);
            if (documentId == null) return null;
            int colon = documentId.indexOf(':');
            if (colon < 0 || !"primary".equalsIgnoreCase(documentId.substring(0, colon))) return null;
            String relative = documentId.substring(colon + 1);
            File base = Environment.getExternalStorageDirectory().getCanonicalFile();
            File selected = new File(base, relative).getCanonicalFile();
            String prefix = base.getPath() + File.separator;
            if (!selected.getPath().startsWith(prefix) || !selected.isFile()) return null;
            String lower = selected.getName().toLowerCase(java.util.Locale.ROOT);
            if (!lower.endsWith(".ecproj") && !lower.endsWith(".ecprojx")) return null;
            return selected;
        } catch (Exception error) {
            Log.i(TAG, "Project import will use app-private SAF staging", error);
            return null;
        }
    }

"""
if "private File directSharedProject(Uri uri)" not in saf_text:
    helper_marker = "    private static String treeToPath(Uri tree) {"
    if helper_marker not in saf_text:
        raise SystemExit("Could not find Android SAF helper insertion point.")
    saf_text = saf_text.replace(helper_marker, direct_helper + helper_marker, 1)

open_marker = """        if (uris.isEmpty()) { enqueueCancel(id, kind); return; }
        for (Uri uri : uris) persistPermission(uri, data);"""
open_patch = """        if (uris.isEmpty()) { enqueueCancel(id, kind); return; }
        // Preserve the original project location if it is on shared primary storage. Relative
        // paths such as (Footage)/clip.mp4 must remain beside the .ecproj file after selection.
        if (requestCode == REQ_OPEN && uris.size() == 1) {
            File directProject = directSharedProject(uris.get(0));
            if (directProject != null) {
                persistPermission(uris.get(0), data);
                try {
                    JSONArray paths = new JSONArray();
                    paths.put(directProject.getAbsolutePath());
                    JSONObject result = base(id, "open", "ok");
                    result.put("paths", paths);
                    results.offer(result.toString());
                } catch (Exception error) {
                    enqueueError(id, "open", error.toString());
                }
                return;
            }
        }
        for (Uri uri : uris) persistPermission(uri, data);"""
if open_patch not in saf_text:
    if open_marker not in saf_text:
        raise SystemExit("Could not find Android SAF project-open staging point.")
    saf_text = saf_text.replace(open_marker, open_patch, 1)

incoming_old = """                try {
                    File stage = newStageFile(displayName(uri), uri);
                    copyUriToFile(uri, stage);
                    rememberUri(stage, uri);
                    intentPaths.offer(stage.getAbsolutePath());
                } catch (Exception e) {
                    Log.e(TAG, "Could not open the file the system handed the app: " + uri, e);
                }"""
incoming_new = """                try {
                    File directProject = directSharedProject(uri);
                    if (directProject != null) {
                        intentPaths.offer(directProject.getAbsolutePath());
                        continue;
                    }
                    File stage = newStageFile(displayName(uri), uri);
                    copyUriToFile(uri, stage);
                    rememberUri(stage, uri);
                    intentPaths.offer(stage.getAbsolutePath());
                } catch (Exception e) {
                    Log.e(TAG, "Could not open the file the system handed the app: " + uri, e);
                }"""
if incoming_new not in saf_text:
    if incoming_old not in saf_text:
        raise SystemExit("Could not find Android incoming-project staging point.")
    saf_text = saf_text.replace(incoming_old, incoming_new, 1)
saf_template.write_text(saf_text)

# Stream-copy native footage instead of loading entire files into RAM during Collect Files.
engine_file_more = engine_file_more_path.read_text()
old_copy = """                match s.services.read_file(src).and_then(|bytes| s.write_output_with(&protected, dst, &bytes).map_err(std::io::Error::other)) {
                    Ok(()) => copied += 1,
                    Err(e) => errors.push(format!("{src}: {e}")),
                }"""
new_copy = """                let result: std::io::Result<()> = {
                    #[cfg(not(target_arch = "wasm32"))]
                    {
                        // Stream large video files; never allocate a full-file Vec<u8> on Android.
                        std::fs::copy(src, dst).map(|_| ())
                    }
                    #[cfg(target_arch = "wasm32")]
                    {
                        s.services.read_file(src).and_then(|bytes| {
                            s.write_output_with(&protected, dst, &bytes).map_err(std::io::Error::other)
                        })
                    }
                };
                match result {
                    Ok(()) => {
                        copied += 1;
                        #[cfg(not(target_arch = "wasm32"))]
                        created_files.push(dst.clone());
                    }
                    Err(e) => errors.push(format!("{src}: {e}")),
                }"""
if new_copy not in engine_file_more:
    if old_copy not in engine_file_more:
        raise SystemExit("Could not find Collect Files copy block for streaming update.")
    engine_file_more = engine_file_more.replace(old_copy,new_copy,1)

created_marker = "    let mut copied = 0;\n    let mut errors = vec![];"
created_new = "    let mut copied = 0;\n    let mut errors = vec![];\n    #[cfg(not(target_arch = \"wasm32\"))]\n    let mut created_files: Vec<String> = vec![];"
if created_new not in engine_file_more:
    if created_marker not in engine_file_more:
        raise SystemExit("Could not add rollback tracking for collected files.")
    engine_file_more=engine_file_more.replace(created_marker,created_new,1)

copy_guard_old = "            pairs.push((src.clone(), dst));"
copy_guard_new = """            if !crate::output_guard::same_file(std::path::Path::new(src), std::path::Path::new(&dst))
                && std::path::Path::new(&dst).exists()
            {
                return Err(EngineError::Other(format!("Nothing was collected. Destination already exists: {dst}")));
            }
            pairs.push((src.clone(), dst));"""
if copy_guard_new not in engine_file_more:
    if copy_guard_old not in engine_file_more:
        raise SystemExit("Could not add existing-footage destination guard.")
    engine_file_more=engine_file_more.replace(copy_guard_old,copy_guard_new,1)

project_guard_marker = """    if let Some(source) = protected.find(std::path::Path::new(&out)) {
        return Err(EngineError::Other(format!("Nothing was collected. {}", source.refusal(&out, crate::output_guard::Use::Export))));
    }"""
project_guard_new = project_guard_marker + """
    if std::path::Path::new(&out).exists() {
        return Err(EngineError::Other(format!("Nothing was collected. Project destination already exists: {out}")));
    }"""
if project_guard_new not in engine_file_more:
    if project_guard_marker not in engine_file_more:
        raise SystemExit("Could not add existing-project destination guard.")
    engine_file_more=engine_file_more.replace(project_guard_marker,project_guard_new,1)

err_old = """    if !errors.is_empty() {
        let details = errors.iter().take(5).cloned().collect::<Vec<_>>().join("; ");
        return Err(EngineError::Other(format!(
            "Nothing was collected because {} media file(s) could not be copied: {details}",
            errors.len()
        )));
    }"""
err_new = """    if !errors.is_empty() {
        #[cfg(not(target_arch = "wasm32"))]
        for path in &created_files {
            if let Err(error) = std::fs::remove_file(path) {
                log::warn!("Could not remove an incomplete Collect Files copy {path}: {error}");
            }
        }
        let details = errors.iter().take(5).cloned().collect::<Vec<_>>().join("; ");
        return Err(EngineError::Other(format!(
            "Nothing was collected because {} media file(s) could not be copied: {details}",
            errors.len()
        )));
    }"""
if err_new not in engine_file_more:
    if err_old not in engine_file_more:
        raise SystemExit("Could not find Collect Files copy-error guard.")
    engine_file_more=engine_file_more.replace(err_old,err_new,1)
engine_file_more_path.write_text(engine_file_more)


# Preserve the original EffectCraft WASM plug-in memory allowance and parallel execution.
# Add overflow-safe frame-buffer sizing only; do not lower runtime memory budgets.
plugin_runtime = root / "crates/plugin/src/wasm.rs"
if not plugin_runtime.is_file():
    raise SystemExit("Could not find EffectCraft WebAssembly plug-in runtime.")
plugin_text = plugin_runtime.read_text()
old_render = """    fn render(&self, frame: &mut PluginFrame, params: &PluginParams, time: f64) -> Result<(), String> {
        let n = frame.pixels.len();
        let params_bytes = params.flat.len() * 8;
        let total = params_bytes + n * 16;"""
new_render = """    fn render(&self, frame: &mut PluginFrame, params: &PluginParams, time: f64) -> Result<(), String> {
        let n = frame.pixels.len();
        let params_bytes = params.flat.len().checked_mul(8).ok_or("plug-in parameter buffer is too large")?;
        let pixels_bytes = n.checked_mul(16).ok_or("plug-in pixel buffer is too large")?;
        let total = params_bytes.checked_add(pixels_bytes).ok_or("plug-in frame buffer is too large")?;"""
if new_render not in plugin_text:
    if old_render not in plugin_text:
        raise SystemExit("Could not add overflow-safe plug-in frame sizing.")
    plugin_text = plugin_text.replace(old_render, new_render, 1)
plugin_runtime.write_text(plugin_text)


# Confirm the import paths are still present after all edits.
frontend_after = frontend_path.read_text()
for needle in required_import_paths:
    if needle not in frontend_after:
        raise SystemExit("Project import regression: " + needle)

# Fix both AI attachment-name borrow sites before the Android Rust build.
# The name is owned before entering egui closures that can clear image_name.
ai_assistant_path = root / "crates/ui-egui/src/ai_assistant.rs"
if ai_assistant_path.is_file():
    assistant = ai_assistant_path.read_text()
    old = "if let Some(name) = &state.image_name {"
    new = "if let Some(name) = state.image_name.clone() {"
    count = assistant.count(old)
    if count:
        assistant = assistant.replace(old, new)
        ai_assistant_path.write_text(assistant)
        print(f"Fixed {count} AI image attachment borrow site(s).")


# The standalone DeepSeek plugin bridge was installed before this export patch.
# Do not replace it with a bundled llama.cpp assistant or bundle a local GGUF model.


print("Export dialog patched; project open/import pathways preserved; frame-rate UI capped at 240 FPS.")
