# Sapphire 2026.5 → EffectCraft Android Compatibility Plan

> This is an independent Android reimplementation plan. Windows `.aex` binaries are reference inputs only and are never executed, loaded, or byte-translated on Android. Names below identify the desktop effect behavior being studied; they do not imply affiliation, source-code reuse, or bit-for-bit equivalence.
>
> Reference set: Boris FX Sapphire 2026.5 OFX/AE documentation. The official package describes 250+ plug-ins and documents effect summaries, parameters, inputs, animation and GPU behavior. The effect list is a coverage inventory, not a claim that every effect is already ported.

## 1. Engineering contract

Every Android implementation must have all of the following before it is marked complete:

1. **Behavior spec** — input semantics, parameter defaults/ranges/units, edge/alpha/color-space behavior, time dependence, and expected look.
2. **Parameter adapter** — stable Android effect ID plus stable parameter IDs; aliases for desktop parameter names; explicit units and normalized-value conversion.
3. **Interactive preview** — parameters update the same render implementation used by final output; scaled previews use the host `scale` value correctly.
4. **Final renderer** — deterministic output, premultiplied RGBA correctness, edge handling, alpha behavior, bounded memory/CPU/GPU cost.
5. **Animation** — all animatable scalar/vector/color controls are ordinary EffectCraft properties, with keyframes and expressions supplied by the host property system. Do not create a separate, incompatible keyframe store.
6. **Visual regression** — reference frames at fixed resolution/time, side-by-side comparison, difference image, and tolerances for geometry, luminance, hue, edge width, halo radius and temporal stability.
7. **Honest compatibility label** — “Android compatible recreation” until comparison proves a documented fidelity target. Never label a recreation as the original proprietary Sapphire binary.

## 2. Host capabilities and current gaps

### Capabilities already present in EffectCraft

- WASM API v1 exposes `ec_api_version`, `ec_manifest_ptr`, `ec_manifest_len`, `ec_alloc`, and `ec_render`.
- The host converts plug-in manifest parameters into ordinary effect properties. Sliders, angles, checkboxes, popups, points and colors therefore flow through Effect Controls, property animation/keyframes, expressions and the existing render pipeline.
- The host passes layer time and preview scale to `ec_render`.
- The host frame is premultiplied RGBA float data. Point parameters are converted by the host from layer-relative coordinates to frame pixels before the WASM render call. Plugin code must not normalize or scale those points a second time.
- One effect implementation is used for preview and final render; quality settings may choose lower preview resolution, but must not silently change parameter meaning.

### API v1 limits that prevent full parity for some effects

- The current frame contract is one RGBA image plus scalar parameters. It does not provide independent Source/Background/Matte/Lens/Occlusion/Depth/Vector inputs.
- It does not provide arbitrary neighboring source frames, a persistent temporal history/cache contract, motion-vector planes, a tracking service, or Mocha spline data.
- It does not expose a general GPU compute interface to a WASM module. Large blur, optical flow, particle and convolution effects should move to native Rust/C++/WGSL GPU passes when needed.
- Several Sapphire effects are inherently two-input transitions, depth-aware effects, tracked effects, or temporal effects. They must remain “host API required” until those inputs/services are implemented. A one-frame visual approximation must not be presented as full compatibility.

### Host API v2 workstream (required for the full catalogue)

Add versioned optional auxiliary inputs with explicit dimensions, transforms, color space, alpha mode and frame-time access; a deterministic temporal-frame request interface; mask/depth/motion-vector planes; and optional GPU-backed render passes. Keep v1 modules working unchanged. Add API capability negotiation so older modules still load. All new inputs must be immutable during a render call and bounded by the host memory/fuel policy.

## 3. Detailed reference parameter maps

These are the first high-priority desktop parameter families to map. Exact desktop defaults/ranges are to be captured from the matching official effect page/version before finalizing the Android adapter.

