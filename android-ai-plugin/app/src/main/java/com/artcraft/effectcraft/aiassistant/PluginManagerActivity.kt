package com.artcraft.effectcraft.aiassistant

import android.app.Activity
import android.app.DownloadManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import java.io.File
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.zip.ZipInputStream
import org.json.JSONObject

class PluginManagerActivity : Activity() {
    private lateinit var statusText: TextView
    private lateinit var progressBar: ProgressBar
    private lateinit var downloadButton: Button
    private lateinit var importButton: Button
    private val handler = Handler(Looper.getMainLooper())
    private val preferences by lazy { getSharedPreferences("deepseek_plugin", Context.MODE_PRIVATE) }
    private val modelFile: File
        get() = File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), MODEL_FILE)
    private val downloadManager by lazy { getSystemService(DownloadManager::class.java) }

    private val pollDownload = object : Runnable {
        override fun run() {
            val id = preferences.getLong(KEY_DOWNLOAD_ID, 0L)
            if (id == 0L) return
            val cursor = downloadManager.query(DownloadManager.Query().setFilterById(id))
            cursor.use {
                if (it == null || !it.moveToFirst()) {
                    statusText.text = "未找到下载任务，可重新开始下载。"
                    preferences.edit().remove(KEY_DOWNLOAD_ID).apply()
                    downloadButton.isEnabled = true
                    return
                }
                val status = it.getInt(it.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS))
                val downloaded = it.getLong(it.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR))
                val total = it.getLong(it.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES))
                if (total > 0L) {
                    val percent = ((downloaded * 100L) / total).toInt().coerceIn(0, 100)
                    progressBar.progress = percent
                    statusText.text = "正在下载 DeepSeek 本地模型：" + percent + "%（" +
                        formatBytes(downloaded) + " / " + formatBytes(total) + "）"
                } else {
                    statusText.text = "正在连接模型文件并下载… 已接收 " + formatBytes(downloaded)
                }

                when (status) {
                    DownloadManager.STATUS_SUCCESSFUL -> {
                        preferences.edit().remove(KEY_DOWNLOAD_ID).apply()
                        if (modelFile.isFile && modelFile.length() > MIN_MODEL_BYTES) {
                            progressBar.progress = 100
                            statusText.text = "DeepSeek 模型已准备完成。现在可以断网，在 Ae 中使用本地 AI 助手。"
                            downloadButton.text = "模型已就绪"
                            downloadButton.isEnabled = false
                        } else {
                            statusText.text = "下载文件不完整，请删除后重新下载。"
                            modelFile.delete()
                            downloadButton.isEnabled = true
                        }
                        return
                    }
                    DownloadManager.STATUS_FAILED -> {
                        val reason = it.getInt(it.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON))
                        val usedMirror = preferences.getBoolean(KEY_USE_MIRROR, true)
                        preferences.edit().remove(KEY_DOWNLOAD_ID).apply()
                        modelFile.delete()
                        if (usedMirror) {
                            statusText.text = "国内镜像暂不可用（错误 " + reason + "），正在自动切换官方源…"
                            downloadButton.isEnabled = false
                            handler.postDelayed({ enqueueModelDownload(false) }, 1200L)
                        } else {
                            statusText.text = "镜像和官方源均下载失败（错误 " + reason + "）。请更换网络后重试。"
                            downloadButton.isEnabled = true
                        }
                        return
                    }
                    else -> handler.postDelayed(this, 1000L)
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildScreen()
        if (modelFile.isFile && modelFile.length() > MIN_MODEL_BYTES) {
            progressBar.progress = 100
            statusText.text = "DeepSeek 模型已准备完成。现在可以断网，在 Ae 中使用本地 AI 助手。"
            downloadButton.text = "模型已就绪"
            downloadButton.isEnabled = false
        } else {
            statusText.text = "尚未准备本地模型。可导入 AI 插件包 ZIP，也可直接下载约 1.02 GB 的 DeepSeek 模型。"
            handler.post(pollDownload)
        }
    }

    private fun buildScreen() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(24), dp(34), dp(24), dp(24))
        }
        root.addView(TextView(this).apply {
            text = "Ae DeepSeek AI 插件"
            textSize = 22f
            gravity = Gravity.CENTER
        }, matchWidth())
        root.addView(TextView(this).apply {
            text = "集成在 Ae 主程序内 · 本地推理 · 无云端 API"
            textSize = 14f
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, dp(18))
        }, matchWidth())
        statusText = TextView(this).apply {
            textSize = 15f
            gravity = Gravity.CENTER
        }
        root.addView(statusText, matchWidth())
        progressBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100
            progress = 0
        }
        root.addView(progressBar, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(10)).apply {
            topMargin = dp(20)
            bottomMargin = dp(20)
        })
        importButton = Button(this).apply {
            text = "导入 AI 插件包 ZIP"
            setOnClickListener { chooseModelPackage() }
        }
        root.addView(importButton, matchWidth())
        downloadButton = Button(this).apply {
            text = "直接下载 DeepSeek 本地模型（约 1.02 GB）"
            setOnClickListener { beginDownload() }
        }
        root.addView(downloadButton, matchWidth())
        root.addView(TextView(this).apply {
            text = "模型只下载一次并保存在本机应用私有目录。聊天推理在手机本地完成，不会把聊天内容发送到云端。"
            textSize = 13f
            gravity = Gravity.CENTER
            setPadding(0, dp(24), 0, 0)
        }, matchWidth())
        setContentView(root)
    }

    private fun chooseModelPackage() {
        val picker = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "*/*"
            putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("application/zip", "application/x-zip-compressed"))
            putExtra(Intent.EXTRA_TITLE, "选择 Ae DeepSeek AI 插件包")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        }
        startActivityForResult(picker, IMPORT_MODEL_REQUEST)
    }

    @Deprecated("Use the model package picker result")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != IMPORT_MODEL_REQUEST || resultCode != Activity.RESULT_OK) return
        val uri = data?.data ?: run {
            statusText.text = "没有取得所选文件，请重新选择。"
            return
        }
        importButton.isEnabled = false
        downloadButton.isEnabled = false
        progressBar.progress = 0
        statusText.text = "正在验证并导入 AI 插件包…"
        Thread({ importModelPackage(uri) }, "EffectCraftModelPackageImport").start()
    }

    private fun importModelPackage(uri: Uri) {
        val parent = modelFile.parentFile ?: run {
            runOnUiThread {
                statusText.text = "无法创建本地模型目录。"
                importButton.isEnabled = true
                downloadButton.isEnabled = true
            }
            return
        }
        val partial = File(parent, MODEL_FILE + ".importing")
        var completed = false
        try {
            if ((!parent.isDirectory && !parent.mkdirs()) || !parent.isDirectory) {
                throw IllegalStateException("无法创建应用内部模型目录。")
            }
            var manifest: JSONObject? = null
            var expectedSize = 0L
            var expectedSha256 = ""
            var copied = 0L
            var foundModel = false
            val digest = MessageDigest.getInstance("SHA-256")
            val buffer = ByteArray(1024 * 1024)
            val raw = contentResolver.openInputStream(uri)
                ?: throw IllegalStateException("无法读取所选 AI 插件包。")
            raw.use { input ->
                ZipInputStream(BufferedInputStream(input)).use { zip ->
                    var entry = zip.nextEntry
                    while (entry != null) {
                        when (entry.name) {
                            "plugin.json" -> {
                                val bytes = ByteArrayOutputStream()
                                val smallBuffer = ByteArray(4096)
                                var manifestBytes = 0
                                while (true) {
                                    val count = zip.read(smallBuffer)
                                    if (count < 0) break
                                    manifestBytes += count
                                    if (manifestBytes > 64 * 1024) {
                                        throw IllegalStateException("AI 插件包清单文件过大。")
                                    }
                                    bytes.write(smallBuffer, 0, count)
                                }
                                val parsed = JSONObject(bytes.toString("UTF-8"))
                                if (parsed.optString("format") != MODEL_PACKAGE_FORMAT ||
                                    parsed.optInt("format_version", 0) != 1 ||
                                    parsed.optString("id") != MODEL_PACKAGE_ID ||
                                    parsed.optString("model_file") != MODEL_FILE) {
                                    throw IllegalStateException("这不是 Ae DeepSeek AI 模型插件包。")
                                }
                                expectedSize = parsed.optLong("model_size_bytes", 0L)
                                expectedSha256 = parsed.optString("model_sha256", "")
                                if (expectedSize < MIN_MODEL_BYTES ||
                                    expectedSize > MAX_MODEL_BYTES ||
                                    !expectedSha256.matches(Regex("^[0-9a-fA-F]{64}$"))) {
                                    throw IllegalStateException("AI 插件包模型大小或校验信息不正确。")
                                }
                                manifest = parsed
                            }
                            MODEL_FILE, "models/" + MODEL_FILE -> {
                                if (manifest == null) {
                                    throw IllegalStateException("插件包清单缺失或顺序不正确。")
                                }
                                FileOutputStream(partial, false).use { output ->
                                    while (true) {
                                        val count = zip.read(buffer)
                                        if (count < 0) break
                                        copied += count.toLong()
                                        if (copied > MAX_MODEL_BYTES || copied > expectedSize) {
                                            throw IllegalStateException("模型文件超过清单声明的大小。")
                                        }
                                        output.write(buffer, 0, count)
                                        digest.update(buffer, 0, count)
                                        if (copied % (16L * 1024L * 1024L) < buffer.size) {
                                            val percent = ((copied * 100L) / expectedSize).toInt().coerceIn(0, 99)
                                            handler.post {
                                                progressBar.progress = percent
                                                statusText.text = "正在导入 DeepSeek 本地模型：$percent%（" +
                                                    formatBytes(copied) + " / " + formatBytes(expectedSize) + "）"
                                            }
                                        }
                                    }
                                }
                                foundModel = true
                            }
                            else -> {
                                // Ignore unrelated metadata files; never extract arbitrary paths.
                                while (zip.read(buffer) >= 0) { }
                            }
                        }
                        zip.closeEntry()
                        entry = zip.nextEntry
                    }
                }
            }
            if (manifest == null || !foundModel || copied < MIN_MODEL_BYTES) {
                throw IllegalStateException("插件包中没有完整的 DeepSeek 模型文件。")
            }
            if (copied != expectedSize) {
                throw IllegalStateException("模型文件大小与插件清单不一致。")
            }
            val actualSha = digest.digest().joinToString("") { "%02x".format(it) }
            if (!actualSha.equals(expectedSha256, ignoreCase = true)) {
                throw IllegalStateException("模型校验失败；文件可能已损坏，请重新下载插件包。")
            }
            if (modelFile.exists() && !modelFile.delete()) {
                throw IllegalStateException("无法替换旧模型文件，请先关闭正在使用的 AI 助手。")
            }
            if (!partial.renameTo(modelFile)) {
                partial.inputStream().use { source ->
                    FileOutputStream(modelFile).use { target -> source.copyTo(target) }
                }
                partial.delete()
            }
            completed = true
            handler.post {
                progressBar.progress = 100
                statusText.text = "DeepSeek 本地模型导入成功。现在可以断网使用 AI 助手。"
                downloadButton.text = "模型已就绪"
                downloadButton.isEnabled = false
                importButton.isEnabled = true
            }
        } catch (error: Exception) {
            partial.delete()
            handler.post {
                statusText.text = "AI 插件包导入失败：" + (error.message ?: error.javaClass.simpleName)
                importButton.isEnabled = true
                downloadButton.isEnabled = true
            }
        } finally {
            if (!completed) partial.delete()
        }
    }

    private fun beginDownload() {
        if (modelFile.isFile && modelFile.length() > MIN_MODEL_BYTES) {
            statusText.text = "模型已存在，可以离线使用。"
            downloadButton.isEnabled = false
            return
        }
        downloadButton.isEnabled = false
        progressBar.progress = 0
        statusText.text = "正在创建下载任务…"
        enqueueModelDownload(true)
    }

    private fun enqueueModelDownload(useMirror: Boolean) {
        val source = if (useMirror) MODEL_MIRROR_URL else MODEL_URL
        try {
            val request = DownloadManager.Request(Uri.parse(source))
                .setTitle("DeepSeek 本地模型")
                .setDescription(if (useMirror) "国内镜像优先 · Ae 离线模型（约 1.02 GB）" else "官方源备用 · Ae 离线模型（约 1.02 GB）")
                .setMimeType("application/octet-stream")
                .setAllowedOverMetered(true)
                .setAllowedOverRoaming(false)
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalFilesDir(this, Environment.DIRECTORY_DOWNLOADS, MODEL_FILE)
            val id = downloadManager.enqueue(request)
            preferences.edit()
                .putLong(KEY_DOWNLOAD_ID, id)
                .putBoolean(KEY_USE_MIRROR, useMirror)
                .apply()
            statusText.text = if (useMirror) "正在尝试国内镜像下载 DeepSeek 模型…" else "正在切换 Hugging Face 官方源下载…"
            handler.removeCallbacks(pollDownload)
            handler.post(pollDownload)
        } catch (error: Exception) {
            statusText.text = "无法开始下载：" + (error.message ?: "未知错误")
            downloadButton.isEnabled = true
        }
    }

    override fun onResume() {
        super.onResume()
        if (::statusText.isInitialized && !isModelReady()) {
            handler.removeCallbacks(pollDownload)
            handler.post(pollDownload)
        }
    }

    override fun onDestroy() {
        handler.removeCallbacks(pollDownload)
        super.onDestroy()
    }

    private fun isModelReady() = modelFile.isFile && modelFile.length() > MIN_MODEL_BYTES
    private fun matchWidth() = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun formatBytes(value: Long): String = if (value >= 1024L * 1024L * 1024L) {
        "%.2f GB".format(value.toDouble() / (1024.0 * 1024.0 * 1024.0))
    } else {
        "%.0f MB".format(value.toDouble() / (1024.0 * 1024.0))
    }

    companion object {
        private const val IMPORT_MODEL_REQUEST = 0x5D31
        private const val MODEL_PACKAGE_FORMAT = "effectcraft-ai-model-plugin"
        private const val MODEL_PACKAGE_ID = "com.artcraft.effectcraft.deepseek.model"
        private const val MAX_MODEL_BYTES = 2L * 1024L * 1024L * 1024L
        private const val MODEL_FILE = "DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf"
        private const val KEY_DOWNLOAD_ID = "model_download_id"
        private const val KEY_USE_MIRROR = "model_download_use_mirror"
        private const val MIN_MODEL_BYTES = 500L * 1024L * 1024L
        private const val MODEL_MIRROR_URL = "https://hf-mirror.com/bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf?download=true"
        private const val MODEL_URL = "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf?download=true"
    }
}
