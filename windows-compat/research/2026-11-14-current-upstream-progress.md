# EffectCraft Windows x86/x64 on Android ARM64 — 2026-11-14 research update

## Executive status

**No Android-device execution breakthrough yet.** The strongest new result is a reproducible Android NDK/Bionic build of current-upstream Box64 with BOX32 enabled. Current-main FEX ARM64EC/WoW64 PE DLLs and the standard Box64 ARM64 backend also build. Windows x86/x64 AEX host workers build on Windows CI. None of these results proves that Windows PE/AEX code has executed inside an Android ARM64 app process.

## Upstream source audit (current as checked on 2026-11-14)

| Project | Current revision checked | Relevance |
|---|---|---|
| [AndreRH/Hangover](https://github.com/AndreRH/hangover) | `56e385b7ff490edd281b288f420677093563560b` (2026-08-28) | Native ARM64 Wine host; WoW64 breaks out at Win32/Wine syscall boundary; ARM64EC + FEX for x86_64 PE. Upstream describes emulator DLLs rather than emulating the entire Wine installation. |
| [AndreRH/Wine hangover-11.16](https://github.com/AndreRH/wine/tree/hangover-11.16) | `628d1aeb09803d3fa9170023e7203060e955bfe8` | Wine source used by the official Termux package recipe. Termux's package recipe and Hangover release submodule do not point at the same Wine commit; this source mismatch must be resolved/recorded when reproducing the package. |
| [FEX](https://github.com/FEX-Emu/FEX) | `ea43314f040633c76fb5891ff31d8a7c3dc533b8` (2026-11-14) | Current-main x86/x86_64 dynamic recompiler and ARM64EC/WoW64 PE backends. |
| [Box64](https://github.com/ptitSeb/box64) | `6441fcfaeb69487039b0fd8cfb948c9e3f18c3d6` (2026-11-13) | Current-main x86_64 translation and optional BOX32 support. |
| [Termux packages](https://github.com/termux/termux-packages) | `e0ce77d242bb9f9adb48cc38dca4d69b3b6d0af9` (2026-11-13) | Official Bionic package recipe for Hangover Wine 11.16. |

### Architecture conclusion

The preferred Android path remains **native Bionic ARM64 Wine/Hangover + PE emulator DLLs**:
- x86_64 Windows PE: `libarm64ecfex.dll` / FEX ARM64EC (`HODLL64`).
- x86 Windows PE: `libwow64fex.dll` / FEX WoW64 (`HODLL`), with `wowbox64.dll` as an alternative backend.
- Launch the native Bionic Wine host and helpers through Android `/system/bin/linker64`; do not run the Bionic Wine host inside a glibc-built Linux Box64 process.
- Do not stack multiple emulators around Wine as the default architecture. Keep Box64/FEX as guest PE translators at the WoW64/ARM64EC boundary.

Official upstream overview: https://github.com/AndreRH/hangover#how-it-works

## New build evidence

### Box64 BOX32 — current upstream

- Run: https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43552790576
- Box64 revision: `6441fcfaeb69487039b0fd8cfb948c9e3f18c3d6`
- Result: **659/659** compile/link steps succeeded.
- Output: Android ARM64 ELF64 PIE; interpreter `/system/bin/linker64`.
- Artifact: `EffectCraft-Box64-BOX32-Android-ARM64`, artifact ID `14097046894`.
- Artifact ZIP digest: `0162a851f02bd3995e56e25b046fde7b42a61900f64cf4da4a1df1a7bc00180a`.
- Applied Bionic fixes: resolver state no longer reads glibc-private `struct __res_state`; Bionic netdb reentrant APIs use the existing buffer-safe Box64 adapters; Bionic allocator/obstack/signal/thread/posix_spawn compatibility patches apply.
- **Not tested:** execution of an x86 Linux ELF, Wine WoW64, Windows PE32, or AEX on Android.

### Standard Box64 + FEX PE backends

- Run: https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43552787304
- Standard Android ARM64 Box64 build: success; artifact ID `14097370088`.
- FEX current-main ARM64EC/WoW64 PE DLL build: success; artifact ID `14097081836`.
- FEX checks: `libarm64ecfex.dll` is PE machine `0x8664` with CHPE metadata; `libwow64fex.dll` is PE machine `0xaa64`; required Wine CPU exports were checked.
- Windows x64 AEX host worker build: success; artifact ID `14096927597`.
- Separate Windows x86 AEX host worker build: success; artifact ID `14096114769`.
- These are component/host builds, not Android runtime tests.

### Graphics fallback

- CLVK Android ARM64 OpenCL-on-Vulkan library build: success in [run 43552783777](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43552783777).
- No real OpenCL ICD was loaded by Wine and no plug-in kernel was executed. Termux Hangover's package recipe currently disables OpenCL, so this remains experimental.

## Failures converted into actionable findings

### Do not wrap Bionic Wine in glibc Box64

The previous ARM64 CI AEX run [43552783748](https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43552783748) failed before starting the Windows worker. The Wine binary requested `/system/bin/linker64`, but the Box64 host was a glibc Linux ARM64 binary; Box64 reported unresolved `__libc_init` and SIGSEGV. This is a host-libc mismatch, not a PE/AEX failure. The workflow was changed to an audit-only negative control and no longer attempts this invalid combination.

### 32-bit PE exception continuation is a real compatibility risk

[Box64 issue #4304](https://github.com/ptitSeb/box64/issues/4304) remains open. An exception-heavy packed PE32 DLL can hang during `DllMain(PROCESS_ATTACH)` under WowBox64 or fault under FEX. The report includes divide-by-zero, illegal-instruction and single-step exceptions, suggesting SEH/VEH continuation or trap-flag handling may be involved. Before claiming x86 plug-in support, add a reproducible PE32 fixture covering:
- continuable access violation / divide-by-zero / illegal-instruction exceptions;
- VEH and SEH nested handlers;
- single-step / trap-flag continuation;
- exception unwind through DLL initialization and worker threads.

### Termux Hangover 11.16 reproduction

Official Termux source recipe:
https://github.com/termux/termux-packages/tree/e0ce77d242bb9f9adb48cc38dca4d69b3b6d0af9/x11-packages/hangover-wine

The recipe enables `i386,aarch64,arm64ec`, OpenGL, Vulkan, PulseAudio and SDL; it disables OpenCL and ALSA. It packages FEX ARM64EC, FEX WoW64 and Box64 WoW64 emulator DLLs.

Build attempts exposed CI setup gaps:
1. SDK cmdline-tools layout and license-pipe handling were corrected.
2. NDK r30 verification was corrected to check the actual `clang` executable rather than a nonexistent generic target wrapper.
3. The Termux build must be invoked through `scripts/run-docker.sh`, not by running `build-package.sh` directly on the Ubuntu host. The package builder needs its own container and a mounted `/data/TERMUX_ARCH` marker.
4. The official package-builder image lacked `autopoint` for the fontconfig dependency. A small overlay Dockerfile now installs it on top of a digest-pinned base image.

Current corrected reproduction run: https://github.com/Qianqian442/EffectCraft-AI-Build/actions/runs/43553764486 (in progress at the time of this note). No Hangover .deb package build has passed yet.

Termux issue [#27663](https://github.com/termux/termux-packages/issues/27663) was closed on 2026-03-21 after a user reported x86/x64 startup recovery by installing the complete Hangover package set and recreating a clean Wine prefix. The thread also notes possible x64 freezes, so complete package placement and prefix creation must be validated.

## Next verification steps

1. Finish the Termux Hangover 11.16 reproduction using the pinned package-builder overlay; inspect all .deb packages, Bionic ELF interpreters, PE machine types, checksums, and the transitive SBOM.
2. Resolve the Termux Wine source revision mismatch and all hard-coded `/data/data/com.termux/files/usr` paths before private-storage relocation.
3. Integrate the Bionic Wine host and complete emulator DLL set into an EffectCraft-private prefix; route every Wine/wineserver/helper Bionic ELF through the EffectCraft linker64 exec bridge under the app UID.
4. Build an Android ARM64 emulator test app for the minimal Bionic launcher, then run minimal Win32 and x86_64 PE samples. Emulator success must be kept separate from physical OPPO/Huawei device success.
5. Add the PE32 SEH/VEH/trap-flag fixture; only then test the x86 AEX host.
6. Test x64 and x86 AEX workers with real third-party plug-ins, parameter reads/writes, lifecycle callbacks and render output; report missing AE suites explicitly.
7. Complete SBOM/license review before packaging or redistributing Wine/Hangover, FEX, Box64 and Termux components.

## Explicit non-claims

- No x86 or x86_64 Windows PE has yet been proven to execute inside EffectCraft on an Android ARM64 device.
- No third-party AEX plug-in has yet been loaded and rendered on an Android device.
- No installable EffectCraft APK containing this runtime is ready.
- Component compilation does not imply full Windows API, AE SDK, GPU, audio, input or plug-in compatibility.
