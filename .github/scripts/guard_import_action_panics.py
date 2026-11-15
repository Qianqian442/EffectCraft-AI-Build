#!/usr/bin/env python3
"""Convert Rust panics from file import commands into a recoverable error state."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_IMPORT_PANIC_ISOLATION_V1"


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/ui-egui/src/menus/frontend.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return

    old = "    let r = app.session.execute(id, Value::Object(p)).map_err(|e| e.to_string());"
    new = r'''    // EFFECTCRAFT_ANDROID_IMPORT_PANIC_ISOLATION_V1
    // A malformed archive/parser panic must not unwind through the Android UI loop.
    let r = match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        app.session.execute(id, Value::Object(p)).map_err(|e| e.to_string())
    })) {
        Ok(result) => result,
        Err(payload) => {
            let detail = payload.downcast_ref::<&str>().map(|value| (*value).to_string())
                .or_else(|| payload.downcast_ref::<String>().cloned())
                .unwrap_or_else(|| "unknown importer panic".to_string());
            eprintln!("EffectCraft file action panic isolated: {detail}");
            Err("导入操作遇到异常，已隔离本次错误。请检查工程文件是否完整、格式是否正确，然后重试。".to_string())
        }
    };'''
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"Expected one shared file-action execution point, found {count}.")
    source = source.replace(old, new, 1)
    if MARKER not in source or "catch_unwind" not in source:
        raise SystemExit("File-import panic isolation was not installed.")
    path.write_text(source, encoding="utf-8")
    print("Installed a recoverable panic boundary around file-picker command execution.")


if __name__ == "__main__":
    main()
