#!/usr/bin/env python3
"""Install one AM Move & Transform workspace with side keyframe controls and Effects action."""
from __future__ import annotations
import os
from pathlib import Path

MARKER = "EFFECTCRAFT_AM_SINGLE_MOTION_WORKSPACE_V1"

WORKSPACE = r'''
// EFFECTCRAFT_AM_SINGLE_MOTION_WORKSPACE_V1
fn am_motion_editor(app: &mut EffectcraftApp, ui: &mut egui::Ui, rect: Rect) {
    let ctx = ui.ctx().clone();
    let Some(layer_id) = ctx.data(|d| d.get_temp::<u64>(Id::new(AM_ACTIVE_LAYER_ID))) else {
        ui.painter().text(rect.center(), Align2::CENTER_CENTER, "请先选择图层素材。", Tokens::ui(12.0), app.tokens.text_dim);
        return;
    };
    let mut section = ctx.data(|d| d.get_temp::<String>(Id::new(AM_MOTION_TAB_ID))).unwrap_or_else(|| "transform".into());
    let mut mode = ctx.data(|d| d.get_temp::<String>(Id::new("am-motion-transform-control"))).unwrap_or_else(|| "move".into());
    let mut curve_target = ctx.data(|d| d.get_temp::<String>(Id::new("am-motion-curve-target"))).unwrap_or_else(|| "move".into());
    let property_mode = if mode == "curve" { curve_target.as_str() } else { mode.as_str() };
    let mut linked = ctx.data(|d| d.get_temp::<bool>(Id::new("am-motion-linked-scale"))).unwrap_or(true);
    let t = app.tokens;
    let left_w = 42.0;
    let right_w = 58.0;
    let footer_h = 42.0;
    let left = Rect::from_min_max(rect.min, pos2(rect.min.x + left_w, rect.max.y - footer_h));
    let right = Rect::from_min_max(pos2(rect.max.x - right_w, rect.min.y), pos2(rect.max.x, rect.max.y - footer_h));
    let center = Rect::from_min_max(pos2(left.max.x + 3.0, rect.min.y + 3.0), pos2(right.min.x - 3.0, rect.max.y - footer_h - 3.0));
    let footer = Rect::from_min_max(pos2(rect.min.x, rect.max.y - footer_h), rect.max);
    let painter = ui.painter().with_clip_rect(rect);
    painter.rect_filled(rect, 8.0, t.panel_bg);
    painter.line_segment([left.right_top(), left.right_bottom()], Stroke::new(1.0, t.separator));
    painter.line_segment([right.left_top(), right.left_bottom()], Stroke::new(1.0, t.separator));
    painter.line_segment([footer.left_top(), footer.right_top()], Stroke::new(1.0, t.separator));

    let close = ui.put(Rect::from_min_size(pos2(left.min.x + 5.0, left.min.y + 4.0), vec2(32.0, 31.0)), egui::Button::new("‹"));
    app.auto.add_response("am.motion.back", &close, "返回图层操作");
    if close.clicked() { ctx.data_mut(|d| d.remove::<String>(Id::new("am-mobile-tool-drawer"))); return; }

    if section == "effects" {
        let back = ui.put(Rect::from_min_size(pos2(center.min.x + 5.0, center.min.y + 3.0), vec2(94.0, 28.0)), egui::Button::new("‹ 返回变换"));
        app.auto.add_response("am.motion.effects.back", &back, "返回移动与变换");
        if back.clicked() { section = "transform".into(); ctx.data_mut(|d| d.insert_temp(Id::new(AM_MOTION_TAB_ID), section.clone())); }
        let body = Rect::from_min_max(pos2(center.min.x + 3.0, center.min.y + 36.0), center.max);
        ctx.data_mut(|d| d.insert_temp(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1"), true));
        let mut child = ui.new_child(egui::UiBuilder::new().max_rect(body));
        crate::panels::show(app, &mut child, PanelKind::EffectControls, body);
        ctx.data_mut(|d| d.remove::<bool>(Id::new("EFFECTCRAFT_AM_TOUCH_DRAW_CONTEXT_V1")));
        let add = ui.put(Rect::from_min_size(pos2(footer.max.x - 105.0, footer.min.y + 5.0), vec2(98.0, 32.0)), egui::Button::new("＋ 添加效果"));
        app.auto.add_response("am.motion.effects.add", &add, "打开效果浏览器");
        if add.clicked() { am_open_effect_browser(&ctx, Some(layer_id)); }
        return;
    }

    let time = app.session.time();
    let path = match property_mode {
        "rotate" => "transform/rotation", "scale" => "transform/scale",
        "tilt_x" => "transform/rotationX", "tilt_y" => "transform/rotationY",
        _ => "transform/position",
    };
    let snapshot = app.session.active_comp().and_then(|comp| {
        let layer = comp.layers.iter().find(|l| l.id.0 == layer_id)?;
        let lt = layer.layer_time(time);
        let vec = |p: &str, d: [f64; 3]| layer.props.prop(p).map(|q| q.value_at(lt).as_vec3()).unwrap_or(d);
        let scalar = |p: &str| layer.props.prop(p).map(|q| q.value_at(lt).as_f64()).unwrap_or(0.0);
        let separate = layer.props.prop("transform/position").is_none();
        let position = if separate {
            [scalar("transform/positionX"), scalar("transform/positionY"), scalar("transform/positionZ")]
        } else { vec("transform/position", [0.0; 3]) };
        let prop = layer.props.prop(path).or_else(|| if property_mode == "move" { layer.props.prop("transform/positionX") } else { None });
        let segment = prop.and_then(|q| q.keys.windows(2).enumerate().find_map(|(i, pair)| {
            let a = layer.comp_time(pair[0].time); let b = layer.comp_time(pair[1].time);
            if time > a.min(b) && time < a.max(b) { Some((q.uid, pair[0].time.seconds(), pair[1].time.seconds(), i + 1, i + 2)) } else { None }
        }));
        let has_key = if property_mode == "move" && separate {
            ["transform/positionX", "transform/positionY", "transform/positionZ"].iter().filter_map(|p| layer.props.prop(p)).any(|p| p.keys.iter().any(|k| k.time == lt))
        } else { prop.is_some_and(|p| p.keys.iter().any(|k| k.time == lt)) };
        Some((separate, position, scalar("transform/rotation"), vec("transform/scale", [100.0; 3]),
            scalar("transform/rotationX"), scalar("transform/rotationY"), layer.is_3d(), has_key, prop.map(|p| p.uid), segment))
    });
    let Some((separate, mut position, mut rotation, mut scale, mut tilt_x, mut tilt_y, is_3d, has_key, prop_uid, segment)) = snapshot else {
        ui.painter().text(center.center(), Align2::CENTER_CENTER, "无法读取当前图层的变换属性。", Tokens::ui(11.0), t.text_dim); return;
    };

    // Left toolbar: keyframe add/remove, curve access and one-frame key positioning.
    let left_items = [("◇+", "add"), ("◇−", "remove"), ("曲", "curve"), ("◀", "prev"), ("▶", "next")];
    for (i, (label, action)) in left_items.into_iter().enumerate() {
        let r = Rect::from_min_size(pos2(left.min.x + 4.0, left.min.y + 44.0 + i as f32 * 39.0), vec2(34.0, 34.0));
        let response = ui.put(r, egui::Button::new(label).min_size(r.size()));
        app.auto.add_response(&format!("am.motion.left.{action}"), &response, label);
        if response.clicked() {
            match action {
                "add" | "remove" => {
                    if action == "add" && has_key {
                        app.ui.status = "当前时间已经有这个属性的关键帧。".into();
                    } else if action == "remove" && !has_key {
                        app.ui.status = "当前时间没有此属性的关键帧。".into();
                    } else {
                        match property_mode {
                            "move" => invoke(app, &ctx, "keys.toggleTransform", json!({"layers":[layer_id], "prop":"position"})),
                            "rotate" => invoke(app, &ctx, "keys.toggleTransform", json!({"layers":[layer_id], "prop":"rotation"})),
                            "scale" => invoke(app, &ctx, "keys.toggleTransform", json!({"layers":[layer_id], "prop":"scale"})),
                            _ => invoke(app, &ctx, "prop.toggleKey", json!({"layer":layer_id, "path":path})),
                        }
                    }
                }
                "curve" => {
                    if mode != "curve" {
                        curve_target = mode.clone();
                        ctx.data_mut(|d| d.insert_temp(Id::new("am-motion-curve-target"), curve_target.clone()));
                    }
                    mode = "curve".into();
                    ctx.data_mut(|d| d.insert_temp(Id::new("am-motion-transform-control"), mode.clone()));
                }
                "prev" | "next" => {
                    if let (Some(uid), Some((_, first, second, _, _))) = (prop_uid, segment) {
                        let at = if action == "prev" { first } else { second };
                        invoke(app, &ctx, "keys.select", json!({"keys":[{"layer":layer_id,"prop":uid,"time":at}],"timeBase":"layer","selectProperties":true}));
                        invoke(app, &ctx, "keys.nudge", json!({"frames":if action == "prev" {-1} else {1}}));
                    } else { app.ui.status = "请把播放头放在两个关键帧之间。".into(); }
                }
                _ => {}
            }
        }
    }

    // Right toolbar: transform mode selector, 3D toggle and horizontal/vertical flips.
    for (i, (label, value)) in [("位置","move"),("旋转","rotate"),("缩放","scale"),("倾斜X","tilt_x"),("倾斜Y","tilt_y")].into_iter().enumerate() {
        let r = Rect::from_min_size(pos2(right.min.x + 4.0, right.min.y + 5.0 + i as f32 * 38.0), vec2(50.0, 33.0));
        let response = ui.put(r, egui::Button::new(if mode == value { format!("● {label}") } else { label.into() }).min_size(r.size()));
        app.auto.add_response(&format!("am.motion.mode.{value}"), &response, label);
        if response.clicked() { mode = value.into(); ctx.data_mut(|d| d.insert_temp(Id::new("am-motion-transform-control"), mode.clone())); }
    }
    let three = ui.put(Rect::from_min_size(pos2(right.min.x + 4.0, right.max.y - 105.0), vec2(50.0, 30.0)), egui::Button::new(if is_3d {"3D ✓"} else {"3D"}));
    if three.clicked() { invoke(app, &ctx, "layer.setSwitch", json!({"layers":[layer_id],"switch":"threeD","value":!is_3d})); }
    let flip_h = ui.put(Rect::from_min_size(pos2(right.min.x + 4.0, right.max.y - 71.0), vec2(50.0, 30.0)), egui::Button::new("翻转H"));
    if flip_h.clicked() { am_flip_scale(app, &ctx, layer_id, 0); }
    let flip_v = ui.put(Rect::from_min_size(pos2(right.min.x + 4.0, right.max.y - 37.0), vec2(50.0, 30.0)), egui::Button::new("翻转V"));
    if flip_v.clicked() { am_flip_scale(app, &ctx, layer_id, 1); }

    if mode == "curve" {
        if let Some((uid, first, second, _, _)) = segment {
            let graph = Rect::from_min_max(pos2(center.min.x + 10.0, center.min.y + 10.0), pos2(center.max.x - 10.0, center.min.y + 105.0));
            let gp = ui.painter().with_clip_rect(graph);
            gp.line_segment([graph.left_bottom(), graph.right_bottom()], Stroke::new(1.0, t.separator));
            gp.line_segment([graph.left_bottom(), graph.left_top()], Stroke::new(1.0, t.separator));
            let mut previous = graph.left_bottom();
            for n in 1..=28 { let x=n as f32/28.0; let y=x*x*(3.0-2.0*x); let next=pos2(graph.min.x+x*graph.width(),graph.max.y-y*graph.height()); gp.line_segment([previous,next],Stroke::new(2.0,t.accent)); previous=next; }
            let mut in_inf = ctx.data(|d| d.get_temp::<f32>(Id::new("am-motion-curve-influence-in"))).unwrap_or(0.33);
            let mut out_inf = ctx.data(|d| d.get_temp::<f32>(Id::new("am-motion-curve-influence-out"))).unwrap_or(0.33);
            let a = ui.put(Rect::from_min_size(pos2(center.min.x+8.0,center.min.y+110.0),vec2(center.width()-16.0,25.0)),egui::Slider::new(&mut in_inf,0.01..=1.0).text("入影响"));
            let b = ui.put(Rect::from_min_size(pos2(center.min.x+8.0,center.min.y+138.0),vec2(center.width()-16.0,25.0)),egui::Slider::new(&mut out_inf,0.01..=1.0).text("出影响"));
            if a.changed() || b.changed() {
                ctx.data_mut(|d| { d.insert_temp(Id::new("am-motion-curve-influence-in"),in_inf); d.insert_temp(Id::new("am-motion-curve-influence-out"),out_inf); });
                invoke(app,&ctx,"keys.select",json!({"keys":[{"layer":layer_id,"prop":uid,"time":first},{"layer":layer_id,"prop":uid,"time":second}],"timeBase":"layer","selectProperties":true}));
                invoke(app,&ctx,"keys.velocity",json!({"inInfluence":[in_inf as f64],"outInfluence":[out_inf as f64]}));
            }
            for (i,(label,curve)) in [("线性","linear"),("缓入","ease_in"),("缓出","ease_out"),("缓入缓出","ease"),("贝塞尔","bezier"),("连续","continuous"),("自动","auto"),("保持","hold")].into_iter().enumerate() {
                let col=i%2; let row=i/2;
                let r=Rect::from_min_size(pos2(center.min.x+8.0+col as f32*(center.width()-20.0)/2.0,center.min.y+169.0+row as f32*29.0),vec2((center.width()-25.0)/2.0,25.0));
                let response=ui.put(r,egui::Button::new(label).min_size(r.size()));
                if response.clicked() { invoke(app,&ctx,"keys.setSegmentCurve",json!({"layer":layer_id,"prop":uid,"first":first,"second":second,"curve":curve})); }
            }
        } else { ui.painter().text(center.center(),Align2::CENTER_CENTER,"请将播放头移到同一属性的两个关键帧之间。",Tokens::ui(10.5),t.text_dim); }
    } else {
        let title = match mode.as_str() {"rotate"=>"旋转角度","scale"=>"缩放比例","tilt_x"=>"X 轴倾斜","tilt_y"=>"Y 轴倾斜",_=>"位置"};
        ui.painter().text(pos2(center.center().x,center.min.y+12.0),Align2::CENTER_CENTER,title,Tokens::semibold(11.0),t.text);
        let x=center.min.x+8.0; let w=(center.width()-16.0).max(30.0); let mut y=center.min.y+27.0;
        match mode.as_str() {
            "move" => {
                let rx=ui.put(Rect::from_min_size(pos2(x,y),vec2(w,26.0)),egui::Slider::new(&mut position[0],-10000.0..=10000.0).text("X"));
                if rx.changed() { if separate {invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/positionX","value":position[0]}));} else {invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/position","value":position}));} }
                y+=29.0;
                let ry=ui.put(Rect::from_min_size(pos2(x,y),vec2(w,26.0)),egui::Slider::new(&mut position[1],-10000.0..=10000.0).text("Y"));
                if ry.changed() { if separate {invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/positionY","value":position[1]}));} else {invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/position","value":position}));} }
            }
            "rotate" => { let r=ui.put(Rect::from_min_size(pos2(x,y),vec2(w,28.0)),egui::Slider::new(&mut rotation,-360.0..=360.0).text("角度")); if r.changed(){invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/rotation","value":rotation}));} }
            "scale" => {
                let rx=ui.put(Rect::from_min_size(pos2(x,y),vec2(w,26.0)),egui::Slider::new(&mut scale[0],-1000.0..=1000.0).text("宽度"));
                if rx.changed() { if linked {scale[1]=scale[0];} invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/scale","value":scale})); }
                y+=29.0;
                let ry=ui.put(Rect::from_min_size(pos2(x,y),vec2(w,26.0)),egui::Slider::new(&mut scale[1],-1000.0..=1000.0).text("高度"));
                if ry.changed() { if linked {scale[0]=scale[1];} invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/scale","value":scale})); }
                let lock=ui.put(Rect::from_min_size(pos2(x,y+27.0),vec2(112.0,23.0)),egui::Button::new(if linked {"🔒 锁定比例"} else {"🔓 自由缩放"}));
                if lock.clicked(){linked=!linked;ctx.data_mut(|d|d.insert_temp(Id::new("am-motion-linked-scale"),linked));}
            }
            "tilt_x" => { let r=ui.put(Rect::from_min_size(pos2(x,y),vec2(w,28.0)),egui::Slider::new(&mut tilt_x,-180.0..=180.0).text("X 倾斜")); if r.changed(){invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/rotationX","value":tilt_x}));} }
            "tilt_y" => { let r=ui.put(Rect::from_min_size(pos2(x,y),vec2(w,28.0)),egui::Slider::new(&mut tilt_y,-180.0..=180.0).text("Y 倾斜")); if r.changed(){invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/rotationY","value":tilt_y}));} }
            _=>{}
        }
        let pad_y=if mode=="move"{y+31.0}else if mode=="scale"{y+55.0}else{y+36.0};
        let pad=Rect::from_min_max(pos2(center.min.x+9.0,pad_y),pos2(center.max.x-9.0,center.max.y-8.0));
        let drag=ui.interact(pad,Id::new(("am-motion-touch-pad",mode.as_str())),Sense::drag());
        ui.painter().rect_filled(pad,9.0,t.field_bg);
        ui.painter().rect_stroke(pad,9.0,Stroke::new(1.0,t.separator),StrokeKind::Inside);
        if mode == "rotate" {
            let c = pad.center();
            let radius = (pad.width().min(pad.height()) * 0.34).max(22.0);
            ui.painter().circle_filled(c, radius + 13.0, t.panel_bg);
            ui.painter().circle_stroke(c, radius, Stroke::new(2.0, t.separator));
            ui.painter().circle_stroke(c, radius * 0.68, Stroke::new(1.0, t.separator));
            let angle = rotation.to_radians();
            let handle = pos2(c.x + angle.cos() * radius, c.y + angle.sin() * radius);
            ui.painter().line_segment([c, handle], Stroke::new(2.0, t.accent));
            ui.painter().circle_filled(handle, 7.0, t.accent);
            ui.painter().text(c, Align2::CENTER_CENTER, format!("{rotation:.1}°"), Tokens::semibold(15.0), t.text);
            ui.painter().text(pos2(c.x, pad.max.y - 8.0), Align2::CENTER_BOTTOM, "拖动圆盘以旋转图层", Tokens::ui(9.5), t.text_dim);
        } else {
            ui.painter().text(pad.center(),Align2::CENTER_CENTER,match mode.as_str(){"scale"=>"拖动此处以放大或缩小","tilt_x"|"tilt_y"=>"拖动此处以调整倾斜",_=>"滑动此处以移动图层"},Tokens::ui(10.0),t.text_dim);
        }
        if drag.dragged() {
            let d=ctx.input(|i|i.pointer.delta());
            match mode.as_str() {
                "rotate"=>{
                    if let Some(pointer) = ctx.input(|i| i.pointer.interact_pos()) {
                        let c = pad.center();
                        rotation = (pointer.y - c.y).atan2(pointer.x - c.x).to_degrees() as f64;
                    } else {
                        rotation += d.x as f64 * 0.55;
                    }
                    invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/rotation","value":rotation,"merge":"am-motion-rotate"}));
                }
                "scale"=>{let k=(d.x-d.y) as f64*0.35;scale[0]+=k;if linked{scale[1]+=k;}else{scale[1]-=d.y as f64*0.35;}invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/scale","value":scale,"merge":"am-motion-scale"}));}
                "tilt_x"=>{tilt_x-=d.y as f64*0.55;invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/rotationX","value":tilt_x,"merge":"am-motion-tilt-x"}));}
                "tilt_y"=>{tilt_y+=d.x as f64*0.55;invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/rotationY","value":tilt_y,"merge":"am-motion-tilt-y"}));}
                _=>{position[0]+=d.x as f64;position[1]-=d.y as f64;if separate{invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/positionX","value":position[0],"merge":"am-motion-x"}));invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/positionY","value":position[1],"merge":"am-motion-y"}));}else{invoke(app,&ctx,"prop.set",json!({"layer":layer_id,"path":"transform/position","value":position,"merge":"am-motion-position"}));}}
            }
        }
    }

    let effect=ui.put(Rect::from_min_size(pos2(footer.max.x-98.0,footer.min.y+5.0),vec2(90.0,32.0)),egui::Button::new("＋ 效果"));
    app.auto.add_response("am.motion.effects.open",&effect,"打开效果浏览器");
    if effect.clicked(){section="effects".into();ctx.data_mut(|d|d.insert_temp(Id::new(AM_MOTION_TAB_ID),section));am_open_effect_browser(&ctx,Some(layer_id));}
    ui.painter().text(pos2(footer.min.x+10.0,footer.center().y),Align2::LEFT_CENTER,if has_key{"当前时间已有关键帧"}else{"左侧可添加关键帧"},Tokens::ui(9.5),t.text_dim);
}
'''

