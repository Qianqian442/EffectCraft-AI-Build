//! Import a useful, explicitly reported subset of Alight Motion XML and NodeVideo projects.
//! The importer lives behind the existing File > Import > EffectCraft Project command.

use std::collections::HashMap;
use std::io::{Cursor, Read, Write};
use std::path::{Component, Path, PathBuf};

use effectcraft_color::Label;
use effectcraft_keyframe::TextDoc;
use effectcraft_project::build::{self, Ids};
use effectcraft_project::{
    Comp, Footage, FootageKind, ItemId, ItemKind, LayerSource, Project, Value,
};
use effectcraft_time::{FrameRate, Tick};
use serde_json::{Value as J, json};

use crate::{EngineError, Result, Session, cmd};
use super::{CommandSpec, always};

const MAX_PROJECT_BYTES: usize = 128 * 1024 * 1024;
const MAX_ZIP_ENTRIES: usize = 10_000;
// Large project packages may contain camera originals. Stream entries to disk rather than
// allocating the decompressed archive in RAM; retain a generous disk-expansion safety ceiling.
const MAX_ZIP_TOTAL: u64 = 8 * 1024 * 1024 * 1024;
const MAX_ZIP_ENTRY: u64 = 4 * 1024 * 1024 * 1024;

#[derive(Clone, Copy)]
struct Xform {
    pos: [f64; 2],
    scale: [f64; 2],
    rotation: f64,
    opacity: f64,
}
impl Default for Xform {
    fn default() -> Self {
        Self { pos: [0.5, 0.5], scale: [1.0, 1.0], rotation: 0.0, opacity: 1.0 }
    }
}
impl Xform {
    fn compose(self, child: Self) -> Self {
        Self {
            pos: [
                self.pos[0] + (child.pos[0] - 0.5) * self.scale[0],
                self.pos[1] + (child.pos[1] - 0.5) * self.scale[1],
            ],
            scale: [self.scale[0] * child.scale[0], self.scale[1] * child.scale[1]],
            rotation: self.rotation + child.rotation,
            opacity: (self.opacity * child.opacity).clamp(0.0, 1.0),
        }
    }
}

fn err(message: impl Into<String>) -> EngineError {
    EngineError::Other(message.into())
}
fn safe_name(name: &str) -> String {
    let result: String = name.chars().map(|c| {
        if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '_' }
    }).collect();
    if result.is_empty() { "Imported_Project".into() } else { result }
}
fn ext(path: &str) -> String {
    Path::new(path).extension().and_then(|e| e.to_str()).unwrap_or("").to_ascii_lowercase()
}

/// ZIP entries are written only below this newly-created app-owned directory. Parent traversal,
/// absolute paths, symlinks, excessive entry counts and oversized archives are refused.
fn extract_project_zip(s: &Session, path: &str) -> Result<(String, String)> {
    let config = s.config.as_ref().and_then(|c| c.dir())
        .ok_or_else(|| err("No writable app project directory is available for package extraction"))?;
    let stem = Path::new(path).file_stem().map(|x| x.to_string_lossy().to_string()).unwrap_or_else(|| "Imported_Project".into());
    let import_id = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_millis();
    let root = config.join("Imported-Projects").join(format!("{}-{import_id}", safe_name(&stem)));
    std::fs::create_dir_all(&root).map_err(|e| err(format!("Cannot create import directory: {e}")))?;
    let file = std::fs::File::open(path).map_err(|e| err(format!("Cannot read ZIP package: {e}")))?;
    let mut archive = zip::ZipArchive::new(file).map_err(|e| err(format!("Invalid project ZIP: {e}")))?;
    if archive.len() > MAX_ZIP_ENTRIES {
        return Err(err("Project ZIP contains more than 10,000 entries"));
    }

    let mut total = 0_u64;
    let mut project_file: Option<PathBuf> = None;
    for index in 0..archive.len() {
        let mut entry = archive.by_index(index).map_err(|e| err(format!("Cannot read ZIP entry: {e}")))?;
        if entry.is_dir() { continue; }
        let name = entry.name().map_err(|e| err(format!("Invalid ZIP entry name: {e}")))?.to_string();
        if name.contains('\\') || name.contains('\0') { continue; }
        let relative = Path::new(&name);
        if relative.components().any(|c| !matches!(c, Component::Normal(_))) { continue; }
        let size = entry.size();
        if size > MAX_ZIP_ENTRY {
            return Err(err(format!("ZIP entry {name} exceeds the 4 GB safety limit")));
        }
        total = total.saturating_add(size);
        if total > MAX_ZIP_TOTAL {
            return Err(err("Project ZIP expands beyond the 8 GB safety limit"));
        }

        let destination = root.join(relative);
        if let Some(parent) = destination.parent() {
            std::fs::create_dir_all(parent).map_err(|e| err(format!("Cannot create package folder: {e}")))?;
        }
        let mut output = std::fs::File::create(&destination)
            .map_err(|e| err(format!("Cannot create {name}: {e}")))?;
        let mut limited = (&mut entry).take(MAX_ZIP_ENTRY + 1);
        let copied = std::io::copy(&mut limited, &mut output)
            .map_err(|e| err(format!("Cannot extract {name}: {e}")))?;
        if copied > MAX_ZIP_ENTRY {
            return Err(err(format!("ZIP entry {name} exceeds the 4 GB safety limit")));
        }
        if copied != size {
            return Err(err(format!("ZIP entry {name} size does not match its archive metadata")));
        }
        let lower = name.to_ascii_lowercase();
        if lower.ends_with(".ecproj") || lower.ends_with(".ecprojx") {
            project_file = Some(destination);
        } else if project_file.is_none() && (lower.ends_with("draft_content.json") || lower.ends_with(".capcut.json")) {
            project_file = Some(destination);
        } else if lower.ends_with(".nv") {
            if project_file.is_none() { project_file = Some(destination); }
        } else if project_file.is_none() && (lower.ends_with(".xml") || lower.ends_with(".alight")) {
            project_file = Some(destination);
        }
    }
    let file = project_file.ok_or_else(|| err("此 ZIP 不包含 EffectCraft 手机版工程（.ecproj/.ecprojx）、NodeVideo .nv、Alight Motion XML 或 CapCut 工程文件"))?;
    let file_ext = ext(&file.to_string_lossy());
    Ok((file.to_string_lossy().to_string(), root.to_string_lossy().to_string()))
}

fn collect_refs<'a>(root: &'a J) -> HashMap<&'a str, &'a J> {
    let mut refs = HashMap::new();
    let mut stack = vec![root];
    while let Some(value) = stack.pop() {
        match value {
            J::Object(map) => {
                if let Some(id) = map.get("$id").and_then(J::as_str) {
                    refs.insert(id, value);
                }
                stack.extend(map.values());
            }
            J::Array(items) => stack.extend(items),
            _ => {}
        }
    }
    refs
}
fn deref<'a>(value: &'a J, refs: &HashMap<&'a str, &'a J>) -> &'a J {
    value.get("$ref").and_then(J::as_str).and_then(|id| refs.get(id).copied()).unwrap_or(value)
}
fn type_name(value: &J) -> &str {
    value.get("$type").and_then(J::as_str).unwrap_or("")
}
fn props_of<'a>(node: &'a J, refs: &HashMap<&'a str, &'a J>) -> Vec<&'a J> {
    node.get("Props").and_then(J::as_array).map(|a| a.iter().map(|x| deref(x, refs)).collect()).unwrap_or_default()
}
fn data_of<'a>(node: &'a J, refs: &HashMap<&'a str, &'a J>, kind: &str) -> Option<&'a J> {
    props_of(node, refs).into_iter().find(|p| type_name(p).contains(kind))
}
fn param<'a>(data: &'a J, refs: &HashMap<&'a str, &'a J>, name: &str) -> Option<&'a J> {
    let value = data.get("Params")?.get(name)?;
    Some(deref(value, refs))
}
fn number(value: Option<&J>, fallback: f64) -> f64 {
    value.and_then(|v| v.get("Value").and_then(J::as_f64).or_else(|| v.as_f64())).filter(|v| v.is_finite()).unwrap_or(fallback)
}
fn vector2<'a>(value: Option<&'a J>, refs: &HashMap<&'a str, &'a J>, fallback: [f64; 2]) -> [f64; 2] {
    let Some(value) = value else { return fallback };
    let params = value.get("Params").and_then(J::as_array);
    if let Some(p) = params {
        if p.len() >= 2 {
            return [
                number(Some(deref(&p[0], refs)), fallback[0]),
                number(Some(deref(&p[1], refs)), fallback[1]),
            ];
        }
    }
    fallback
}
fn timeline(node: &J, key: &str, fallback: f64) -> f64 {
    node.get("TimeLine").and_then(|t| t.get(key)).and_then(J::as_f64).filter(|v| v.is_finite()).unwrap_or(fallback)
}
fn nv_transform(node: &J, refs: &HashMap<&str, &J>) -> Xform {
    let Some(data) = data_of(node, refs, "DataTransform") else { return Xform::default() };
    let p = |name| param(data, refs, name);
    Xform {
        pos: vector2(p("_position"), refs, [0.5, 0.5]),
        scale: vector2(p("_scale"), refs, [1.0, 1.0]),
        rotation: number(p("_rotation"), 0.0),
        opacity: number(p("_opacity"), 1.0),
    }
}
fn register_imported_fonts(base: &str) -> HashMap<String, String> {
    let mut families = HashMap::new();
    let mut pending = vec![
        Path::new(base).join("Fonts"),
        Path::new(base).join("fonts"),
    ];
    let mut checked = 0usize;
    while let Some(dir) = pending.pop() {
        if checked >= 256 { break; }
        let Ok(entries) = std::fs::read_dir(&dir) else { continue };
        for entry in entries.flatten() {
            checked += 1;
            if checked >= 256 { break; }
            let path = entry.path();
            if path.is_dir() {
                pending.push(path);
                continue;
            }
            let extension = ext(&path.to_string_lossy());
            if !matches!(extension.as_str(), "ttf" | "otf" | "ttc" | "otc") { continue; }
            let Ok(metadata) = std::fs::metadata(&path) else { continue };
            if metadata.len() == 0 || metadata.len() > 32 * 1024 * 1024 { continue; }
            let Ok(bytes) = std::fs::read(&path) else { continue };
            let ids = effectcraft_text::fonts::add_font_data(bytes);
            let Some(id) = ids.first().copied() else { continue };
            let family = effectcraft_text::fonts::face(id).info.family.clone();
            if let Some(file_name) = path.file_name().and_then(|n| n.to_str()) {
                families.insert(file_name.to_ascii_lowercase(), family);
            }
        }
    }
    families
}

