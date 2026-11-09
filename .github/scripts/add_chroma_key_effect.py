#!/usr/bin/env python3
"""Add a dedicated Chroma Key effect with color presets and custom eyedropper sampling."""
from __future__ import annotations

import os
from pathlib import Path


MARKER = "EFFECTCRAFT_ANDROID_CHROMA_KEY_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    keying_path = root / "crates/effects/src/keying.rs"
    i18n_path = root / "crates/ui-egui/src/i18n/effects.rs"
    if not root.is_dir() or not keying_path.is_file() or not i18n_path.is_file():
        raise SystemExit("EFFECTCRAFT_DIR must point to EffectCraft source with keying.rs and i18n/effects.rs")

    keying = keying_path.read_text(encoding="utf-8")
    if MARKER not in keying:
        function = r'''
// EFFECTCRAFT_ANDROID_CHROMA_KEY_V1
/// Chroma Key with common screen-colour presets and an arbitrary sampled/custom colour.
fn chroma_key(ctx: &EffectCtx, mut b: Buf) -> Buf {
    let preset = ctx.params.e("keyPreset");
    let custom = ctx.params.color("keyColor");
    let key = match preset {
        0 => [0.0, 1.0, 0.0], // green
        1 => [0.0, 0.0, 1.0], // blue
        2 => [1.0, 0.0, 0.0], // red
        3 => [1.0, 1.0, 0.0], // yellow
        4 => [0.0, 1.0, 1.0], // cyan
        5 => [1.0, 0.0, 1.0], // magenta
        6 => [1.0, 1.0, 1.0], // white
        7 => [0.0, 0.0, 0.0], // black
        _ => [custom[0], custom[1], custom[2]], // custom / eyedropper
    };
    let mode = ctx.params.e("matchMode");
    let tolerance = ctx.params.f("tolerance") as f32 / 100.0;
    let softness = ctx.params.f("softness") as f32 / 100.0;
    let keep = ctx.params.e("keyOperation") == 1;
    let key_chroma = chroma(key);
    let matte = matte_of(&b.img, |colour, _| {
        let distance = match mode {
            1 => hue_dist(colour, key),
            2 => {
                let sample = chroma(colour);
                ((sample[0] - key_chroma[0]).powi(2) + (sample[1] - key_chroma[1]).powi(2)).sqrt()
                    / std::f32::consts::SQRT_2
            }
            _ => {
                ((colour[0] - key[0]).powi(2)
                    + (colour[1] - key[1]).powi(2)
                    + (colour[2] - key[2]).powi(2))
                .sqrt()
                    / 3.0_f32.sqrt()
            }
        };
        let matched = if softness > 1e-6 {
            ((distance - tolerance) / softness).clamp(0.0, 1.0)
        } else if distance > tolerance {
            1.0
        } else {
            0.0
        };
        if keep { 1.0 - matched } else { matched }
    });
    let matte = thin_feather(
        matte,
        ctx.params.f("edgeThin") * b.scale,
        ctx.params.f("edgeFeather") * b.scale,
    );
    apply_matte(&mut b.img, &matte, ctx.params.e("view"));
    b
}

'''
        keying = replace_once(
            keying,
            "// ---- Color Key (obsolete) ----",
            function + "// ---- Color Key (obsolete) ----",
            "chroma key renderer insertion",
        )

        spec_anchor = '''        spec(
            "ec.key.colorkey",
'''
        chroma_spec = '''        spec(
            "ec.key.chromakey",
            "Chroma Key",
            "Keying",
            vec![
                p("view", "预览模式", Value::Enum(0), popup(&["最终结果", "原始画面", "遮罩预览"])),
                p("keyPreset", "扣图颜色", Value::Enum(0), popup(&["绿色", "蓝色", "红色", "黄色", "青色", "洋红", "白色", "黑色", "自定义"])),
                p("keyColor", "自定义颜色", col(0.0, 1.0, 0.0), ParamUi::Color),
                p("matchMode", "颜色匹配方式", Value::Enum(0), popup(&["RGB 颜色", "色相", "色度"])),
                p("tolerance", "匹配容差", num(22.0), pct()),
                p("softness", "边缘过渡", num(12.0), pct()),
                p("keyOperation", "扣图方式", Value::Enum(0), popup(&["移除所选颜色", "仅保留所选颜色"])),
                p("edgeThin", "边缘收缩 / 扩展", num(0.0), thin()),
                p("edgeFeather", "边缘羽化", num(0.0), feather()),
            ],
            chroma_key,
        ),
'''
        keying = replace_once(keying, spec_anchor, chroma_spec + spec_anchor, "chroma key effect registration")

        test_anchor = '''    #[test]
    fn linear_color_key_removes_green() {
'''
        tests = '''    #[test]
    fn chroma_key_removes_green_with_preset() {
        let out = run("ec.key.chromakey", &[], green_screen());
        assert!(out.get(2, 2)[3] < 0.01, "{:?}", out.get(2, 2));
        assert!(out.get(12, 2)[3] > 0.99, "{:?}", out.get(12, 2));
    }

    #[test]
    fn chroma_key_supports_custom_sampled_color() {
        let out = run(
            "ec.key.chromakey",
            &[
                ("keyPreset", Value::Enum(8)),
                ("keyColor", green()),
            ],
            green_screen(),
        );
        assert!(out.get(2, 2)[3] < 0.01, "{:?}", out.get(2, 2));
        assert!(out.get(12, 2)[3] > 0.99, "{:?}", out.get(12, 2));
    }

'''
        keying = replace_once(keying, test_anchor, tests + test_anchor, "chroma key tests")
        if MARKER not in keying or keying.count('"ec.key.chromakey"') < 3:
            raise SystemExit("Chroma Key renderer / registry markers did not validate")
        keying_path.write_text(keying, encoding="utf-8")

    i18n = i18n_path.read_text(encoding="utf-8")
    row = '    ("ec.key.chromakey", "Chroma Key", "色度键"),\n'
    if row not in i18n:
        anchor = '    ("ec.key.colordifference", "Color Difference Key", "颜色差值键"),\n'
        i18n = replace_once(i18n, anchor, row + anchor, "Simplified Chinese Chroma Key name")
    i18n_path.write_text(i18n, encoding="utf-8")

    if MARKER not in keying_path.read_text(encoding="utf-8") or row not in i18n_path.read_text(encoding="utf-8"):
        raise SystemExit("Chroma Key integration verification failed")
    print("Added Chroma Key to the Keying effects menu with green, blue, red, yellow, cyan, magenta, white, black and custom color selection.")
    print("Custom color uses Effect Controls' existing color picker and viewer eyedropper; tolerance, softness, edge-thin and feather controls are included.")


if __name__ == "__main__":
    main()