| Desktop effect | Function and algorithm family | Desktop controls that need mapping | Android rendering target |
|---|---|---|---|
| Glow | Threshold highlight extraction → multi-scale separable Gaussian/convolution → composite | Threshold, Brightness, Color, Glow Width, Width X/Y, Width Red/Green/Blue, Subpixel, Combine, Affect Alpha, Glow From Alpha, Glow Under Source, Edge Mode, Expand Borders, Atmosphere controls | Smooth multi-scale halo; per-channel width falloff; correct highlight roll-off; optional spectrum and alpha control; no hard box blur rings |
| GlowAura | Direction/gradient-following colored aura pattern | Threshold, Width, Frequency, Phase, Twist, Color, Brightness | Gradient-aligned radial aura filaments with stable phase animation; not a simple tinted blur |
| GlowDarks / GlowOrthicon | Extract dark regions → soften/attenuate/composite | Threshold, Darkness, Width, Mix/Combine, edge and alpha controls | Deep smoky dark halo without crushing unrelated midtones |
| GlowDist / GlowEdges / GlowRainbow | Edge threshold/distance field → inward/outward glow; optional spectrum coloring | Threshold, Width, Thickness, Color, RGB width, Edge side, Mix | Thin and thick edges produce controlled glow; spectrum must vary smoothly with edge distance |
| GlowNoise / GlowRings / UltraGlow / ZGlow | Noise-modulated glow, ring convolution, multi-pass glow, depth glow | Threshold, Width, Detail, Frequency, Seed, Speed, Ring width/thickness, After Glow, Depth and quality controls | Repeatable noise unless jitter is enabled; ring profile and glow pyramid; Z variants require depth input |
| LensFlare | Procedural optical element assembly along hotspot-to-pivot axis | Lens preset/design, Hotspot, Pivot, Brightness, Scale, Rotation, Color, Element visibility/size, Occlusion, Softness, Invert, Use Color | Lens-specific ghost elements, aperture shape, spectral rings, streaks and occlusion; preset editor later |
| LensFlareAutoTrack | Detect/track a flare point over source frames | Tracking ROI, threshold, smoothing, offset, lens design, confidence | Requires temporal tracker service; manual hotspot fallback must be clearly labeled |
| Rays / EdgeRays / Streaks | Threshold source, extract features, radial or directional light accumulation | Threshold, Length, Brightness, Density, Angle/Origin, Rays Res, Color, Mask, Edge controls | Soft volumetric beams from bright sources, controlled spread, stable sampling and no visible radial banding |
| Glint / GlintRainbow / Glare | Threshold bright pixels, star-kernel convolution, rainbow/spectral halo and ray compositing | Threshold, Size, Brightness, Ray count/angle, Color, Shift, Rainbow, Glare style, Convolve, Resolution | Subpixel-stable star glints, physically plausible aperture rays and spectral rings |
| Blur | Separable Gaussian/triangle/box kernel | Width, Width X/Y, Filter, Effect Color/Mono, Edge Mode, Mask, Quality, Mix | Continuous fractional radius; scale-aware; no radius stepping; proper premultiplied alpha |
| BlurChannels / BlurChroma / BlurDirectional | Per-channel or luma/chroma decomposition followed by separate blur kernels | Channel widths, Luma/Chroma widths, Direction, Filter, X/Y, Mix | Independent channel blur; preserve neutral edges when chroma only is blurred |
| BlurMotion / BlurMoCurves | Integrate samples across spatial transforms or animated transform curves | From/To transform, shutter, samples, curve controls, motion blur length | Requires transform sampling and potentially per-frame motion; current directional approximation is not full match |
| RackDefocus / AdvancedDefocus / DefocusPrism | Circle-of-confusion convolution with aperture shape and chromatic separation | Focus/defocus, iris points, rotation, blade curvature, bokeh boost, chromatic separation, highlight gamma | Polygon/cat-eye bokeh, shape rotation, edge falloff and highlight energy; not a Gaussian blur |
| Distort | Inverse-map source coordinates from a separate Lens image gradient | Lens input, Amount, Scale, Center, Blur, Edge Mode, Mask | Requires second input plane for true lens-driven displacement; radial swirl is a separate Android effect |
| DistortChroma / DistortRGB / WarpChroma | Split color planes and apply different displacement transforms | RGB offsets, channel scale/rotation, lens gradient, amount, center | Color fringes with controlled channel displacement; no alpha fringe |
| WarpBubble / WarpBubble2 / WarpPuddle / WarpVortex / WarpWaves | Inverse mapping with analytic or noise displacement fields | Center, Amplitude, Frequency, Phase, Speed, Radius, Inner/Outer falloff | Smooth subpixel warp, deterministic phase, seamless edge behavior; animate phase/time |
| WarpFishEye / WarpMagnify / WarpPolar / WarpPerspective / WarpCornerPin | Lens projection, radial mapping, homography or corner-constrained mapping | Center, radius, magnification, perspective corners, fit/edge mode | Stable inverse mapping with bilinear sampling and no holes |
| Cartoon / CartoonPaint / Sketch / Etching / BrushOil / BrushChalk / Crosshatch | Edge-aware smoothing, quantization, orientation fields and procedural strokes | Edge threshold/width, detail, palette/levels, stroke size/angle/density, texture seed | Preserve major contours and stable texture between frames; use edge-aware filters, not simple posterize |
| HalfTone / HalfToneColor / HalfToneRings | Periodic screen-space dot/ring sampling with luma/color separation | Cell frequency, dot size, angle, smooth source, color/dot mode, phase, contrast | Subpixel antialiasing; correct CMY/RGB separation; dots must not crawl during animation |
| PixelSort / Mosaic / TileScramble / RomanTile | Threshold segmentation, scanline/radial ordering, block sampling/reordering | Pattern, threshold range, direction, tile size, seed, amount, edge/matte | Stable tile boundaries and deterministic sort; preserve source alpha |
| FilmEffect / FilmDamage / BleachBypass / VintageColor2Strip / VintageColor3Strip | Film response curve, dye/channel matrix, grain, halation and damage overlays | Stock/preset, exposure, contrast, color response, grain size/amount, flicker, dust, scratches, weave | Color-managed LUT/curves plus time-stable grain and procedural damage; compare using fixed source and display transform |
| Grain / GrainStatic / UltraGrain / GrainRemove | Deterministic spatial noise, temporal noise, denoise/edge preservation | Amount, size, color/mono, seed, temporal coherence, edge threshold/detail | Same frame/time produces identical grain; animated grain changes only when specified |
| Vignette / SoftFocus / Beauty | Spatial falloff mask plus color/detail processing | Center, radius, squareness, feather, opacity, color; skin mask/range, smoothing, glow | Smooth ellipse/shape mask, no edge clipping; Beauty needs a skin segmentation mask |
| Adjust family: Gamma, HueSatBright, DuoTone, QuadTone, TriTone, Monochrome, Tint, Threshold, ChannelSwitcher | Color transforms in a defined working color space | Per-channel offsets/scales, gamma, hue/saturation/brightness, shadow/highlight colors, thresholds, blend | Color-managed operations, no unintended gamut clipping, alpha unaffected unless explicitly requested |
| Gradient / GradientMulti / GradientRadial / Grid / Shape | Procedural geometry and color interpolation | Control points, colors, radius, position, rotation, shape points, feather, noise | Resolution-independent procedural output and keyframeable control points |
| Clouds / Aurora / Texture* / Caustics / Sparkles | Seeded procedural noise, fractal fields, advection and particle-like marks | Seed, frequency, octaves, color stops, phase, speed, density, scale | Deterministic noise, stable temporal evolution; large procedural fields use GPU when available |
| Zap / ZapFrom / ZapTo / UltraZap / LaserBeam / MuzzleFlash | Spline/branch generation, noisy path, glow and smoke compositing | Start/end/spline, branches, thickness, jitter, seed, color, glow, speed | Keyframeable path points, deterministic branches, soft alpha and glow; ballistic smoke/particles later |
| Dissolve*/Wipe*/Swish*/CardFlip/FilmRoll/WhipLash | Two-clip compositing plus animated masks, geometry and secondary effects | A/B inputs, completion, pattern, edge width, direction, softness, transform, motion blur | Requires API v2 two-input compositing; not a single-layer shader masquerading as a transition |
| Feedback*/Trails/TimeAverage/TimeDisplace/TimeSlice/TimeWarpRGB/FlickerMatch | Frame history, temporal sampling and/or per-channel time offsets | History length, decay, frame offset, displacement map, per-channel offset, seed, match region | Requires deterministic frame cache and temporal evaluation, random-access-safe history reset |
| Retime / RepairFrames / MotionDetect / NearestColor / LensFlareAutoTrack | Optical flow, motion estimation, scene/feature tracking or temporal aggregation | Search radius, confidence, reference frame, motion quality, tracking region, threshold | Requires a motion/tracking pipeline and multi-frame test suite; cannot be reproduced by a per-frame color filter |
| 3D/depth effects: ZBlur / ZGlow / ZDefocus / ZFog* / ZComp / Light3D / SpotLight | Depth-buffer compositing, depth-aware blur/fog/lighting | Depth source, near/far, focus plane, falloff, light position/direction, cone/softness | Requires depth auxiliary plane and consistent camera/coordinate transform |

