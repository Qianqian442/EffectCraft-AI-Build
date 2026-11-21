//! Offline PE/x86 instruction and control-flow reconstruction for desktop effect plug-ins.
//!
//! This is a static analysis aid, not a semantic Windows-to-Android compiler. It preserves the
//! original binary and produces a bounded instruction/CFG report to guide a lawful ARM64 port.
use std::collections::BTreeSet;

use iced_x86::{Decoder, DecoderOptions, FlowControl};
use serde_json::{json, Value};

const MAX_EXECUTABLE_BYTES: usize = 64 * 1024 * 1024;
const MAX_INSTRUCTIONS: usize = 500_000;
const MAX_SECTIONS: usize = 96;

#[derive(Clone, Debug)]
struct Section {
    name: String,
    virtual_address: u32,
    virtual_size: u32,
    raw_offset: u32,
    raw_size: u32,
    characteristics: u32,
}

fn u16_at(bytes: &[u8], offset: usize) -> Option<u16> {
    Some(u16::from_le_bytes(bytes.get(offset..offset + 2)?.try_into().ok()?))
}
fn u32_at(bytes: &[u8], offset: usize) -> Option<u32> {
    Some(u32::from_le_bytes(bytes.get(offset..offset + 4)?.try_into().ok()?))
}
fn u64_at(bytes: &[u8], offset: usize) -> Option<u64> {
    Some(u64::from_le_bytes(bytes.get(offset..offset + 8)?.try_into().ok()?))
}
fn c_string(bytes: &[u8], offset: usize, limit: usize) -> String {
    let Some(tail) = bytes.get(offset..) else { return String::new() };
    let end = tail.iter().take(limit).position(|b| *b == 0).unwrap_or(tail.len().min(limit));
    String::from_utf8_lossy(&tail[..end]).into_owned()
}

fn rva_to_file(sections: &[Section], rva: u32) -> Option<usize> {
    for section in sections {
        let extent = section.virtual_size.max(section.raw_size);
        if rva >= section.virtual_address && rva < section.virtual_address.checked_add(extent)? {
            let delta = rva - section.virtual_address;
            if delta >= section.raw_size { return None; }
            return usize::try_from(section.raw_offset.checked_add(delta)?).ok();
        }
    }
    None
}

fn parse_sections(bytes: &[u8], table: usize, count: usize) -> Result<Vec<Section>, String> {
    if count == 0 || count > MAX_SECTIONS {
        return Err(format!("PE section count {count} is outside the supported range"));
    }
    let mut output = Vec::with_capacity(count);
    for index in 0..count {
        let offset = table.checked_add(index.checked_mul(40).ok_or("section offset overflow")?)
            .ok_or("section offset overflow")?;
        let header = bytes.get(offset..offset + 40).ok_or("truncated PE section table")?;
        let name_end = header[..8].iter().position(|b| *b == 0).unwrap_or(8);
        let name = String::from_utf8_lossy(&header[..name_end]).into_owned();
        let virtual_size = u32_at(header, 8).ok_or("bad section virtual size")?;
        let virtual_address = u32_at(header, 12).ok_or("bad section RVA")?;
        let raw_size = u32_at(header, 16).ok_or("bad section raw size")?;
        let raw_offset = u32_at(header, 20).ok_or("bad section raw offset")?;
        let characteristics = u32_at(header, 36).ok_or("bad section characteristics")?;
        let end = usize::try_from(raw_offset).ok().and_then(|x| x.checked_add(raw_size as usize))
            .ok_or("section raw range overflow")?;
        if raw_size > 0 && end > bytes.len() {
            return Err(format!("section {name} extends beyond the input file"));
        }
        output.push(Section { name, virtual_address, virtual_size, raw_offset, raw_size, characteristics });
    }
    Ok(output)
}

fn directory_pair(bytes: &[u8], directory_start: usize, index: usize, directory_count: u32) -> (u32, u32) {
    if index as u32 >= directory_count { return (0, 0); }
    let offset = directory_start.saturating_add(index.saturating_mul(8));
    (u32_at(bytes, offset).unwrap_or(0), u32_at(bytes, offset + 4).unwrap_or(0))
}