fn media_file(base: &str, stored: &str) -> Option<String> {
    let stored_path = Path::new(stored);
    let basename = stored_path.file_name()?;
    let base_path = Path::new(base);
    let candidates = [
        stored_path.to_path_buf(),
        base_path.join("Medias").join(basename),
        base_path.join("medias").join(basename),
        base_path.join("assets").join(basename),
        base_path.join("media").join(basename),
        base_path.join(basename),
    ];
    candidates.into_iter().find(|p| p.is_file()).map(|p| p.to_string_lossy().to_string())
}
fn node_label(node: &J, fallback: &str) -> String {
    node.get("Name").and_then(J::as_str).filter(|s| !s.trim().is_empty()).unwrap_or(fallback).to_string()
}
fn comp_id(project: &Project, id: ItemId) -> Result<Comp> {
    project.comp(id).cloned().ok_or_else(|| err("Imported composition was not created"))
}
fn set_prop(layer: &mut effectcraft_project::Layer, path: &str, value: Value) {
    if let Some(prop) = layer.props.prop_mut(path) { prop.value = value; }
}
fn set_transform(layer: &mut effectcraft_project::Layer, transform: Xform, width: u32, height: u32) {
    set_prop(layer, "transform/position", Value::Vec3([
        transform.pos[0] * width as f64, transform.pos[1] * height as f64, 0.0,
    ]));
    set_prop(layer, "transform/scale", Value::Vec3([
        transform.scale[0] * 100.0, transform.scale[1] * 100.0, 100.0,
    ]));
    set_prop(layer, "transform/rotation", Value::Scalar(transform.rotation));
    set_prop(layer, "transform/opacity", Value::Scalar(transform.opacity * 100.0));
}
fn attach_layer(
    project: &mut Project,
    comp_id: ItemId,
    comp: &Comp,
    name: &str,
    source: LayerSource,
    size: (u32, u32),
    start: f64,
    in_point: f64,
    out_point: f64,
    stretch: f64,
    transform: Xform,
) -> Result<effectcraft_project::Layer> {
    let duration = Tick::from_seconds_f64((out_point - in_point).max(1.0 / comp.frame_rate.as_f64()));
    let mut layer = build::layer(project, comp, name, source, size, Some(duration));
    layer.start_time = Tick::from_seconds_f64(start);
    layer.in_point = Tick::from_seconds_f64(in_point.max(0.0));
    layer.out_point = Tick::from_seconds_f64(out_point.max(in_point + 1.0 / comp.frame_rate.as_f64()));
    layer.stretch = if stretch.is_finite() && stretch.abs() >= 0.0001 { stretch * 100.0 } else { 100.0 };
    set_transform(&mut layer, transform, comp.width, comp.height);
    Ok(layer)
}
fn push_layer(project: &mut Project, comp_id: ItemId, layer: effectcraft_project::Layer) -> Result<()> {
    project.comp_mut(comp_id).ok_or_else(|| err("Imported composition disappeared"))?.layers.push(layer);
    Ok(())
}
fn read_nv_project_settings(root: &J, refs: &HashMap<&str, &J>) -> (u32, u32, FrameRate, f64) {
    let mut width = 1920_u32;
    let mut height = 1080_u32;
    let mut fps = 30.0_f64;
    if let Some(data) = data_of(root, refs, "DataProjectSetting") {
        if let Some(res) = param(data, refs, "_resolution") {
            width = res.get("Width").and_then(J::as_f64).unwrap_or(width as f64) as u32;
            height = res.get("Height").and_then(J::as_f64).unwrap_or(height as f64) as u32;
        }
        fps = param(data, refs, "_fps").map(|v| number(Some(v), fps)).unwrap_or(fps);
    }
    width = width.clamp(64, 8192);
    height = height.clamp(64, 8192);
    fps = fps.clamp(1.0, 240.0);
    let duration = timeline(root, "End", root.get("FixedDuration").and_then(J::as_f64).unwrap_or(10.0)).max(1.0 / fps);
    (width, height, FrameRate::from_f64(fps), duration.min(24.0 * 60.0 * 60.0))
}
fn has_nv_keyframes(node: &J, refs: &HashMap<&str, &J>) -> bool {
    let mut stack = vec![node];
    let mut visited = std::collections::HashSet::new();
    while let Some(value) = stack.pop() {
        if let Some(id) = value.get("$id").and_then(J::as_str) {
            if !visited.insert(id) { continue; }
        }
        if let Some(keys) = value.get("KeyFrames").and_then(J::as_array) {
            if !keys.is_empty() { return true; }
        }
        if let Some(reference) = value.get("$ref").and_then(J::as_str) {
            if let Some(target) = refs.get(reference) { stack.push(*target); }
        }
        match value {
            J::Object(map) => stack.extend(map.values()),
            J::Array(items) => stack.extend(items),
            _ => {}
        }
    }
    false
}
fn node_effect_warning(node: &J, refs: &HashMap<&str, &J>, warnings: &mut Vec<String>) {
    let effects = props_of(node, refs).into_iter().filter(|p| type_name(p).contains("DataEffect")).count();
    if effects > 0 {
        warnings.push(format!("{}: {} NodeVideo effect block(s) need manual recreation", node_label(node, "Layer"), effects));
    }
}

