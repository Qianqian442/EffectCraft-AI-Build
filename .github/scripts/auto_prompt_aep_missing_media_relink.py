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
    marker = "EFFECTCRAFT_AEP_AUTO_PROMPT_MISSING_MEDIA_RELINK_V2"

    if marker not in source:
        source = replace_once(
            source,
            '    let res = s.edit("Import After Effects Project", None, |proj, st| {',
            '    let mut res = s.edit("Import After Effects Project", None, |proj, st| {',
            "make the After Effects import report updateable after media recovery",
        )
        source = replace_once(
            source,
            "    let losses = res.report.total_losses();",
            """    // EFFECTCRAFT_AEP_AUTO_PROMPT_MISSING_MEDIA_RELINK_V2
    let prompt_media_relink = !res.report.missing_footage.is_empty();
    let mut auto_relink_ok = false;
    if prompt_media_relink {
        // Reuse the same recursive, filename-and-metadata checked relinker used by
        // File > Dependencies. Scan beside the imported AEP automatically; never guess
        // between duplicate filenames or incompatible media.
        if let Some(folder) = std::path::Path::new(&path).parent().and_then(|value| value.to_str()) {
            match s.execute("file.relinkFootage", json!({"folder": folder, "wait": true})) {
                Ok(_) => auto_relink_ok = true,
                Err(error) => log::warn!("Automatic AEP package media recovery was not completed: {error}"),
            }
        }
        let imported_ids: std::collections::HashSet<_> = res.items.iter().copied().collect();
        res.report.missing_footage = res.items.iter().filter_map(|id| {
            let item = s.project.item(*id)?;
            let ItemKind::Footage(footage) = &item.kind else { return None; };
            (footage.missing && imported_ids.contains(id)).then(|| footage.path.clone())
        }).collect();
    }
    let losses = res.report.total_losses();""",
            "automatically relink extracted AEP footage and refresh missing-media diagnostics",
        )
        old_import_tail = """    s.toast(if losses == 0 {
        format!("Imported {name}")
    } else {
        format!("Imported {name} ({losses} unsupported item{} not imported)", if losses == 1 { "" } else { "s" })
    });
    Ok(json!({"""
        new_import_tail = """    s.toast(if losses == 0 {
        format!("Imported {name}")
    } else {
        format!("Imported {name} ({losses} unsupported item{} not imported)", if losses == 1 { "" } else { "s" })
    });
    if prompt_media_relink && auto_relink_ok {
        s.toast(format!(
            "工程已自动扫描素材并完成安全匹配；仍有 {} 项未能安全匹配，请手动检查。",
            res.report.missing_footage.len()
        ));
    } else if prompt_media_relink {
        s.toast("工程已导入，但自动素材扫描未能完成，请使用“文件 → 重新链接缺失素材”。");
    }
    Ok(json!({"""
        source = replace_once(source, old_import_tail, new_import_tail, "AEP post-import missing-media guidance")

    required = (
        marker,
        "let mut res = s.edit(\"Import After Effects Project\"",
        "let prompt_media_relink = !res.report.missing_footage.is_empty();",
        's.execute("file.relinkFootage", json!({"folder": folder, "wait": true}))',
        "res.report.missing_footage = res.items.iter().filter_map",
        "自动扫描并恢复素材",
    )
    for token in required:
        if token not in source:
            raise SystemExit(f"AEP automatic missing-media relink prompt is incomplete: {token}")

    path.write_text(source, encoding="utf-8")
    print("AEP imports with missing footage now offer the existing folder relinker immediately.")
    print("Ambiguous or incompatible package assets remain as missing-footage placeholders; unique metadata-compatible files are relinked automatically.")


if __name__ == "__main__":
    main()