fn import_summary(bytes: &[u8], sections: &[Section], import_rva: u32) -> (usize, Vec<String>) {
    let Some(mut offset) = rva_to_file(sections, import_rva) else { return (0, Vec::new()) };
    let mut count = 0usize;
    let mut names = Vec::new();
    for _ in 0..4096 {
        let Some(descriptor) = bytes.get(offset..offset + 20) else { break };
        let original = u32_at(descriptor, 0).unwrap_or(0);
        let name_rva = u32_at(descriptor, 12).unwrap_or(0);
        let first_thunk = u32_at(descriptor, 16).unwrap_or(0);
        if original == 0 && name_rva == 0 && first_thunk == 0 { break; }
        if let Some(name_at) = rva_to_file(sections, name_rva) {
            let name = c_string(bytes, name_at, 260);
            if !name.is_empty() {
                count += 1;
                if names.len() < 48 { names.push(name); }
            }
        }
        offset = match offset.checked_add(20) { Some(value) => value, None => break };
    }
    (count, names)
}

fn export_summary(bytes: &[u8], sections: &[Section], export_rva: u32) -> (usize, Vec<String>) {
    let Some(offset) = rva_to_file(sections, export_rva) else { return (0, Vec::new()) };
    let Some(directory) = bytes.get(offset..offset + 40) else { return (0, Vec::new()) };
    let count = u32_at(directory, 24).unwrap_or(0).min(65_536) as usize;
    let names_rva = u32_at(directory, 32).unwrap_or(0);
    let Some(names_at) = rva_to_file(sections, names_rva) else { return (count, Vec::new()) };
    let mut names = Vec::new();
    for i in 0..count.min(48) {
        let Some(name_rva) = u32_at(bytes, names_at + i * 4) else { break };
        if let Some(name_at) = rva_to_file(sections, name_rva) {
            let name = c_string(bytes, name_at, 260);
            if !name.is_empty() { names.push(name); }
        }
    }
    (count, names)
}

