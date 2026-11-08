//! Local RIFE / Real-ESRGAN video processing bridge.
use std::{
    env,
    io::{Read, Write},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::{Mutex, OnceLock},
};

use effectcraft_raster::Image;

struct VideoWorker {
    child: Child,
    stdin: ChildStdin,
    stdout: ChildStdout,
}

static WORKER: OnceLock<Mutex<Option<VideoWorker>>> = OnceLock::new();

impl VideoWorker {
    fn start() -> Result<Self, String> {
        let worker_path = env::var("EFFECTCRAFT_AI_VIDEO_WORKER_PATH")
            .map_err(|_| "APK 中未找到本地视频 AI 推理程序".to_string())?;
        let rife_model = env::var("EFFECTCRAFT_RIFE_MODEL_PATH")
            .map_err(|_| "APK 中未找到 RIFE 4.6 模型".to_string())?;
        let sr_param = env::var("EFFECTCRAFT_ESRGAN_PARAM_PATH")
            .map_err(|_| "APK 中未找到 Real-ESRGAN 参数文件".to_string())?;
        let sr_model = env::var("EFFECTCRAFT_ESRGAN_MODEL_PATH")
            .map_err(|_| "APK 中未找到 Real-ESRGAN 权重文件".to_string())?;

        let mut child = Command::new(worker_path)
            .arg(rife_model)
            .arg(sr_param)
            .arg(sr_model)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| format!("启动本地视频 AI 引擎失败：{e}"))?;

        let stdin = match child.stdin.take() {
            Some(value) => value,
            None => {
                let _ = child.kill();
                let _ = child.wait();
                return Err("无法连接视频 AI 输入管道".into());
            }
        };
        let mut stdout = match child.stdout.take() {
            Some(value) => value,
            None => {
                let _ = child.kill();
                let _ = child.wait();
                return Err("无法连接视频 AI 输出管道".into());
            }
        };
        let ready = match read_u32(&mut stdout) {
            Ok(value) => value,
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("本地视频 AI 引擎启动握手失败：{error}"));
            }
        };
        if ready != 0 {
            let _ = child.kill();
            let _ = child.wait();
            return Err("本地 RIFE / Real-ESRGAN 模型加载失败".into());
        }
        Ok(Self { child, stdin, stdout })
    }

    fn process(&mut self, op: u32, first: &Image, second: Option<&Image>, timestep: f32, background: [f32; 3]) -> Result<Image, String> {
        let width = first.width;
        let height = first.height;
        if width == 0 || height == 0 || width > 2048 || height > 2048 {
            return Err("当前本地 RIFE / Real-ESRGAN 推理接口的单边输入尺寸上限为 2048 像素".into());
        }
        if let Some(other) = second {
            if other.width != width || other.height != height {
                return Err("RIFE 输入帧尺寸不一致".into());
            }
        }

        let a = to_rgb(first, background)?;
        let b = second.map(|img| to_rgb(img, background)).transpose()?;

        self.stdin.write_all(&op.to_le_bytes()).map_err(|e| format!("发送视频 AI 请求失败：{e}"))?;
        self.stdin.write_all(&width.to_le_bytes()).map_err(|e| format!("发送视频宽度失败：{e}"))?;
        self.stdin.write_all(&height.to_le_bytes()).map_err(|e| format!("发送视频高度失败：{e}"))?;
        self.stdin.write_all(&timestep.to_le_bytes()).map_err(|e| format!("发送 RIFE 时间参数失败：{e}"))?;
        self.stdin.write_all(&a).map_err(|e| format!("发送视频帧失败：{e}"))?;
        if let Some(bytes) = &b {
            self.stdin.write_all(bytes).map_err(|e| format!("发送第二帧失败：{e}"))?;
        }
        self.stdin.flush().map_err(|e| format!("提交视频 AI 请求失败：{e}"))?;

        let status = read_u32(&mut self.stdout)? as i32;
        let out_width = read_u32(&mut self.stdout)?;
        let out_height = read_u32(&mut self.stdout)?;
        let out_bytes = read_u64(&mut self.stdout)?;
        if status != 0 {
            return Err(if op == 1 {
                "RIFE 4.6 插帧推理失败".into()
            } else {
                "Real-ESRGAN 超分推理失败".into()
            });
        }
        let expected = (out_width as u64)
            .checked_mul(out_height as u64)
            .and_then(|v| v.checked_mul(3))
            .ok_or_else(|| "视频 AI 返回的尺寸溢出".to_string())?;
        if out_width == 0 || out_height == 0 || out_width > 8192 || out_height > 8192 || out_bytes != expected {
            return Err("视频 AI 引擎返回了无效的画面尺寸".into());
        }
        let output_len = usize::try_from(out_bytes)
            .map_err(|_| "视频 AI 输出大小超出当前系统可寻址范围".to_string())?;
        let mut pixels = Vec::new();
        pixels.try_reserve_exact(output_len)
            .map_err(|_| "系统无法为当前 AI 输出分配足够内存，请降低分辨率或关闭 AI 处理".to_string())?;
        pixels.resize(output_len, 0u8);
        self.stdout.read_exact(&mut pixels).map_err(|e| format!("读取视频 AI 结果失败：{e}"))?;
        Ok(from_rgb(out_width, out_height, &pixels))
    }
}