## 4. Full reference coverage inventory

All names below are in the official Sapphire 2026.5 effect documentation. Coverage status in this repository must be tracked independently from the desktop name. “Implemented” means a real Android renderer with tests, not a placeholder or a filename match.

### Lighting, glow, rays and optical flares

Glow, GlowAura, GlowDarks, GlowDist, GlowEdges, GlowNoise, GlowOrthicon, GlowRainbow, GlowRings, UltraGlow, ZGlow, Rays, EdgeRays, Streaks, LensFlare, LensFlareAutoTrack, LightLeak, Glint, GlintRainbow, Glare, BokehLights, DropShadow, Flashbulbs, Light3D, SpotLight.

### Stylize, paint, halftone, film and grain

AutoPaint, Sketch, Etching, BrushOil, BrushChalk, Crosshatch, Cartoon, CartoonPaint, Posterize, HalfTone, HalfToneColor, HalfToneRings, KaleidoTriangles, KaleidoSquares, KaleidoDiamonds, KaleidoOct, KaleidoPolar, KaleidoRadial, FlysEyeCircles, FlysEyeHex, FlysEyeRect, TileScramble, FilmBurn, FilmEffect, FilmDamage, FilmBurnTransition, VHSDamage, Vignette, BleachBypass, Grain, GrainStatic, UltraGrain, Diffuse, VintageColor2Strip, VintageColor3Strip, EdgeDetect, EdgeDetectDouble, EdgesInDirection, EdgeColorize, Emboss, EmbossShiny, EmbossDistort, EmbossGlass, BandPass, ColorFuse, DogVision, DigitalDamage, JpegDamage, TVDamage, Grunge, Mosaic, PixelSort, PseudoColor, PsykoBlobs, PsykoStripes, PrismLens, RomanTile, ScanLines, ScanLinesMono, Solarize, StripSlide, Zebrafy, ZebrafyColor, ZFogExponential, ZFogLinear.

