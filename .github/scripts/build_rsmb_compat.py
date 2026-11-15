#!/usr/bin/env python3
"""Compile the standalone Android RSMB-style directional-blur compatibility effect."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


EFFECT_ID = "org.effectcraft.compat.rsmb-motion-blur"


def validate_chinese_manifest(source: str) -> dict:
    match = re.search(r'#\[cfg\(sapphire_motion\)\]\s*\{\s*r#"(.*?)"#\s*\}', source, re.S)
    if not match:
        raise SystemExit("RSMB 兼容效果清单不存在")
    try:
        manifest = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise SystemExit(f"RSMB 兼容效果清单格式错误：{error}") from error
    if manifest.get("id") != EFFECT_ID or manifest.get("api") != 1:
        raise SystemExit("RSMB 兼容效果标识或接口版本不正确")
    visible = [manifest.get("name"), manifest.get("category"), manifest.get("description"), manifest.get("author")]
    for param in manifest.get("params", []):
        visible.append(param.get("name"))
        visible.extend(param.get("options", []))
    for value in visible:
        if not isinstance(value, str) or not value.strip() or re.search(r"[A-Za-z]", value):
            raise SystemExit(f"方向运动模糊界面包含空白或英文标签：{value!r}")
    return manifest


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    source = Path(__file__).with_name("sapphire_compat_pack.rs")
    if not source.is_file():
        raise SystemExit(f"缺少方向运动模糊效果源码：{source}")
    manifest = validate_chinese_manifest(source.read_text(encoding="utf-8"))

    output = root / "assets" / "rsmb-compat"
    output.mkdir(parents=True, exist_ok=True)
    target = output / "ec_rsmb_motion_blur.wasm"
    rustc = os.environ.get("RUSTC", "rustc")
    command = [
        rustc, "--edition=2024", "--target=wasm32-unknown-unknown",
        "--crate-type=cdylib", "-C", "opt-level=z", "-C", "panic=abort",
        "--cfg", "sapphire_motion", str(source), "-o", str(target),
    ]
    print("Building standalone RSMB compatibility effect:", " ".join(command))
    subprocess.run(command, check=True)

    data = target.read_bytes()
    if len(data) < 1024 or data[:8] != b"\x00asm\x01\x00\x00\x00":
        raise SystemExit(f"Invalid or unexpectedly small RSMB WASM module: {target}")
    if EFFECT_ID.encode("utf-8") not in data:
        raise SystemExit(f"RSMB WASM does not contain its expected standalone effect id: {EFFECT_ID}")
    for export in (b"ec_api_version", b"ec_manifest_ptr", b"ec_manifest_len", b"ec_alloc", b"ec_render"):
        if export not in data:
            raise SystemExit(f"RSMB WASM export missing: {export.decode()}")

    bundle = {
        "name": "方向运动模糊兼容效果插件",
        "version": "1.0.0",
        "format": "效果工坊安全隔离效果模块",
        "desktop_binary_support": False,
        "notice": "安卓方向模糊兼容重实现；不包含电脑版原版插件或原版运动矢量估算功能。",
        "effects": [{
            "id": EFFECT_ID,
            "file": target.name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "api": 1,
        }],
    }
    (output / "bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Built standalone RSMB compatibility module at {target}")


if __name__ == "__main__":
    main()