impl Drop for VideoWorker {
    fn drop(&mut self) {
        // Do not leave an orphaned inference subprocess when an export is cancelled or the app closes.
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn worker() -> Result<std::sync::MutexGuard<'static, Option<VideoWorker>>, String> {
    let shared = WORKER.get_or_init(|| Mutex::new(None));
    shared.lock().map_err(|_| "本地视频 AI 引擎锁已损坏".into())
}

fn is_transport_error(error: &str) -> bool {
    ["发送", "读取", "提交"].iter().any(|prefix| error.starts_with(prefix))
}

fn process_with_recovery(
    op: u32,
    first: &Image,
    second: Option<&Image>,
    timestep: f32,
    background: [f32; 3],
) -> Result<Image, String> {
    let mut slot = worker()?;
    let worker_exited = match slot.as_mut() {
        Some(existing) => match existing.child.try_wait() {
            Ok(status) => status.is_some(),
            Err(_) => true,
        },
        None => true,
    };
    if worker_exited {
        slot.take();
        *slot = Some(VideoWorker::start()?);
    }

    let result = slot.as_mut()
        .ok_or_else(|| "本地视频 AI 引擎尚未启动".to_string())?
        .process(op, first, second, timestep, background);

    let broken_pipe = result.as_ref().err().map(|error| is_transport_error(error)).unwrap_or(false);
    if broken_pipe {
        // A native AI worker crash is isolated from the editor. Recreate it once and retry this frame.
        slot.take();
        *slot = Some(VideoWorker::start()?);
        return slot.as_mut()
            .ok_or_else(|| "本地视频 AI 引擎重启失败".to_string())?
            .process(op, first, second, timestep, background);
    }
    result
}

fn read_u32(reader: &mut impl Read) -> Result<u32, String> {
    let mut bytes = [0u8; 4];
    reader.read_exact(&mut bytes).map_err(|e| format!("读取视频 AI 状态失败：{e}"))?;
    Ok(u32::from_le_bytes(bytes))
}

fn read_u64(reader: &mut impl Read) -> Result<u64, String> {
    let mut bytes = [0u8; 8];
    reader.read_exact(&mut bytes).map_err(|e| format!("读取视频 AI 数据长度失败：{e}"))?;
    Ok(u64::from_le_bytes(bytes))
}

fn to_rgb(image: &Image, background: [f32; 3]) -> Result<Vec<u8>, String> {
    let rgba = image.to_rgba8_over(background);
    let byte_len = (image.width as usize)
        .checked_mul(image.height as usize)
        .and_then(|pixels| pixels.checked_mul(3))
        .ok_or_else(|| "视频 AI 输入画面尺寸溢出".to_string())?;
    let mut rgb = Vec::new();
    rgb.try_reserve_exact(byte_len)
        .map_err(|_| "系统无法为当前 AI 输入分配足够内存".to_string())?;
    for pixel in rgba.chunks_exact(4) {
        rgb.extend_from_slice(&pixel[..3]);
    }
    Ok(rgb)
}

fn from_rgb(width: u32, height: u32, rgb: &[u8]) -> Image {
    let mut image = Image::new(width, height);
    for (pixel, bytes) in image.data.iter_mut().zip(rgb.chunks_exact(3)) {
        *pixel = [
            bytes[0] as f32 / 255.0,
            bytes[1] as f32 / 255.0,
            bytes[2] as f32 / 255.0,
            1.0,
        ];
    }
    image
}

/// Synthesize one in-between frame with the locally bundled RIFE 4.6 model.
pub(crate) fn interpolate(first: &Image, second: &Image, timestep: f32, background: [f32; 3]) -> Result<Image, String> {
    if !(0.0..=1.0).contains(&timestep) {
        return Err("RIFE 插帧时间必须在 0 到 1 之间".into());
    }
    process_with_recovery(1, first, Some(second), timestep, background)
}

/// Apply local Real-ESRGAN x4 super-resolution to one rendered frame.
pub(crate) fn upscale(frame: &Image, background: [f32; 3]) -> Result<Image, String> {
    process_with_recovery(2, frame, None, 0.0, background)
}
