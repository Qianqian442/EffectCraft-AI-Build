//! Fully local EffectCraft help bubble. No cloud endpoint or API key is used.
use std::{num::NonZeroU32, path::Path, sync::{mpsc::{self, Receiver}, Mutex, OnceLock}};
use egui::{Color32, Id, Order, Sense, pos2, vec2};
use llama_cpp_2::{
    context::params::LlamaContextParams,
    llama_backend::LlamaBackend,
    llama_batch::LlamaBatch,
    model::{params::LlamaModelParams, LlamaChatMessage, LlamaModel},
    sampling::LlamaSampler,
};
use crate::EffectcraftApp;

const KNOWLEDGE: &str = "EffectCraft 0.21.1 本地操作知识：\n\
合成（Composition）：在项目面板新建合成，设置画布宽高、帧率和时长。\n\
素材导入：使用文件菜单的导入功能，或把视频、图片、音频拖入项目。\n\
时间轴：把素材放入时间轴图层；移动播放头定位时间；关键帧用于记录属性在不同时间的值。\n\
特效：选中图层后在效果面板添加效果，调整参数；可为支持的参数添加关键帧。\n\
预览：播放头和预览窗口用于查看当前帧；复杂合成可降低预览分辨率以提高响应。\n\
导出：打开导出面板选择格式、分辨率、帧率和质量；工程导出用于分享可继续编辑的项目，需同时收集素材。\n\
工程导入：通过文件打开/导入项目功能选择项目文件；缺失素材时需要重新定位原素材。\n\
本地 AI：若用户问到尚未确认存在的菜单或功能，不得猜测；提醒以当前版本实际界面为准。";
const MODEL_ENV: &str = "EFFECTCRAFT_AI_MODEL_PATH";
const CONTEXT: u32 = 1536;
const MAX_OUTPUT: usize = 256;
const AVATAR: &[u8] = include_bytes!("../../../assets/ae-avatar.png");

struct LoadedModel { _backend: LlamaBackend, model: LlamaModel }
static LOADED_MODEL: OnceLock<Mutex<Option<LoadedModel>>> = OnceLock::new();

fn loaded_model_store() -> &'static Mutex<Option<LoadedModel>> {
    LOADED_MODEL.get_or_init(|| Mutex::new(None))
}

/// Release the large mmap-backed model when the assistant is closed and no request is running.
fn release_model_if_idle() {
    if let Ok(mut loaded) = loaded_model_store().lock() {
        *loaded = None;
    }
}

