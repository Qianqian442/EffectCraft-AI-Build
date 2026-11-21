#!/usr/bin/env python3
"""Integrate the offline x86 PE instruction/CFG reconstruction engine into the Android importer."""
from __future__ import annotations
import os
from pathlib import Path

MARKER = "EFFECTCRAFT_AEX_BINARY_RECONSTRUCTION_IR_V1"

def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one patch point, found {count}")
    return source.replace(old, new, 1)

def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    ui = root / "crates/ui-egui"
    lib = ui / "src/lib.rs"
    cargo = ui / "Cargo.toml"
    # The APK workflow checks this repository out under build-assets/, while PR
    # validation checks it out directly at GITHUB_WORKSPACE. Resolve both paths
    # from this script's own repository root so the same patch works in both jobs.
    build_assets = Path(__file__).resolve().parents[2]
    module_source = build_assets / "windows-compat/aex-reconstruction/src/lib.rs"
    migration_script = build_assets / ".github/scripts/add_plugin_migration_progress.py"
    if not module_source.is_file() or not migration_script.is_file():
        raise SystemExit("PE reconstruction source or migration generator is missing.")
    module_path = ui / "src/windows_binary_reconstruction.rs"
    module = module_source.read_text(encoding="utf-8")
    if MARKER not in module:
        module = module.replace("//! Offline PE/", "//! " + MARKER + "\n//! Offline PE/", 1)
    module_path.write_text(module, encoding="utf-8")

    lib_source = lib.read_text(encoding="utf-8")
    lib_source = replace_once(
        lib_source,
        'mod plugin_migration;\n',
        'mod plugin_migration;\n#[cfg(not(target_arch = "wasm32"))]\nmod windows_binary_reconstruction;\n',
        "PE reconstruction module declaration",
    )
    lib.write_text(lib_source, encoding="utf-8")

    cargo_source = cargo.read_text(encoding="utf-8")
    if 'iced-x86 = { version = "1.21.0"' not in cargo_source:
        anchor = 'sys-locale = { workspace = true }\n'
        dependency = anchor + 'iced-x86 = { version = "1.21.0", default-features = false, features = ["std", "decoder", "instr_info"] }\n'
        cargo_source = replace_once(cargo_source, anchor, dependency, "iced-x86 dependency")
    cargo.write_text(cargo_source, encoding="utf-8")

    script = migration_script.read_text(encoding="utf-8")
    script = replace_once(
        script,
        '            Self::AggressivePort => "逐个 AEX 执行 PE 分析与已安装 Wine/Proton + FEXCore/Box64 隔离试跑，检查参数往返、重复 CPU 帧渲染与正常退出。只有提供可用源代码且依赖/授权允许时才另行重编译；未知闭源插件不承诺自动还原为 ARM64。",',
        '            Self::AggressivePort => "逐个 AEX 执行 PE 导入/导出、指令/控制流分析，并在 Android 上对已安装 Wine/Proton + FEXCore/Box64 宿主路线隔离试跑，检查参数往返、重复 CPU 帧渲染与正常退出。静态 IR 和样本试跑不等于自动重编译任意闭源插件；只有可用源码且依赖/授权允许时才考虑 ARM64 重编译。",',
        "aggressive reconstruction mode description",
    )
    script = replace_once(
        script,
        'struct ScanReport {\n    file_count: usize,\n    native_count: usize,\n    native_names: Vec<String>,\n    total_bytes: u64,\n}',
        'struct ScanReport {\n    file_count: usize,\n    native_count: usize,\n    native_names: Vec<String>,\n    total_bytes: u64,\n    binary_reconstruction: Vec<String>,\n}',
        "reconstruction scan report",
    )
    script = replace_once(
        script,
        'let result = scan_archive(&worker_path, &worker_progress);',
        'let result = scan_archive(&worker_path, &worker_progress, mode);',
        "pass selected mode to PE scanner",
    )
    script = replace_once(
        script,
        'fn scan_archive(path: &str, progress: &AtomicUsize) -> Result<ScanReport, String> {',
        'fn scan_archive(path: &str, progress: &AtomicUsize, mode: MigrationMode) -> Result<ScanReport, String> {',
        "scan_archive signature",
    )
    script = replace_once(
        script,
        '    let mut native_names = Vec::new();\n    let mut completed_bytes = 0u64;',
        '    let mut native_names = Vec::new();\n    let mut binary_reconstruction = Vec::new();\n    let mut completed_bytes = 0u64;',
        "reconstruction result accumulator",
    )
    script = replace_once(
        script,
        '        if is_native {\n            native_count += 1;\n            if native_names.len() < 8 { native_names.push(entry_name.clone()); }\n        }\n        loop {',
        '        if is_native {\n            native_count += 1;\n            if native_names.len() < 8 { native_names.push(entry_name.clone()); }\n        }\n        let extension_is_pe = ["aex", "dll", "ofx"].contains(&extension.as_str());\n        let mut pe_bytes = if mode == MigrationMode::AggressivePort && extension_is_pe && entry.size() <= MAX_ENTRY_BYTES {\n            Some(Vec::with_capacity(entry.size() as usize))\n        } else { None };\n        loop {',
        "capture native PE bytes for aggressive analysis",
    )
    script = replace_once(
        script,
        '            completed_bytes = completed_bytes.saturating_add(read as u64);\n            if completed_bytes > MAX_TOTAL_BYTES {',
        '            if let Some(data) = pe_bytes.as_mut() {\n                if data.len().saturating_add(read) <= MAX_ENTRY_BYTES as usize {\n                    data.extend_from_slice(&buffer[..read]);\n                }\n            }\n            completed_bytes = completed_bytes.saturating_add(read as u64);\n            if completed_bytes > MAX_TOTAL_BYTES {',
        "capture PE chunk while respecting archive limits",
    )
    script = replace_once(
        script,
        '            progress.store(value, Ordering::Release);\n        }\n    }\n    progress.store(SCAN_PROGRESS_MAX, Ordering::Release);\n    Ok(ScanReport { file_count, native_count, native_names, total_bytes })',
        '            progress.store(value, Ordering::Release);\n        }\n        if let Some(data) = pe_bytes {\n            match crate::windows_binary_reconstruction::reconstruct_pe(&data) {\n                Ok(report) => {\n                    let architecture = report.get("architecture").and_then(Value::as_str).unwrap_or("unknown");\n                    let instructions = report.get("instruction_count").and_then(Value::as_u64).unwrap_or(0);\n                    let blocks = report.get("basic_block_candidates").and_then(Value::as_u64).unwrap_or(0);\n                    let imports = report.get("imported_dll_count").and_then(Value::as_u64).unwrap_or(0);\n                    let exports = report.get("exported_symbol_count").and_then(Value::as_u64).unwrap_or(0);\n                    let stamp = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_millis();\n                    let report_path = std::env::temp_dir().join(format!("ae-pe-rebuild-{index}-{stamp}.json"));\n                    let report_saved = serde_json::to_vec_pretty(&report).ok().and_then(|bytes| std::fs::write(&report_path, bytes).ok()).is_some();\n                    binary_reconstruction.push(format!("{}：{} PE；指令 {} 条；基本块候选 {}；导入 DLL {} 个；导出符号 {} 个；IR 报告 {}", entry_name, architecture, instructions, blocks, imports, exports, if report_saved { report_path.display().to_string() } else { "保存失败".to_string() }));\n                }\n                Err(error) => binary_reconstruction.push(format!("{}：未识别为可分析的 x86/x64 PE；{}", entry_name, error)),\n            }\n        }\n    }\n    progress.store(SCAN_PROGRESS_MAX, Ordering::Release);\n    Ok(ScanReport { file_count, native_count, native_names, total_bytes, binary_reconstruction })',
        "write reconstruction JSON report and return summary",
    )
    script = replace_once(
        script,
        '    lines.push("注意：当前构建已加入方式选择和报告记录；Box64/Box86/FEX/QEMU/Wine 的实际运行时试跑、后端手动切换和暴力二进制重建引擎尚未集成，不会伪称已执行。".into());',
        '    if !scan.binary_reconstruction.is_empty() {\n        lines.push("暴力二进制结构重建：已在本机离线解析 PE 导入/导出表、解码 x86/x64 指令并恢复基本块候选；生成的 JSON IR 报告保存在下面的应用临时目录。".into());\n        lines.extend(scan.binary_reconstruction.iter().cloned());\n        lines.push("重要：这是静态 IR 恢复，不等于自动重编译成 ARM64，也不证明 Windows API/AEX 宿主语义已移植。".into());\n    } else {\n        lines.push("暴力二进制重建仅在选择该模式时执行；当前结果不包含静态 PE 重建报告。".into());\n    }',
        "replace stale unintegrated-engine disclaimer",
    )
    migration_script.write_text(script, encoding="utf-8")

    # The build order generates plugin_migration.rs before this integration script runs.
    # Patch the already-generated module too; changing only the generator would defer
    # the feature until a later regeneration and leave the current APK without it.
    generated_module = ui / "src/plugin_migration.rs"
    module_source = generated_module.read_text(encoding="utf-8")
    module_replacements = [
        (
            '            Self::AggressivePort => "逐个 AEX 执行 PE 分析与已安装 Wine/Proton + FEXCore/Box64 隔离试跑，检查参数往返、重复 CPU 帧渲染与正常退出。只有提供可用源代码且依赖/授权允许时才另行重编译；未知闭源插件不承诺自动还原为 ARM64。",',
            '            Self::AggressivePort => "逐个 AEX 执行 PE 导入/导出、指令/控制流分析，并在 Android 上对已安装 Wine/Proton + FEXCore/Box64 宿主路线隔离试跑，检查参数往返、重复 CPU 帧渲染与正常退出。静态 IR 和样本试跑不等于自动重编译任意闭源插件；只有可用源码且依赖/授权允许时才考虑 ARM64 重编译。",',
            "generated aggressive-mode description",
        ),
        (
            'struct ScanReport {\n    file_count: usize,\n    native_count: usize,\n    native_names: Vec<String>,\n    total_bytes: u64,\n}',
            'struct ScanReport {\n    file_count: usize,\n    native_count: usize,\n    native_names: Vec<String>,\n    total_bytes: u64,\n    binary_reconstruction: Vec<String>,\n}',
            "generated reconstruction scan report",
        ),
        (
            'let result = scan_archive(&worker_path, &worker_progress);',
            'let result = scan_archive(&worker_path, &worker_progress, mode);',
            "generated scanner mode argument",
        ),
        (
            'fn scan_archive(path: &str, progress: &AtomicUsize) -> Result<ScanReport, String> {',
            'fn scan_archive(path: &str, progress: &AtomicUsize, mode: MigrationMode) -> Result<ScanReport, String> {',
            "generated scan_archive signature",
        ),
        (
            '    let mut native_names = Vec::new();\n    let mut completed_bytes = 0u64;',
            '    let mut native_names = Vec::new();\n    let mut binary_reconstruction = Vec::new();\n    let mut completed_bytes = 0u64;',
            "generated reconstruction accumulator",
        ),
        (
            '        if is_native {\n            native_count += 1;\n            if native_names.len() < 8 { native_names.push(entry_name.clone()); }\n        }\n        loop {',
            '        if is_native {\n            native_count += 1;\n            if native_names.len() < 8 { native_names.push(entry_name.clone()); }\n        }\n        let extension_is_pe = ["aex", "dll", "ofx"].contains(&extension.as_str());\n        let mut pe_bytes = if mode == MigrationMode::AggressivePort && extension_is_pe && entry.size() <= MAX_ENTRY_BYTES {\n            Some(Vec::with_capacity(entry.size() as usize))\n        } else { None };\n        loop {',
            "generated PE byte capture",
        ),
        (
            '            completed_bytes = completed_bytes.saturating_add(read as u64);\n            if completed_bytes > MAX_TOTAL_BYTES {',
            '            if let Some(data) = pe_bytes.as_mut() {\n                if data.len().saturating_add(read) <= MAX_ENTRY_BYTES as usize {\n                    data.extend_from_slice(&buffer[..read]);\n                }\n            }\n            completed_bytes = completed_bytes.saturating_add(read as u64);\n            if completed_bytes > MAX_TOTAL_BYTES {',
            "generated bounded PE capture",
        ),
        (
            '            progress.store(value, Ordering::Release);\n        }\n    }\n    progress.store(SCAN_PROGRESS_MAX, Ordering::Release);\n    Ok(ScanReport { file_count, native_count, native_names, total_bytes })',
            '            progress.store(value, Ordering::Release);\n        }\n        if let Some(data) = pe_bytes {\n            match crate::windows_binary_reconstruction::reconstruct_pe(&data) {\n                Ok(report) => {\n                    let architecture = report.get("architecture").and_then(Value::as_str).unwrap_or("unknown");\n                    let instructions = report.get("instruction_count").and_then(Value::as_u64).unwrap_or(0);\n                    let blocks = report.get("basic_block_candidates").and_then(Value::as_u64).unwrap_or(0);\n                    let imports = report.get("imported_dll_count").and_then(Value::as_u64).unwrap_or(0);\n                    let exports = report.get("exported_symbol_count").and_then(Value::as_u64).unwrap_or(0);\n                    let stamp = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_millis();\n                    let report_path = std::env::temp_dir().join(format!("ae-pe-rebuild-{index}-{stamp}.json"));\n                    let report_saved = serde_json::to_vec_pretty(&report).ok().and_then(|bytes| std::fs::write(&report_path, bytes).ok()).is_some();\n                    binary_reconstruction.push(format!("{}：{} PE；指令 {} 条；基本块候选 {}；导入 DLL {} 个；导出符号 {} 个；IR 报告 {}", entry_name, architecture, instructions, blocks, imports, exports, if report_saved { report_path.display().to_string() } else { "保存失败".to_string() }));\n                }\n                Err(error) => binary_reconstruction.push(format!("{}：未识别为可分析的 x86/x64 PE；{}", entry_name, error)),\n            }\n        }\n    }\n    progress.store(SCAN_PROGRESS_MAX, Ordering::Release);\n    Ok(ScanReport { file_count, native_count, native_names, total_bytes, binary_reconstruction })',
            "generated PE decode and JSON report",
        ),
        (
            '    lines.push("注意：当前构建已加入方式选择和报告记录；Box64/Box86/FEX/QEMU/Wine 的实际运行时试跑、后端手动切换和暴力二进制重建引擎尚未集成，不会伪称已执行。".into());',
            '    if !scan.binary_reconstruction.is_empty() {\n        lines.push("暴力二进制结构重建：已在本机离线解析 PE 导入/导出表、解码 x86/x64 指令并恢复基本块候选；生成的 JSON IR 报告保存在下面的应用临时目录。".into());\n        lines.extend(scan.binary_reconstruction.iter().cloned());\n        lines.push("重要：这是静态 IR 恢复，不等于自动重编译成 ARM64，也不证明 Windows API/AEX 宿主语义已移植。".into());\n    } else {\n        lines.push("暴力二进制重建仅在选择该模式时执行；当前结果不包含静态 PE 重建报告。".into());\n    }',
            "generated reconstruction report display",
        ),
    ]
    for old, new, label in module_replacements:
        module_source = replace_once(module_source, old, new, label)
    generated_module.write_text(module_source, encoding="utf-8")

    print("Integrated offline PE import/export parsing, x86/x64 instruction decoding, branch/basic-block recovery and JSON IR reports into the active Ae migration module.")

if __name__ == "__main__":
    main()
