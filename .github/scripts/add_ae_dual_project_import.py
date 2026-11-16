#!/usr/bin/env python3
"""Add separate desktop AE and EffectCraft-mobile exported-project import entries."""
from __future__ import annotations

import os
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    aep = root / "crates/engine/src/cmd/aep.rs"
    am_nv = root / "crates/engine/src/cmd/am_nv.rs"
    frontend = root / "crates/ui-egui/src/menus/frontend.rs"
    menu = root / "crates/engine/src/menus.rs"
    losses = root / "crates/ui-egui/src/panels/aep_losses.rs"

    for path in (aep, am_nv, frontend, menu, losses):
        if not path.is_file():
            raise SystemExit(f"Required project-import source is missing: {path}")

    aep_source = aep.read_text(encoding="utf-8")
    if "pub(crate) fn import_aep(" not in aep_source:
        raise SystemExit("The original AE desktop importer is not available")
    if "file.importAepDesktop" not in aep_source:
        replace_once(
            aep,
            "pub fn specs() -> Vec<CommandSpec> {\n    vec![cmd!(",
            """pub fn specs() -> Vec<CommandSpec> {
    vec![
        cmd!("file.importAepDesktop", "AE Desktop Project...", ["File", "Import"], None,
            "{path (.aep or .aepx)} — imports an Adobe After Effects desktop project",
            always, import_aep),
        cmd!(""",
            "register the separate desktop AE import command",
        )

    # EffectCraft mobile exports are native .ecproj/.ecprojx files. The Share action
    # packages the collected .ecproj and its Footage directory into a ZIP. Import those
    # formats through the existing native EffectCraft project reader, never the AEP parser.
    am_nv_source = am_nv.read_text(encoding="utf-8")
    if "file.importEffectCraftMobile" not in am_nv_source:
        mobile_command = """fn import_effectcraft_mobile_project(s: &mut Session, p: &J) -> Result<J> {
    let path = p.get("path").and_then(J::as_str)
        .ok_or_else(|| err("缺少自有工程路径"))?.to_string();
    let actual = match ext(&path).as_str() {
        "ecproj" | "ecprojx" => path,
        "zip" => {
            let (actual, _package_root) = extract_project_zip(s, &path)?;
            if !matches!(ext(&actual).as_str(), "ecproj" | "ecprojx") {
                return Err(err("ZIP 中没有找到自有工程 .ecproj/.ecprojx 文件"));
            }
            actual
        }
        _ => return Err(err("自有工程仅支持 .ecproj、.ecprojx，或包含工程文件及素材的 ZIP 包")),
    };
    super::import_project::import_project(s, &json!({"path": actual}))
}

"""
        replace_once(
            am_nv,
            "pub fn specs() -> Vec<CommandSpec> {\n    vec![",
            mobile_command + """pub fn specs() -> Vec<CommandSpec> {
    vec![
        cmd!("file.importEffectCraftMobile", "自有工程包...", ["File", "Import"], None,
            "{path (.ecproj/.ecprojx or .zip containing the project and collected footage)} — 导入 Ae 自有工程及其收集的素材",
            always, import_effectcraft_mobile_project),
""",
            "register EffectCraft mobile-export project import",
        )

    replace_once(
        am_nv,
        'let file = project_file.ok_or_else(|| err("该 ZIP 不包含自有工程 .ecproj/.ecprojx、NodeVideo .nv 或 Alight Motion XML 工程"))?;',
        'let file = project_file.ok_or_else(|| err("该 ZIP 不包含自有工程 .ecproj/.ecprojx、NodeVideo .nv 或 Alight Motion XML 工程"))?;',
        "explain supported project types in ZIP errors",
    )

    frontend_source = frontend.read_text(encoding="utf-8")
    if '        "file.importAep" => ("path", Ask::Open(&["aep", "aepx"])),' not in frontend_source:
        raise SystemExit("The original After Effects project picker changed unexpectedly")
    replace_once(
        frontend,
        '        "file.importAep" => ("path", Ask::Open(&["aep", "aepx"])),',
        """        "file.importAepDesktop" => ("path", Ask::Open(&["aep", "aepx"])),
        "file.importEffectCraftMobile" => ("path", Ask::Open(&["ecproj", "ecprojx", "zip"])),
        "file.importAep" => ("path", Ask::Open(&["aep", "aepx"])),""",
        "add distinct desktop-AE and EffectCraft-mobile file pickers",
    )

    replace_once(
        menu,
        "      After Effects Project... | file.importAep\n",
        """      AE 电脑版工程... | file.importAepDesktop
      自有工程包... | file.importEffectCraftMobile
      After Effects Project... | file.importAep
""",
        "add distinct desktop AE and EffectCraft mobile import menu entries",
    )

    # Keep the original AE dry-run/loss-consent path and apply it to the new desktop alias.
    replace_once(
        losses,
        '    let command = if id == "file.importAep" {\n        Some("file.importAep")',
        '    let command = if id == "file.importAep" || id == "file.importAepDesktop" {\n        Some(id)',
        "protect the new desktop AE entry with the original loss confirmation",
    )

    replace_once(
        losses,
        "/// A loss category (`snake_case` in the report) as words: `layer_styles` → `Layer styles`.",
        """/// Whether the report contains actionable, project-specific issues that the user should review.
/// The reader publishes standing format limitations for every parsed project. Always make the
/// user review that compatibility envelope before committing an import, even if this particular
/// project has no counted losses or missing assets.
fn needs_prompt(report: &Value) -> bool {
    report["losses"].as_array().is_some_and(|items| !items.is_empty())
        || report["missingFootage"].as_array().is_some_and(|items| !items.is_empty())
        || report["missingFonts"].as_array().is_some_and(|items| !items.is_empty())
        || report["limitations"].as_array().is_some_and(|items| !items.is_empty())
}

/// Import diagnostics that are distinct from counted losses. These are shown alongside the
/// loss categories so users can relink media and install fonts before judging the result.
fn diagnostics(report: &Value) -> Vec<(String, Vec<String>)> {
    const MAX_DETAILS: usize = 20;
    let mut result = Vec::new();
    for (key, title) in [
        ("missingFootage", "Missing footage — relink these files before final render"),
        ("missingFonts", "Missing fonts — fallback font will be used"),
        ("limitations", "Reader limitations — these fields are not currently decoded"),
    ] {
        let Some(values) = report[key].as_array() else { continue };
        if values.is_empty() {
            continue;
        }
        let mut details: Vec<String> = values.iter()
            .filter_map(Value::as_str)
            .take(MAX_DETAILS)
            .map(str::to_string)
            .collect();
        if values.len() > MAX_DETAILS {
            details.push(format!("… and {} more", values.len() - MAX_DETAILS));
        }
        result.push((format!("{} ({})", tr(title), values.len()), details));
    }
    result
}

/// Counts of the content the importer recognised. The counts are evidence of parsing, not a
/// promise that the imported project renders identically to After Effects.
fn imported_lines(report: &Value) -> Vec<String> {
    const FIELDS: &[(&str, &str)] = &[
        ("folders", "文件夹"), ("compositions", "合成"), ("solids", "纯色素材"),
        ("footage", "素材文件"), ("layers", "图层"), ("solidLayers", "纯色图层"),
        ("nullLayers", "空对象图层"), ("adjustmentLayers", "调整图层"),
        ("footageLayers", "素材图层"), ("precompLayers", "预合成图层"),
        ("textLayers", "文字图层"), ("keyframes", "关键帧"), ("expressions", "表达式"),
        ("masks", "蒙版"), ("trackMattes", "轨道遮罩"), ("markers", "标记"),
        ("timeRemaps", "时间重映射"), ("shapeLayers", "形状图层"), ("shapeItems", "形状项目"),
        ("cameras", "摄像机"), ("lights", "灯光"), ("textAnimators", "文字动画器"),
        ("effects", "效果实例"), ("layerStyles", "图层样式"),
    ];
    let mut labels: Vec<String> = FIELDS.iter()
        .filter_map(|(key, label)| report["imported"][*key].as_u64()
            .filter(|count| *count > 0)
            .map(|count| format!("{label} {count}")))
        .collect();
    if labels.is_empty() {
        return vec!["未识别到可导入的工程项目".to_string()];
    }
    let mut rows = Vec::new();
    while !labels.is_empty() {
        let take = labels.len().min(4);
        let rest = labels.split_off(take);
        rows.push(labels.join("  ·  "));
        labels = rest;
    }
    rows
}

/// A loss category (`snake_case` in the report) as words: `layer_styles` → `Layer styles`.""",
        "show missing-media, missing-font and reader-limit diagnostics",
    )
    replace_once(
        losses,
        '    if report["losses"].as_array().is_none_or(|l| l.is_empty()) {\n        return Ok(false);\n    }',
        '    if !needs_prompt(&report) {\n        return Ok(false);\n    }',
        "run the full project-specific and reader-limitation preflight guard",
    )
    replace_once(
        losses,
        "const DETAILS: usize = 3;",
        "const DETAILS: usize = 20;",
        "show up to twenty concrete examples for every loss category",
    )
    replace_once(
        losses,
        '        let text = tr("Some parts of this project cannot be imported exactly (left out or changed):");',
        '        let text = tr("Review items that may be missing, substituted, or not fully supported before importing:");',
        "make the import-review heading cover missing and substituted content",
    )
    replace_once(
        losses,
        '            let label = tr("Import Anyway");',
        '            let label = "继续导入（仍有未支持内容）";',
        "make the partial-import consent explicit",
    )
    replace_once(
        losses,
        """            for (head, details) in lines(&report) {
                ui.label(egui::RichText::new(head).color(t.tab_text_active));
                for d in details {
                    ui.label(egui::RichText::new(format!("    {d}")).color(t.text_dim).size(11.0));
                }
            }""",
        """            ui.label(egui::RichText::new("预计识别并导入的内容：").color(t.tab_text_active));
            for line in imported_lines(&report) {
                ui.label(egui::RichText::new(format!("    {line}")).color(t.text_dim).size(11.0));
            }
            ui.separator();
            ui.label(egui::RichText::new("未支持、替代或需要处理的内容：").color(t.tab_text_active));
            for (head, details) in lines(&report) {
                ui.label(egui::RichText::new(head).color(t.tab_text_active));
                for d in details {
                    ui.label(egui::RichText::new(format!("    {d}")).color(t.text_dim).size(11.0));
                }
            }
            for (head, details) in diagnostics(&report) {
                ui.add_space(4.0);
                ui.label(egui::RichText::new(head).color(t.tab_text_active));
                for d in details {
                    ui.label(egui::RichText::new(format!("    {d}")).color(t.text_dim).size(11.0));
                }
            }""",
        "display recognised project counts and all import diagnostics",
    )
    replace_once(
        losses,
        """    #[test]
    fn the_report_reads_as_categories_with_counts_and_details() {""",
        """    #[test]
    fn all_project_specific_issues_and_reader_limitations_require_review() {
        assert!(needs_prompt(&json!({"losses": [], "missingFootage": ["D:/media/clip.mov"]})));
        assert!(needs_prompt(&json!({"losses": [], "missingFonts": ["ExamplePS-Bold"]})));
        assert!(needs_prompt(&json!({"losses": [], "missingFootage": [], "missingFonts": [], "limitations": ["frame blending"]})));
        assert!(!needs_prompt(&json!({"losses": [], "missingFootage": [], "missingFonts": [], "limitations": []})));
    }

    #[test]
    fn imported_summary_lists_every_nonzero_imported_category() {
        let report = json!({"imported": {"compositions": 2, "layers": 7, "keyframes": 12, "effects": 3, "masks": 0}});
        let rows = imported_lines(&report);
        assert_eq!(rows.len(), 1);
        assert!(rows[0].contains("合成 2"));
        assert!(rows[0].contains("图层 7"));
        assert!(rows[0].contains("关键帧 12"));
        assert!(rows[0].contains("效果实例 3"));
        assert!(!rows[0].contains("蒙版 0"));
    }

    #[test]
    fn diagnostics_include_missing_media_fonts_and_reader_limitations() {
        let report = json!({
            "missingFootage": ["D:/media/clip.mov"],
            "missingFonts": ["ExamplePS-Bold"],
            "limitations": ["Frame blending is not decoded."]
        });
        let items = diagnostics(&report);
        assert_eq!(items.len(), 3);
        assert!(items[0].0.starts_with("Missing footage"));
        assert_eq!(items[0].1, vec!["D:/media/clip.mov".to_string()]);
        assert!(items[1].0.starts_with("Missing fonts"));
        assert_eq!(items[1].1, vec!["ExamplePS-Bold".to_string()]);
        assert!(items[2].0.starts_with("Reader limitations"));
        assert_eq!(items[2].1, vec!["Frame blending is not decoded.".to_string()]);
    }

    #[test]
    fn the_report_reads_as_categories_with_counts_and_details() {""",
        "add tests for import preflight diagnostics and prompt conditions",
    )

    aep_now = aep.read_text(encoding="utf-8")
    am_nv_now = am_nv.read_text(encoding="utf-8")
    frontend_now = frontend.read_text(encoding="utf-8")
    menu_now = menu.read_text(encoding="utf-8")
    losses_now = losses.read_text(encoding="utf-8")
    if "file.importAepDesktop" not in aep_now:
        raise SystemExit("The desktop AE command was not registered")
    if "file.importAep" not in aep_now:
        raise SystemExit("The original AE import command was not preserved")
    if "file.importEffectCraftMobile" not in am_nv_now or "import_effectcraft_mobile_project" not in am_nv_now:
        raise SystemExit("The EffectCraft mobile project import command is incomplete")
    if '\"file.importEffectCraftMobile\" => (\"path\", Ask::Open(&[\"ecproj\", \"ecprojx\", \"zip\"]))' not in frontend_now:
        raise SystemExit("The mobile picker must accept .ecproj/.ecprojx and ZIP packages")
    if "AE 电脑版工程... | file.importAepDesktop" not in menu_now:
        raise SystemExit("The desktop AE menu entry is missing")
    if "自有工程包... | file.importEffectCraftMobile" not in menu_now:
        raise SystemExit("The EffectCraft mobile menu entry is missing")
    if 'id == "file.importAep" || id == "file.importAepDesktop"' not in losses_now:
        raise SystemExit("The desktop AE loss confirmation guard is missing")
    for required in ("fn needs_prompt(report: &Value)", "if !needs_prompt(&report)", "fn imported_lines(report: &Value)", "继续导入（仍有未支持内容）", "const DETAILS: usize = 20;"):
        if required not in losses_now:
            raise SystemExit(f"The full desktop-AE preflight report is missing: {required}")
    print("Desktop import: .aep/.aepx through the original After Effects importer.")
    print("Import review: show recognised object counts, up to 20 loss examples per category, missing assets/fonts and standing parser limitations before any import.")
    print("Mobile import: EffectCraft .ecproj/.ecprojx or the ZIP exported by EffectCraft mobile, including collected footage.")
    print("Original Import Project and original After Effects import commands remain available.")
    print("Mobile EffectCraft projects are routed to the native project reader, not the AEP parser.")


if __name__ == "__main__":
    main()