/// Parse a PE32/PE32+ file, decode executable sections and recover a bounded basic-block CFG.
pub(crate) fn reconstruct_pe(bytes: &[u8]) -> Result<Value, String> {
    if bytes.len() < 0x40 || bytes.get(..2) != Some(b"MZ") {
        return Err("input is not a DOS/PE binary".into());
    }
    let pe_offset = u32_at(bytes, 0x3c).ok_or("missing PE offset")? as usize;
    let signature = bytes.get(pe_offset..pe_offset + 4).ok_or("truncated PE signature")?;
    if signature != b"PE\0\0" { return Err("invalid PE signature".into()); }
    let coff = pe_offset + 4;
    let machine = u16_at(bytes, coff).ok_or("missing PE machine")?;
    let section_count = u16_at(bytes, coff + 2).ok_or("missing PE section count")? as usize;
    let optional_size = u16_at(bytes, coff + 16).ok_or("missing optional-header size")? as usize;
    let optional = coff + 20;
    let magic = u16_at(bytes, optional).ok_or("missing PE optional-header magic")?;
    let (bitness, image_base, directory_relative, number_relative) = match magic {
        0x10b => (32, u32_at(bytes, optional + 28).ok_or("missing PE32 image base")? as u64, 96usize, 92usize),
        0x20b => (64, u64_at(bytes, optional + 24).ok_or("missing PE32+ image base")?, 112usize, 108usize),
        _ => return Err(format!("unsupported PE optional-header magic 0x{magic:04x}")),
    };
    let architecture = match machine {
        0x014c if bitness == 32 => "x86",
        0x8664 if bitness == 64 => "x86-64",
        0xaa64 => "ARM64",
        0xa641 => "ARM64EC",
        _ => "unknown",
    };
    if !matches!(machine, 0x014c | 0x8664) {
        return Err(format!("static x86 decoder does not support {architecture} PE machine 0x{machine:04x}"));
    }
    let entry_rva = u32_at(bytes, optional + 16).ok_or("missing PE entrypoint RVA")?;
    let directory_count = u32_at(bytes, optional + number_relative).unwrap_or(0).min(16);
    let directory_start = optional + directory_relative;
    let (export_rva, _) = directory_pair(bytes, directory_start, 0, directory_count);
    let (import_rva, _) = directory_pair(bytes, directory_start, 1, directory_count);
    let sections = parse_sections(bytes, optional + optional_size, section_count)?;
    let (import_count, imported_dlls) = import_summary(bytes, &sections, import_rva);
    let (export_count, exported_symbols) = export_summary(bytes, &sections, export_rva);

    let mut executable_bytes = 0usize;
    let mut instruction_count = 0usize;
    let mut invalid_instructions = 0usize;
    let mut branch_count = 0usize;
    let mut indirect_branches = 0usize;
    let mut leaders = BTreeSet::new();
    let mut section_reports = Vec::new();
    let mut instruction_ir = Vec::new();
    let mut block_starts = Vec::new();
    let mut truncated = false;

    for section in sections.iter().filter(|s| s.characteristics & 0x2000_0000 != 0 && s.raw_size > 0) {
        let start = section.raw_offset as usize;
        let end = start.checked_add(section.raw_size as usize).ok_or("executable section overflow")?;
        let code = bytes.get(start..end).ok_or("truncated executable section")?;
        executable_bytes = executable_bytes.saturating_add(code.len());
        if executable_bytes > MAX_EXECUTABLE_BYTES {
            return Err("executable sections exceed the 64 MB static-analysis budget".into());
        }
        let ip = image_base.saturating_add(section.virtual_address as u64);
        let mut decoder = Decoder::with_ip(bitness, code, ip, DecoderOptions::NONE);
        let mut local_instructions = 0usize;
        if decoder.can_decode() { leaders.insert(ip); }
        while decoder.can_decode() {
            if instruction_count >= MAX_INSTRUCTIONS {
                truncated = true;
                break;
            }
            let instruction = decoder.decode();
            local_instructions += 1;
            instruction_count += 1;
            if !instruction.is_invalid() && instruction_ir.len() < 50_000 {
                let flow_name = format!("{:?}", instruction.flow_control());
                let branch_target = if matches!(
                    instruction.flow_control(),
                    FlowControl::ConditionalBranch
                        | FlowControl::UnconditionalBranch
                        | FlowControl::IndirectBranch
                        | FlowControl::Call
                        | FlowControl::IndirectCall
                ) {
                    Some(format!("0x{:x}", instruction.near_branch_target()))
                } else {
                    None
                };
                instruction_ir.push(json!({
                    "ip": format!("0x{:x}", instruction.ip()),
                    "mnemonic": format!("{:?}", instruction.mnemonic()),
                    "flow": flow_name,
                    "branch_target": branch_target,
                    "size": instruction.len(),
                    "section": section.name,
                }));
            }
            if instruction.is_invalid() {
                invalid_instructions += 1;
                continue;
            }
            let flow = instruction.flow_control();
            let next_ip = decoder.ip();
            match flow {
                FlowControl::ConditionalBranch => {
                    branch_count += 1;
                    let target = instruction.near_branch_target();
                    if target >= ip && target < ip.saturating_add(section.virtual_size.max(section.raw_size) as u64) {
                        leaders.insert(target);
                    }
                    leaders.insert(next_ip);
                }
                FlowControl::UnconditionalBranch => {
                    branch_count += 1;
                    let target = instruction.near_branch_target();
                    if target >= ip && target < ip.saturating_add(section.virtual_size.max(section.raw_size) as u64) {
                        leaders.insert(target);
                    }
                }
                FlowControl::IndirectBranch => {
                    branch_count += 1;
                    indirect_branches += 1;
                }
                FlowControl::Call | FlowControl::IndirectCall => {
                    let target = instruction.near_branch_target();
                    if target != 0 && target >= ip && target < ip.saturating_add(section.virtual_size.max(section.raw_size) as u64) {
                        leaders.insert(target);
                    }
                    leaders.insert(next_ip);
                }
                FlowControl::Return | FlowControl::Interrupt | FlowControl::XbeginXabortXend => {
                    leaders.insert(next_ip);
                }
                _ => {}
            }
        }
        section_reports.push(json!({
            "name": section.name,
            "rva": format!("0x{:08x}", section.virtual_address),
            "virtual_size": section.virtual_size,
            "raw_size": section.raw_size,
            "decoded_instructions": local_instructions,
        }));
        if truncated { break; }
    }

    let block_count = leaders.len();
    block_starts.extend(leaders.iter().take(10_000).map(|address| format!("0x{address:x}")));
    let notes = if truncated {
        "instruction cap reached; analysis is partial, not a complete rebuild"
    } else {
        "static instruction/CFG reconstruction only; no Windows API or AEX semantics are emulated"
    };
    Ok(json!({
        "format": "PE",
        "machine": format!("0x{machine:04x}"),
        "architecture": architecture,
        "bitness": bitness,
        "image_base": format!("0x{image_base:x}"),
        "entry_point_rva": format!("0x{entry_rva:08x}"),
        "section_count": sections.len(),
        "executable_section_count": section_reports.len(),
        "executable_bytes": executable_bytes,
        "instruction_count": instruction_count,
        "invalid_instruction_count": invalid_instructions,
        "basic_block_candidates": block_count,
        "branch_count": branch_count,
        "indirect_branch_count": indirect_branches,
        "imported_dll_count": import_count,
        "imported_dlls": imported_dlls,
        "exported_symbol_count": export_count,
        "exported_symbols": exported_symbols,
        "sections": section_reports,
        "instruction_ir": instruction_ir,
        "basic_block_starts": block_starts,
        "truncated": truncated,
        "status": "static_ir_recovered_not_native_recompiled",
        "notes": notes,
    }))
}
