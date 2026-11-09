//! Import a useful, explicitly reported subset of Alight Motion XML and NodeVideo projects.
//! The importer lives behind the existing File > Import > EffectCraft Project command.

use std::collections::HashMap;
use std::io::Read;
use std::path::{Component, Path, PathBuf};

use effectcraft_color::Label;
use effectcraft_keyframe::TextDoc;
use effectcraft_project::build::{self, Ids};
use effectcraft_project::{
    Comp, Footage, FootageKind, ItemId, ItemKind, LayerSource, Project, Value,
};
use effectcraft_time::{FrameRate, Tick};
use serde_json::{Value as J, json};

use crate::{EngineError, Result, Session};

const MAX_PROJECT_BYTES: usize = 128 * 1024 * 1024;
const MAX_ZIP_ENTRIES: usize = 512;
const MAX_ZIP_TOTAL: u64 = 256 * 1024 * 1024;
const MAX_ZIP_ENTRY: u64 = 64 * 1024 * 1024;

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
    let root = config.join("Imported-Projects").join(safe_name(&stem));
    std::fs::create_dir_all(&root).map_err(|e| err(format!("Cannot create import directory: {e}")))?;
    let file = std::fs::File::open(path).map_err(|e| err(format!("Cannot read ZIP package: {e}")))?;
    let mut archive = zip::ZipArchive::new(file).map_err(|e| err(format!("Invalid project ZIP: {e}")))?;
    if archive.len() > MAX_ZIP_ENTRIES {
        return Err(err("Project ZIP contains more than 512 entries"));
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
            return Err(err(format!("ZIP entry {name} exceeds the 64 MB safety limit")));
        }
        total = total.saturating_add(size);
        if total > MAX_ZIP_TOTAL {
            return Err(err("Project ZIP expands beyond the 256 MB safety limit"));
        }

        let destination = root.join(relative);
        if let Some(parent) = destination.parent() {
            std::fs::create_dir_all(parent).map_err(|e| err(format!("Cannot create package folder: {e}")))?;
        }
        let mut bytes = Vec::new();
        (&mut entry).take(MAX_ZIP_ENTRY + 1).read_to_end(&mut bytes)
            .map_err(|e| err(format!("Cannot extract {name}: {e}")))?;
        if bytes.len() as u64 > MAX_ZIP_ENTRY {
            return Err(err(format!("ZIP entry {name} exceeds the 64 MB safety limit")));
        }
        std::fs::write(&destination, &bytes).map_err(|e| err(format!("Cannot save {name}: {e}")))?;
        let lower = name.to_ascii_lowercase();
        if lower.ends_with(".nv") {
            project_file = Some(destination);
        } else if project_file.is_none() && (lower.ends_with(".xml") || lower.ends_with(".alight")) {
            project_file = Some(destination);
        }
    }
    let file = project_file.ok_or_else(|| err("This ZIP does not contain a NodeVideo .nv project or an Alight Motion XML project"))?;
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
        let layer = attach_layer(project, comp_id, comp, &name, LayerSource::Shape, (size.0 as u32, size.1 as u32),
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
        let font = params.and_then(|p| p.get("_font")).map(|v| deref(v, refs)).and_then(|v| v.get("PickedFont")).and_then(J::as_str).unwrap_or("Inter").to_string();
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
            import_nv_node(project, folder, comp_id, comp, child, refs, base, local, depth + 1, missing, warnings, created_items)?;
        }
    }
    Ok(())
}

fn import_nodevideo(s: &mut Session, path: &str, base: &str, bytes: &[u8]) -> Result<J> {
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
            import_nv_node(project, folder, cid, &comp_copy, node, &refs, base, Xform::default(), 0,
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
fn import_alight_xml(s: &mut Session, path: &str, base: &str, bytes: &[u8]) -> Result<J> {
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

    let mut layer_nodes = Vec::new();
    for node in scene.descendants().filter(|n| n.is_element() && n.tag_name().name() == "layer") {
        layer_nodes.push(node);
    }
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
                doc.font = node.attribute("font").unwrap_or("Inter").to_string();
                doc.size = attr_f(*node, "size", 72.0).clamp(1.0, 512.0);
                if let Some(color) = node.attribute("fillColor") {
                    let rgba = parse_xml_color(color);
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
            } else if kind.eq_ignore_ascii_case("media") || kind.eq_ignore_ascii_case("image") {
                let media = node.descendants().find(|n| n.is_element() && n.tag_name().name() == "media");
                let stored = media.and_then(|m| m.attribute("filename").or_else(|| m.attribute("uri"))).unwrap_or("");
                let found = media_file(base, stored);
                let media_path = found.clone().unwrap_or_else(|| stored.to_string());
                let mut footage = Footage::default();
                footage.path = media_path.clone();
                footage.kind = if matches!(ext(stored).as_str(), "mp4" | "mov" | "m4v" | "mkv" | "webm" | "avi") { FootageKind::Video } else { FootageKind::Still };
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
                let fill = node.attribute("fillColor").unwrap_or("#FFFFFFFF");
                let rgba = parse_xml_color(fill);
                let layer = attach_layer(project, cid, &comp_copy, &layer_name, LayerSource::Shape, (width, height),
                    start, 0.0, end - start, 1.0, transform)?;
                let mut ids = Ids(&mut project.next_id);
                let shape = build::shape_rect(&mut ids, [width as f64 * 0.5, height as f64 * 0.5], [0.0, 0.0], 0.0);
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
    let actual = if ext(path) == "zip" || ext(path) == "alight" && std::fs::read(path).ok().is_some_and(|b| b.starts_with(b"PK")) {
        extract_project_zip(s, path)?.0
    } else {
        path.to_string()
    };
    let bytes = match std::fs::read(&actual) {
        Ok(bytes) => bytes,
        Err(_) => s.services.read_file(&actual).map_err(|e| err(format!("Cannot read selected project file: {e}")))?,
    };
    if ext(&actual) == "nv" || bytes.first().is_some_and(|b| *b == b'{') {
        let base = Path::new(&actual).parent().unwrap_or(Path::new("")).to_string_lossy().to_string();
        import_nodevideo(s, &actual, &base, &bytes)
    } else if ext(&actual) == "xml" || ext(&actual) == "alight" || bytes.starts_with(b"<?xml") || bytes.starts_with(b"<scene") {
        let base = Path::new(&actual).parent().unwrap_or(Path::new("")).to_string_lossy().to_string();
        import_alight_xml(s, &actual, &base, &bytes)
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
        let xml = r#"<scene width="1080" height="1920" fps="30"><layer type="shape" startTime="0" endTime="1000"/></scene>"#;
        let parsed = roxmltree::Document::parse(xml).expect("basic scene XML");
        assert_eq!(parsed.root_element().tag_name().name(), "scene");
    }
}