fn import_nv_node(
    project: &mut Project,
    folder: ItemId,
    comp_id: ItemId,
    comp: &Comp,
    node: &J,
    refs: &HashMap<&str, &J>,
    base: &str,
    font_map: &HashMap<String, String>,
    parent: Xform,
    depth: usize,
    missing: &mut Vec<String>,
    warnings: &mut Vec<String>,
    created_items: &mut Vec<u64>,
) -> Result<()> {
    if depth > 64 { warnings.push("Some deeply nested NodeVideo groups were skipped".into()); return Ok(()); }
    let kind = type_name(node);
    let local = parent.compose(nv_transform(node, refs));
    let name = node_label(node, "Imported Layer");
    node_effect_warning(node, refs, warnings);
    if (kind.contains("NodeGroup") || kind.contains("NodeCamera")) {
        if node.get("ChildList").and_then(J::as_array).is_some_and(|children| !children.is_empty()) {
            warnings.push(format!("{name}: group/camera hierarchy was flattened; 3D camera projection is not preserved"));
        }
    }
    if has_nv_keyframes(node, refs) {
        warnings.push(format!("{name}: NodeVideo keyframe data is not converted in this importer pass"));
    }
    let start = timeline(node, "Pos", 0.0);
    let in_point = timeline(node, "Start", 0.0);
    let out_point = timeline(node, "End", timeline(node, "Duration", comp.duration.seconds()));
    let stretch = timeline(node, "Stretch", 1.0);

    if kind.contains("NodeMediaImage") || kind.contains("NodeMediaVideo") {
        let asset = node.get("AssetImage").or_else(|| node.get("AssetVideo"));
        let stored = asset.and_then(|a| a.get("AbsolutePath")).and_then(J::as_str).unwrap_or("");
        let found = media_file(base, stored);
        let path = found.clone().unwrap_or_else(|| stored.to_string());
        let mut footage = Footage::default();
        footage.path = path.clone();
        footage.kind = if kind.contains("Video") { FootageKind::Video } else { FootageKind::Still };
        footage.width = asset.and_then(|a| a.get("Width")).and_then(J::as_u64).unwrap_or(0).min(8192) as u32;
        footage.height = asset.and_then(|a| a.get("Height")).and_then(J::as_u64).unwrap_or(0).min(8192) as u32;
        footage.frame_rate = comp.frame_rate;
        footage.duration = Tick::from_seconds_f64((out_point - in_point).max(0.1));
        footage.has_video = true;
        footage.missing = found.is_none();
        if found.is_none() {
            missing.push(format!("{name}: {}", Path::new(stored).file_name().unwrap_or_default().to_string_lossy()));
        }
        let item = project.add_item(&name, Label::None, Some(folder), ItemKind::Footage(footage));
        created_items.push(item.0);
        let layer = attach_layer(project, comp_id, comp, &name, LayerSource::Footage { item }, (asset.and_then(|a| a.get("Width")).and_then(J::as_u64).unwrap_or(comp.width as u64).min(8192) as u32,
            asset.and_then(|a| a.get("Height")).and_then(J::as_u64).unwrap_or(comp.height as u64).min(8192) as u32),
            start, in_point, out_point, stretch, local)?;
        push_layer(project, comp_id, layer)?;
    } else if kind.contains("NodeShape") {
        let data = data_of(node, refs, "DataShape");
        let params = data.and_then(|d| d.get("Params"));
        let val = |key: &str| params.and_then(|p| p.get(key)).map(|v| deref(v, refs));
        let shape_type = val("_shape_type").map(|v| number(Some(v), 0.0) as u32).unwrap_or(0);
        let shape_size = vector2(val("_shape_size"), refs, [1.0, 1.0]);
        let color_value = val("_fill_color").and_then(|v| v.get("Color"));
        let color = [
            color_value.and_then(|c| c.get("r")).and_then(J::as_f64).unwrap_or(1.0),
            color_value.and_then(|c| c.get("g")).and_then(J::as_f64).unwrap_or(1.0),
            color_value.and_then(|c| c.get("b")).and_then(J::as_f64).unwrap_or(1.0),
            color_value.and_then(|c| c.get("a")).and_then(J::as_f64).unwrap_or(1.0),
        ];
        let size = ((shape_size[0] * comp.width as f64).abs().clamp(1.0, 8192.0),
                    (shape_size[1] * comp.height as f64).abs().clamp(1.0, 8192.0));
        let mut layer = attach_layer(project, comp_id, comp, &name, LayerSource::Shape, (size.0 as u32, size.1 as u32),
            start, in_point, out_point, stretch, local)?;
        let mut ids = Ids(&mut project.next_id);
        let path = if shape_type == 1 {
            build::shape_rect(&mut ids, [size.0, size.1], [0.0, 0.0],
                val("_rectangle_roundness").map(|v| number(Some(v), 0.0)).unwrap_or(0.0))
        } else {
            if shape_type > 1 { warnings.push(format!("{name}: NodeVideo polygon/pen shape imported as an ellipse approximation")); }
            build::shape_ellipse(&mut ids, [size.0, size.1], [0.0, 0.0])
        };
        let fill = build::shape_fill(&mut ids, color);
        let group = build::shape_group(&mut ids, &name, vec![path, fill]);
        drop(ids);
        if let Some(contents) = layer.props.sub_mut("contents") {
            contents.children.push(group.into());
        }
        push_layer(project, comp_id, layer)?;
    } else if kind.contains("NodeViewText") || kind.contains("NodeText") {
        let data = data_of(node, refs, "DataText3D");
        let params = data.and_then(|d| d.get("Params"));
        let text = params.and_then(|p| p.get("_text")).map(|v| deref(v, refs)).and_then(|v| v.get("Text")).and_then(J::as_str).unwrap_or("").to_string();
        let picked_font = params.and_then(|p| p.get("_font")).map(|v| deref(v, refs)).and_then(|v| v.get("PickedFont")).and_then(J::as_str).unwrap_or("Inter").to_string();
        let font = font_map.get(&picked_font.to_ascii_lowercase()).cloned().unwrap_or(picked_font);
        let size = params.and_then(|p| p.get("_size")).map(|v| deref(v, refs)).map(|v| number(Some(v), 1.0)).unwrap_or(1.0);
        let mut layer = attach_layer(project, comp_id, comp, &name, LayerSource::Text, (comp.width, comp.height),
            start, in_point, out_point, stretch, local)?;
        let mut doc = TextDoc::default();
        doc.text = text;
        doc.font = font;
        doc.size = (size * 72.0).clamp(1.0, 512.0);
        if let Some(text_group) = layer.props.sub_mut("text") {
            if let Some(prop) = text_group.get_mut("sourceText") {
                prop.value = Value::Text(Box::new(doc));
            }
        }
        if kind.contains("3D") { warnings.push(format!("{name}: 3D text converted to a 2D text layer")); }
        push_layer(project, comp_id, layer)?;
        if let Some(text_anim) = props_of(node, refs).into_iter().find(|p| type_name(p).contains("DataTextAnimation")) {
            if text_anim.get("Params").and_then(|p| p.get("_animation_list")).is_some() {
                warnings.push(format!("{name}: NodeVideo text animation not converted"));
            }
        }
    } else if !kind.contains("NodeGroup") && !kind.contains("NodeCamera") {
        warnings.push(format!("{name}: unsupported NodeVideo layer type was skipped ({})", kind.split(',').next().unwrap_or(kind)));
    }

    if let Some(children) = node.get("ChildList").and_then(J::as_array) {
        for child in children {
            import_nv_node(project, folder, comp_id, comp, child, refs, base, font_map, local, depth + 1, missing, warnings, created_items)?;
        }
    }
    Ok(())
}

fn import_nodevideo(s: &mut Session, path: &str, base: &str, bytes: &[u8], font_map: &HashMap<String, String>) -> Result<J> {
    if bytes.len() > MAX_PROJECT_BYTES { return Err(err("NodeVideo project is larger than 128 MB")); }
    let root: J = serde_json::from_slice(bytes).map_err(|e| err(format!("NodeVideo .nv file is not valid JSON: {e}")))?;
    let refs = collect_refs(&root);
    if root.get("ChildList").and_then(J::as_array).is_none() {
        return Err(err("This JSON file does not have a NodeVideo project hierarchy"));
    }
    let (width, height, rate, duration) = read_nv_project_settings(&root, &refs);
    let name = root.get("Name").and_then(J::as_str).filter(|n| *n != "Root")
        .map(str::to_string).or_else(|| Path::new(path).file_stem().map(|s| s.to_string_lossy().to_string())).unwrap_or_else(|| "NodeVideo Project".into());
    let roots = root.get("ChildList").and_then(J::as_array).cloned().unwrap_or_default();
    let (folder, cid, items, missing, warnings) = s.edit("Import NodeVideo Project", None, |project, state| {
        let folder = project.add_item(&name, Label::Yellow, None, ItemKind::Folder);
        let comp = Comp::new(width, height, rate, Tick::from_seconds_f64(duration));
        let cid = project.add_item(&name, Label::Sandstone, Some(folder), ItemKind::Comp(comp.into()));
        let comp_copy = comp_id(project, cid)?;
        let mut items = Vec::new();
        let mut missing = Vec::new();
        let mut warnings = Vec::new();
        for node in &roots {
            import_nv_node(project, folder, cid, &comp_copy, node, &refs, base, font_map, Xform::default(), 0,
                &mut missing, &mut warnings, &mut items)?;
        }
        if !missing.is_empty() { warnings.push(format!("{} media file(s) were not found; placeholders were created", missing.len())); }
        state.project_selection = vec![folder];
        Ok((folder, cid, items, missing, warnings))
    })?;
    s.open_comp(cid);
    let mut all_warnings = warnings.clone();
    if !missing.is_empty() { all_warnings.push("Choose File > Replace Footage to relink missing media".into()); }
    s.toast(if all_warnings.is_empty() { format!("Imported NodeVideo project {name}") } else {
        format!("Imported NodeVideo project {name} ({} import notes)", all_warnings.len())
    });
    Ok(json!({"folder": folder.0, "comp": cid.0, "items": items, "missingMedia": missing, "warnings": all_warnings}))
}