### Color, channel, composite and matte

ChannelSwitcher, ClampChroma, DuoTone, Gamma, Hotspots, HueSatBright, Invert, Monochrome, OCIOTransform, QuadTone, Threshold, Tint, TriTone, ShowBadColors, EdgeFlash, Layer, MathOps, MatteOps, MatteOpsComp, ZComp.

### Blur, sharpen and defocus

AdvancedDefocus, Beauty, Blur, BlurChannels, BlurChroma, BlurDirectional, BlurMoCurves, BlurMotion, Convolve, ConvolveComp, Deband, DefocusPrism, EdgeBlur, EdgeAwareBlur, FreeLens, GrainRemove, Median, RackDefocus, RackDfComp, Sharpen, SoftFocus, ZConvolve, ZDefocus, ZBlur.

### Distortion, warp, lens and shake

Distort, DistortBlur, DistortChroma, DistortRGB, InfiniteZoom, ParallaxStrips, WarpBubble, WarpBubble2, WarpChroma, WarpCornerPin, WarpDrops, WarpFishEye, WarpMagnify, WarpPerspective, WarpPolar, WarpPuddle, WarpPuff, WarpRepeat, WarpTransform, WarpVortex, WarpWaves, WarpWaves2, Shake, StretchFrameEdges.

### Procedural render, gradients, geometry and particles

Aurora, Caustics, Clouds, CloudsColorSmooth, CloudsMultColor, CloudsPerspective, CloudsPsyko, CloudsVortex, Dust, Flashbulbs, Gradient, GradientMulti, GradientRadial, Grid, LaserBeam, Luna, MuzzleFlash, NightSky, Shape, Sparkles, SparklesColor, TextureCells, TextureChromaSpiral, TextureFlux, TextureFolded, TextureLoops, TextureMicro, TextureMoire, TextureNeurons, TextureNoiseEmboss, TextureNoisePaint, TexturePlasma, TextureRidges, TextureSpots, TextureTiles, TextureWeave.

