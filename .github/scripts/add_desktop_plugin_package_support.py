#!/usr/bin/env python3
"""Add safe desktop plugin package inspection and install compatible AE extensions."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_ANDROID_DESKTOP_PLUGIN_PACKAGE_IMPORT_V1"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one insertion point, found {count}")
    return source.replace(old, new, 1)


def patch_effect_loader(root: Path) -> None:
    path = root / "crates/engine/src/cmd/effect.rs"
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Desktop plugin package import is already patched.")
        return

    helper = r'''
// EFFECTCRAFT_ANDROID_DESKTOP_PLUGIN_PACKAGE_IMPORT_V1
/// Inspect a desktop plug-in ZIP and install only formats EffectCraft can safely host.
/// Native .aex/.dll/.ofx binaries are preserved for analysis but are never executed.
fn install_desktop_plugin_archive(s: &mut Session, archive_path: &str) -> Result<Value> {
    const CMD: &str = "effect.plugins.load";
    const MAX_ENTRIES: usize = 512;
    const MAX_TOTAL_BYTES: u64 = 256 * 1024 * 1024;
    const MAX_MODULE_BYTES: u64 = 64 * 1024 * 1024;
    const MAX_SCRIPT_BYTES: u64 = 16 * 1024 * 1024;
    const MAX_ASSET_BYTES: u64 = 32 * 1024 * 1024;
    const MAX_NATIVE_BYTES: u64 = 64 * 1024 * 1024;

    // Score only candidates that have actually run and passed every mandatory gate.
    // Unexecuted candidates retain a null score and can never be auto-selected.
    fn trial_metric(route: &Value, key: &str) -> f64 {
        route.get("metrics")
            .and_then(|metrics| metrics.get(key))
            .and_then(Value::as_f64)
            .unwrap_or(0.0)
            .clamp(0.0, 100.0)
    }

    fn rank_desktop_native_trials(metadata: &mut [Value]) {
        const REQUIRED_GATES: [&str; 8] = [
            "binary_load",
            "host_api_coverage",
            "parameter_roundtrip",
            "preview_render",
            "final_render",
            "cancellation",
            "stability",
            "license_ok",
        ];
        for plugin in metadata.iter_mut() {
            let mut best: Option<(f64, Value)> = None;
            if let Some(routes) = plugin.get_mut("candidate_routes").and_then(Value::as_array_mut) {
                for route in routes.iter_mut() {
                    let executed = route.get("translation_executed").and_then(Value::as_bool) == Some(true);
                    let passed = route.get("status").and_then(Value::as_str) == Some("passed");
                    let gates_passed = route.get("hard_gates").is_some_and(|gates| {
                        REQUIRED_GATES.iter().all(|key| gates.get(*key).and_then(Value::as_bool) == Some(true))
                    });
                    if !executed || !passed || !gates_passed {
                        route["score"] = Value::Null;
                        continue;
                    }
                    let score =
                        trial_metric(route, "host_api_coverage") * 0.20
                        + trial_metric(route, "parameter_animation_coverage") * 0.15
                        + trial_metric(route, "render_correctness") * 0.20
                        + trial_metric(route, "feature_coverage") * 0.15
                        + trial_metric(route, "visual_fidelity") * 0.15
                        + trial_metric(route, "stability") * 0.10
                        + trial_metric(route, "performance") * 0.05;
                    route["score"] = json!(score);
                    if best.as_ref().is_none_or(|(best_score, _)| score > *best_score) {
                        best = Some((score, route.clone()));
                    }
                }
            }
            if let Some((score, selected)) = best {
                plugin["selected_route"] = selected;
                plugin["trial_score"] = json!(score);
                plugin["trial_execution_status"] = json!("passed");
            }
        }
    }

    // Extract visible ASCII and UTF-16LE strings without loading or executing the binary.
    // AE PiPL resources carry effect names, categories and match-name identifiers; plug-in
    // binaries may also retain parameter labels and UI text as readable strings.
    fn readable_plugin_strings(bytes: &[u8]) -> Vec<String> {
        fn push_run(output: &mut Vec<String>, run: &mut Vec<u8>) {
            if run.len() >= 4 && output.len() < 160 {
                let value = String::from_utf8_lossy(run).trim().to_string();
                if !value.is_empty() && !output.contains(&value) {
                    output.push(value.chars().take(180).collect());
                }
            }
            run.clear();
        }
        let mut output = Vec::new();
        let mut ascii = Vec::new();
        for byte in bytes.iter().copied() {
            if (0x20..=0x7e).contains(&byte) { ascii.push(byte); }
            else { push_run(&mut output, &mut ascii); }
        }
        push_run(&mut output, &mut ascii);
        let mut wide = Vec::new();
        for pair in bytes.chunks_exact(2) {
            let unit = u16::from_le_bytes([pair[0], pair[1]]);
            if (0x20..=0x7e).contains(&unit) { wide.push(unit as u8); }
            else { push_run(&mut output, &mut wide); }
        }
        push_run(&mut output, &mut wide);
        output
    }

    fn native_binary_info(bytes: &[u8]) -> (&'static str, &'static str) {
        if bytes.len() >= 2 && &bytes[..2] == b"MZ" {
            if bytes.len() >= 0x40 {
                let offset = u32::from_le_bytes([bytes[0x3c], bytes[0x3d], bytes[0x3e], bytes[0x3f]]) as usize;
                if let Some(header) = bytes.get(offset..offset.saturating_add(6)) {
                    if header.len() >= 6 && &header[..4] == b"PE\0\0" {
                        let machine = u16::from_le_bytes([header[4], header[5]]);
                        let arch = match machine {
                            0x014c => "32 位 x86",
                            0x8664 => "64 位 x86",
                            0xaa64 => "64 位 ARM",
                            0x01c4 => "32 位 ARM",
                            0x0200 => "英特尔安腾 64 位",
                            _ => "未知可执行文件架构",
                        };
                        return ("Windows 可执行文件", arch);
                    }
                }
            }
            return ("Windows 程序或动态库", "架构未识别");
        }
        if bytes.len() >= 20 && &bytes[..4] == b"\x7fELF" {
            let machine = if bytes[5] == 2 {
                u16::from_be_bytes([bytes[18], bytes[19]])
            } else {
                u16::from_le_bytes([bytes[18], bytes[19]])
            };
            let arch = match machine {
                3 => "32 位 x86",
                40 => "32 位 ARM",
                62 => "64 位 x86",
                183 => "64 位 ARM",
                243 => "RISC-V 架构",
                _ => "未知 Linux 可执行文件架构",
            };
            return ("Linux 可执行文件", arch);
        }
        if bytes.len() >= 4 {
            let magic = u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]);
            return match magic {
                0xfeedface => ("苹果系统原生文件", "32 位大端"),
                0xcefaedfe => ("苹果系统原生文件", "32 位小端"),
                0xfeedfacf => ("苹果系统原生文件", "64 位大端"),
                0xcffaedfe => ("苹果系统原生文件", "64 位小端"),
                0xcafebabe | 0xbebafeca | 0xcafebabf | 0xbfbafeca => ("苹果通用原生文件", "包含多种架构"),
                _ => ("未知原生文件", "架构未识别"),
            };
        }
        ("未知原生文件", "架构未识别")
    }

    // Produce an honest execution route for each binary. Box64/Box86 translate CPU
    // instructions at runtime; they do not rewrite a PE/ELF plug-in into an ARM64 file.
    // Wine supplies the Windows loader/API for PE binaries. A separate plug-in host ABI
    // bridge is still required before any native desktop plug-in can render inside Ae.
    fn native_translation_route(
        binary_format: &str,
        architecture: &str,
        extension: &str,
    ) -> (&'static str, &'static str, &'static str, &'static str) {
        let ext = extension.to_ascii_lowercase();
        let host = match ext.as_str() {
            "ofx" => "OpenFX 1.x Host API 桥接（C ABI）",
            "aex" => "Adobe After Effects SDK 宿主桥接（尚未实现）",
            "8bf" => "Photoshop Filter SDK 宿主桥接（尚未实现）",
            "prm" => "Premiere 插件宿主 ABI 桥接（尚未实现）",
            _ => "需先识别并实现该插件对应的宿主 ABI",
        };
        match (binary_format, architecture) {
            ("Windows 可执行文件", "64 位 x86") => (
                "Box64 + Wine64",
                "ARM64 / Android arm64-v8a",
                "x86-64 PE 动态转译候选；当前只做架构识别，尚未执行转译；仍需 Windows API 与插件宿主桥接",
                host,
            ),
            ("Windows 可执行文件", "32 位 x86") => (
                "Box86 + Wine32（需 32 位客体运行库）；Box64 + Wine WOW64 为实验备选",
                "ARM64 / Android arm64-v8a",
                "x86 PE 动态转译候选；32 位客体环境尚未接入，当前未执行转译；仍需 Windows API 与插件宿主桥接",
                host,
            ),
            ("Linux 可执行文件", "64 位 x86") => (
                "Box64",
                "ARM64 / Android arm64-v8a",
                "x86-64 ELF 动态转译候选；需 glibc 客体环境及匹配的 Linux 插件宿主 ABI；当前未执行转译",
                host,
            ),
            ("Linux 可执行文件", "32 位 x86") => (
                "Box86（需 ARM32 客体运行库）",
                "ARM64 / Android arm64-v8a",
                "x86 ELF 动态转译候选；需 32 位客体运行库及插件宿主 ABI；当前未执行转译",
                host,
            ),
            ("Windows 可执行文件", "64 位 ARM") | ("Linux 可执行文件", "64 位 ARM") => (
                "ARM64 原生指令路径",
                "ARM64 / Android arm64-v8a",
                "CPU 架构匹配；操作系统 ABI 与插件宿主接口仍需适配",
                host,
            ),
            ("苹果系统原生文件", _) | ("苹果通用原生文件", _) => (
                "不自动转译",
                "ARM64 / Android arm64-v8a",
                "macOS Mach-O 插件依赖 macOS ABI；需要可用源代码后移植，或针对效果重新实现",
                host,
            ),
            _ => (
                "未确定（保留原件）",
                "ARM64 / Android arm64-v8a",
                "二进制格式或 CPU 架构无法可靠识别；不尝试执行",
                host,
            ),
        }
    }

    // List every technically plausible execution route in a deterministic order.
    // Routes are candidates only: the importer must not mark a route successful until
    // an isolated worker actually completes the full host/render test suite.
    fn native_translation_trials(
        binary_format: &str,
        architecture: &str,
        extension: &str,
    ) -> Vec<Value> {
        let ext = extension.to_ascii_lowercase();
        let host = match ext.as_str() {
            "ofx" => "OpenFX 1.x host adapter",
            "aex" => "Adobe After Effects SDK host adapter",
            "8bf" => "Photoshop Filter SDK host adapter",
            "prm" => "Premiere plug-in host adapter",
            _ => "format-specific plug-in host adapter",
        };
        let mut routes = Vec::new();
        let mut add = |id: &str, backend: &str, prerequisites: &str, notes: &str| {
            routes.push(json!({
                "id": id,
                "backend": backend,
                "host_adapter": host,
                "target_abi": "Android ARM64 / arm64-v8a",
                "prerequisites": prerequisites,
                "notes": notes,
                "status": "not_run_runtime_not_integrated",
                "translation_executed": false,
                "score": Value::Null
            }));
        };

        match (binary_format, architecture) {
            ("Windows 可执行文件", "64 位 x86") => {
                add(
                    "wine_box64_x86_64",
                    "Wine64 + Box64",
                    "Windows x86-64 guest libraries, Box64 ARM64 build, Wine64, private glibc guest rootfs",
                    "首选验证路线；Winlator demonstrates the Wine + Box64 Android architecture",
                );
                add(
                    "wine_fex_x86_64",
                    "Wine64 + FEX",
                    "FEX-compatible Linux ARM64 guest rootfs and supported 4 KiB page-size kernel",
                    "备选动态转译路线；需独立验证 FEX 与 Wine guest 的系统调用和 Android 内核兼容性",
                );
                add(
                    "wine_qemu_x86_64",
                    "Wine64 + QEMU x86_64-user",
                    "QEMU linux-user, matching x86-64 guest rootfs and Wine runtime",
                    "慢速兼容参考路线；用于可行性对照，不预设性能可用",
                );
            }
            ("Windows 可执行文件", "32 位 x86") => {
                add(
                    "wine_box86_i386",
                    "Wine32 + Box86",
                    "32-bit x86 Wine guest and compatible 32-bit ARM guest libraries",
                    "传统 32 位候选路线；需验证 Android ARM64 上的 32 位 guest 运行库",
                );
                add(
                    "wine_wow64_box64_i386",
                    "Wine WOW64 + Box64",
                    "Wine build with working x86-on-x86-64 WoW64 path plus Box64",
                    "实验性备选；仅在所选 Wine/Box64 构建通过 32 位组件测试后启用",
                );
                add(
                    "wine_fex_i386",
                    "Wine32 + FEX",
                    "FEX 32-bit x86 support, compatible guest rootfs and supported 4 KiB page-size kernel",
                    "备选动态转译路线；需验证 32 位 Wine guest 的调用约定和系统接口",
                );
                add(
                    "wine_qemu_i386",
                    "Wine32 + QEMU i386-user",
                    "QEMU linux-user i386 target, matching guest rootfs and Wine32",
                    "慢速兼容参考路线；在隔离环境中用于对照，不预设性能可用",
                );
            }
            ("Linux 可执行文件", "64 位 x86") => {
                add("linux_box64_x86_64", "Box64", "glibc x86-64 guest rootfs and required shared libraries", "优先 Linux ELF 动态转译路线");
                add("linux_fex_x86_64", "FEX", "FEX-compatible x86-64 rootfs and supported 4 KiB page-size kernel", "高兼容度备选；需核实内核页大小与 guest ABI");
                add("linux_qemu_x86_64", "QEMU x86_64-user", "QEMU linux-user x86-64 target and guest rootfs", "慢速参考路线；优先用于完整性对照");
            }
            ("Linux 可执行文件", "32 位 x86") => {
                add("linux_box86_i386", "Box86", "32-bit x86 guest libraries and compatible ARM userspace", "优先 32 位 Linux ELF 动态转译路线");
                add("linux_fex_i386", "FEX i386", "FEX 32-bit guest support, rootfs and supported 4 KiB page-size kernel", "32 位备选动态转译路线");
                add("linux_qemu_i386", "QEMU i386-user", "QEMU linux-user i386 target and guest rootfs", "慢速参考路线；优先用于完整性对照");
            }
            ("Windows 可执行文件", "64 位 ARM") => {
                add("wine_arm64_native", "Wine ARM64 native", "ARM64 PE support and matching Windows API imports", "CPU 无需 x86 转译；仍需 Windows API 与插件宿主桥接");
            }
            ("Linux 可执行文件", "64 位 ARM") => {
                add("linux_arm64_native", "ARM64 native loader", "AArch64 ELF and compatible Android/Linux ABI", "CPU 架构匹配；仍需依赖库和插件宿主桥接");
            }
            ("苹果系统原生文件", _) | ("苹果通用原生文件", _) => {
                add("mach_o_static_rebuild", "Ghidra analysis + source rebuild / clean reimplementation", "Readable source or legally usable interface/algorithm information", "macOS Mach-O is not directly executable on Android; this is a reconstruction path, not CPU translation");
            }
            _ => {}
        }
        drop(add);
        routes
    }

    // Aggressive compatibility is an ordered set of explicit host/runtime profiles.
    // It may adapt optional behavior, but must never fake required APIs or bypass licensing.
    fn forced_compatibility_profiles(extension: &str) -> Vec<Value> {
        let ext = extension.to_ascii_lowercase();
        let host_profile = match ext.as_str() {
            "ofx" => "OpenFX suite capability negotiation and optional-suite shims",
            "aex" => "Adobe SDK suite compatibility adapter; only documented/legally usable interfaces",
            "8bf" => "Photoshop Filter host callback adapter",
            "prm" => "Premiere host callback adapter",
            _ => "format-specific host callback adapter",
        };
        vec![
            json!({"id":"legacy_os_and_runtime","name":"旧版系统与运行库兼容", "actions":["选择可用 Windows API 版本配置","补齐合法可再分发的 VC runtime / .NET 依赖"], "status":"planned_not_run"}),
            json!({"id":"host_optional_suite_shims","name":"插件宿主接口兼容", "actions":[host_profile, "只对明确标记为 optional 的接口提供有边界的兼容实现", "required API 缺失时必须判定失败"], "status":"planned_not_run"}),
            json!({"id":"pixel_format_matrix","name":"画面格式强制适配", "actions":["RGBA / BGRA 通道转换","8/16/32-bit 像素深度适配","预乘/直通 Alpha 与行跨度适配"], "status":"planned_not_run"}),
            json!({"id":"render_execution_fallbacks","name":"渲染兼容回退", "actions":["GPU 不可用时尝试 CPU 路径","多线程失败后尝试串行渲染","逐帧与时间序列两种调用模式"], "status":"planned_not_run"}),
            json!({"id":"cpu_feature_fallbacks","name":"CPU 指令与功能降级", "actions":["按运行时能力屏蔽不可用 CPU 扩展","逐级降低可选图形/加速特性"], "status":"planned_not_run"}),
            json!({"id":"source_or_binary_reconstruction","name":"强力移植 / 重构", "actions":["有源码时使用 Android NDK/Clang 重编译 ARM64","无源码时使用 Ghidra 分析导入、导出、控制流和资源","可用时用 Remill 提升指令到 LLVM IR 作辅助分析","按效果算法重写成 ARM64/WASM 兼容插件并进行参考帧回归"], "status":"planned_not_run"})
        ]
    }

    // Match only effects for which this APK actually ships an Android reimplementation.
    // Probe both package paths and readable strings embedded in native plug-in binaries.
    fn desktop_native_compatibility(source: &str, probe: &str) -> Option<Value> {
        let token = probe.to_ascii_lowercase()
            .replace('_', "")
            .replace('-', "")
            .replace(' ', "")
            .replace('.', "");
        let (effect_id, effect_name, note) = if token.contains("rsmb") {
            ("org.effectcraft.compat.rsmb-motion-blur", "方向运动模糊（兼容效果）",
             "安卓方向运动模糊兼容效果；不包含电脑版原版运动矢量估算功能")
        } else if token.contains("sglowaura") || token.contains("sapphireglowaura") || token.contains("glowaura") {
            ("org.effectcraft.sapphire.compat.glow-aura", "蓝宝石光晕氛围",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("sglow") || token.contains("sapphireglow") {
            ("org.effectcraft.sapphire.compat.glow", "蓝宝石光晕",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("slensflare") || token.contains("sapphirelensflare") {
            ("org.effectcraft.sapphire.compat.lensflare", "蓝宝石镜头光斑",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("sblur") || token.contains("sapphireblur") {
            ("org.effectcraft.sapphire.compat.blur", "蓝宝石模糊",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("sdistort") || token.contains("sapphiredistort") {
            ("org.effectcraft.sapphire.compat.distort", "蓝宝石扭曲",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("sstylize") || token.contains("sapphirestylize") {
            ("org.effectcraft.sapphire.compat.stylize", "蓝宝石风格化",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("sglint") || token.contains("sapphireglint") {
            ("org.effectcraft.sapphire.compat.glint", "蓝宝石星芒",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("srays") || token.contains("sapphirerays") {
            ("org.effectcraft.sapphire.compat.rays", "蓝宝石光线",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("shalftone") || token.contains("sapphirehalftone") {
            ("org.effectcraft.sapphire.compat.halftone", "蓝宝石半色调",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else if token.contains("spixelsort") || token.contains("sapphirepixelsort") {
            ("org.effectcraft.sapphire.compat.pixelsort", "蓝宝石像素排序",
             "效果工坊兼容重实现；并非电脑版原厂插件")
        } else {
            return None;
        };
        Some(json!({
            "source": source,
            "effect_id": effect_id,
            "effect_name": effect_name,
            "note": note
        }))
    }

    fn push_unique_native_mapping(mappings: &mut Vec<Value>, mapping: Value) {
        let source = mapping.get("source").cloned();
        let effect_id = mapping.get("effect_id").cloned();
        // Keep separate source files visible even when several files map to the same Android
        // effect module (for example, a plug-in binary plus an auxiliary native component).
        if !mappings.iter().any(|existing| {
            existing.get("source") == source.as_ref()
                && existing.get("effect_id") == effect_id.as_ref()
        }) {
            mappings.push(mapping);
        }
    }

    let cfg = s.config.clone()
        .ok_or_else(|| bad(CMD, "当前会话没有可写的插件目录"))?;
    let root = cfg.dir()
        .ok_or_else(|| bad(CMD, "当前存储环境没有可访问的插件目录"))?;
    let plugins_dir = root.join("Plug-ins");
    std::fs::create_dir_all(&plugins_dir)
        .map_err(|error| bad(CMD, format!("无法创建插件目录：{error}")))?;

    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let staging = plugins_dir.join("Import-Staging").join(format!("desktop_{stamp}"));
    let install_dir = staging.join("install");
    let wat_dir = staging.join("wat");
    let assets_dir = plugins_dir.join("Imported-Assets").join(format!("desktop_{stamp}"));
    let originals_dir = plugins_dir.join("Desktop-Originals").join(format!("desktop_{stamp}"));

    let archive_file = std::fs::File::open(archive_path)
        .map_err(|error| bad(CMD, format!("无法读取插件 ZIP：{error}")))?;
    let mut archive = zip::ZipArchive::new(archive_file)
        .map_err(|error| bad(CMD, format!("插件 ZIP 无效或已损坏：{error}")))?;
    if archive.len() > MAX_ENTRIES {
        return Err(bad(CMD, "插件包文件数量超过 512 个安全上限"));
    }

    let mut total_bytes = 0_u64;
    let mut wasm_count = 0_usize;
    let mut wat_count = 0_usize;
    let mut panel_count = 0_usize;
    let mut script_names: Vec<String> = Vec::new();
    let mut asset_names: Vec<String> = Vec::new();
    let mut native_names: Vec<String> = Vec::new();
    let mut native_mappings: Vec<Value> = Vec::new();
    let mut native_metadata: Vec<Value> = Vec::new();
    let mut skipped_names: Vec<String> = Vec::new();

    for index in 0..archive.len() {
        let mut entry = archive.by_index(index)
            .map_err(|error| bad(CMD, format!("无法读取 ZIP 条目：{error}")))?;
        if entry.is_dir() {
            continue;
        }
        let entry_name = entry.name()
            .map_err(|error| bad(CMD, format!("无法读取 ZIP 文件名：{error}")))?
            .into_owned();
        if entry_name.contains('\\') || entry_name.contains('\0') {
            skipped_names.push(entry_name);
            continue;
        }
        let relative = Path::new(&entry_name);
        if relative.components().any(|component| !matches!(component, Component::Normal(_))) {
            skipped_names.push(entry_name);
            continue;
        }
        if entry_name.split('/').any(|part| part.starts_with('.') || part.eq_ignore_ascii_case("__MACOSX")) {
            continue;
        }
        let Some(file_name) = relative.file_name().and_then(|name| name.to_str()) else {
            skipped_names.push(entry_name);
            continue;
        };
        if file_name.is_empty() || file_name.len() > 180 {
            skipped_names.push(entry_name);
            continue;
        }
        let extension = relative.extension().and_then(|value| value.to_str())
            .unwrap_or_default().to_ascii_lowercase();

        let kind = if extension == "wasm" { "wasm" }
            else if extension == "wat" { "wat" }
            else if extension == "jsx" { "panel" }
            else if extension == "js" { "script" }
            else if ["aex", "dll", "ofx", "so", "dylib", "plugin", "bundle", "prm", "8bf"].contains(&extension.as_str())
                || entry_name.to_ascii_lowercase().contains(".plugin/")
                || entry_name.to_ascii_lowercase().contains(".ofx.bundle/") { "native" }
            else if ["cube", "3dl", "lut", "look", "csp", "spi1d", "spi3d", "spimtx", "cc", "ccc", "cdl", "ocio",
                     "png", "jpg", "jpeg", "webp", "tif", "tiff", "exr", "ttf", "otf",
                     "json", "xml", "txt", "md", "toml", "plist", "rsrc", "r", "rc", "strings", "manifest",
                     "yaml", "yml", "ini", "config", "pdb", "map", "cmake", "mk", "sh", "py", "gradle",
                     "glsl", "frag", "vert", "wgsl", "hlsl", "dctl", "metal",
                     "fx", "osl", "h", "hpp", "c", "cpp", "rs", "sbsar"].contains(&extension.as_str()) { "asset" }
            else if extension == "jsxbin" { "asset" }
            else { "unknown" };

        if kind == "unknown" {
            continue;
        }
        if kind == "encoded_script" {
            skipped_names.push(format!("{file_name}（JSXBIN 未支持）"));
            continue;
        }

        let max_bytes = match kind {
            "wasm" | "wat" => MAX_MODULE_BYTES,
            "panel" | "script" => MAX_SCRIPT_BYTES,
            "native" => MAX_NATIVE_BYTES,
            _ => MAX_ASSET_BYTES,
        };
        let mut bytes = Vec::new();
        (&mut entry).take(max_bytes + 1)
            .read_to_end(&mut bytes)
            .map_err(|error| bad(CMD, format!("读取 {file_name} 失败：{error}")))?;
        let size = u64::try_from(bytes.len()).unwrap_or(u64::MAX);
        if size > max_bytes {
            skipped_names.push(format!("{file_name}（超过单文件安全上限）"));
            continue;
        }
        total_bytes = total_bytes.saturating_add(size);
        if total_bytes > MAX_TOTAL_BYTES {
            return Err(bad(CMD, "插件包可提取文件总量超过 256 MB 安全上限"));
        }
        if bytes.is_empty() {
            continue;
        }

        let destination_name = format!("archive_{index}_{file_name}");
        if !super::scripts::is_bare_name(&destination_name)
            || (cfg!(windows) && super::scripts::windows_unsafe_name(&destination_name)) {
            skipped_names.push(format!("{file_name}（文件名不安全）"));
            continue;
        }

        match kind {
            "wasm" | "panel" => {
                std::fs::create_dir_all(&install_dir)
                    .map_err(|error| bad(CMD, format!("无法创建插件临时目录：{error}")))?;
                std::fs::write(install_dir.join(&destination_name), &bytes)
                    .map_err(|error| bad(CMD, format!("无法暂存 {file_name}：{error}")))?;
                if kind == "wasm" { wasm_count += 1; } else { panel_count += 1; }
            }
            "wat" => {
                std::fs::create_dir_all(&wat_dir)
                    .map_err(|error| bad(CMD, format!("无法创建 WAT 临时目录：{error}")))?;
                std::fs::write(wat_dir.join(&destination_name), &bytes)
                    .map_err(|error| bad(CMD, format!("无法暂存 {file_name}：{error}")))?;
                wat_count += 1;
            }
            "script" => {
                let code = String::from_utf8(bytes)
                    .map_err(|_| bad(CMD, format!("{file_name} 不是 UTF-8 脚本文本，未安装")))?;
                cfg.write(&format!("{}/{destination_name}", super::scripts::SCRIPTS_DIR), &code)
                    .map_err(|error| bad(CMD, format!("无法安装 AE 脚本 {file_name}：{error}")))?;
                script_names.push(destination_name);
            }
            "asset" => {
                std::fs::create_dir_all(&assets_dir)
                    .map_err(|error| bad(CMD, format!("无法创建素材目录：{error}")))?;
                std::fs::write(assets_dir.join(&destination_name), &bytes)
                    .map_err(|error| bad(CMD, format!("无法保存素材 {file_name}：{error}")))?;
                // Read common package manifests for effect identifiers when the binary filename
                // is generic (for example, a bundle named simply "Plugin.aex").
                if ["json", "xml", "txt", "md", "toml", "plist", "rsrc", "r", "rc", "strings", "manifest", "yaml", "yml", "ini", "config", "pdb", "map", "jsxbin"].contains(&extension.as_str()) {
                    let metadata = String::from_utf8_lossy(&bytes);
                    let metadata_strings = readable_plugin_strings(&bytes);
                    let metadata_probe = format!("{}\n{}", metadata, metadata_strings.join("\n"));
                    if let Some(mapping) = desktop_native_compatibility(&entry_name, &metadata_probe) {
                        push_unique_native_mapping(&mut native_mappings, mapping);
                    }
                    if !metadata_strings.is_empty() {
                        // Keep extracted strings private for compatibility matching only.
                        // The UI and import report show counts, never original English labels.
                        native_metadata.push(json!({
                            "file": entry_name,
                            "readable_text_count": metadata_strings.len()
                        }));
                    }
                }
                asset_names.push(destination_name);
            }
            "native" => {
                std::fs::create_dir_all(&originals_dir)
                    .map_err(|error| bad(CMD, format!("无法创建电脑版插件存档目录：{error}")))?;
                std::fs::write(originals_dir.join(&destination_name), &bytes)
                    .map_err(|error| bad(CMD, format!("无法保存原始插件 {file_name}：{error}")))?;
                native_names.push(destination_name);
                // Inspect PiPL-adjacent names and strings embedded in the binary. This is static
                // metadata extraction only: native code is never loaded or executed.
                let embedded_strings = readable_plugin_strings(&bytes);
                let embedded_text = embedded_strings.join("\n");
                if let Some(mapping) = desktop_native_compatibility(&entry_name, &entry_name)
                    .or_else(|| desktop_native_compatibility(&entry_name, &embedded_text))
                {
                    push_unique_native_mapping(&mut native_mappings, mapping);
                }
                let (binary_format, architecture) = native_binary_info(&bytes);
                let extension = Path::new(&entry_name)
                    .extension()
                    .and_then(|value| value.to_str())
                    .unwrap_or_default();
                let (translation_backend, target_abi, translation_status, host_adapter) =
                    native_translation_route(binary_format, architecture, extension);
                let candidate_routes = native_translation_trials(binary_format, architecture, extension);
                let forced_profiles = forced_compatibility_profiles(extension);
                native_metadata.push(json!({
                    "file": entry_name,
                    "binary_format": binary_format,
                    "architecture": architecture,
                    "translation_backend": translation_backend,
                    "target_abi": target_abi,
                    "translation_status": translation_status,
                    "host_adapter": host_adapter,
                    "translation_executed": false,
                    "candidate_routes": candidate_routes,
                    "forced_compatibility_profiles": forced_profiles,
                    "trial_execution_status": "not_run_runtime_not_integrated",
                    "readable_text_count": embedded_strings.len()
                }));
            }
            _ => {}
        }
    }

    if wasm_count == 0 && wat_count == 0 && panel_count == 0
        && script_names.is_empty() && asset_names.is_empty() && native_names.is_empty() {
        return Err(bad(CMD, "压缩包内没有找到可识别的效果模块、特效软件脚本、素材或电脑插件文件"));
    }

    if !script_names.is_empty() {
        s.scripts_changed();
    }

    let mut installed_wasm = Vec::<String>::new();
    let mut loaded_wasm = Vec::<Value>::new();
    let mut installed_panels = Vec::<String>::new();
    let mut compatibility_errors = Vec::<Value>::new();
    let mut install_entries = if install_dir.is_dir() {
        std::fs::read_dir(&install_dir)
            .map_err(|error| bad(CMD, format!("无法读取插件暂存目录：{error}")))?
            .filter_map(std::result::Result::ok)
            .map(|entry| entry.path())
            .collect::<Vec<_>>()
    } else {
        Vec::new()
    };
    install_entries.sort();

    for source in install_entries {
        let extension = source.extension().and_then(|value| value.to_str()).unwrap_or_default();
        let source_text = source.to_string_lossy().to_string();
        let file_name = source.file_name().map(|value| value.to_string_lossy().to_string()).unwrap_or_default();
        if extension.eq_ignore_ascii_case("wasm") {
            match s.execute("effect.plugins.load", json!({"path": source_text})) {
                Ok(result) => {
                    // Keep only modules that the host successfully validates and loads.
                    // A unique name avoids replacing an existing effect on a later import.
                    let target_name = format!("desktop_{stamp}_{}.wasm", installed_wasm.len());
                    let target = plugins_dir.join(&target_name);
                    match std::fs::copy(&source, &target) {
                        Ok(_) => {
                            installed_wasm.push(target_name);
                            loaded_wasm.push(result);
                        }
                        Err(error) => {
                            let _ = std::fs::remove_file(&target);
                            compatibility_errors.push(json!({"file": file_name, "error": format!("插件已载入本次会话，但无法保存供下次启动使用：{error}")}));
                        }
                    }
                }
                Err(error) => compatibility_errors.push(json!({"file": file_name, "error": error.to_string()})),
            }
        } else if extension.eq_ignore_ascii_case("jsx") {
            match s.execute("file.installScriptUIPanel", json!({"path": source_text})) {
                Ok(_) => installed_panels.push(file_name),
                Err(error) => compatibility_errors.push(json!({"file": file_name, "error": error.to_string()})),
            }
        }
    }

    let mut loaded_wat = Vec::<Value>::new();
    if wat_dir.is_dir() {
        let mut wat_files = std::fs::read_dir(&wat_dir)
            .map_err(|error| bad(CMD, format!("无法读取 WAT 插件暂存目录：{error}")))?
            .filter_map(std::result::Result::ok)
            .map(|entry| entry.path())
            .collect::<Vec<_>>();
        wat_files.sort();
        for source in wat_files {
            let file_name = source.file_name().map(|value| value.to_string_lossy().to_string()).unwrap_or_default();
            match s.execute("effect.plugins.load", json!({"path": source.to_string_lossy()})) {
                Ok(result) => {
                    let target_name = format!("desktop_{stamp}_{}.wat", loaded_wat.len());
                    let target = plugins_dir.join(&target_name);
                    match std::fs::copy(&source, &target) {
                        Ok(_) => loaded_wat.push(result),
                        Err(error) => {
                            let _ = std::fs::remove_file(&target);
                            compatibility_errors.push(json!({"file": file_name, "error": format!("模块文本已载入本次会话，但无法保存供下次启动使用：{error}")}));
                        }
                    }
                }
                Err(error) => compatibility_errors.push(json!({"file": file_name, "error": error.to_string()})),
            }
        }
    }

    // Automatically rank tested routes; current unexecuted plans receive no score and no selection.
    rank_desktop_native_trials(&mut native_metadata);
    let compatibility_match_count = native_mappings.len();
    let compatibility_summary = native_mappings.iter().map(|item| {
        format!(
            "{} → {}：{}",
            item["source"].as_str().unwrap_or(""),
            item["effect_name"].as_str().unwrap_or("兼容效果"),
            item["note"].as_str().unwrap_or("")
        )
    }).collect::<Vec<_>>().join("\n");
    let metadata_summary = native_metadata.iter().map(|item| {
        let file = item.get("file").and_then(Value::as_str).unwrap_or("电脑版插件");
        let format = item.get("binary_format").and_then(Value::as_str).unwrap_or("插件资源信息");
        let architecture = item.get("architecture").and_then(Value::as_str).unwrap_or("未识别");
        let backend = item.get("translation_backend").and_then(Value::as_str).unwrap_or("未确定");
        let target = item.get("target_abi").and_then(Value::as_str).unwrap_or("ARM64");
        let status = item.get("translation_status").and_then(Value::as_str).unwrap_or("尚未执行转译");
        let host = item.get("host_adapter").and_then(Value::as_str).unwrap_or("需适配插件宿主接口");
        let route_names = item.get("candidate_routes").and_then(Value::as_array)
            .map(|routes| routes.iter().filter_map(|route| route.get("backend").and_then(Value::as_str)).collect::<Vec<_>>().join(" → "))
            .unwrap_or_default();
        let selected_backend = item.get("selected_route")
            .and_then(|route| route.get("backend"))
            .and_then(Value::as_str)
            .unwrap_or("暂无通过硬性测试的方案");
        let trial_score = item.get("trial_score").and_then(Value::as_f64);
        let selected_summary = trial_score.map(|score| format!("；实测最佳：{selected_backend}，完整度 {:.1}/100", score))
            .unwrap_or_else(|| "；尚无实测最佳方案，不能自动导入原生插件".into());
        let force_count = item.get("forced_compatibility_profiles").and_then(Value::as_array).map_or(0, |profiles| profiles.len());
        let readable_text_count = item.get("readable_text_count")
            .and_then(Value::as_u64).unwrap_or(0);
        format!("\n[{file}] {format} / {architecture}；首选路线：{backend} → {target}；候选顺序：{route_names}{selected_summary}；状态：{status}；宿主接口：{host}；强制兼容方案：{force_count} 项（当前仅生成计划，尚未执行）；已提取 {readable_text_count} 条可读信息（原始文字仅用于内部匹配，不在界面中显示）")
    }).collect::<Vec<_>>().join("\n");
    let mut install_result = json!({
        "installed": installed_wasm,
        "panels": installed_panels,
        "loaded": loaded_wasm,
        "errors": compatibility_errors,
        "native_compatibility_matches": native_mappings.clone()
    });
    let wat_result = json!({"loaded": loaded_wat, "errors": []});
    let report_dir = plugins_dir.join("Import-Reports");
    std::fs::create_dir_all(&report_dir)
        .map_err(|error| bad(CMD, format!("无法创建插件分析报告目录：{error}")))?;
    let report_path = report_dir.join(format!("desktop-import-{stamp}.txt"));
    let script_count = script_names.len();
    let asset_count = asset_names.len();
    let native_count = native_names.len();
    let skipped_count = skipped_names.len();
    let report = format!(
        "电脑插件包分析报告\n时间：{stamp}\n\n已安装效果模块：{wasm_count}\n已安装脚本交互面板：{panel_count}\n已导入脚本文件：{script_count}\n已归档素材和源码：{asset_count}\n已保存电脑原生插件原件：{native_count}\n已匹配内置兼容效果：{compatibility_match_count}\n{compatibility_summary}\n\n从电脑原生插件中提取的可读信息统计：{metadata_summary}\n跳过文件：{skipped_count}\n\n说明：只有效果模块、模块文本，以及本应用兼容的脚本和面板会进入对应导入流程。\nCPU 转译目标为 Android ARM64（arm64-v8a）。导入分析会按文件格式建立候选路线：Windows x86-64 可比较 Wine+Box64、Wine+FEX、Wine+QEMU user-mode；Windows x86 可比较 Wine32+Box86、Wine WOW64+Box64、Wine32+FEX、Wine32+QEMU；Linux ELF 可比较 Box64/Box86、FEX、QEMU user-mode。只有系统 ABI、客体运行库、内核页大小和插件宿主接口满足条件时才属于可试路线。Box64/Box86/FEX/QEMU 是运行时动态转译/模拟，不会把原始插件文件改写成 ARM64 二进制。当前版本仅识别架构、生成候选顺序与强制兼容策略，并保存原件；所有候选路线均标记 not_run_runtime_not_integrated，translation_executed=false，尚未执行逐项试跑。\n.aex/.dll/.ofx/.plugin 等原生二进制不会在 Ae 主进程中加载或执行。OpenFX 插件需要独立 OFX Host API 桥接；.aex 还需要 Adobe After Effects SDK 宿主接口适配。若文件名匹配到内置兼容效果，报告会列出替代效果；替代效果并非原厂插件。\n移植策略：目标是逐个候选后端在隔离副本中进行同一套加载、宿主 API、参数、预览渲染、最终渲染、关键帧/时序、稳定性、画质和性能测试；按功能完整度与稳定性评分后仅导入通过硬性门槛的最高分方案。强制兼容模式会逐项尝试可选 API 兼容层、像素格式转换、CPU/串行渲染回退与源码重编译/二进制分析重构；不得伪造必需 API，不得绕过插件授权/DRM。当前候选路线和兼容配置只是试验计划，尚未执行。\n.cube 文件可通过内置“应用颜色查找表”效果加载；.3dl/.csp/.spi1d/.spi3d/.spimtx/.cc/.ccc/.cdl 和 .ocio 等色彩配置文件保留给内置色彩管理与文件变换流程读取。插件资源信息、.r、.rc、.rsrc、.plist 属性清单文件和已编译脚本文件会归档并在内部分析；原始英文参数文字仅用于兼容匹配，不会显示在界面或报告中，也不会直接执行。纹理、字体和源码会作为素材保存，不会自动变成可运行插件。\n效果模块、脚本面板和素材存档目录位于：{}\n电脑版原生插件原件目录位于：{}\n",
        assets_dir.display(), originals_dir.display()
    );
    std::fs::write(&report_path, report)
        .map_err(|error| bad(CMD, format!("无法保存插件分析报告：{error}")))?;

    if let Some(object) = install_result.as_object_mut() {
        object.insert("desktop_scripts".into(), json!(script_names));
        object.insert("desktop_assets".into(), json!(asset_names));
        object.insert("desktop_native_requires_port".into(), json!(native_names));
        object.insert("desktop_native_compatibility_matches".into(), json!(native_mappings));
        object.insert("desktop_native_metadata".into(), json!(native_metadata));
        object.insert("desktop_skipped".into(), json!(skipped_names));
        object.insert("wat_result".into(), wat_result);
        object.insert("compatibility_report".into(), json!(report_path.to_string_lossy()));
    }
    let mut notice = format!(
        "电脑插件包分析完成：效果模块 {wasm_count} 个、脚本交互面板 {panel_count} 个、脚本文件 {script_count} 个、素材 {asset_count} 个"
    );
    if native_count > 0 {
        notice.push_str(&format!("；另有 {native_count} 个电脑原生插件需要移植，未在安卓执行"));
    }
    if compatibility_match_count > 0 {
        notice.push_str(&format!("；另匹配到 {compatibility_match_count} 个内置兼容效果"));
    }
    if skipped_count > 0 {
        notice.push_str(&format!("；跳过 {skipped_count} 个不支持或超限文件"));
    }
    notice.push_str(&format!("；报告已保存：{}", report_path.display()));
    s.toast(notice);
    Ok(install_result)
}

'''
    marker = "/// " + chr(96) + "effect.plugins.load" + chr(96) + ": load WASM/WAT effect plug-ins directly or from a ZIP archive.\n"
    source = replace_once(source, marker, helper + marker, "desktop package analyzer insertion")

    anchor = '''    let loader = s.plugin_loader.ok_or_else(|| EngineError::Other("WebAssembly effect plug-ins are not available in this build".into()))?;
    let files: Vec<String> = match (str_p(p, "path"), str_p(p, "folder")) {'''
    replacement = '''    let loader = s.plugin_loader.ok_or_else(|| EngineError::Other("WebAssembly effect plug-ins are not available in this build".into()))?;
    if let Some(path) = str_p(p, "path")
        && Path::new(path).extension().is_some_and(|extension| extension.eq_ignore_ascii_case("zip"))
    {
        return install_desktop_plugin_archive(s, path);
    }
    let files: Vec<String> = match (str_p(p, "path"), str_p(p, "folder")) {'''
    source = replace_once(source, anchor, replacement, "ZIP route to desktop package installer")
    path.write_text(source, encoding="utf-8")
    print("Added safe desktop ZIP inspection, WASM/JSX bundle installation, JS script import and native-binary staging.")


def patch_toolbar(root: Path) -> None:
    path = root / "crates/ui-egui/src/header.rs"
    source = path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_ANDROID_DESKTOP_PLUGIN_IMPORT_MENU_V1"
    if marker in source:
        print("Desktop AE script choice is already present in the unified import menu.")
        return

    # The menu no longer imports a separate DeepSeek APK/ZIP. It now only imports effect
    # plug-ins; the embedded DeepSeek model manager is opened from the AI assistant itself.
    state_with_advanced_ai = "    let mut import_wasm = false;\n    let mut import_desktop_advanced = false;\n    let mut import_ai = false;\n"
    state_with_advanced_no_ai = "    let mut import_wasm = false;\n    let mut import_desktop_advanced = false;\n"
    state_with_ai = "    let mut import_wasm = false;\n    let mut import_ai = false;\n"
    state_without_ai = "    let mut import_wasm = false;\n"
    if state_with_advanced_ai in source:
        source = replace_once(
            source, state_with_advanced_ai,
            state_with_advanced_ai + "    let mut import_script = false;\n    let mut import_panel = false;\n",
            "toolbar import state",
        )
        keep_ai_flag = True
        keep_advanced_flag = True
    elif state_with_advanced_no_ai in source:
        source = replace_once(
            source, state_with_advanced_no_ai,
            state_with_advanced_no_ai + "    let mut import_script = false;\n    let mut import_panel = false;\n",
            "toolbar import state",
        )
        keep_ai_flag = False
        keep_advanced_flag = True
    elif state_with_ai in source:
        source = replace_once(
            source, state_with_ai,
            state_with_ai + "    let mut import_script = false;\n    let mut import_panel = false;\n",
            "toolbar import state",
        )
        keep_ai_flag = True
        keep_advanced_flag = False
    elif state_without_ai in source:
        source = replace_once(
            source, state_without_ai,
            state_without_ai + "    let mut import_script = false;\n    let mut import_panel = false;\n",
            "toolbar import state",
        )
        keep_ai_flag = False
        keep_advanced_flag = False
    else:
        raise SystemExit("Could not locate the WASM plug-in import state in the toolbar.")

    wasm_button = '''                if popup.button("导入效果插件包（支持 .wasm、.wat、.zip）").clicked() {
                    import_wasm = true;
                }
'''
    script_buttons = '''                // EFFECTCRAFT_ANDROID_DESKTOP_PLUGIN_IMPORT_MENU_V1
                if popup.button("特效软件脚本（.jsx、.js）").clicked() {
                    import_script = true;
                }
                if popup.button("脚本交互面板（.jsx）").clicked() {
                    import_panel = true;
                }
'''
    source = replace_once(source, wasm_button, wasm_button + script_buttons, "desktop script menu item")

    if keep_advanced_flag and keep_ai_flag:
        old_close = "        menu_open = popup_open && !close_menu && !import_wasm && !import_desktop_advanced && !import_ai;\n"
        new_close = "        menu_open = popup_open && !close_menu && !import_wasm && !import_desktop_advanced && !import_ai && !import_script && !import_panel;\n"
    elif keep_advanced_flag:
        old_close = "        menu_open = popup_open && !close_menu && !import_wasm && !import_desktop_advanced;\n"
        new_close = "        menu_open = popup_open && !close_menu && !import_wasm && !import_desktop_advanced && !import_script && !import_panel;\n"
    elif keep_ai_flag:
        old_close = "        menu_open = popup_open && !close_menu && !import_wasm && !import_ai;\n"
        new_close = "        menu_open = popup_open && !close_menu && !import_wasm && !import_ai && !import_script && !import_panel;\n"
    else:
        old_close = "        menu_open = popup_open && !close_menu && !import_wasm;\n"
        new_close = "        menu_open = popup_open && !close_menu && !import_wasm && !import_script && !import_panel;\n"
    source = replace_once(source, old_close, new_close, "desktop script menu close state")

    route_anchor = "    x + 84.0\n"
    routes = '''    if import_script {
        match crate::menus::invoke(app, ui.ctx(), "file.installScript", json!({})) {
            Ok(_) => app.ui.status = "脚本文件已导入；可在“文件 → 脚本”中使用。".into(),
            Err(error) => app.ui.status = error,
        }
    }
    if import_panel {
        match crate::menus::invoke(app, ui.ctx(), "file.installScriptUIPanel", json!({})) {
            Ok(_) => app.ui.status = "脚本交互面板已导入；可在“窗口”菜单中打开。".into(),
            Err(error) => app.ui.status = error,
        }
    }
'''
    source = replace_once(source, route_anchor, routes + route_anchor, "AE script installer route")
    path.write_text(source, encoding="utf-8")
    print("Added AE .jsx/.js import through EffectCraft's original script installer inside the unified plug-in entry.")


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    if not root.is_dir():
        raise SystemExit("EFFECTCRAFT_DIR must point to the checked-out EffectCraft source")
    patch_effect_loader(root)
    patch_toolbar(root)
    print("Desktop plug-in ZIPs now install compatible WASM modules and JSX panels, import JS scripts, archive portable resources, and preserve native binaries for later porting.")
    print("No desktop native binary is executed by the Android app.")


if __name__ == "__main__":
    main()