fn attr_f(node: roxmltree::Node<'_, '_>, key: &str, fallback: f64) -> f64 {
    node.attribute(key).and_then(|s| s.parse::<f64>().ok()).filter(|v| v.is_finite()).unwrap_or(fallback)
}
fn split_pair(value: &str, fallback: [f64; 2]) -> [f64; 2] {
    let mut it = value.split(|c: char| c == ',' || c == ' ' || c == ';').filter(|s| !s.is_empty());
    [
        it.next().and_then(|s| s.parse().ok()).unwrap_or(fallback[0]),
        it.next().and_then(|s| s.parse().ok()).unwrap_or(fallback[1]),
    ]
}
fn xml_child<'a, 'input>(node: roxmltree::Node<'a, 'input>, name: &str) -> Option<roxmltree::Node<'a, 'input>> {
    node.children().find(|n| n.is_element() && n.tag_name().name() == name)
}
fn xml_value(node: roxmltree::Node<'_, '_>, key: &str, fallback: &str) -> String {
    xml_child(node, key).and_then(|n| n.attribute("value").map(str::to_string).or_else(|| n.text().map(str::to_string))).unwrap_or_else(|| fallback.into())
}
fn xml_transform(node: roxmltree::Node<'_, '_>, width: u32, height: u32) -> Xform {
    let tr = xml_child(node, "transform").unwrap_or(node);
    let pos = split_pair(&xml_value(tr, "location", &format!("{},{}", width as f64 / 2.0, height as f64 / 2.0)),
        [width as f64 / 2.0, height as f64 / 2.0]);
    let mut scale = split_pair(&xml_value(tr, "scale", "1,1"), [1.0, 1.0]);
    if scale[0].abs() > 10.0 { scale[0] /= 100.0; }
    if scale[1].abs() > 10.0 { scale[1] /= 100.0; }
    let rotation = xml_value(tr, "rotation", "0").parse().unwrap_or(0.0);
    let mut opacity = xml_value(tr, "opacity", "1").parse::<f64>().unwrap_or(1.0);
    if opacity > 1.0 { opacity /= 100.0; }
    Xform { pos: [pos[0] / width.max(1) as f64, pos[1] / height.max(1) as f64], scale, rotation, opacity: opacity.clamp(0.0, 1.0) }
}
fn import_alight_xml(s: &mut Session, path: &str, base: &str, bytes: &[u8], font_map: &HashMap<String, String>) -> Result<J> {
    if bytes.len() > MAX_PROJECT_BYTES { return Err(err("Alight Motion XML is larger than 128 MB")); }
    let text = std::str::from_utf8(bytes).map_err(|_| err("Alight Motion XML must be UTF-8"))?;
    if text.contains("<!DOCTYPE") || text.contains("<!ENTITY") {
        return Err(err("XML DTD and external entities are not accepted"));
    }
    let document = roxmltree::Document::parse(text).map_err(|e| err(format!("Invalid Alight Motion XML: {e}")))?;
    let scene = document.root_element();
    if scene.tag_name().name() != "scene" {
        return Err(err("This XML file is not an Alight Motion scene project"));
    }
    let width = attr_f(scene, "width", 1080.0).round().clamp(64.0, 8192.0) as u32;
    let height = attr_f(scene, "height", 1920.0).round().clamp(64.0, 8192.0) as u32;
    let fps = attr_f(scene, "fps", 30.0).clamp(1.0, 240.0);
    let rate = FrameRate::from_f64(fps);
    let name = Path::new(path).file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_else(|| "Alight Motion Project".into());

    // Alight Motion uses concrete layer tags such as shape/text/group/color, not <layer>.
    let layer_nodes: Vec<_> = scene.descendants().filter(|n| {
        n.is_element() && matches!(n.tag_name().name(), "shape" | "text" | "group" | "color" | "drawing")
    }).collect();
    if layer_nodes.is_empty() {
        return Err(err("Alight Motion scene does not contain any supported layer elements"));
    }
    let max_end = layer_nodes.iter().map(|n| attr_f(*n, "endTime", 0.0)).fold(0.0_f64, f64::max);
    // Alight Motion XML stores layer time in milliseconds; infer the scene extent from its layers.
    let duration = if max_end > 0.0 { (max_end / 1000.0).clamp(0.1, 86400.0) } else { 10.0 };
    let (folder, cid, items, missing, warnings) = s.edit("Import Alight Motion Project", None, |project, state| {
        let folder = project.add_item(&name, Label::Yellow, None, ItemKind::Folder);
        let comp = Comp::new(width, height, rate, Tick::from_seconds_f64(duration));
        let cid = project.add_item(&name, Label::Sandstone, Some(folder), ItemKind::Comp(comp.into()));
        let comp_copy = comp_id(project, cid)?;
        let mut items = Vec::new();
        let mut missing = Vec::new();
        let mut warnings = Vec::new();
        for node in &layer_nodes {
            let kind = node.attribute("type").unwrap_or_else(|| node.tag_name().name());
            let start_ms = attr_f(*node, "startTime", 0.0);
            let end_ms = attr_f(*node, "endTime", max_end.max(1000.0));
            let start = (start_ms / 1000.0).max(0.0);
            let end = (end_ms / 1000.0).max(start + 0.02);
            let transform = xml_transform(*node, width, height);
            let label = node.attribute("label").unwrap_or("Imported Layer");
            let layer_name = node.attribute("name").unwrap_or(label).to_string();
            if node.descendants().any(|n| n.is_element() && n.tag_name().name() == "effect") {
                warnings.push(format!("{layer_name}: Alight Motion effects are not converted yet"));
            }
            if kind.eq_ignore_ascii_case("text") {
                let content = node.descendants().find(|n| n.is_element() && n.tag_name().name() == "content")
                    .and_then(|n| n.text()).unwrap_or("").to_string();
                let mut layer = attach_layer(project, cid, &comp_copy, &layer_name, LayerSource::Text,
                    (width, height), start, 0.0, end - start, 1.0, transform)?;
                let mut doc = TextDoc::default();
                doc.text = content;
                let font_spec = node.attribute("font").unwrap_or("Inter");
                let requested_font = font_spec.strip_prefix("googlefonts?name=")
                    .unwrap_or(font_spec).split('&').next().unwrap_or("Inter").to_string();
                let font_key = Path::new(&requested_font).file_name().and_then(|n| n.to_str()).unwrap_or(&requested_font).to_ascii_lowercase();
                doc.font = font_map.get(&font_key).cloned().unwrap_or(requested_font);
                doc.size = attr_f(*node, "size", 72.0).clamp(1.0, 512.0);
                if let Some(color_node) = xml_child(*node, "fillColor") {
                    let rgba = parse_xml_color(&xml_value(color_node, "value", "#FFFFFFFF"));
                    doc.fill = [rgba[0] as f32, rgba[1] as f32, rgba[2] as f32, rgba[3] as f32];
                }
                if node.descendants().any(|n| n.is_element() && n.tag_name().name() == "kf") {
                    warnings.push(format!("{layer_name}: Alight Motion keyframe curves are not converted in this importer pass"));
                }
                if let Some(group) = layer.props.sub_mut("text") {
                    if let Some(prop) = group.get_mut("sourceText") { prop.value = Value::Text(Box::new(doc)); }
                }
                push_layer(project, cid, layer)?;
                warnings.push(format!("{layer_name}: unsupported Alight Motion text styling/effects were simplified"));
            } else if kind.eq_ignore_ascii_case("media") || kind.eq_ignore_ascii_case("image")
                || (kind.eq_ignore_ascii_case("shape") && node.attribute("fillType").is_some_and(|v| v.eq_ignore_ascii_case("media"))) {
                let media = node.descendants().find(|n| n.is_element() && n.tag_name().name() == "media");
                let stored = media.and_then(|m| m.attribute("filename").or_else(|| m.attribute("uri")).or_else(|| m.attribute("path")))
                    .or_else(|| node.attribute("fillVideo"))
                    .or_else(|| node.attribute("fillImage"))
                    .unwrap_or("");
                let stored = stored.strip_prefix("file://").unwrap_or(stored);
                let found = media_file(base, stored);
                let media_path = found.clone().unwrap_or_else(|| stored.to_string());
                let mut footage = Footage::default();
                footage.path = media_path.clone();
                footage.kind = if matches!(ext(stored).as_str(), "mp4" | "mov" | "m4v" | "mkv" | "webm" | "avi") || node.attribute("fillVideo").is_some() { FootageKind::Video } else { FootageKind::Still };
                footage.width = width;
                footage.height = height;
                footage.frame_rate = rate;
                footage.duration = Tick::from_seconds_f64(end - start);
                footage.has_video = true;
                footage.missing = found.is_none();
                if found.is_none() { missing.push(format!("{layer_name}: {stored}")); }
                let item = project.add_item(&layer_name, Label::None, Some(folder), ItemKind::Footage(footage));
                items.push(item.0);
                let layer = attach_layer(project, cid, &comp_copy, &layer_name, LayerSource::Footage { item }, (width, height),
                    start, 0.0, end - start, 1.0, transform)?;
                push_layer(project, cid, layer)?;
            } else if kind.eq_ignore_ascii_case("shape") || kind.eq_ignore_ascii_case("color") {
                let fill = xml_child(*node, "fillColor").map(|v| xml_value(v, "value", "#FFFFFFFF"))
                    .or_else(|| node.attribute("fillColor").map(str::to_string))
                    .unwrap_or_else(|| "#FFFFFFFF".to_string());
                let rgba = parse_xml_color(&fill);
                let mut shape_size = [width as f64 * 0.5, height as f64 * 0.5];
                if let Some(size_prop) = node.children().find(|n| n.is_element() && n.tag_name().name() == "property" && n.attribute("name") == Some("size")) {
                    shape_size = split_pair(&xml_value(size_prop, "value", ""), shape_size);
                }
                if kind.eq_ignore_ascii_case("color") { shape_size = [width as f64, height as f64]; }
                let mut layer = attach_layer(project, cid, &comp_copy, &layer_name, LayerSource::Shape, (width, height),
                    start, 0.0, end - start, 1.0, transform)?;
                let mut ids = Ids(&mut project.next_id);
                let shape_name = node.attribute("s").unwrap_or("");
                let shape = if shape_name.contains("circle") || shape_name.contains("ellipse") {
                    build::shape_ellipse(&mut ids, shape_size, [0.0, 0.0])
                } else {
                    if !shape_name.is_empty() && !shape_name.contains("rect") {
                        warnings.push(format!("{layer_name}: Alight Motion vector shape {shape_name} was simplified to a rectangle"));
                    }
                    build::shape_rect(&mut ids, shape_size, [0.0, 0.0], 0.0)
                };
                let fill = build::shape_fill(&mut ids, rgba);
                let group = build::shape_group(&mut ids, &layer_name, vec![shape, fill]);
                drop(ids);
                if let Some(contents) = layer.props.sub_mut("contents") { contents.children.push(group.into()); }
                push_layer(project, cid, layer)?;
            } else if kind.eq_ignore_ascii_case("group") {
                warnings.push(format!("{layer_name}: group container flattened; group-specific effects may be lost"));
            } else {
                warnings.push(format!("{layer_name}: unsupported Alight Motion layer type {kind} was skipped"));
            }
        }
        if !missing.is_empty() { warnings.push(format!("{} media file(s) were not found; placeholders were created", missing.len())); }
        state.project_selection = vec![folder];
        Ok((folder, cid, items, missing, warnings))
    })?;
    s.open_comp(cid);
    s.toast(format!("Imported Alight Motion project {name} ({} import notes)", warnings.len()));
    Ok(json!({"folder": folder.0, "comp": cid.0, "items": items, "missingMedia": missing, "warnings": warnings}))
}

