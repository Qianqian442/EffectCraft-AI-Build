#!/usr/bin/env python3
"""Offer the existing safe relinker immediately after an AEP import finds missing media."""
from __future__ import annotations

import os
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    n = source.count(old)
    if n != 1:
        raise SystemExit(f"{label}: expected one exact anchor, found {n}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    path = root / "crates/engine/src/cmd/aep.rs"
    if not path.is_file():
        raise SystemExit(f"After Effects desktop importer is missing: {path}")
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_AEP_AUTO_PROMPT_MISSING_MEDIA_RELINK_V1"

    if marker not in source:
        source = replace_once(
            source,
            "    let losses = res.report.total_losses();",
            """    let losses = res.report.total_losses();
    // EFFECTCRAFT_AEP_AUTO_PROMPT_MISSING_MEDIA_RELINK_V1
    let prompt_media_relink = !res.report.missing_footage.is_empty();""",
            "AEP missing-media relink trigger",
        )
        source = replace_once(
            source,
            """    s.toast(if losses == 0 {
        format!("Imported {name}")
    } else {
        format!("Imported {name} ({losses} unsupported item{} not imported)", if losses == 1 { "" } else { "s" })
    });
    Ok(json!({""",
            """    s.toast(if losses == 0 {
        format!("Imported {name}")
    } else {
        format!("Imported {name} ({losses} unsupported item{} not imported)", if losses == 1 { "" } else { "s" })
    });
    // Let the user locate external media after the project and its placeholder items exist.
    // Cancel keeps the project imported; the Relink Missing Footage menu remains available.
    if prompt_media_relink {
        s.events.push(crate::Event::Frontend {
            command: "file.relinkFootage".into(),
            params: json!({}),
        });
    }
    Ok(json!({""",
            "AEP post-import missing-media folder picker",
        )

    required = (
        marker,
        "let prompt_media_relink = !res.report.missing_footage.is_empty();",
        'command: "file.relinkFootage".into(),',
        'params: json!({}),',
    )
    for token in required:
        if token not in source:
            raise SystemExit(f"AEP automatic missing-media relink prompt is incomplete: {token}")

    path.write_text(source, encoding="utf-8")
    print("AEP imports with missing footage now offer the existing folder relinker immediately.")
    print("Cancelling the folder picker keeps the imported project and all missing-footage placeholders intact.")


if __name__ == "__main__":
    main()
