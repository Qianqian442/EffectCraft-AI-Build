# Ae DeepSeek AI model package

This directory contains the local DeepSeek runtime sources that are embedded into the main Ae Android APK, plus the metadata and Kotlin helpers used by the model manager.

## Delivery format

The runtime and model manager are part of the main Ae APK. The model itself is delivered as one importable ZIP data package:

- `ai-model.json`
- `DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf` (approximately 1.02 GB)

The ZIP is **not an APK** and does not ask Android to install another application. In Ae, open the AI assistant, choose **导入 AI 模型包**, and select the ZIP. The app copies the model into its private storage after validating the package identifier, file length and SHA-256 checksum.

The existing in-app network download path remains available as a fallback. Once the model is imported or downloaded, text inference runs locally without a network connection.

## Build

Run the GitHub Actions workflow **Build Ae DeepSeek AI model package (ZIP only)**. It downloads the quantized model, creates the checksum manifest, verifies the ZIP, and publishes `Ae-DeepSeek-AI-Plugin.zip`.

The Android runtime is built as part of the main APK workflow. This workflow does not build or publish a standalone companion APK.
