//! EffectCraft's in-app assistant UI. Inference and model storage live in the
//! separately installed Android AI plugin; this module contains no llama.cpp code.
use std::{
    sync::{
        atomic::{AtomicU64, AtomicUsize, Ordering},
        mpsc::{self, Receiver},
    },
    time::Duration,
};

use egui::{Color32, Id, Order, Sense, pos2, vec2};
use crate::EffectcraftApp;

const AVATAR: &[u8] = include_bytes!("../../../assets/ae-avatar.png");

#[cfg(target_os = "android")]
static ANDROID_VM_PTR: AtomicUsize = AtomicUsize::new(0);
static REQUEST_ID: AtomicU64 = AtomicU64::new(1);

#[cfg(target_os = "android")]
pub(crate) fn init_android_vm(ptr: *mut std::ffi::c_void) {
    ANDROID_VM_PTR.store(ptr as usize, Ordering::Release);
}

#[derive(Clone)]
struct ChatLine {
    role: &'static str,
    text: String,
}

pub(crate) struct State {
    open: bool,
    input: String,
    lines: Vec<ChatLine>,
    pending: Option<Receiver<Result<String, String>>>,
    notice: String,
    avatar: Option<egui::TextureHandle>,
    plugin_installed: Option<bool>,
    probe_frames: u16,
}

impl Default for State {
    fn default() -> Self {
        Self {
            open: false,
            input: String::new(),
            lines: vec![ChatLine {
                role: "assistant",
                text: "你好！我是 EffectCraft AI 助手。导入 DeepSeek AI 插件 ZIP 并准备本地模型后，即可在这里离线对话。".into(),
            }],
            pending: None,
            notice: String::new(),
            avatar: None,
            plugin_installed: None,
            probe_frames: 0,
        }
    }
}

pub(crate) fn show(app: &mut EffectcraftApp, root: &mut egui::Ui) {
    let ctx = root.ctx().clone();
    let state = &mut app.ai_assistant;
    let avatar = state.avatar.get_or_insert_with(|| {
        let rgba = image::load_from_memory(AVATAR)
            .expect("embedded AI avatar must decode")
            .to_rgba8();
        let size = [rgba.width() as usize, rgba.height() as usize];
        ctx.load_texture(
            "effectcraft-ai-avatar",
            egui::ColorImage::from_rgba_unmultiplied(size, rgba.as_raw()),
            egui::TextureOptions::LINEAR,
        )
    }).clone();

    state.probe_frames = state.probe_frames.wrapping_add(1);
    if state.plugin_installed.is_none() || state.probe_frames % 90 == 0 {
        state.plugin_installed = Some(ai_plugin_available());
    }
    poll_result(state, &ctx);

    let screen = ctx.content_rect();
    egui::Area::new(Id::new("effectcraft-ai-bubble"))
        .order(Order::Foreground)
        .movable(true)
        .default_pos(pos2(
            (screen.max.x - 64.0).max(screen.min.x + 8.0),
            (screen.max.y - 92.0).max(screen.min.y + 8.0),
        ))
        .show(&ctx, |ui| {
            let button = egui::Image::new(&avatar)
                .fit_to_exact_size(vec2(48.0, 48.0))
                .corner_radius(24)
                .sense(Sense::click());
            if ui.add(button).clicked() {
                state.open = !state.open;
            }
        });

    if !state.open {
        return;
    }

    let mut send = false;
    let mut import_plugin = false;
    let mut manage_model = false;
    let mut window_open = state.open;
    egui::Window::new("EffectCraft AI 助手")
        .id(Id::new("effectcraft-ai-chat-window"))
        .order(Order::Foreground)
        .movable(true)
        .default_pos(pos2(
            (screen.max.x - 350.0).max(screen.min.x + 8.0),
            (screen.max.y - 560.0).max(screen.min.y + 8.0),
        ))
        .default_size(vec2(330.0, 450.0))
        .min_size(vec2(280.0, 300.0))
        .resizable(true)
        .open(&mut window_open)
        .show(&ctx, |ui| {
            ui.label("DeepSeek 本地推理 · 插件通过 ZIP 导入");
            if state.plugin_installed == Some(true) {
                ui.small("AI 插件已导入；首次使用请先准备模型。");
            } else {
                ui.colored_label(Color32::from_rgb(210, 145, 35), "尚未导入 DeepSeek AI 插件 ZIP。");
            }
            ui.separator();
            egui::ScrollArea::vertical()
                .stick_to_bottom(true)
                .max_height(245.0)
                .show(ui, |ui| {
                    for line in &state.lines {
                        let user = line.role == "user";
                        ui.horizontal_wrapped(|ui| {
                            ui.label(
                                egui::RichText::new(if user { "我：" } else { "AI：" })
                                    .strong()
                                    .color(if user {
                                        Color32::from_rgb(70, 130, 230)
                                    } else {
                                        Color32::from_rgb(45, 165, 120)
                                    }),
                            );
                            ui.label(&line.text);
                        });
                        ui.add_space(5.0);
                    }
                    if state.pending.is_some() {
                        ui.horizontal(|ui| {
                            ui.spinner();
                            ui.label("DeepSeek 正在本地推理…");
                        });
                    }
                });
            ui.separator();
            ui.add(
                egui::TextEdit::multiline(&mut state.input)
                    .hint_text("输入你不懂的功能或操作…")
                    .desired_rows(2),
            );
            ui.horizontal(|ui| {
                if ui.add_enabled(
                    state.pending.is_none() && !state.input.trim().is_empty(),
                    egui::Button::new("发送"),
                ).clicked() {
                    send = true;
                }
                if ui.button("清空对话").clicked() {
                    state.lines.clear();
                }
            });
            ui.horizontal(|ui| {
                if ui.button("导入 AI 插件").clicked() {
                    import_plugin = true;
                }
                if ui.add_enabled(state.plugin_installed == Some(true), egui::Button::new("模型管理")).clicked() {
                    manage_model = true;
                }
            });
            if !state.notice.is_empty() {
                ui.colored_label(Color32::from_rgb(210, 145, 35), &state.notice);
            }
        });

    state.open = window_open;
    if import_plugin {
        match open_ai_plugin_import() {
            Ok(()) => {
                state.notice = "请选择 DeepSeek AI 插件 ZIP。随后 Android 会显示一次系统安装确认。".into();
            }
            Err(error) => state.notice = error,
        }
    }
    if manage_model {
        match open_ai_plugin_manager() {
            Ok(()) => state.notice = "已请求打开 AI 插件的模型管理界面。".into(),
            Err(error) => state.notice = error,
        }
    }
    if send {
        start_request(state);
    }
}

