#!/usr/bin/env python3
"""Bundle offline Chinese Sherpa-ONNX TTS and an independent SoundTouch pitch DSP for Ae."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

SHERPA_VERSION = "2.0.3"
AAR_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/v{SHERPA_VERSION}/sherpa-onnx-{SHERPA_VERSION}.aar"
AAR_SHA256 = "4c766e2e74c9d33d595338c21fe3b305c73ba45d47e96a235675c33142a2ec50"
MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/sherpa-onnx-vits-zh-ll.tar.bz2"
SOUNDTOUCH_URL = "https://github.com/hipxel/soundtouch-android/archive/refs/heads/main.tar.gz"
PITCH_CMAKE = r"""
cmake_minimum_required(VERSION 3.18)
project(AePitchShifter LANGUAGES C CXX)
add_subdirectory(soundtouch)
add_library(AePitchShifter SHARED AePitchShifter.cpp)
target_include_directories(AePitchShifter PRIVATE soundtouch/include)
target_link_libraries(AePitchShifter PRIVATE SoundTouch log)
target_compile_options(AePitchShifter PRIVATE -fno-rtti -fno-exceptions -fvisibility=hidden -O3)
set_target_properties(AePitchShifter PROPERTIES CXX_STANDARD 98)
"""
PITCH_CPP = r"""
#include <jni.h>
#include <SoundTouch.h>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

using soundtouch::SoundTouch;
using soundtouch::SAMPLETYPE;