fn capcut_material<'a>(draft: &'a J, category: &str, id: &str) -> Option<&'a J> {
    draft.get("materials")?.get(category)?.as_array()?.iter()
        .find(|m| m.get("id").and_then(J::as_str) == Some(id))
}
fn capcut_secs(v: Option<&J>, fallback: f64) -> f64 {
    v.and_then(J::as_f64).filter(|n| n.is_finite()).map(|n| n / 1_000_000.0).unwrap_or(fallback)
}
fn capcut_media_path(base: &str, stored: &str) -> Option<String> {
    if let Some(path) = media_file(base, stored) { return Some(path); }
    let name = Path::new(stored.replace('\\', "/").as_str()).file_name()?.to_string_lossy().to_ascii_lowercase();
    if name.is_empty() { return None; }
    let mut pending = vec![PathBuf::from(base)];
    let mut checked = 0usize;
    while let Some(dir) = pending.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else { continue };
        for entry in entries.flatten() {
            checked += 1;
            if checked > 20_000 { return None; }
            let path = entry.path();
            if path.is_dir() { pending.push(path); }
            else if path.file_name().is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case(&name)) {
                return Some(path.to_string_lossy().to_string());
            }
        }
    }
    None
}
fn import_capcut(s: &mut Session, path: &str, base: &str, bytes: &[u8]) -> Result<J> {
    if bytes.len() > MAX_PROJECT_BYTES { return Err(err("CapCut draft_content.json exceeds the 128 MB JSON safety limit")); }
    let draft: J = serde_json::from_slice(bytes).map_err(|e| err(format!("Invalid CapCut draft_content.json: {e}")))?;
    let tracks = draft.get("tracks").and_then(J::as_array)
        .ok_or_else(|| err("This JSON is not a CapCut project: tracks[] was not found"))?;
    if draft.get("materials").and_then(J::as_object).is_none() {
        return Err(err("This JSON is not a CapCut project: materials{} was not found"));
    }
    let width = draft.get("canvas_config").and_then(|v| v.get("width")).and_then(J::as_u64).unwrap_or(1080).clamp(64, 8192) as u32;
    let height = draft.get("canvas_config").and_then(|v| v.get("height")).and_then(J::as_u64).unwrap_or(1920).clamp(64, 8192) as u32;
    let fps = draft.get("fps").and_then(J::as_f64).filter(|n| n.is_finite()).unwrap_or(30.0).clamp(1.0, 240.0);
    let rate = FrameRate::from_f64(fps);
    let draft_duration = capcut_secs(draft.get("duration"), 10.0).clamp(0.1, 86_400.0);
    let name = draft.get("name").and_then(J::as_str).filter(|n| !n.trim().is_empty()).map(str::to_string)
        .or_else(|| Path::new(base).file_name().map(|n| n.to_string_lossy().to_string()))
        .or_else(|| Path::new(path).parent().and_then(|p| p.file_name()).map(|n| n.to_string_lossy().to_string()))
        .unwrap_or_else(|| "CapCut Project".into());
    let mut initial_warnings = Vec::new();
    let unsupported = tracks.iter().filter(|t| !matches!(t.get("type").and_then(J::as_str).unwrap_or(""), "video" | "audio" | "text")).count();
    if unsupported > 0 { initial_warnings.push(format!("{unsupported} sticker/effect/filter/adjustment track(s) were skipped")); }
    let result = s.edit("Import CapCut Project", None, |project, state| {
        let folder = project.add_item(&name, Label::Yellow, None, ItemKind::Folder);
        let comp = Comp::new(width, height, rate, Tick::from_seconds_f64(draft_duration));
        let cid = project.add_item(&name, Label::Sandstone, Some(folder), ItemKind::Comp(comp.into()));
        let comp_copy = comp_id(project, cid)?;
        let mut items = Vec::new();
        let mut missing = Vec::new();
        let mut warnings = initial_warnings;
        let mut max_end = draft_duration;
        // CapCut track 0 is the base lane; EffectCraft stores the first layer at the top.
        for track in tracks.iter().rev() {
            let kind = track.get("type").and_then(J::as_str).unwrap_or("");
            let category = match kind { "video" => "videos", "audio" => "audios", "text" => "texts", _ => continue };
            let Some(segments) = track.get("segments").and_then(J::as_array) else { continue };
            for segment in segments {
                let id = segment.get("material_id").and_then(J::as_str).unwrap_or("");
                let Some(material) = capcut_material(&draft, category, id) else {
                    warnings.push(format!("CapCut segment {id}: referenced material was not found"));
                    continue;
                };
                let display_name = material.get("material_name").or_else(|| material.get("name")).and_then(J::as_str)
                    .filter(|v| !v.trim().is_empty())
                    .map(str::to_owned)
                    .or_else(|| material.get("path").and_then(J::as_str).and_then(|p| {
                        let normalized = p.replace('\\', "/");
                        Path::new(&normalized).file_name().map(|n| n.to_string_lossy().to_string())
                    }))
                    .unwrap_or_else(|| if kind == "text" { "CapCut Text" } else { "CapCut Clip" }.to_string());
                let target = segment.get("target_timerange");
                let timeline_start = capcut_secs(target.and_then(|v| v.get("start")), 0.0).max(0.0);
                let target_duration = capcut_secs(target.and_then(|v| v.get("duration")), 1.0 / fps).clamp(1.0 / fps, 86_400.0);
                max_end = max_end.max(timeline_start + target_duration);
                let source = segment.get("source_timerange");
                let source_start = capcut_secs(source.and_then(|v| v.get("start")), 0.0).max(0.0);
                let source_duration = capcut_secs(source.and_then(|v| v.get("duration")), target_duration).max(1.0 / fps);
                let stretch = (target_duration / source_duration).clamp(0.001, 1000.0);
                let layer_start = timeline_start - source_start * stretch;
                let clip = segment.get("clip");
                let clip_pos = clip.and_then(|v| v.get("transform"));
                let transform = Xform {
                    pos: [
                        (clip_pos.and_then(|v| v.get("x")).and_then(J::as_f64).unwrap_or(0.0) + 1.0) * 0.5,
                        (1.0 - clip_pos.and_then(|v| v.get("y")).and_then(J::as_f64).unwrap_or(0.0)) * 0.5,
                    ],
                    scale: [
                        clip.and_then(|v| v.get("scale")).and_then(|v| v.get("x")).and_then(J::as_f64).unwrap_or(1.0).clamp(0.001, 100.0),
                        clip.and_then(|v| v.get("scale")).and_then(|v| v.get("y")).and_then(J::as_f64).unwrap_or(1.0).clamp(0.001, 100.0),
                    ],
                    rotation: clip.and_then(|v| v.get("rotation")).and_then(J::as_f64).unwrap_or(0.0),
                    opacity: clip.and_then(|v| v.get("alpha")).and_then(J::as_f64).unwrap_or(1.0).clamp(0.0, 1.0),
                };
                if kind == "text" {
                    let rich = material.get("content").and_then(J::as_str).and_then(|v| serde_json::from_str::<J>(v).ok());
                    let text = rich.as_ref().and_then(|v| v.get("text")).and_then(J::as_str)
                        .or_else(|| material.get("text").and_then(J::as_str)).unwrap_or("").to_string();
                    if text.is_empty() { warnings.push(format!("{display_name}: empty text layer skipped")); continue; }
                    let mut layer = attach_layer(project, cid, &comp_copy, &display_name, LayerSource::Text,
                        (width, height), layer_start, timeline_start, timeline_start + target_duration, stretch, transform)?;
                    let mut doc = TextDoc::default();
                    doc.text = text;
                    doc.size = material.get("font_size").and_then(J::as_f64).unwrap_or(48.0).clamp(1.0, 512.0);
                    doc.font = material.get("font_path").and_then(J::as_str).and_then(|p| {
                        let normalized = p.replace('\\', "/");
                        Path::new(&normalized).file_name().map(|n| n.to_string_lossy().to_string())
                    }).unwrap_or_else(|| "Inter".into());
                    let color = parse_xml_color(material.get("text_color").and_then(J::as_str).unwrap_or("#FFFFFFFF"));
                    doc.fill = [color[0] as f32, color[1] as f32, color[2] as f32, color[3] as f32];
                    if let Some(group) = layer.props.sub_mut("text") {
                        if let Some(prop) = group.get_mut("sourceText") { prop.value = Value::Text(Box::new(doc)); }
                    }
                    push_layer(project, cid, layer)?;
                    warnings.push(format!("{display_name}: text imported; advanced styling/templates may be simplified"));
                } else {
                    let stored = material.get("path").or_else(|| material.get("file_path")).and_then(J::as_str).unwrap_or("");
                    let found = capcut_media_path(base, stored);
                    let mut footage = Footage::default();
                    footage.path = found.clone().unwrap_or_else(|| stored.to_string());
                    footage.kind = if kind == "audio" { FootageKind::Audio }
                        else if material.get("type").and_then(J::as_str) == Some("photo") { FootageKind::Still } else { FootageKind::Video };
                    footage.width = material.get("width").and_then(J::as_u64).unwrap_or(width as u64).clamp(1, 8192) as u32;
                    footage.height = material.get("height").and_then(J::as_u64).unwrap_or(height as u64).clamp(1, 8192) as u32;
                    footage.frame_rate = rate;
                    footage.duration = Tick::from_seconds_f64(capcut_secs(material.get("duration"), source_duration).clamp(1.0 / fps, 86_400.0));
                    footage.has_video = kind == "video";
                    footage.has_audio = kind == "audio" || material.get("has_audio").and_then(J::as_bool).unwrap_or(false);
                    footage.missing = found.is_none();
                    if found.is_none() {
                        missing.push(format!("{display_name}: {}", Path::new(stored.replace('\\', "/").as_str()).file_name().unwrap_or_default().to_string_lossy()));
                    }
                    let item = project.add_item(&display_name, Label::None, Some(folder), ItemKind::Footage(footage));
                    items.push(item.0);
                    let size = (
                        material.get("width").and_then(J::as_u64).unwrap_or(width as u64).clamp(1,8192) as u32,
                        material.get("height").and_then(J::as_u64).unwrap_or(height as u64).clamp(1,8192) as u32,
                    );
                    let mut layer = attach_layer(project, cid, &comp_copy, &display_name, LayerSource::Footage { item },
                        size, layer_start, timeline_start, timeline_start + target_duration, stretch, transform)?;
                    if kind == "audio" { layer.switches.video = false; layer.switches.audio = true; }
                    push_layer(project, cid, layer)?;
                }
                if segment.get("common_keyframes").and_then(J::as_array).is_some_and(|keys| !keys.is_empty()) {
                    warnings.push(format!("{display_name}: CapCut keyframes detected; their curves/animated parameters are not fully mapped yet"));
                }
                if segment.get("extra_material_refs").and_then(J::as_array).is_some_and(|refs| !refs.is_empty()) {
                    warnings.push(format!("{display_name}: attached CapCut effects/transitions were not converted in this import pass"));
                }
            }
        }
        if let Some(comp) = project.comp_mut(cid) {
            if max_end > comp.duration.seconds() {
                comp.duration = Tick::from_seconds_f64(max_end);
                comp.work_area = (Tick::ZERO, comp.duration);
            }
        }
        if !missing.is_empty() { warnings.push(format!("{} media file(s) were not found; placeholders were created", missing.len())); }
        state.project_selection = vec![folder];
        Ok((folder, cid, items, missing, warnings))
    })?;
    let (folder, cid, items, missing, warnings) = result;
    s.open_comp(cid);
    s.toast(if warnings.is_empty() { format!("Imported CapCut project {name}") }
        else { format!("Imported CapCut project {name} ({} import notes)", warnings.len()) });
    Ok(json!({"folder": folder.0, "comp": cid.0, "items": items, "missingMedia": missing, "warnings": warnings}))
}