#[derive(Clone)]
struct ChatLine { role: &'static str, text: String }
pub(crate) struct State {
    open: bool,
    input: String,
    lines: Vec<ChatLine>,
    pending: Option<Receiver<Result<String, String>>>,
    notice: String,
    avatar: Option<egui::TextureHandle>,
}
impl Default for State {
    fn default() -> Self {
        Self {
            open: false, input: String::new(),
            lines: vec![ChatLine { role: "assistant", text: "你好！我是 EffectCraft 本地 AI 助手。DeepSeek 模型随应用安装，断网也能回答，不需要 API Key。你可以询问合成、素材、特效、关键帧和导出操作。".into() }],
            pending: None, notice: String::new(), avatar: None,
        }
    }
}

pub(crate) fn show(app: &mut EffectcraftApp, root: &mut egui::Ui) {
    let ctx = root.ctx().clone();
    let state = &mut app.ai_assistant;
    let avatar = state.avatar.get_or_insert_with(|| {
        let rgba = image::load_from_memory(AVATAR).expect("embedded AI avatar must decode").to_rgba8();
        let size = [rgba.width() as usize, rgba.height() as usize];
        ctx.load_texture("effectcraft-ai-avatar", egui::ColorImage::from_rgba_unmultiplied(size, rgba.as_raw()), egui::TextureOptions::LINEAR)
    }).clone();
    poll_result(state, &ctx);
    if !state.open && state.pending.is_none() {
        release_model_if_idle();
    }
    let screen = ctx.content_rect();
    egui::Area::new(Id::new("effectcraft-ai-bubble"))
        .order(Order::Foreground).movable(true)
        .default_pos(pos2((screen.max.x - 64.0).max(screen.min.x + 8.0), (screen.max.y - 92.0).max(screen.min.y + 8.0)))
        .show(&ctx, |ui| {
            let button = egui::Image::new(&avatar).fit_to_exact_size(vec2(48.0, 48.0)).corner_radius(24).sense(Sense::click());
            if ui.add(button).clicked() { state.open = !state.open; }
        });
    if !state.open { return; }
    let mut send = false;
    let mut window_open = state.open;
    egui::Window::new("EffectCraft 本地 AI 助手")
        .id(Id::new("effectcraft-ai-chat-window")).order(Order::Foreground)
        .default_pos(pos2((screen.max.x - 350.0).max(screen.min.x + 8.0), (screen.max.y - 560.0).max(screen.min.y + 8.0)))
        .default_size(vec2(330.0, 430.0)).min_size(vec2(280.0, 300.0)).resizable(true)
        .open(&mut window_open).show(&ctx, |ui| {
            ui.label("本地离线运行 · 不需要联网 · 不需要 API Key");
            ui.label("DeepSeek-R1-Distill-Qwen-1.5B · IQ4_XS");
            ui.small("关闭助手窗口后释放模型内存");
            ui.separator();
            egui::ScrollArea::vertical().stick_to_bottom(true).max_height(260.0).show(ui, |ui| {
                for line in &state.lines {
                    let user = line.role == "user";
                    ui.horizontal_wrapped(|ui| {
                        ui.label(egui::RichText::new(if user { "我：" } else { "AI：" }).strong().color(if user { Color32::from_rgb(70,130,230) } else { Color32::from_rgb(45,165,120) }));
                        ui.label(&line.text);
                    });
                    ui.add_space(5.0);
                }
                if state.pending.is_some() { ui.horizontal(|ui| { ui.spinner(); ui.label("本地模型正在推理…首次加载会较慢"); }); }
            });
            ui.separator();
            ui.add(egui::TextEdit::multiline(&mut state.input).hint_text("输入你不懂的功能或操作…").desired_rows(2));
            ui.horizontal(|ui| {
                if ui.add_enabled(state.pending.is_none() && !state.input.trim().is_empty(), egui::Button::new("发送")).clicked() { send = true; }
                if ui.button("清空对话").clicked() { state.lines.clear(); }
            });
            if !state.notice.is_empty() { ui.colored_label(Color32::from_rgb(210,145,35), &state.notice); }
        });
    state.open = window_open;
    if send { start_request(state); }
}

fn start_request(state: &mut State) {
    if state.pending.is_some() { return; }
    let prompt = state.input.trim().to_string();
    if prompt.is_empty() { return; }
    let model_path = std::env::var(MODEL_ENV).unwrap_or_default();
    if model_path.is_empty() || !Path::new(&model_path).is_file() {
        state.notice = "未找到 APK 内置的 DeepSeek 模型。请安装完整离线 AI 版本，并确保设备有足够存储空间。".into();
        return;
    }
    state.lines.push(ChatLine { role: "user", text: prompt });
    state.input.clear(); state.notice.clear();
    let history: Vec<(String, String)> = state.lines.iter().rev().take(8).rev().map(|m| (m.role.to_owned(), m.text.clone())).collect();
    let (tx, rx) = mpsc::channel();
    state.pending = Some(rx);
    std::thread::spawn(move || { let _ = tx.send(local_chat(&model_path, &history)); });
}

fn local_chat(path: &str, history: &[(String, String)]) -> Result<String, String> {
    let mut guard = loaded_model_store().lock().map_err(|_| "本地模型锁异常".to_string())?;
    if guard.is_none() {
        let backend = LlamaBackend::init().map_err(|e| format!("初始化本地引擎失败：{e}"))?;
        let model = LlamaModel::load_from_file(&backend, path, &LlamaModelParams::default())
            .map_err(|e| format!("加载 DeepSeek 模型失败：{e}"))?;
        *guard = Some(LoadedModel { _backend: backend, model });
    }
    let loaded = guard.as_ref().ok_or_else(|| "本地模型尚未加载".to_string())?;
    let model = &loaded.model;
    let manual = KNOWLEDGE.chars().take(3200).collect::<String>();
    let sys = format!("你是 EffectCraft 0.21.1 中文操作助手。用简体中文回答，优先给出准确菜单路径和分步操作；无依据时明确说不知道，不要编造。\n\nEffectCraft 手册摘录：\n{manual}");
    let mut messages = vec![LlamaChatMessage::new("system".into(), sys).map_err(|e| e.to_string())?];
    for (role, content) in history { messages.push(LlamaChatMessage::new(role.clone(), content.clone()).map_err(|e| e.to_string())?); }
    let template = model.chat_template(None).map_err(|e| format!("读取模型对话模板失败：{e}"))?;
    let prompt = model.apply_chat_template(&template, &messages, true).map_err(|e| format!("创建本地提示词失败：{e}"))?;
    let vocab = model.vocab();
    let tokens = vocab.tokenize(prompt.as_bytes(), true, true);
    if tokens.is_empty() || tokens.len() + MAX_OUTPUT >= CONTEXT as usize { return Err("对话太长，请清空部分历史记录后重试。".into()); }
    let n_ctx = NonZeroU32::new(CONTEXT).ok_or_else(|| "上下文长度配置无效".to_string())?;
    let params = LlamaContextParams::default().with_n_ctx(Some(n_ctx)).with_n_batch(128).with_n_ubatch(64).with_n_threads(2).with_n_threads_batch(2);
    let mut ctx = model.new_context(&loaded._backend, params).map_err(|e| format!("创建推理上下文失败：{e}"))?;
    let mut batch = LlamaBatch::new(CONTEXT as usize, 1);
    let last = i32::try_from(tokens.len() - 1).map_err(|_| "提示词过长".to_string())?;
    for (i, token) in tokens.iter().copied().enumerate() {
        let pos = i32::try_from(i).map_err(|_| "提示词过长".to_string())?;
        batch.add(token, pos, &[0], pos == last).map_err(|e| format!("准备推理批次失败：{e}"))?;
    }
    ctx.decode(&mut batch).map_err(|e| format!("模型处理输入失败：{e}"))?;
    let mut sampler = LlamaSampler::chain_simple([LlamaSampler::temp(0.45), LlamaSampler::dist(1234)]);
    let mut bytes = Vec::new();
    let mut pos = i32::try_from(tokens.len()).map_err(|_| "提示词过长".to_string())?;
    for _ in 0..MAX_OUTPUT {
        let token = sampler.sample(&ctx, batch.n_tokens() - 1);
        sampler.accept(token);
        if vocab.is_eog(token) { break; }
        bytes.extend_from_slice(&vocab.token_to_piece(token, false, None));
        batch.clear();
        batch.add(token, pos, &[0], true).map_err(|e| format!("更新推理批次失败：{e}"))?;
        ctx.decode(&mut batch).map_err(|e| format!("生成回答失败：{e}"))?;
        pos = pos.saturating_add(1);
    }
    let decoded = String::from_utf8_lossy(&bytes);
    let final_text = decoded.rsplit_once("</think>").map_or(decoded.as_ref(), |(_, answer)| answer).trim().to_owned();
    if final_text.is_empty() { Err("本地模型没有生成可显示的回答，请换一种问法。".into()) } else { Ok(final_text) }
}

fn poll_result(state: &mut State, ctx: &egui::Context) {
    let Some(rx) = state.pending.as_ref() else { return; };
    match rx.try_recv() {
        Ok(Ok(text)) => { state.lines.push(ChatLine { role: "assistant", text }); state.pending = None; ctx.request_repaint(); }
        Ok(Err(error)) => { state.lines.push(ChatLine { role: "assistant", text: error }); state.pending = None; ctx.request_repaint(); }
        Err(mpsc::TryRecvError::Disconnected) => { state.lines.push(ChatLine { role: "assistant", text: "本地 AI 推理线程意外中断。".into() }); state.pending = None; ctx.request_repaint(); }
        Err(mpsc::TryRecvError::Empty) => ctx.request_repaint_after(std::time::Duration::from_millis(120)),
    }
}