extern "C" JNIEXPORT jfloatArray JNICALL
Java_com_artcraft_effectcraft_EffectCraftActivity_pitchShiftSamples(
        JNIEnv* env, jclass, jfloatArray input, jint sampleRate, jdouble semitones) {
    if (input == nullptr || sampleRate < 8000 || sampleRate > 96000 ||
        !std::isfinite(semitones) || semitones < -12.0 || semitones > 12.0) {
        return nullptr;
    }
    const jsize count = env->GetArrayLength(input);
    if (count <= 0 || count > 8000000) return nullptr;

    jboolean copied = JNI_FALSE;
    jfloat* source = env->GetFloatArrayElements(input, &copied);
    if (source == nullptr) return nullptr;

    std::vector<SAMPLETYPE> pcm;
    pcm.resize(static_cast<size_t>(count));
    for (jsize i = 0; i < count; ++i) {
        const float v = std::max(-1.0f, std::min(1.0f, source[i]));
        pcm[static_cast<size_t>(i)] = static_cast<SAMPLETYPE>(v * 32767.0f);
    }
    env->ReleaseFloatArrayElements(input, source, JNI_ABORT);

    SoundTouch processor;
    processor.setSampleRate(static_cast<unsigned int>(sampleRate));
    processor.setChannels(1);
    processor.setPitchSemiTones(static_cast<double>(semitones));
    processor.putSamples(pcm.data(), static_cast<unsigned int>(pcm.size()));
    processor.flush();

    const unsigned int available = processor.numSamples();
    if (available == 0 || available > 12000000U) return nullptr;
    std::vector<SAMPLETYPE> shifted(available);
    const unsigned int received = processor.receiveSamples(shifted.data(), available);
    if (received == 0) return nullptr;

    jfloatArray output = env->NewFloatArray(static_cast<jsize>(received));
    if (output == nullptr) return nullptr;
    std::vector<jfloat> values(received);
    for (unsigned int i = 0; i < received; ++i) {
        values[i] = static_cast<float>(shifted[i]) / 32768.0f;
    }
    env->SetFloatArrayRegion(output, 0, static_cast<jsize>(received), values.data());
    return output;
}
"""

def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size > 1024:
        return
    temporary = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "Ae-Android-Builder"})
    with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)
    if temporary.stat().st_size < 1024:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Download is unexpectedly small: {url}")
    temporary.replace(target)

def extract_safe(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, "r:*") as tar:
        for member in tar.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"Unsafe archive path: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise RuntimeError(f"Cannot extract: {member.name}")
                with source, target.open("wb") as out:
                    shutil.copyfileobj(source, out, length=1024 * 1024)
            else:
                raise RuntimeError(f"Unsupported archive entry: {member.name}")

def find_ndk() -> Path:
    candidates = [
        os.environ.get("ANDROID_NDK_HOME"),
        os.environ.get("ANDROID_NDK_ROOT"),
        os.environ.get("NDK_HOME"),
    ]
    sdk = Path(os.environ.get("ANDROID_SDK_ROOT", os.environ.get("ANDROID_HOME", "/usr/local/lib/android/sdk")))
    if sdk.is_dir():
        candidates.extend(str(p) for p in sorted((sdk / "ndk").glob("*"), reverse=True))
    for value in candidates:
        if value:
            path = Path(value)
            if (path / "build" / "cmake" / "android.toolchain.cmake").is_file():
                return path
    raise RuntimeError("Android NDK not found; cannot compile local pitch processor.")

def install_gradle_dependency(builder: Path) -> None:
    source = builder / "lib" / "android_project.py"
    text = source.read_text(encoding="utf-8")
    marker = "AE_SHERPA_OFFLINE_TTS_AAR_V1"
    if marker not in text:
        anchor = "implementation 'androidx.games:games-activity:4.4.0'"
        if text.count(anchor) != 1:
            raise RuntimeError("Cannot locate Android Gradle dependency anchor in android_project.py")
        text = text.replace(anchor, anchor + "\n    // " + marker + "\n    implementation files('libs/sherpa-onnx-2.0.3.aar')", 1)
        source.write_text(text, encoding="utf-8")

def install_extra_jni(builder: Path, library: Path) -> None:
    target = builder / "templates" / "android-extra-jniLibs" / "arm64-v8a" / "libAePitchShifter.so"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(library, target)

    common = builder / "lib" / "build-common.sh"
    text = common.read_text(encoding="utf-8")
    marker = "AE_SOUNDTOUCH_PITCH_DSP_V1"
    if marker not in text:
        anchor = 'GRADLE_JDK="$(find_gradle_jdk || true)"'
        block = (
            '# ' + marker + '\n'
            'EXTRA_JNILIBS="$ROOT/templates/android-extra-jniLibs"\n'
            'if [[ -d "$EXTRA_JNILIBS" ]]; then\n'
            '    mkdir -p "$ANDROID_DIR/jniLibs"\n'
            '    cp -a "$EXTRA_JNILIBS/." "$ANDROID_DIR/jniLibs/"\n'
            'fi\n\n'
        )
        if text.count(anchor) != 1:
            raise RuntimeError("Cannot locate Gradle boundary in build-common.sh")
        text = text.replace(anchor, block + anchor, 1)
        common.write_text(text, encoding="utf-8")

def main() -> None:
    builder = Path(os.environ.get("ARTCRAFT_DIR", "")).resolve()
    if not builder.is_dir():
        raise SystemExit("ARTCRAFT_DIR is required.")
    workspace = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir()))
    cache = workspace / "ae-offline-tts-cache"
    cache.mkdir(parents=True, exist_ok=True)

    aar = cache / f"sherpa-onnx-{SHERPA_VERSION}.aar"
    download(AAR_URL, aar)
    digest = hashlib.sha256(aar.read_bytes()).hexdigest()
    if digest != AAR_SHA256:
        raise RuntimeError(f"Sherpa AAR SHA-256 mismatch: {digest}")
    gradle_libs = builder / "templates" / "gradle" / "libs"
    gradle_libs.mkdir(parents=True, exist_ok=True)
    shutil.copy2(aar, gradle_libs / aar.name)
    install_gradle_dependency(builder)

    model_archive = cache / "sherpa-onnx-vits-zh-ll.tar.bz2"
    download(MODEL_URL, model_archive)
    model_extract = cache / "model"
    if not (model_extract / "sherpa-onnx-vits-zh-ll" / "model.onnx").is_file():
        shutil.rmtree(model_extract, ignore_errors=True)
        extract_safe(model_archive, model_extract)
    model_source = model_extract / "sherpa-onnx-vits-zh-ll"
    required = ("model.onnx", "tokens.txt", "lexicon.txt", "date.fst", "phone.fst", "number.fst", "new_heteronym.fst")
    for name in required:
        p = model_source / name
        if not p.is_file() or p.stat().st_size == 0:
            raise RuntimeError(f"Offline TTS model file missing: {name}")
    if (model_source / "model.onnx").stat().st_size < 80 * 1024 * 1024:
        raise RuntimeError("Offline TTS model.onnx is smaller than the expected Chinese VITS model.")

    app_assets = builder / "source" / "effectcraft" / "assets" / "ae-tts" / "sherpa-onnx-vits-zh-ll"
    shutil.rmtree(app_assets, ignore_errors=True)
    shutil.copytree(model_source, app_assets)
    if not (app_assets / "model.onnx").is_file():
        raise RuntimeError("Offline model was not copied into Android packaged assets.")

    soundtouch_archive = cache / "soundtouch-android.tar.gz"
    download(SOUNDTOUCH_URL, soundtouch_archive)
    soundtouch_extract = cache / "soundtouch"
    if not list(soundtouch_extract.glob("*/src/main/cpp/soundtouch/CMakeLists.txt")):
        shutil.rmtree(soundtouch_extract, ignore_errors=True)
        extract_safe(soundtouch_archive, soundtouch_extract)
    candidates = list(soundtouch_extract.glob("*/src/main/cpp"))
    if not candidates:
        raise RuntimeError("SoundTouch source tree is missing.")
    cpp_source = candidates[0]
    with tempfile.TemporaryDirectory(prefix="ae-pitch-") as work:
        workdir = Path(work)
        cmake_source = workdir / "src"
        cmake_source.mkdir()
        shutil.copytree(cpp_source / "soundtouch", cmake_source / "soundtouch")
        (cmake_source / "CMakeLists.txt").write_text(PITCH_CMAKE, encoding="utf-8")
        (cmake_source / "AePitchShifter.cpp").write_text(PITCH_CPP, encoding="utf-8")
        ndk = find_ndk()
        build_dir = workdir / "build"
        subprocess.run([
            "cmake", "-S", str(cmake_source), "-B", str(build_dir),
            f"-DCMAKE_TOOLCHAIN_FILE={ndk / 'build/cmake/android.toolchain.cmake'}",
            "-DANDROID_ABI=arm64-v8a", "-DANDROID_PLATFORM=android-21",
            "-DCMAKE_BUILD_TYPE=Release",
        ], check=True)
        subprocess.run(["cmake", "--build", str(build_dir), "--config", "Release", "--target", "AePitchShifter", "-j2"], check=True)
        library = build_dir / "libAePitchShifter.so"
        if not library.is_file() or library.stat().st_size < 10_000:
            raise RuntimeError("The Android ARM64 pitch DSP did not produce a valid shared library.")
        install_extra_jni(builder, library)

    license_path = cpp_source.parent.parent.parent / "LICENSE.LGPL_2_1.txt"
    if license_path.is_file():
        notice_dir = app_assets.parent / "licenses"
        notice_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(license_path, notice_dir / "SoundTouch-LGPL-2.1.txt")
    print("Bundled offline Chinese VITS TTS (5 speakers), the pinned Sherpa-ONNX Android AAR, and the ARM64 independent pitch DSP.")

if __name__ == "__main__":
    main()