fn active_export_comp(s: &Session) -> Result<(ItemId, Comp)> {
    let id = s.active_comp_id().ok_or_else(|| err("请先打开一个合成工程"))?;
    let comp = s.project.comp(id).cloned().ok_or_else(|| err("当前合成不存在"))?;
    Ok((id, comp))
}

fn export_transform(layer: &effectcraft_project::Layer, comp: &Comp) -> ([f64; 2], [f64; 2], f64, f64) {
    let position = layer.props.prop("transform/position").map(|p| p.value.as_vec2())
        .unwrap_or([comp.width as f64 / 2.0, comp.height as f64 / 2.0]);
    let scale = layer.props.prop("transform/scale").map(|p| p.value.as_vec2()).unwrap_or([100.0, 100.0]);
    let rotation = layer.props.prop("transform/rotation").map(|p| p.value.as_f64()).unwrap_or(0.0);
    let opacity = layer.props.prop("transform/opacity").map(|p| p.value.as_f64()).unwrap_or(100.0);
    (position, scale, rotation, opacity)
}

fn xml_escape(value: &str) -> String {
    value.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
        .replace('"', "&quot;").replace('\'', "&apos;")
}

fn am_argb(color: [f32; 4]) -> String {
    let c = color.map(|v| (v.clamp(0.0, 1.0) * 255.0).round() as u8);
    format!("#{:02X}{:02X}{:02X}{:02X}", c[3], c[0], c[1], c[2])
}

fn export_alight_xml(s: &Session, path: &str) -> Result<J> {
    let (_, comp) = active_export_comp(s)?;
    let name = Path::new(path).file_stem().and_then(|v| v.to_str()).unwrap_or("EffectCraft Project");
    let mut xml = format!(
        "<?xml version='1.0' encoding='UTF-8' ?>\n<scene title=\"{}\" width=\"{}\" height=\"{}\" exportWidth=\"{}\" exportHeight=\"{}\" bgcolor=\"#FF000000\" totalTime=\"{}\" fps=\"{}\" amver=\"106\" ffver=\"101\" am=\"com.alightcreative.motion/5.0.0\" amplatform=\"android\">\n",
        xml_escape(name), comp.width, comp.height, comp.width, comp.height,
        (comp.duration.seconds().max(0.1) * 1000.0).round() as i64,
        comp.frame_rate.as_f64()
    );
    let mut skipped = Vec::new();
    let mut exported = 0usize;
    for (index, layer) in comp.layers.iter().enumerate().rev() {
        let (position, scale, rotation, opacity) = export_transform(layer, &comp);
        let start = (layer.start_time.seconds().max(0.0) * 1000.0).round() as i64;
        let end = (layer.start_time.seconds() + (layer.out_point - layer.in_point).seconds()).max(0.0);
        let end = (end * 1000.0).round() as i64;
        let (tag, attrs, body) = match &layer.source {
            LayerSource::Footage { item } => {
                let Some(item) = s.project.item(*item) else { skipped.push(layer.name.clone()); continue };
                let ItemKind::Footage(footage) = &item.kind else { skipped.push(layer.name.clone()); continue };
                if footage.kind == FootageKind::Audio {
                    skipped.push(format!("{}（纯音频轨）", layer.name));
                    continue;
                }
                let uri = xml_escape(&footage.path);
                let filename = xml_escape(Path::new(&footage.path).file_name().and_then(|v| v.to_str()).unwrap_or(&footage.path));
                ("shape", format!("fillType=\"media\" s=\"30\""), format!("<media filename=\"{filename}\" uri=\"{uri}\" />"))
            }
            LayerSource::Text => {
                let doc = layer.props.prop("text/sourceText").and_then(|p| match &p.value {
                    Value::Text(doc) => Some(doc.as_ref()),
                    _ => None,
                });
                let Some(doc) = doc else { skipped.push(format!("{}（文字文档未识别）", layer.name)); continue };
                let font = xml_escape(&format!("googlefonts?name={}&weight=400", doc.font));
                let body = format!(
                    "<transform><location value=\"{:.3},{:.3}\"/><scale value=\"{:.6},{:.6}\"/><rotation value=\"{:.6}\"/><opacity value=\"{:.6}\"/></transform><fillColor value=\"{}\"/><content>{}</content>",
                    position[0], position[1], scale[0] / 100.0, scale[1] / 100.0, rotation, (opacity / 100.0).clamp(0.0,1.0),
                    am_argb(doc.fill), xml_escape(&doc.text)
                );
                ("text", format!("fillType=\"color\" size=\"{:.3}\" font=\"{font}\" wrapWidth=\"{}\" align=\"left\"", doc.size, comp.width), body)
            }
            LayerSource::Shape | LayerSource::Solid { .. } => {
                ("shape", "fillType=\"color\" s=\".rect\"".to_string(),
                 "<fillColor value=\"#FFFFFFFF\"/>".to_string())
            }
            _ => {
                skipped.push(layer.name.clone());
                continue;
            }
        };
        let body = if matches!(&layer.source, LayerSource::Text) {
            body
        } else {
            format!(
                "<transform><location value=\"{:.3},{:.3}\"/><scale value=\"{:.6},{:.6}\"/><rotation value=\"{:.6}\"/><opacity value=\"{:.6}\"/></transform>{body}",
                position[0], position[1], scale[0] / 100.0, scale[1] / 100.0,
                rotation, (opacity / 100.0).clamp(0.0,1.0)
            )
        };
        xml.push_str(&format!(
            "<{tag} id=\"{}\" label=\"{}\" startTime=\"{start}\" endTime=\"{end}\" {attrs}>{body}</{tag}>\n",
            index + 1, xml_escape(&layer.name)
        ));
        exported += 1;
    }
    xml.push_str("</scene>\n");
    s.write_output(path, xml.as_bytes())?;
    let warning = if skipped.is_empty() {
        "已导出可映射的图层；原素材仍需保持可访问。".to_string()
    } else {
        format!("已导出 {exported} 个图层；{} 个图层/音频/复杂对象未映射：{}。", skipped.len(), skipped.join("、"))
    };
    Ok(json!({"path":path,"format":"alight-motion-xml","exportedLayers":exported,"warnings":warning}))
}

fn zip_single_file(name: &str, bytes: &[u8]) -> Result<Vec<u8>> {
    let cursor = Cursor::new(Vec::new());
    let mut archive = zip::ZipWriter::new(cursor);
    archive.start_file(name, zip::write::SimpleFileOptions::default())
        .map_err(|e| err(format!("创建工程压缩包失败：{e}")))?;
    archive.write_all(bytes).map_err(|e| err(format!("写入工程压缩包失败：{e}")))?;
    archive.finish().map(|c| c.into_inner()).map_err(|e| err(format!("完成工程压缩包失败：{e}")))
}

fn nv_value(value: f64) -> J { json!({"Value": value}) }
fn nv_vector2(value: [f64; 2]) -> J { json!({"Params":[nv_value(value[0]),nv_value(value[1])]}) }

