package com.artcraft.effectcraft.aiassistant;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.StatFs;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final int PICK_MODEL = 7421;
    private static final long MIN_BYTES = 950_000_000L;
    private static final long MAX_BYTES = 1_100_000_000L;
    private static final String MODEL_NAME = "DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf";
    private static final String MODEL_URL = "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf?download=true";

    static { System.loadLibrary("effectcraft_ai"); }

    private static native String nativeGenerate(String modelPath, String question);
    private static native void nativeRelease();

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final ArrayList<String> history = new ArrayList<>();
    private File modelFile;
    private TextView status, transcript;
    private ScrollView scroll;
    private EditText input;
    private Button send, download, importModel;
    private boolean busy;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        modelFile = new File(new File(getFilesDir(), "models"), MODEL_NAME);
        createUi();
        addMessage("AI", "你好！我是 EffectCraft 本地 AI 助手。首次使用请下载或导入 DeepSeek GGUF 模型。模型放在插件私有目录，下载完成后可离线对话。");
        refreshStatus();
    }

    private int dp(int px) { return Math.round(px * getResources().getDisplayMetrics().density); }

    private void createUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(14), dp(12), dp(14), dp(10));
        root.setBackgroundColor(0xFFF4F6FA);

        TextView title = new TextView(this);
        title.setText("EffectCraft AI 助手");
        title.setTextSize(22);
        title.setTextColor(0xFF182230);
        root.addView(title, new LinearLayout.LayoutParams(-1, -2));

        status = new TextView(this);
        status.setTextSize(13);
        status.setTextColor(0xFF526174);
        status.setPadding(0, dp(6), 0, dp(6));
        root.addView(status, new LinearLayout.LayoutParams(-1, -2));

        LinearLayout modelButtons = new LinearLayout(this);
        download = new Button(this);
        download.setText("下载模型");
        importModel = new Button(this);
        importModel.setText("导入 GGUF");
        modelButtons.addView(download, new LinearLayout.LayoutParams(0, dp(48), 1));
        LinearLayout.LayoutParams second = new LinearLayout.LayoutParams(0, dp(48), 1);
        second.leftMargin = dp(6);
        modelButtons.addView(importModel, second);
        root.addView(modelButtons);

        scroll = new ScrollView(this);
        transcript = new TextView(this);
        transcript.setTextSize(15);
        transcript.setTextColor(0xFF1F2937);
        transcript.setPadding(dp(10), dp(10), dp(10), dp(10));
        transcript.setBackgroundColor(0xFFFFFFFF);
        scroll.addView(transcript);
        LinearLayout.LayoutParams chatParams = new LinearLayout.LayoutParams(-1, 0, 1);
        chatParams.topMargin = dp(8);
        chatParams.bottomMargin = dp(8);
        root.addView(scroll, chatParams);

        input = new EditText(this);
        input.setHint("输入 EffectCraft 操作问题…");
        input.setMinLines(2);
        input.setMaxLines(4);
        input.setGravity(Gravity.TOP | Gravity.START);
        root.addView(input, new LinearLayout.LayoutParams(-1, -2));

        send = new Button(this);
        send.setText("发送");
        root.addView(send, new LinearLayout.LayoutParams(-1, dp(48)));
        setContentView(root);

        download.setOnClickListener(v -> downloadModel());
        importModel.setOnClickListener(v -> pickModel());
        send.setOnClickListener(v -> sendQuestion());
    }

    private void pickModel() {
        if (busy) return;
        Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        picker.addCategory(Intent.CATEGORY_OPENABLE);
        picker.setType("*/*");
        picker.putExtra(Intent.EXTRA_TITLE, "选择 DeepSeek GGUF 模型文件");
        startActivityForResult(picker, PICK_MODEL);
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == PICK_MODEL && result == RESULT_OK && data != null && data.getData() != null) {
            setBusy(true);
            setStatus("正在导入并校验模型文件…");
            Uri uri = data.getData();
            worker.execute(() -> copyImportedModel(uri));
        }
    }

    private void downloadModel() {
        if (busy) return;
        StatFs fs = new StatFs(getFilesDir().getAbsolutePath());
        if (fs.getAvailableBytes() < 1_200_000_000L) {
            setStatus("可用空间不足，请先清理至少约 1.2GB 空间。");
            return;
        }
        setBusy(true);
        setStatus("正在连接模型下载源…");
        worker.execute(this::performDownload);
    }

    private void performDownload() {
        File dir = modelFile.getParentFile();
        if (dir == null || (!dir.exists() && !dir.mkdirs())) {
            finishTask("无法创建模型目录。");
            return;
        }
        File part = new File(dir, MODEL_NAME + ".part");
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(MODEL_URL).openConnection();
            connection.setConnectTimeout(30000);
            connection.setReadTimeout(120000);
            connection.setInstanceFollowRedirects(true);
            connection.setRequestProperty("User-Agent", "EffectCraft-AI-Plugin/0.1");
            int code = connection.getResponseCode();
            if (code != HttpURLConnection.HTTP_OK) throw new IllegalStateException("下载源 HTTP " + code);
            long total = connection.getContentLengthLong();
            long count = 0, lastUpdate = 0;
            byte[] buffer = new byte[1024 * 1024];
            try (InputStream in = new BufferedInputStream(connection.getInputStream());
                 FileOutputStream fos = new FileOutputStream(part, false);
                 BufferedOutputStream out = new BufferedOutputStream(fos)) {
                int n;
                while ((n = in.read(buffer)) != -1) {
                    out.write(buffer, 0, n);
                    count += n;
                    if (count - lastUpdate >= 8L * 1024L * 1024L) {
                        lastUpdate = count;
                        long current = count;
                        handler.post(() -> setStatus(progress(current, total)));
                    }
                }
                out.flush();
                fos.getFD().sync();
            }
            verifyModel(part);
            replaceModel(part);
            finishTask("模型下载并校验完成，可以离线对话。");
        } catch (Exception error) {
            part.delete();
            finishTask("模型下载失败：" + message(error) + "。可改用“导入 GGUF”。");
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private String progress(long current, long total) {
        String amount = String.format(java.util.Locale.US, "%.2f GB", current / 1_000_000_000.0);
        return total > 0 ? "模型下载中：" + Math.min(100, current * 100 / total) + "%（" + amount + "）" : "模型下载中：" + amount;
    }

    private void copyImportedModel(Uri uri) {
        File dir = modelFile.getParentFile();
        if (dir == null || (!dir.exists() && !dir.mkdirs())) {
            finishTask("无法创建模型目录。");
            return;
        }
        File part = new File(dir, MODEL_NAME + ".import");
        try {
            InputStream raw = getContentResolver().openInputStream(uri);
            if (raw == null) throw new IllegalStateException("无法读取所选文件。");
            try (InputStream in = new BufferedInputStream(raw);
                 FileOutputStream fos = new FileOutputStream(part, false);
                 BufferedOutputStream out = new BufferedOutputStream(fos)) {
                byte[] buffer = new byte[1024 * 1024];
                long count = 0;
                int n;
                while ((n = in.read(buffer)) != -1) {
                    count += n;
                    if (count > MAX_BYTES) throw new IllegalStateException("文件过大，不是目标模型。");
                    out.write(buffer, 0, n);
                    if (count % (16L * 1024L * 1024L) < buffer.length) {
                        long current = count;
                        handler.post(() -> setStatus(String.format(java.util.Locale.US, "正在导入：%.2f GB", current / 1_000_000_000.0)));
                    }
                }
                out.flush();
                fos.getFD().sync();
            }
            verifyModel(part);
            replaceModel(part);
            finishTask("模型导入并校验完成，可以离线对话。");
        } catch (Exception error) {
            part.delete();
            finishTask("模型导入失败：" + message(error));
        }
    }

    private void verifyModel(File file) throws Exception {
        long size = file.length();
        if (size < MIN_BYTES || size > MAX_BYTES) throw new IllegalStateException("模型文件大小不符合预期（约 1GB）。");
        byte[] magic = new byte[4];
        try (RandomAccessFile raf = new RandomAccessFile(file, "r")) { raf.readFully(magic); }
        if (magic[0] != 'G' || magic[1] != 'G' || magic[2] != 'U' || magic[3] != 'F') {
            throw new IllegalStateException("文件头不是 GGUF 格式。");
        }
    }

    private void replaceModel(File part) {
        if (modelFile.exists() && !modelFile.delete()) throw new IllegalStateException("无法替换旧模型文件。");
        if (!part.renameTo(modelFile)) throw new IllegalStateException("无法保存模型文件。");
    }

    private void sendQuestion() {
        if (busy) return;
        if (!modelFile.isFile()) { setStatus("请先下载或导入 DeepSeek GGUF 模型。"); return; }
        String question = input.getText().toString().trim();
        if (question.isEmpty()) return;
        input.setText("");
        addMessage("我", question);
        history.add("用户：" + question);
        while (history.size() > 10) history.remove(0);
        String prompt = String.join("\n", history) + "\nAI：";
        setBusy(true);
        setStatus("正在加载或运行本地模型，首次加载可能较慢…");
        worker.execute(() -> {
            String result;
            try { result = nativeGenerate(modelFile.getAbsolutePath(), prompt); }
            catch (Throwable error) { result = "ERROR: " + message(error); }
            final String answer = result == null ? "ERROR: 本地推理无返回内容。" : result;
            handler.post(() -> {
                String shown = answer.startsWith("ERROR: ") ? answer.substring(7) : answer;
                addMessage("AI", shown);
                history.add("AI：" + shown);
                while (history.size() > 10) history.remove(0);
                setBusy(false);
                setStatus(answer.startsWith("ERROR: ") ? "推理失败，请检查模型文件或设备内存。" : "本地离线推理完成。");
            });
        });
    }

    private void addMessage(String role, String text) {
        transcript.append(role + "：\n" + text + "\n\n");
        scroll.post(() -> scroll.fullScroll(ScrollView.FOCUS_DOWN));
    }

    private void refreshStatus() {
        if (modelFile.isFile()) {
            try { verifyModel(modelFile); setStatus("DeepSeek 模型已就绪 · 本地离线模式"); return; }
            catch (Exception ignored) { modelFile.delete(); }
        }
        setStatus("尚未安装模型：点击“下载模型”或“导入 GGUF”。");
    }

    private void setBusy(boolean value) {
        busy = value;
        handler.post(() -> {
            if (download != null) download.setEnabled(!value);
            if (importModel != null) importModel.setEnabled(!value);
            if (send != null) send.setEnabled(!value);
        });
    }

    private void finishTask(String message) {
        handler.post(() -> {
            setBusy(false);
            if (modelFile.isFile()) {
                try { verifyModel(modelFile); setStatus("DeepSeek 模型已就绪 · 本地离线模式"); return; }
                catch (Exception ignored) { modelFile.delete(); }
            }
            setStatus(message);
        });
    }

    private void setStatus(String text) { handler.post(() -> status.setText(text)); }
    private static String message(Throwable error) {
        String text = error.getMessage();
        return text == null || text.trim().isEmpty() ? error.getClass().getSimpleName() : text;
    }

    @Override protected void onDestroy() {
        try { worker.execute(MainActivity::nativeRelease); worker.shutdown(); }
        catch (RuntimeException ignored) {}
        super.onDestroy();
    }
}