fn start_request(state: &mut State) {
    if state.pending.is_some() {
        return;
    }
    let question = state.input.trim().to_string();
    if question.is_empty() {
        return;
    }
    if state.plugin_installed != Some(true) {
        state.notice = "请先点击“导入 AI 插件”，选择 ZIP 并按 Android 系统提示完成安装后，即可使用本地 DeepSeek。".into();
        return;
    }

    state.lines.push(ChatLine {
        role: "user",
        text: question,
    });
    state.input.clear();
    state.notice.clear();

    let history = state.lines
        .iter()
        .rev()
        .take(8)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .map(|line| format!("{}：{}", if line.role == "user" { "用户" } else { "助手" }, line.text))
        .collect::<Vec<_>>()
        .join("\n");
    let id = REQUEST_ID.fetch_add(1, Ordering::Relaxed).to_string();
    let (tx, rx) = mpsc::channel();
    state.pending = Some(rx);

    std::thread::spawn(move || {
        let result = ai_plugin_request(&id, &history);
        let _ = tx.send(result);
    });
}

fn poll_result(state: &mut State, ctx: &egui::Context) {
    let Some(rx) = state.pending.as_ref() else {
        return;
    };
    match rx.try_recv() {
        Ok(Ok(text)) => {
            state.lines.push(ChatLine {
                role: "assistant",
                text,
            });
            state.pending = None;
            ctx.request_repaint();
        }
        Ok(Err(error)) => {
            state.lines.push(ChatLine {
                role: "assistant",
                text: error.clone(),
            });
            state.notice = error;
            state.pending = None;
            ctx.request_repaint();
        }
        Err(mpsc::TryRecvError::Disconnected) => {
            state.lines.push(ChatLine {
                role: "assistant",
                text: "AI 插件通信意外中断，请重新连接插件后重试。".into(),
            });
            state.pending = None;
            ctx.request_repaint();
        }
        Err(mpsc::TryRecvError::Empty) => {
            ctx.request_repaint_after(Duration::from_millis(120));
        }
    }
}

#[cfg(target_os = "android")]
fn with_android_vm<T>(
    f: impl FnOnce(&jni::vm::JavaVM) -> Result<T, String>,
) -> Result<T, String> {
    let ptr = ANDROID_VM_PTR.load(Ordering::Acquire);
    if ptr == 0 {
        return Err("Android AI 插件桥接尚未初始化。".into());
    }
    let vm = jni::vm::JavaVM::singleton().map_err(|error| error.to_string())?;
    f(&vm)
}

