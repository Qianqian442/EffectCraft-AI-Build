package com.artcraft.effectcraft.aiassistant

import android.app.Activity
import android.app.DownloadManager
import android.content.Context
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
import java.security.MessageDigest
import java.util.concurrent.Executors
import java.util.zip.ZipInputStream
import org.json.JSONObject

class PluginManagerActivity : Activity() {
    private lateinit var statusText: TextView
    private lateinit var progressBar: ProgressBar
    private lateinit var downloadButton: Button
    private lateinit var importButton: Button
    private val handler = Handler(Looper.getMainLooper())
    private val preferences by lazy { getSharedPreferences("deepseek_plugin", Context.MODE_PRIVATE) }
    private val modelDirectory: File
        get() = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: filesDir
    private val modelFile: File
        get() = File(modelDirectory, MODEL_FILE)
    private val previousModelFile: File
        get() = File(modelDirectory, MODEL_FILE + ".previous")
    private val downloadManager by lazy { getSystemService(DownloadManager::class.java) }
    private val importExecutor = Executors.newSingleThreadExecutor()
    private var importingPackage = false

    companion object {
        private const val MODEL_FILE = "DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf"
        private const val KEY_DOWNLOAD_ID = "model_download_id"
        private const val KEY_USE_MIRROR = "model_download_use_mirror"
        private const val MIN_MODEL_BYTES = 500L * 1024L * 1024L
        private const val MAX_MODEL_BYTES = 2L * 1024L * 1024L * 1024L
        private const val MODEL_PACKAGE_REQUEST = 0xAE21
        private const val MODEL_PACKAGE_FORMAT = "ae-ai-model-package"
        private const val MODEL_PACKAGE_ID = "ae.deepseek.r1.distill.qwen.1.5b.iq4_xs"
        private const val MODEL_MIRROR_URL = "https://hf-mirror.com/bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf?download=true"
        private const val MODEL_URL = "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf?download=true"
    }

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
        // Recover a previously verified model if Android stopped the app during replacement.
        if (!modelFile.exists() && previousModelFile.isFile) previousModelFile.renameTo(modelFile)
        else if (modelFile.exists() && previousModelFile.exists()) previousModelFile.delete()
        buildScreen()
        if (modelFile.isFile && modelFile.length() > MIN_MODEL_BYTES) {
            progressBar.progress = 100
            statusText.text = "DeepSeek 模型已准备完成。现在可以断网，在 Ae 中使用本地 AI 助手。"
            downloadButton.text = "模型已就绪"
            downloadButton.isEnabled = false
        } else {
            statusText.text = "首次使用请导入 Ae AI 模型包 ZIP；如暂时没有 ZIP，也可使用下面的网络下载备用入口。导入或下载完成后可离线推理。"
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
            text = "Ae DeepSeek AI 模型管理"
            textSize = 22f
            gravity = Gravity.CENTER
        }, matchWidth())
        root.addView(TextView(this).apply {
            text = "内置本地推理引擎 · ARM64 · 导入模型包后可离线运行"
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
            text = "导入 Ae AI 模型包 ZIP（约 1.02 GB）"
            setOnClickListener { chooseModelPackage() }
        }
        root.addView(importButton, matchWidth())

        downloadButton = Button(this).apply {
            text = "下载 DeepSeek 本地模型（约 1.02 GB）"
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
        if (importingPackage) return
        val intent = android.content.Intent(android.content.Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(android.content.Intent.CATEGORY_OPENABLE)
            type = "application/zip"
            putExtra(android.content.Intent.EXTRA_MIME_TYPES, arrayOf("application/zip", "application/octet-stream"))
        }
        try {
            startActivityForResult(intent, MODEL_PACKAGE_REQUEST)
        } catch (error: Exception) {
            statusText.text = "无法打开文件选择器：" + (error.message ?: "未知错误")
        }
    }

    @Deprecated("Use the file picker result callback for the imported AI model package.")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: android.content.Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != MODEL_PACKAGE_REQUEST || resultCode != Activity.RESULT_OK) return
        val uri = data?.data ?: run {
            statusText.text = "没有选择 AI 模型包。"
            return
        }
        if (importingPackage) return
        importingPackage = true
        importButton.isEnabled = false
        downloadButton.isEnabled = false
        progressBar.progress = 0
        statusText.text = "正在校验并导入 AI 模型包…"
        importExecutor.execute {
            val tempFile = File(modelDirectory, MODEL_FILE + ".importing")
            try {
                tempFile.parentFile?.mkdirs()
                val digest = MessageDigest.getInstance("SHA-256")
                var manifest: JSONObject? = null
                var copied = 0L
                var expectedBytes = -1L
                var expectedHash = ""
                var modelFound = false
                val input = contentResolver.openInputStream(uri)
                    ?: throw IllegalStateException("无法读取所选 ZIP 文件。")
                input.use { raw ->
                    ZipInputStream(raw).use { zip ->
                        var entry = zip.nextEntry
                        while (entry != null) {
                            if (entry.isDirectory) {
                                zip.closeEntry()
                                entry = zip.nextEntry
                                continue
                            }
                            when (entry.name) {
                                "ai-model.json" -> {
                                    if (manifest != null) throw IllegalArgumentException("模型包包含重复的 ai-model.json。")
                                    val bytes = zip.readBytes()
                                    if (bytes.size > 64 * 1024) throw IllegalArgumentException("AI 模型包清单文件过大。")
                                    val parsed = JSONObject(String(bytes, Charsets.UTF_8))
                                    if (parsed.optString("format") != MODEL_PACKAGE_FORMAT ||
                                        parsed.optInt("format_version", -1) != 1 ||
                                        parsed.optString("id") != MODEL_PACKAGE_ID ||
                                        parsed.optString("model_file") != MODEL_FILE) {
                                        throw IllegalArgumentException("这不是 Ae 支持的 DeepSeek AI 模型包。")
                                    }
                                    expectedBytes = parsed.optLong("size_bytes", -1L)
                                    expectedHash = parsed.optString("sha256").lowercase()
                                    if (expectedBytes < MIN_MODEL_BYTES || expectedBytes > MAX_MODEL_BYTES ||
                                        !expectedHash.matches(Regex("[0-9a-f]{64}"))) {
                                        throw IllegalArgumentException("AI 模型包大小或 SHA-256 清单无效。")
                                    }
                                    manifest = parsed
                                }
                                MODEL_FILE -> {
                                    if (manifest == null) throw IllegalArgumentException("模型包清单必须先于模型文件。")
                                    if (modelFound) throw IllegalArgumentException("模型包包含重复模型文件。")
                                    modelFound = true
                                    tempFile.outputStream().buffered().use { output ->
                                        val buffer = ByteArray(1024 * 1024)
                                        while (true) {
                                            val count = zip.read(buffer)
                                            if (count < 0) break
                                            copied += count
                                            if (copied > expectedBytes || copied > MAX_MODEL_BYTES) {
                                                throw IllegalArgumentException("模型文件超过清单声明的大小。")
                                            }
                                            digest.update(buffer, 0, count)
                                            output.write(buffer, 0, count)
                                            if (copied % (16L * 1024L * 1024L) < buffer.size) {
                                                val percent = ((copied * 100L) / expectedBytes).toInt().coerceIn(0, 99)
                                                runOnUiThread {
                                                    progressBar.progress = percent
                                                    statusText.text = "正在导入 DeepSeek 模型：${percent}%（${formatBytes(copied)} / ${formatBytes(expectedBytes)}）"
                                                }
                                            }
                                        }
                                        output.flush()
                                    }
                                    val actualHash = digest.digest().joinToString("") { "%02x".format(it) }
                                    if (copied != expectedBytes || actualHash != expectedHash) {
                                        throw IllegalArgumentException("模型文件大小或 SHA-256 校验失败，未覆盖已有模型。")
                                    }
                                }
                                else -> throw IllegalArgumentException("模型包包含不支持的文件：${entry.name}")
                            }
                            zip.closeEntry()
                            entry = zip.nextEntry
                        }
                    }
                }
                if (manifest == null || !modelFound || !tempFile.isFile || tempFile.length() < MIN_MODEL_BYTES) {
                    throw IllegalArgumentException("AI 模型包不完整，未找到有效的 DeepSeek 模型文件。")
                }
                val backupFile = previousModelFile
                if (backupFile.exists() && !backupFile.delete()) {
                    throw IllegalStateException("无法清理上次导入留下的临时备份；旧模型未改动。")
                }
                val hadPreviousModel = modelFile.exists()
                if (hadPreviousModel && !modelFile.renameTo(backupFile)) {
                    throw IllegalStateException("无法备份现有模型；原模型保持不变。")
                }
                if (!tempFile.renameTo(modelFile)) {
                    if (hadPreviousModel) backupFile.renameTo(modelFile)
                    throw IllegalStateException("模型已校验，但写入应用目录失败；已尝试恢复原模型。请检查可用存储空间。")
                }
                if (hadPreviousModel) backupFile.delete()
                runOnUiThread {
                    importingPackage = false
                    progressBar.progress = 100
                    statusText.text = "Ae DeepSeek AI 模型导入成功。现在可以离线使用。"
                    importButton.text = "模型已导入"
                    downloadButton.text = "模型已就绪"
                    importButton.isEnabled = true
                    downloadButton.isEnabled = false
                }
            } catch (error: Exception) {
                tempFile.delete()
                runOnUiThread {
                    importingPackage = false
                    statusText.text = "导入失败：" + (error.message ?: error.javaClass.simpleName)
                    importButton.isEnabled = true
                    downloadButton.isEnabled = true
                }
            }
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
        importExecutor.shutdownNow()
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


}