def replace_function(source: str) -> str:
    start = source.find("fn am_motion_editor(")
    end = source.find("\nfn tool_drawer(", start)
    if start < 0 or end < 0:
        raise SystemExit("Could not locate generated AM motion editor.")
    return source[:start] + WORKSPACE.strip() + "\n" + source[end:]


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    path = root / "crates/ui-egui/src/am_editor.rs"
    if not path.is_file():
        raise SystemExit("Generated AM editor source does not exist.")
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("AM single motion workspace already installed.")
        return
    source = replace_function(source)
    title_line = '    p.text(pos2(header.min.x + 10.0, header.center().y), Align2::LEFT_CENTER, title, Tokens::semibold(11.0), t.text);'
    title_expr = '    let title = if kind == "motion" && ui.ctx().data(|d| d.get_temp::<String>(Id::new(AM_MOTION_TAB_ID))).as_deref() == Some("effects") { "效果参数" } else { title };\n' + title_line
    if title_line in source and title_expr not in source:
        source = source.replace(title_line, title_expr, 1)
    source = source.replace('        "motion" => "移动与效果",', '        "motion" => "移动与变换",', 1)
    source = source.replace('    if kind != "add" {', '    if kind != "add" && kind != "motion" {', 1)
    old_height = '''        if kind == "motion" {
            (rect.height() * 0.74).clamp(340.0, 680.0).min(rect.height() * 0.84)
        } else if kind == "keyframes" {'''
    new_height = '''        if kind == "motion" {
            (rect.height() * 0.86).clamp(420.0, 760.0).min(rect.height() * 0.90)
        } else if kind == "keyframes" {'''
    if old_height in source:
        source = source.replace(old_height, new_height, 1)
    elif new_height not in source:
        raise SystemExit("Could not enlarge the unified AM bottom sheet.")
    required = (
        MARKER, 'Sense::drag()', '"滑动此处以移动图层"', 'PanelKind::EffectControls',
        'am_open_effect_browser(&ctx,Some(layer_id))', '"keys.toggleTransform"',
        '"keys.setSegmentCurve"', '"keys.velocity"',
    )
    # keys.velocity is wired through the native curve influence sliders.
    missing = [x for x in required if x not in source]
    if missing:
        raise SystemExit("AM workspace verification failed: " + "; ".join(missing))
    path.write_text(source, encoding="utf-8")
    print("Installed one AM transform sheet with left keyframe/curve rail, centre touch area, right transform rail and bottom-right Effects button.")


if __name__ == "__main__":
    main()