fn export_nodevideo(s: &Session, path: &str) -> Result<J> {
    let (comp_id, comp) = active_export_comp(s)?;
    let mut children = Vec::new();
    let mut skipped = Vec::new();
    for layer in comp.layers.iter().rev() {
        let (position, scale, rotation, opacity) = export_transform(layer, &comp);
        let duration = (layer.out_point - layer.in_point).seconds().max(0.0);
        let timeline = json!({
            "Pos":layer.start_time.seconds().max(0.0),"Start":layer.in_point.seconds().max(0.0),
            "End":layer.out_point.seconds().max(0.0),"Duration":duration,"Stretch":(layer.stretch/100.0).max(0.0001)
        });
        let transform = json!({
            "$id":format!("ec-transform-{}",layer.id.0),
            "$type":"NodeVideo.Data.DataTransform, Assembly-CSharp",
            "Params":{
                "_position":nv_vector2([position[0]/comp.width as f64,position[1]/comp.height as f64]),
                "_scale":nv_vector2([scale[0]/100.0,scale[1]/100.0]),
                "_rotation":nv_value(rotation),"_opacity":nv_value((opacity/100.0).clamp(0.0,1.0))
            }
        });
        let mut node = match &layer.source {
            LayerSource::Footage { item } => {
                let Some(item) = s.project.item(*item) else { skipped.push(layer.name.clone()); continue };
                let ItemKind::Footage(footage) = &item.kind else { skipped.push(layer.name.clone()); continue };
                if footage.kind == FootageKind::Audio {
                    skipped.push(format!("{}（纯音频轨）",layer.name)); continue;
                }
                let image = footage.kind == FootageKind::Still;
                json!({
                    "$type":if image {"NodeVideo.Node.NodeMediaImage, Assembly-CSharp"} else {"NodeVideo.Node.NodeMediaVideo, Assembly-CSharp"},
                    "$id":format!("ec-node-{}",layer.id.0),"Name":layer.name,"TimeLine":timeline,
                    "Props":[transform],
                    "AssetImage":if image {json!({"AbsolutePath":footage.path,"Width":footage.width,"Height":footage.height})} else {J::Null},
                    "AssetVideo":if image {J::Null} else {json!({"AbsolutePath":footage.path,"Width":footage.width,"Height":footage.height,"Duration":footage.duration.seconds()})},
                    "ChildList":[]
                })
            }
            LayerSource::Text => {
                let doc = layer.props.prop("text/sourceText").and_then(|p| match &p.value { Value::Text(doc)=>Some(doc.as_ref()), _=>None });
                let Some(doc)=doc else { skipped.push(format!("{}（文字文档未识别）",layer.name)); continue };
                let data=json!({
                    "$id":format!("ec-text-{}",layer.id.0),
                    "$type":"NodeVideo.Data.DataText3D, Assembly-CSharp",
                    "Params":{"_text":{"Text":doc.text},"_font":{"PickedFont":doc.font},"_size":nv_value(doc.size/72.0)}
                });
                json!({"$type":"NodeVideo.Node.NodeViewText, Assembly-CSharp","$id":format!("ec-node-{}",layer.id.0),
                    "Name":layer.name,"TimeLine":timeline,"Props":[transform,data],"ChildList":[]})
            }
            LayerSource::Shape | LayerSource::Solid { .. } => {
                let data=json!({
                    "$id":format!("ec-shape-{}",layer.id.0),
                    "$type":"NodeVideo.Data.DataShape, Assembly-CSharp",
                    "Params":{
                        "_shape_type":nv_value(1.0),
                        "_shape_size":nv_vector2([1.0,1.0]),
                        "_fill_color":{"Color":{"r":1.0,"g":1.0,"b":1.0,"a":1.0}}
                    }
                });
                json!({"$type":"NodeVideo.Node.NodeShape, Assembly-CSharp","$id":format!("ec-node-{}",layer.id.0),
                    "Name":layer.name,"TimeLine":timeline,"Props":[transform,data],"ChildList":[]})
            }
            _ => { skipped.push(layer.name.clone()); continue; }
        };
        if let Some(obj)=node.as_object_mut() {
            obj.insert("Enabled".into(),json!(true));
        }
        children.push(node);
    }
    let root = json!({
        "$type":"NodeVideo.Node.NodeGroup, Assembly-CSharp","$id":"ec-root","Name":"EffectCraft Project",
        "FixedDuration":comp.duration.seconds(),"TimeLine":{"Pos":0.0,"Start":0.0,"End":comp.duration.seconds()},
        "Props":[{
            "$id":"ec-project-setting","$type":"NodeVideo.Data.DataProjectSetting, Assembly-CSharp",
            "Params":{"_resolution":{"Width":comp.width,"Height":comp.height},"_fps":nv_value(comp.frame_rate.as_f64())}
        }],
        "ChildList":children
    });
    let bytes=serde_json::to_vec_pretty(&root).map_err(|e|err(format!("生成 NodeVideo 工程失败：{e}")))?;
    let archive=zip_single_file("EffectCraft.nv",&bytes)?;
    s.write_output(path,&archive)?;
    let warning=if skipped.is_empty() {"已输出当前合成的基础图层/文字/变换；素材路径仍指向原文件。".to_string()}
        else {format!("已输出当前合成；{} 个复杂图层或纯音频未映射：{}。素材路径仍指向原文件。",skipped.len(),skipped.join("、"))};
    Ok(json!({"path":path,"format":"nodevideo-project-zip","exportedLayers":children.len(),"warnings":warning,"sourceComp":comp_id.0}))
}

fn capcut_id(prefix: &str, id: u64) -> String {
    format!("{:08x}-0000-4000-8000-{:012x}", id as u32, id)
}

fn export_capcut(s: &Session, path: &str) -> Result<J> {
    let (comp_id, comp) = active_export_comp(s)?;
    let mut tracks=Vec::new();
    let mut videos=Vec::new();
    let mut audios=Vec::new();
    let mut texts=Vec::new();
    let mut skipped=Vec::new();
    let mut render_index=0usize;
    for layer in comp.layers.iter().rev() {
        let (position,scale,rotation,opacity)=export_transform(layer,&comp);
        let target_start=(layer.start_time.seconds().max(0.0)*1_000_000.0).round() as i64;
        let target_duration=((layer.out_point-layer.in_point).seconds().max(0.0)*1_000_000.0).round() as i64;
        if target_duration<=0 { skipped.push(layer.name.clone()); continue; }
        let speed=if layer.stretch.abs()>0.0001 {100.0/layer.stretch} else {1.0};
        let source_duration=(target_duration as f64*speed.abs()).round() as i64;
        let (kind,material_id,material)=match &layer.source {
            LayerSource::Footage { item }=>{
                let Some(item)=s.project.item(*item) else {skipped.push(layer.name.clone());continue};
                let ItemKind::Footage(f)=&item.kind else {skipped.push(layer.name.clone());continue};
                let mid=capcut_id("mat",layer.id.0);
                if f.kind==FootageKind::Audio {
                    ("audio",mid.clone(),json!({"id":mid,"path":f.path,"name":layer.name,"duration":(f.duration.seconds()*1_000_000.0) as i64,"type":"music"}))
                } else {
                    ("video",mid.clone(),json!({"id":mid,"path":f.path,"material_name":layer.name,"type":if f.kind==FootageKind::Still {"photo"} else {"video"},
                        "duration":(f.duration.seconds()*1_000_000.0) as i64,"width":f.width,"height":f.height,"fps":comp.frame_rate.as_f64(),"has_audio":f.has_audio}))
                }
            }
            LayerSource::Text=>{
                let doc=layer.props.prop("text/sourceText").and_then(|p|match &p.value{Value::Text(doc)=>Some(doc.as_ref()),_=>None});
                let Some(doc)=doc else {skipped.push(format!("{}（文字文档未识别）",layer.name));continue};
                let mid=capcut_id("txt",layer.id.0);
                let content=json!({"styles":[{"range":[0,doc.text.encode_utf16().count()],"size":doc.size,"bold":doc.faux_bold,"italic":doc.faux_italic,
                    "underline":false,"fill":{"alpha":doc.fill[3],"content":{"render_type":"solid","solid":{"alpha":doc.fill[3],"color":[doc.fill[0],doc.fill[1],doc.fill[2]]}}}}],"text":doc.text}).to_string();
                ("text",mid.clone(),json!({"id":mid,"type":"text","content":content,"alignment":1,"font_size":doc.size,"text_color":format!("#{:02X}{:02X}{:02X}",(doc.fill[0]*255.0) as u8,(doc.fill[1]*255.0) as u8,(doc.fill[2]*255.0) as u8)}))
            }
            LayerSource::Shape|LayerSource::Solid{..}=>{skipped.push(format!("{}（CapCut 本轮不转换原生形状/固态层）",layer.name));continue}
            _=>{skipped.push(layer.name.clone());continue}
        };
        let media_type=kind;
        match media_type { "audio"=>audios.push(material), "video"=>videos.push(material), "text"=>texts.push(material), _=>{} }
        let segment_id=capcut_id("seg",layer.id.0);
        let track_id=capcut_id("trk",layer.id.0);
        let segment=json!({
            "id":segment_id,"material_id":material_id,"raw_segment_id":track_id,
            "target_timerange":{"start":target_start,"duration":target_duration},
            "source_timerange":{"start":0,"duration":source_duration},
            "speed":speed.abs().clamp(0.01,100.0),"volume":1.0,"visible":true,"reverse":speed<0.0,
            "clip":{"alpha":(opacity/100.0).clamp(0.0,1.0),"rotation":rotation,
                "scale":{"x":(scale[0]/100.0).abs(),"y":(scale[1]/100.0).abs()},
                "transform":{"x":position[0]-comp.width as f64/2.0,"y":position[1]-comp.height as f64/2.0},
                "flip":{"horizontal":scale[0]<0.0,"vertical":scale[1]<0.0}},
            "render_index":render_index,"track_render_index":0,"track_attribute":0,
            "extra_material_refs":[],"common_keyframes":[],"keyframe_refs":[]
        });
        tracks.push(json!({"id":track_id,"type":kind,"name":layer.name,"is_default_name":false,"attribute":0,"flag":0,"segments":[segment]}));
        render_index+=1;
    }
    let w=comp.width;
    let h=comp.height;
    let fps=comp.frame_rate.as_f64();
    let duration=(comp.duration.seconds().max(0.1)*1_000_000.0).round() as i64;
    let ratio=format!("{w}:{h}");
    let project_id=capcut_id("project",comp_id.0);
    let draft=json!({
        "id":project_id,"name":"EffectCraft Project","duration":duration,"fps":fps,
        "canvas_config":{"width":w,"height":h,"ratio":ratio},
        "platform":{"app_source":"cc","app_version":"6.2.8","os":"windows"},
        "tracks":tracks,
        "materials":{"videos":videos,"audios":audios,"texts":texts,"speeds":[],"material_animations":[],"audio_fades":[],"transitions":[],"masks":[],"canvases":[]},
        "extra_info":{},"free_render_index_mode_on":false
    });
    let bytes=serde_json::to_vec_pretty(&draft).map_err(|e|err(format!("生成 CapCut 工程失败：{e}")))?;
    let archive=zip::ZipWriter::new(Cursor::new(Vec::new()));
    let mut archive=archive;
    archive.start_file("draft_content.json",zip::write::SimpleFileOptions::default()).map_err(|e|err(format!("创建 CapCut 工程包失败：{e}")))?;
    archive.write_all(&bytes).map_err(|e|err(format!("写入 CapCut 工程包失败：{e}")))?;
    let meta=json!({"draft_id":project_id,"draft_name":"EffectCraft Project","fps":fps,"width":w,"height":h,"duration":duration});
    archive.start_file("draft_meta_info.json",zip::write::SimpleFileOptions::default()).map_err(|e|err(format!("写入 CapCut 元数据失败：{e}")))?;
    archive.write_all(serde_json::to_string_pretty(&meta).map_err(|e|err(e.to_string()))?.as_bytes()).map_err(|e|err(format!("写入 CapCut 元数据失败：{e}")))?;
    let bytes=archive.finish().map_err(|e|err(format!("完成 CapCut 工程包失败：{e}")))?.into_inner();
    s.write_output(path,&bytes)?;
    let warning=if skipped.is_empty() {"基础视频、音频、文字片段已写入 CapCut 草稿包；素材仍引用原文件路径。".to_string()}
        else {format!("基础视频/音频/文字已输出；{} 个复杂图层未映射：{}。素材仍引用原文件路径。",skipped.len(),skipped.join("、"))};
    Ok(json!({"path":path,"format":"capcut-draft-zip","exportedTracks":render_index,"warnings":warning,"sourceComp":comp_id.0}))
}