### Time and temporal processing

CutToDissolve, Feedback, FeedbackBubble, FeedbackDistort, FieldRemove, FreezeFrame, GetFrame, JitterFrames, MotionDetect, NearestColor, RandomEdits, RepairFrames, Retime, ReverseClip, ReverseEdits, TimeAverage, TimeDisplace, TimeSlice, TimeWarpRGB, Trails, TrailsDiffuse, Flicker, FlickerMatch, FlickerMatchColor, FlickerMatchMatte, FlickerMchMatteColor, FlickerRemove, FlickerRemoveColor, FlickerRemoveMatte, FlickerRmMatteColor.

### Transitions

Dissolve, DissolveAutoPaint, DissolveBlur, DissolveBubble, DissolveDefocus, DissolveDiffuse, DissolveDigitalDamage, DissolveDistort, DissolveEdgeRays, DissolveFilm, DissolveFlashbulbs, DissolveGlare, DissolveGlint, DissolveGlintRainbow, DissolveGlow, DissolveLensFlare, DissolveLuma, DissolvePixelMosh, DissolvePixelSort, DissolvePuddle, DissolveRays, DissolveShake, DissolveSpeckle, DissolveStatic, DissolveTiles, DissolveUltraGlow, DissolveVortex, DissolveWaves, DissolveZap, WipeBlobs, WipeBubble, WipeCells, WipeChecker, WipeCircle, WipeClock, WipeClouds, WipeDiffuse, WipeDots, WipeDoubleWedge, WipeFlux, WipeFourWedges, WipeLine, WipeMoire, WipePixelate, WipePlasma, WipePointalize, WipeRectangle, WipeRings, WipeStar, WipeStripes, WipeTiles, WipeWeave, WipeWedge, SwishPan, Swish3D, CardFlip, FilmRoll, FlutterCut, HyperPull, HyperPush, ParallaxStripsTransition, StripSlideTransition, TVChannelChange, WhipLash.

## 5. Implementation order

### Phase A — core single-frame visual effects

Glow/GlowAura/GlowEdges/GlowRings, LensFlare, Glint, Glare, Rays, Blur, BlurDirectional, Distort, DistortRGB/Chroma, Vignette, Grain, HalfTone, PixelSort, EdgeDetect, Cartoon, Posterize, WarpWaves, WarpVortex, Kaleidoscope, ScanLines.

### Phase B — richer single-frame effects

Bokeh, streaks, light leaks, film response/damage, texture and cloud generators, caustics, shape/gradient renderers, emboss, color-fuse/LUT, channel and matte operations.

### Phase C — host API v2 and multi-input effects

Lens-driven distortions, background/matte transitions, occlusion-aware flares, depth effects, Mocha/track-driven effects, two-clip transitions, temporal effects and frame-history processors.

## 6. Visual comparison and quality gates

For every supported effect, use a fixed set of reference inputs: dark scene with point highlights, bright texture, hard geometric edges, skin/portrait, transparent foreground, moving object, high-frequency detail and 16-bit/32-bit HDR sample. Capture desktop reference frames and Android outputs at matching dimensions, frame rate, time, working/display color spaces and parameters.

Record:
- image-wide SSIM/PSNR only as supporting metrics (not as the sole acceptance test);
- edge displacement and blur radius;
- halo centroid, radius, falloff and RGB dispersion;
- hue/saturation and luminance histogram drift;
- alpha-edge contamination and premultiplication correctness;
- temporal shimmer, random-seed reproducibility and parameter interpolation behavior;
- preview-to-final-render difference.

A visual mismatch is not “fixed” by reducing the reference quality, hiding a parameter or using a lower-resolution export. Optimize performance after the full-quality path is correct.

## 7. Project implementation status at baseline

- Existing WASM compatibility pack: Glow, GlowAura, LensFlare, Blur, Distort, Stylize.
- Existing independent mobile modules: RSMB-style directional blur and Looks Studio color grading.
- Current compatibility modules are original EffectCraft implementations. They are not original Sapphire source code and do not reproduce proprietary algorithms by declaration alone.
- Immediate engineering work: improve renderer sampling, scale handling, optical light effects and stylize algorithms; add per-effect render tests; then expand the pack and host input API.