#[cfg(target_os = "android")]
fn ai_plugin_available() -> bool {
    with_android_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<bool> {
            let activity_class = env.load_class(jni::jni_str!("com.artcraft.effectcraft.EffectCraftActivity"))?;
            Ok(env.call_static_method(
                &activity_class,
                jni::jni_str!("isAiPluginInstalled"),
                jni::jni_sig!("()Z"),
                &[],
            )?.z()?)
        }).map_err(|e| e.to_string())
    }).unwrap_or(false)
}

#[cfg(not(target_os = "android"))]
fn ai_plugin_available() -> bool {
    false
}

#[cfg(target_os = "android")]
fn ai_plugin_request(request_id: &str, prompt: &str) -> Result<String, String> {
    let submitted = with_android_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<bool> {
            let activity_class = env.load_class(jni::jni_str!("com.artcraft.effectcraft.EffectCraftActivity"))?;
            let id = env.new_string(request_id)?;
            let prompt = env.new_string(prompt)?;
            Ok(env.call_static_method(
                &activity_class,
                jni::jni_str!("submitAiPrompt"),
                jni::jni_sig!("(Ljava/lang/String;Ljava/lang/String;)Z"),
                &[jni::objects::JValue::Object(&id), jni::objects::JValue::Object(&prompt)],
            )?.z()?)
        }).map_err(|e| e.to_string())
    })?;
    if !submitted {
        return Err("无法连接 AI 插件。请确认已导入 ZIP 并按系统提示安装插件，然后重新打开助手。".into());
    }

    for _ in 0..12_000 {
        let response = with_android_vm(|vm| {
            vm.attach_current_thread(|env| -> jni::errors::Result<Option<String>> {
                let activity_class = env.load_class(jni::jni_str!("com.artcraft.effectcraft.EffectCraftActivity"))?;
                let id = env.new_string(request_id)?;
                let object = env.call_static_method(
                    &activity_class,
                    jni::jni_str!("pollAiResponse"),
                    jni::jni_sig!("(Ljava/lang/String;)Ljava/lang/String;"),
                    &[jni::objects::JValue::Object(&id)],
                )?.l()?;
                if object.is_null() {
                    return Ok(None);
                }
                let response = env.as_cast::<jni::objects::JString>(&object)?;
                Ok(Some(response.to_string()))
            }).map_err(|e| e.to_string())
        })?;
        if let Some(response) = response {
            return if let Some(message) = response.strip_prefix("ERROR: ") {
                Err(message.to_string())
            } else {
                Ok(response)
            };
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    Err("AI 插件响应超时，请检查模型是否已准备好，并确保手机没有清理插件进程。".into())
}

#[cfg(not(target_os = "android"))]
fn ai_plugin_request(_request_id: &str, _prompt: &str) -> Result<String, String> {
    Err("独立 AI 插件连接仅在 Android 版本中启用。".into())
}

#[cfg(target_os = "android")]
pub(crate) fn open_ai_plugin_import() -> Result<(), String> {
    with_android_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<()> {
            let activity_class = env.load_class(jni::jni_str!("com.artcraft.effectcraft.EffectCraftActivity"))?;
            env.call_static_method(
                &activity_class,
                jni::jni_str!("openAiPluginImport"),
                jni::jni_sig!("()V"),
                &[],
            )?;
            Ok(())
        }).map_err(|e| e.to_string())
    })
}

#[cfg(not(target_os = "android"))]
pub(crate) fn open_ai_plugin_import() -> Result<(), String> {
    Err("请在 Android 版 EffectCraft 中导入 AI 插件。".into())
}

#[cfg(target_os = "android")]
fn open_ai_plugin_manager() -> Result<(), String> {
    with_android_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<()> {
            let activity_class = env.load_class(jni::jni_str!("com.artcraft.effectcraft.EffectCraftActivity"))?;
            env.call_static_method(
                &activity_class,
                jni::jni_str!("openAiPluginManager"),
                jni::jni_sig!("()V"),
                &[],
            )?;
            Ok(())
        }).map_err(|e| e.to_string())
    })
}

#[cfg(not(target_os = "android"))]
fn open_ai_plugin_manager() -> Result<(), String> {
    Err("AI 插件模型管理仅在 Android 版本中启用。".into())
}
