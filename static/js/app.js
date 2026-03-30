const form = document.getElementById("generate-form");
const fileInput = document.getElementById("files");
const fileList = document.getElementById("file-list");
const submitBtn = document.getElementById("submit-btn");
const statusCard = document.getElementById("status-card");
const statusPill = document.getElementById("status-pill");
const statusText = document.getElementById("status-text");
const progressStage = document.getElementById("progress-stage");
const progressPercent = document.getElementById("progress-percent");
const progressFill = document.getElementById("progress-fill");
const downloadLink = document.getElementById("download-link");
const summaryList = document.getElementById("summary-list");
const documentList = document.getElementById("document-list");
const warningBox = document.getElementById("warning-box");

let activeJobId = null;
let pollTimer = null;

const STAGE_LABELS = {
    queued: "等待后台开始",
    upload: "上传已完成",
    parsing: "正在解析文档",
    analyzing: "正在分析主题内容",
    generating: "正在生成 PPT",
    completed: "处理完成",
    error: "处理失败"
};

fileInput.addEventListener("change", () => {
    const files = Array.from(fileInput.files || []);
    if (!files.length) {
        fileList.textContent = "暂未选择文件";
        fileList.classList.add("empty");
        return;
    }

    fileList.classList.remove("empty");
    fileList.innerHTML = files
        .map((file, index) => `${index + 1}. ${file.name} (${Math.round(file.size / 1024)} KB)`)
        .join("<br>");
});

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const topic = document.getElementById("topic").value.trim();
    const files = fileInput.files;

    if (!topic) {
        showState("请先输入主题。", "缺少主题");
        setProgress(0, "queued");
        return;
    }
    if (!files || !files.length) {
        showState("请先上传至少一个 PDF 或 Word 文件。", "缺少文件");
        setProgress(0, "queued");
        return;
    }

    const formData = new FormData();
    formData.append("topic", topic);
    Array.from(files).forEach((file) => formData.append("files", file));

    stopPolling();
    activeJobId = null;
    submitBtn.disabled = true;
    submitBtn.textContent = "正在提交任务...";
    showState("文件上传后会自动进入解析和生成流程。", "提交中");
    setProgress(2, "queued");
    downloadLink.classList.add("hidden");
    warningBox.classList.add("hidden");
    summaryList.innerHTML = "";
    documentList.innerHTML = "";

    try {
        const response = await fetch("/api/jobs", {
            method: "POST",
            body: formData
        });
        const payload = await readJson(response);

        if (!response.ok) {
            throw new Error(payload.error || "任务创建失败。");
        }

        activeJobId = payload.job_id;
        showState("任务已创建，后台开始处理。", "处理中");
        setProgress(4, "queued");
        submitBtn.textContent = "正在处理中...";
        startPolling(activeJobId);
    } catch (error) {
        showState(error.message || "处理失败，请重试。", "失败");
        setProgress(100, "error");
        submitBtn.disabled = false;
        submitBtn.textContent = "生成 PPT";
    }
});

function startPolling(jobId) {
    stopPolling();
    pollJob(jobId);
    pollTimer = window.setInterval(() => pollJob(jobId), 1200);
}

function stopPolling() {
    if (pollTimer) {
        window.clearInterval(pollTimer);
        pollTimer = null;
    }
}

async function pollJob(jobId) {
    try {
        const response = await fetch(`/api/jobs/${jobId}`, { cache: "no-store" });
        const payload = await readJson(response);

        if (!response.ok) {
            throw new Error(payload.error || "无法获取任务状态。");
        }

        setProgress(payload.progress || 0, payload.stage || "queued");
        showState(payload.message || "正在处理中。", statusLabel(payload.status || "running"));

        if (payload.status === "completed") {
            stopPolling();
            finalizeSuccess(payload.result || {});
            return;
        }

        if (payload.status === "error") {
            stopPolling();
            showState(payload.message || payload.error || "处理失败。", "失败");
            setProgress(100, "error");
            submitBtn.disabled = false;
            submitBtn.textContent = "生成 PPT";
        }
    } catch (error) {
        stopPolling();
        showState(error.message || "轮询任务状态失败。", "失败");
        setProgress(100, "error");
        submitBtn.disabled = false;
        submitBtn.textContent = "生成 PPT";
    }
}

function finalizeSuccess(result) {
    showState(result.message || "PPT 已生成。", "已完成");
    setProgress(100, "completed");
    downloadLink.href = result.download_url;
    downloadLink.download = result.filename;
    downloadLink.classList.remove("hidden");
    renderSummary(result.summary || []);
    renderDocuments(result.documents || []);
    renderWarnings(result.warnings || []);
    submitBtn.disabled = false;
    submitBtn.textContent = "重新生成 PPT";
}

function showState(message, label) {
    statusCard.classList.remove("hidden");
    statusPill.textContent = label;
    statusText.textContent = message;
}

function setProgress(progress, stage) {
    const value = Math.max(0, Math.min(100, Number(progress) || 0));
    progressFill.style.width = `${value}%`;
    progressPercent.textContent = `${value}%`;
    progressStage.textContent = STAGE_LABELS[stage] || "处理中";
}

function statusLabel(status) {
    const map = {
        queued: "排队中",
        running: "处理中",
        completed: "已完成",
        error: "失败"
    };
    return map[status] || "处理中";
}

function renderSummary(items) {
    summaryList.innerHTML = "";
    items.forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item;
        summaryList.appendChild(li);
    });
}

function renderDocuments(documents) {
    documentList.innerHTML = "";
    documents.forEach((docItem) => {
        const card = document.createElement("article");
        card.className = "doc-card";
        const bullets = (docItem.bullets || [])
            .map((bullet) => `<li>${escapeHtml(bullet)}</li>`)
            .join("");

        card.innerHTML = `
            <h4>${escapeHtml(docItem.title || docItem.filename)}</h4>
            <div class="doc-meta">
                作者：${escapeHtml(docItem.authors || "未识别")}<br>
                文件：${escapeHtml(docItem.filename)}<br>
                图片：${docItem.images} 张 | 相关度：${docItem.score}<br>
                概述：${escapeHtml(docItem.overview || "暂无概述")}
            </div>
            <ul class="doc-bullets">${bullets}</ul>
        `;
        documentList.appendChild(card);
    });
}

function renderWarnings(warnings) {
    if (!warnings.length) {
        warningBox.classList.add("hidden");
        warningBox.textContent = "";
        return;
    }
    warningBox.classList.remove("hidden");
    warningBox.innerHTML = warnings.map((item) => `• ${escapeHtml(item)}`).join("<br>");
}

async function readJson(response) {
    try {
        return await response.json();
    } catch (_error) {
        return {};
    }
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}
