#!/usr/bin/env python3
"""Register Google's lightweight MediaPipe Selfie Segmenter as an on-device mask model."""
from pathlib import Path
import os

MARKER = "EFFECTCRAFT_MEDIAPIPE_SELFIE_SEGMENTER_V1"


def once(src: str, old: str, new: str, label: str) -> str:
    if new in src:
        return src
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return src.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"])
    path = root / "crates/segment/src/lib.rs"
    src = path.read_text(encoding="utf-8")
    if MARKER in src:
        print("MediaPipe Selfie Segmenter already integrated.")
        return

    info = r'''
/// MediaPipe Selfie Segmenter (Google, Apache-2.0): lightweight person/background mask.
pub const SELFIE_SEGMENTER: ModelInfo = ModelInfo {
    id: "mediapipe-selfie-segmenter",
    task: Task::Mask,
    name: "MediaPipe 人像分割",
    description: "Google's MobileNetV3-like on-device person/background segmenter. Produces a soft person mask for video background removal.",
    authors: "Tingbo Hou, Siargy Pisarchyk and Karthik Raveendran (Google / MediaPipe)",
    licence: "Apache-2.0",
    licence_url: "https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Selfie%20Segmentation.pdf",
    homepage: "https://developers.google.com/edge/mediapipe/solutions/vision/image_segmenter",
    url: "https://huggingface.co/litert-community/MediaPipe-ImageSegmenter-Selfie-Square/resolve/main/selfie_segmenter.tflite",
    source: "https://huggingface.co/litert-community/MediaPipe-ImageSegmenter-Selfie-Square/resolve/main/selfie_segmenter.tflite",
    file_name: "selfie_segmenter.tflite",
    size: 249_537,
    sha256: "191ac9529ae506ee0beefa6b2c945a172dab9d07d1e802a290a4e4038226658b",
};
'''
    src = once(src, "/// The trained models, besides the built-in classical engines.\n",
               info + "\n/// The trained models, besides the built-in classical engines.\n",
               "selfie segmenter model registry")
    src = src.replace(
        "pub const MODELS: &[ModelInfo] = &[MOBILE_SAM, SAM2_TINY, SAM2_SMALL, SAM2_BASE_PLUS, SAM2_LARGE, FACE_LANDMARKER];",
        "pub const MODELS: &[ModelInfo] = &[MOBILE_SAM, SAM2_TINY, SAM2_SMALL, SAM2_BASE_PLUS, SAM2_LARGE, FACE_LANDMARKER, SELFIE_SEGMENTER];",
        1,
    )
    if "SELFIE_SEGMENTER" not in src or "FACE_LANDMARKER, SELFIE_SEGMENTER" not in src:
        raise SystemExit("Could not add Selfie Segmenter to the model registry")

    src = once(
        src,
        "        Some(Loader::MediaPipe) => Ok(Loaded::Face(Arc::new(mediapipe::FaceLandmarker::from_task(bytes)?))),\n",
        "        Some(Loader::MediaPipe) => Ok(Loaded::Face(Arc::new(mediapipe::FaceLandmarker::from_task(bytes)?))),\n"
        "        Some(Loader::SelfieSegmenter) => Ok(Loaded::Mask(Arc::new(SelfieSegmenter { net: tflite::Model::read(bytes)? }))),\n",
        "selfie segmenter loader",
    )
    src = once(
        src,
        "    MediaPipe,\n",
        "    MediaPipe,\n    SelfieSegmenter,\n",
        "selfie segmenter loader enum",
    )
    src = once(
        src,
        '        "mediapipe-face" => Some(Loader::MediaPipe),\n',
        '        "mediapipe-face" => Some(Loader::MediaPipe),\n        "mediapipe-selfie-segmenter" => Some(Loader::SelfieSegmenter),\n',
        "selfie segmenter loader dispatch",
    )

    impl_code = r'''
// EFFECTCRAFT_MEDIAPIPE_SELFIE_SEGMENTER_V1
/// Google's tiny TFLite person/background network. The prompt is intentionally ignored:
/// unlike SAM, this model detects prominent people without clicks or boxes.
struct SelfieSegmenter {
    net: tflite::Model,
}

impl MaskModel for SelfieSegmenter {
    fn info(&self) -> &'static ModelInfo {
        &SELFIE_SEGMENTER
    }

    fn segment(&self, rgb: &[[f32; 3]], w: usize, h: usize, _prompt: &Prompt) -> Result<Vec<f32>> {
        const SIDE: usize = 256;
        if w == 0 || h == 0 || w.checked_mul(h) != Some(rgb.len()) || w.max(h) > 8192 {
            return Err("Selfie Segmenter received invalid frame dimensions".into());
        }
        if self.net.input_shape(0) != Some(&[1, SIDE, SIDE, 3][..])
            || self.net.output(0).map(|(shape, _)| shape) != Some(&[1, SIDE, SIDE, 1][..])
        {
            return Err("Selfie Segmenter model tensor layout is not the verified 256×256 RGB mask layout".into());
        }

        // Fit the complete frame into the square input. Letterboxing avoids cropping a person's
        // head or feet; the output mask is cropped back to the same fitted rectangle.
        let scale = (SIDE as f64 / w as f64).min(SIDE as f64 / h as f64);
        let rw = ((w as f64 * scale).round() as usize).clamp(1, SIDE);
        let rh = ((h as f64 * scale).round() as usize).clamp(1, SIDE);
        let ox = (SIDE - rw) / 2;
        let oy = (SIDE - rh) / 2;
        let mut input = vec![0.0f32; SIDE * SIDE * 3];
        for y in 0..rh {
            for x in 0..rw {
                let sx = ((x as f64 + 0.5) * w as f64 / rw as f64 - 0.5).clamp(0.0, (w - 1) as f64);
                let sy = ((y as f64 + 0.5) * h as f64 / rh as f64 - 0.5).clamp(0.0, (h - 1) as f64);
                let x0 = sx.floor() as usize;
                let y0 = sy.floor() as usize;
                let x1 = (x0 + 1).min(w - 1);
                let y1 = (y0 + 1).min(h - 1);
                let fx = (sx - x0 as f64) as f32;
                let fy = (sy - y0 as f64) as f32;
                let a = rgb[y0 * w + x0];
                let b = rgb[y0 * w + x1];
                let c = rgb[y1 * w + x0];
                let d = rgb[y1 * w + x1];
                let dst = ((oy + y) * SIDE + ox + x) * 3;
                for ch in 0..3 {
                    let top = a[ch] + (b[ch] - a[ch]) * fx;
                    let bottom = c[ch] + (d[ch] - c[ch]) * fx;
                    input[dst + ch] = (top + (bottom - top) * fy).clamp(0.0, 1.0);
                }
            }
        }

        let outputs = self.net.run(&[&input])?;
        let mask = outputs.first().ok_or("Selfie Segmenter returned no mask")?;
        if mask.len() != SIDE * SIDE {
            return Err(format!("Selfie Segmenter returned {} values; expected {}", mask.len(), SIDE * SIDE));
        }
        let mut out = vec![0.0f32; w * h];
        for y in 0..h {
            for x in 0..w {
                let mx = ox as f64 + (x as f64 + 0.5) * rw as f64 / w as f64 - 0.5;
                let my = oy as f64 + (y as f64 + 0.5) * rh as f64 / h as f64 - 0.5;
                let mx = mx.clamp(0.0, (SIDE - 1) as f64);
                let my = my.clamp(0.0, (SIDE - 1) as f64);
                let x0 = mx.floor() as usize;
                let y0 = my.floor() as usize;
                let x1 = (x0 + 1).min(SIDE - 1);
                let y1 = (y0 + 1).min(SIDE - 1);
                let fx = (mx - x0 as f64) as f32;
                let fy = (my - y0 as f64) as f32;
                let a = mask[y0 * SIDE + x0];
                let b = mask[y0 * SIDE + x1];
                let c = mask[y1 * SIDE + x0];
                let d = mask[y1 * SIDE + x1];
                let top = a + (b - a) * fx;
                let bottom = c + (d - c) * fx;
                out[y * w + x] = (top + (bottom - top) * fy).clamp(0.0, 1.0);
            }
        }
        Ok(out)
    }
}

'''
    src = once(src, "struct Sam {\n", impl_code + "struct Sam {\n", "selfie segmenter implementation")
    path.write_text(src, encoding="utf-8")

    attribution = root / "ATTRIBUTION.md"
    if attribution.exists():
        a = attribution.read_text(encoding="utf-8")
        entry = "\n- **MediaPipe Selfie Segmentation** — Tingbo Hou, Siargy Pisarchyk and Karthik Raveendran (Google); Apache-2.0; lightweight on-device human/background segmentation model. Model card: https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Selfie%20Segmentation.pdf\n"
        if "MediaPipe Selfie Segmentation" not in a:
            attribution.write_text(a.rstrip() + "\n" + entry, encoding="utf-8")

    print("Registered Google's 249,537-byte Apache-2.0 Selfie Segmenter TFLite model and its prompt-free MaskModel adapter.")
    print("Model download is SHA-256 verified by the existing model manager; no model weights are bundled into the base APK.")


if __name__ == "__main__":
    main()