fn notify_exported_project(s: &mut Session, path: &str, format: &str) {
    s.events.push(crate::Event::Frontend {
        command: "effectcraft.projectExported".into(),
        params: json!({"path": path, "format": format}),
    });
}

fn export_alight_command(s: &mut Session, p: &J) -> Result<J> {
    let path=p.get("path").and_then(J::as_str).ok_or_else(||err("缺少导出路径"))?;
    let result = export_alight_xml(s,path)?;
    notify_exported_project(s, path, "AM");
    Ok(result)
}
fn export_nodevideo_command(s: &mut Session, p: &J) -> Result<J> {
    let path=p.get("path").and_then(J::as_str).ok_or_else(||err("缺少导出路径"))?;
    let result = export_nodevideo(s,path)?;
    notify_exported_project(s, path, "NV");
    Ok(result)
}
fn export_capcut_command(s: &mut Session, p: &J) -> Result<J> {
    let path=p.get("path").and_then(J::as_str).ok_or_else(||err("缺少导出路径"))?;
    let result = export_capcut(s,path)?;
    notify_exported_project(s, path, "CapCut");
    Ok(result)
}

pub fn specs() -> Vec<CommandSpec> {
    vec![
        cmd!("file.exportAlightMotion", "Export Alight Motion Project", ["File", "Export"], None, "{path (.xml)} — exports the active composition as Alight Motion scene XML", always, export_alight_command),
        cmd!("file.exportNodeVideo", "Export NodeVideo Project", ["File", "Export"], None, "{path (.zip)} — exports the active composition in a NodeVideo ZIP project package", always, export_nodevideo_command),
        cmd!("file.exportCapCut", "Export CapCut Project", ["File", "Export"], None, "{path (.zip)} — exports the active composition as a CapCut desktop draft package", always, export_capcut_command),
    ]
}

fn parse_xml_color(value: &str) -> [f64; 4] {
    let v = value.trim().trim_start_matches('#');
    let parsed = u32::from_str_radix(v, 16).ok();
    match (v.len(), parsed) {
        (8, Some(n)) => [((n >> 16) & 255) as f64 / 255.0, ((n >> 8) & 255) as f64 / 255.0, (n & 255) as f64 / 255.0, ((n >> 24) & 255) as f64 / 255.0],
        (6, Some(n)) => [((n >> 16) & 255) as f64 / 255.0, ((n >> 8) & 255) as f64 / 255.0, (n & 255) as f64 / 255.0, 1.0],
        _ => [1.0, 1.0, 1.0, 1.0],
    }
}

pub fn import_path(s: &mut Session, path: &str) -> Result<J> {
    let (actual, package_root) = if ext(path) == "zip" || ext(path) == "alight" && std::fs::read(path).ok().is_some_and(|b| b.starts_with(b"PK")) {
        let (file, root) = extract_project_zip(s, path)?;
        (file, Some(root))
    } else { (path.to_string(), None) };
    if matches!(ext(&actual).as_str(), "ecproj" | "ecprojx") {
        return super::import_project::import_project(s, &json!({"path": actual}));
    }
    let bytes = match std::fs::read(&actual) {
        Ok(bytes) => bytes,
        Err(_) => s.services.read_file(&actual).map_err(|e| err(format!("Cannot read selected project file: {e}")))?,
    };
    let base = package_root.unwrap_or_else(|| Path::new(&actual).parent().unwrap_or(Path::new("")).to_string_lossy().to_string());
    if ext(&actual) == "json" && bytes.first().is_some_and(|b| *b == b'{') {
        let probe: J = serde_json::from_slice(&bytes).map_err(|e| err(format!("Invalid project JSON: {e}")))?;
        if probe.get("tracks").and_then(J::as_array).is_some() && probe.get("materials").and_then(J::as_object).is_some() {
            return import_capcut(s, &actual, &base, &bytes);
        }
        let font_map = register_imported_fonts(&base);
        return import_nodevideo(s, &actual, &base, &bytes, &font_map);
    }
    if ext(&actual) == "nv" || bytes.first().is_some_and(|b| *b == b'{') {
        let font_map = register_imported_fonts(&base);
        import_nodevideo(s, &actual, &base, &bytes, &font_map)
    } else if ext(&actual) == "xml" || ext(&actual) == "alight" || bytes.starts_with(b"<?xml") || bytes.starts_with(b"<scene") {
        let font_map = register_imported_fonts(&base);
        import_alight_xml(s, &actual, &base, &bytes, &font_map)
    } else {
        Err(err("This package is not a supported NodeVideo or Alight Motion project"))
    }
}


#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn nodevideo_project_settings_are_read_from_the_root_properties() {
        let root = json!({
            "Name": "Root",
            "FixedDuration": 5.0,
            "TimeLine": {"End": 10.0},
            "Props": [{
                "$id": "settings",
                "$type": "NodeVideo.Data.DataProjectSetting, Assembly-CSharp",
                "Params": {
                    "_resolution": {"Width": 1280.0, "Height": 720.0},
                    "_fps": {"Value": 60.0}
                }
            }],
            "ChildList": []
        });
        let refs = collect_refs(&root);
        let (width, height, fps, duration) = read_nv_project_settings(&root, &refs);
        assert_eq!((width, height), (1280, 720));
        assert!((fps.as_f64() - 60.0).abs() < 0.001);
        assert!((duration - 10.0).abs() < 0.001);
    }

    #[test]
    fn nodevideo_group_transform_composes_scale_and_position() {
        let root = Xform { pos: [0.6, 0.4], scale: [2.0, 0.5], rotation: 15.0, opacity: 0.8 };
        let child = Xform { pos: [0.75, 0.5], scale: [0.5, 2.0], rotation: 5.0, opacity: 0.5 };
        let result = root.compose(child);
        assert!((result.pos[0] - 1.1).abs() < 0.0001);
        assert!((result.pos[1] - 0.4).abs() < 0.0001);
        assert!((result.scale[0] - 1.0).abs() < 0.0001);
        assert!((result.scale[1] - 1.0).abs() < 0.0001);
        assert!((result.rotation - 20.0).abs() < 0.0001);
        assert!((result.opacity - 0.4).abs() < 0.0001);
    }

    #[test]
    fn alight_motion_argb_and_rgb_colors_are_supported() {
        assert_eq!(parse_xml_color("#FFFF0000"), [1.0, 0.0, 0.0, 1.0]);
        assert_eq!(parse_xml_color("#00FF00"), [0.0, 1.0, 0.0, 1.0]);
    }

    #[test]
    fn alight_motion_xml_scene_is_parsed() {
        let xml = r##"<scene width="1080" height="1920" fps="30"><shape s=".rect" startTime="0" endTime="1000"><fillColor value="#FFFF8800"/></shape></scene>"##;
        let parsed = roxmltree::Document::parse(xml).expect("basic scene XML");
        assert_eq!(parsed.root_element().tag_name().name(), "scene");
        assert!(parsed.root_element().descendants().any(|n| n.is_element() && matches!(n.tag_name().name(), "shape" | "text" | "group")));
    }
}
