#!/usr/bin/env python3
"""Add the 8-control, prompt-free AI person cutout effect using the registered person model."""
from pathlib import Path
import os

MARKER = "EFFECTCRAFT_AI_PERSON_CUTOUT_V1"


def once(src: str, old: str, new: str, label: str) -> str:
    if new in src:
        return src
    n = src.count(old)
    if n != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {n}")
    return src.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"])
    source = root / "crates/effects/src/object_matte.rs"
    docs = root / "docs/effects.md"
    if not source.is_file() or not docs.is_file():
        raise SystemExit("Expected EffectCraft object_matte.rs and docs/effects.md")
    s = source.read_text(encoding="utf-8")
    if MARKER not in s:
        s = once(
            s,
            "pub fn specs() -> Vec<EffectSpec> {\n    vec![EffectSpec {\n",
            "pub fn specs() -> Vec<EffectSpec> {\n    let mut effects = vec![EffectSpec {\n",
            "add AI person effect to Object Matte registry",
        )
        s = once(
            s,
            "        float: true,\n    }]\n}\n\nfn f(params: &Params, id: &str) -> f64 {",
            r'''        float: true,
    }];
    // EFFECTCRAFT_AI_PERSON_CUTOUT_V1
    effects.push(EffectSpec {
        id: "ec.matte.aipersoncutout",
        name: "AI 人像抠像",
        category: "Matte",
        params: vec![
            p("strength", "抠像强度", num(50.0), slider(0.0, 100.0, 0.0, 100.0, 1)),
            p("edgeFeather", "边缘羽化", num(1.0), slider(0.0, 30.0, 0.0, 15.0, 1)),
            p("edgeRefine", "边缘细化", num(50.0), slider(0.0, 100.0, 0.0, 100.0, 1)),
            p("backgroundTransparency", "背景透明度", num(100.0), slider(0.0, 100.0, 0.0, 100.0, 1)),
            p("edgeShrink", "边缘收缩", num(0.0), slider(-100.0, 100.0, -100.0, 100.0, 1)),
            p("temporalSmoothing", "时序平滑", num(0.0), slider(0.0, 100.0, 0.0, 100.0, 1)),
            p("detailPreservation", "细节保留", num(75.0), slider(0.0, 100.0, 0.0, 100.0, 1)),
            p("quality", "AI 处理质量", Value::Enum(1), popup(&["快速", "均衡", "高质量"])),
        ],
        render: ai_person_render,
        gpu: false,
        float: true,
    });
    effects
}

fn f(params: &Params, id: &str) -> f64 {''',
            "AI person effect controls",
        )
        render_code = r'''
// EFFECTCRAFT_AI_PERSON_CUTOUT_V1
/// Automatic human/background segmentation. The dedicated MediaPipe model ignores prompts;
/// other selected mask models and the classical engine remain usable as a compatibility fallback.
fn ai_person_render(ctx: &EffectCtx, buf: Buf) -> Buf {
    if ctx.adjustment {
        return buf;
    }
    let fps = ctx.fps();
    if !fps.is_finite() || fps <= 0.0 {
        return buf;
    }
    let frame_index = roto::frame_of(ctx.time, fps);
    let layer_size = ctx.layer_size;
    let img = Arc::new(roto::layer_grid(&buf, layer_size));
    let (w, h) = (img.width as usize, img.height as usize);
    if w == 0 || h == 0 {
        return buf;
    }

    let base_specs = specs();
    let Some(base) = base_specs.iter().find(|spec| spec.id == ID) else { return buf };
    let mut matte_params = Params {
        values: base.params.iter().map(|p| (p.id.to_string(), crate::default_value(p, layer_size))).collect(),
    };
    matte_params.values.insert("objectPoint".into(), Value::Vec2([layer_size[0] * 0.5, layer_size[1] * 0.38]));
    matte_params.values.insert("useBox".into(), Value::Bool(false));
    matte_params.values.insert("objectTracking/trackObject".into(), Value::Bool(false));
    matte_params.values.insert("objectTracking/referenceFrame".into(), Value::Scalar(frame_index as f64));
    matte_params.values.insert("objectTracking/framesBefore".into(), Value::Scalar(0.0));
    matte_params.values.insert("objectTracking/framesAfter".into(), Value::Scalar(0.0));
    matte_params.values.insert("objectMatte/feather".into(), Value::Scalar(f(ctx.params, "edgeFeather").clamp(0.0, 30.0)));
    matte_params.values.insert("objectMatte/contrast".into(), Value::Scalar(f(ctx.params, "edgeRefine").clamp(0.0, 100.0)));
    matte_params.values.insert("objectMatte/shiftEdge".into(), Value::Scalar(f(ctx.params, "edgeShrink").clamp(-100.0, 100.0)));
    matte_params.values.insert("invert".into(), Value::Bool(false));
    matte_params.values.insert("view".into(), Value::Enum(0));

    let quality = match ctx.params.e("quality") {
        0 => 0.5,
        2 => 1.0,
        _ => 0.75,
    };
    let detail = (f(ctx.params, "detailPreservation").clamp(0.0, 100.0) / 100.0) as f64;
    let scale = (quality * (0.65 + detail * 0.35)).clamp(0.35, 1.0);

    let host = ctx.env.host;
    let effects = ctx.env.effect_index;
    let me = img.clone();
    let mut frame = |g: i64| -> Option<Arc<Image>> {
        if g == frame_index {
            return Some(me.clone());
        }
        let other = host?.self_at(g as f64 / fps, effects)?;
        let im = roto::layer_grid(&other, layer_size);
        (im.width as usize == w && im.height as usize == h).then(|| Arc::new(im))
    };

    let model = roto::installed_model();
    let input = MatteFrame { layer_size, fps, frame: frame_index, scale, img: &img };
    let mut alpha = match frame_matte(&matte_params, &input, model.clone(), &mut frame, &|| false) {
        FrameMatte::Alpha(a) if a.len() == w * h => a,
        _ => return buf,
    };

    // Optional two-sided matte smoothing reduces frame-to-frame flicker. Off by default because
    // it adds up to two extra model evaluations per output frame.
    let smooth = (f(ctx.params, "temporalSmoothing").clamp(0.0, 100.0) / 100.0) as f32 * 0.20;
    if smooth > 0.0 {
        let mut neighbors: Vec<Vec<f32>> = Vec::with_capacity(2);
        for offset in [-1_i64, 1_i64] {
            let nf = frame_index.saturating_add(offset);
            let Some(nimg) = frame(nf) else { continue };
            let ni = MatteFrame { layer_size, fps, frame: nf, scale, img: &nimg };
            if let FrameMatte::Alpha(a) = frame_matte(&matte_params, &ni, model.clone(), &mut frame, &|| false) {
                if a.len() == alpha.len() {
                    neighbors.push(a);
                }
            }
        }
        if !neighbors.is_empty() {
            let weight = smooth / neighbors.len() as f32;
            let current = 1.0 - weight * neighbors.len() as f32;
            for i in 0..alpha.len() {
                let mut v = alpha[i] * current;
                for n in &neighbors {
                    v += n[i] * weight;
                }
                alpha[i] = v.clamp(0.0, 1.0);
            }
        }
    }

    let strength = (f(ctx.params, "strength").clamp(0.0, 100.0) / 100.0) as f32;
    let gamma = 2.0_f32.powf((strength - 0.5) * 1.5);
    let detail_gain = detail as f32 * 0.75;
    let bg = (f(ctx.params, "backgroundTransparency").clamp(0.0, 100.0) / 100.0) as f32;
    for a in &mut alpha {
        let mut v = a.clamp(0.0, 1.0).powf(gamma);
        v = ((v - 0.5) * (1.0 + detail_gain) + 0.5).clamp(0.0, 1.0);
        *a = (v + (1.0 - v) * (1.0 - bg)).clamp(0.0, 1.0);
    }
    compose(&buf, Some(&alpha), w, h, false, false)
}

'''
        s = once(s, "fn compose(buf: &Buf, alpha: Option<&[f32]>, w: usize, h: usize, invert: bool, view_matte: bool) -> Buf {",
                 render_code + "fn compose(buf: &Buf, alpha: Option<&[f32]>, w: usize, h: usize, invert: bool, view_matte: bool) -> Buf {",
                 "AI person rendering pipeline")
        test_anchor = "    #[test]\n    fn object_matte_"
        test_code = r'''    #[test]
    fn ai_person_cutout_is_registered_with_eight_controls() {
        let effect = super::specs().into_iter().find(|s| s.id == "ec.matte.aipersoncutout").expect("AI person cutout");
        assert_eq!(effect.name, "AI 人像抠像");
        assert_eq!(effect.params.len(), 8);
        assert!(effect.params.iter().any(|p| p.id == "temporalSmoothing"));
        assert!(effect.params.iter().any(|p| p.id == "backgroundTransparency"));
    }

'''
        s = once(s, test_anchor, test_code + test_anchor, "AI person cutout regression test")
        source.write_text(s, encoding="utf-8")

    d = docs.read_text(encoding="utf-8")
    tick = chr(96)
    row = "| AI 人像抠像 | " + tick + "ec.matte.aipersoncutout" + tick + " | 8 |  | 32 | Implemented |"
    if row not in d:
        d = d.replace(
            "| Matte Choker | " + tick + "ec.matte.mattechoker" + tick + " | 7 | GPU | 32 | Implemented |\n",
            row + "\n| Matte Choker | " + tick + "ec.matte.mattechoker" + tick + " | 7 | GPU | 32 | Implemented |\n",
            1,
        )
        d = d.replace("EffectCraft ships 308 effects with 2987 parameters", "EffectCraft ships 309 effects with 2995 parameters", 1)
        d = d.replace("- **32**: 308 effects process", "- **32**: 309 effects process", 1)
        d = d.replace("- **Status**: 308 implemented in full", "- **Status**: 309 implemented in full", 1)
        docs.write_text(d, encoding="utf-8")

    check = source.read_text(encoding="utf-8")
    if MARKER not in check or check.count('"ec.matte.aipersoncutout"') < 2:
        raise SystemExit("AI person cutout effect integration did not verify")
    if row not in docs.read_text(encoding="utf-8"):
        raise SystemExit("AI person cutout effect documentation did not verify")
    print("Added AI 人像抠像 with 8 controls: strength, feather, edge refine, background transparency, edge shrink, temporal smoothing, detail preservation and quality.")


if __name__ == "__main__":
    main()
