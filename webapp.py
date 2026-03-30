from __future__ import annotations

import os
from pathlib import Path
from threading import Thread
import uuid

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from app.services.document_parser import SUPPORTED_EXTENSIONS
from app.services.job_manager import JobManager
from app.services.workflow import TopicPptWorkflow

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_ROOT = BASE_DIR / "storage" / "uploads"
OUTPUT_ROOT = BASE_DIR / "storage" / "outputs"

UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
(UPLOAD_ROOT / ".gitkeep").touch(exist_ok=True)
(OUTPUT_ROOT / ".gitkeep").touch(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
job_manager = JobManager()


@app.get("/")
def index():
    return render_template("index.html")


@app.errorhandler(RequestEntityTooLarge)
def handle_large_upload(_error):
    return jsonify({"error": "上传文件总大小超出限制，当前上限约为 200MB。请减少文件数量或分批上传。"}), 413


@app.post("/api/jobs")
def create_job():
    topic = (request.form.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "请输入主题。"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "请至少上传一个 PDF 或 Word 文件。"}), 400

    job_id = uuid.uuid4().hex[:12]
    job_upload_dir = UPLOAD_ROOT / job_id
    job_output_dir = OUTPUT_ROOT / job_id
    job_upload_dir.mkdir(parents=True, exist_ok=True)
    job_output_dir.mkdir(parents=True, exist_ok=True)
    try:
        saved_files = _save_uploaded_files(files, job_upload_dir)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not saved_files:
        return jsonify({"error": "未成功保存任何上传文件。"}), 400

    job_manager.create(
        job_id,
        status="queued",
        progress=4,
        stage="queued",
        message=f"文件上传完成，共 {len(saved_files)} 个文件，等待开始处理。",
    )
    worker = Thread(
        target=_run_background_job,
        args=(job_id, topic, saved_files, job_upload_dir, job_output_dir),
        daemon=True,
    )
    worker.start()
    return jsonify({"job_id": job_id, "status": "queued"})


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    job = job_manager.get(job_id)
    if job is None:
        return jsonify({"error": "任务不存在。"}), 404
    return jsonify(job)


@app.post("/api/generate")
def generate():
    topic = (request.form.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "请输入主题。"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "请至少上传一个 PDF 或 Word 文件。"}), 400

    job_id = uuid.uuid4().hex[:12]
    job_upload_dir = UPLOAD_ROOT / job_id
    job_output_dir = OUTPUT_ROOT / job_id
    job_upload_dir.mkdir(parents=True, exist_ok=True)
    job_output_dir.mkdir(parents=True, exist_ok=True)
    try:
        saved_files = _save_uploaded_files(files, job_upload_dir)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not saved_files:
        return jsonify({"error": "未成功保存任何上传文件。"}), 400

    workflow = TopicPptWorkflow(job_upload_dir, job_output_dir)
    try:
        result = workflow.run(topic, saved_files)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify(_serialize_result(job_id, result))


@app.get("/download/<job_id>/<path:filename>")
def download(job_id: str, filename: str):
    directory = OUTPUT_ROOT / job_id
    return send_from_directory(directory, filename, as_attachment=True)


def _run_background_job(
    job_id: str,
    topic: str,
    saved_files: list[Path],
    job_upload_dir: Path,
    job_output_dir: Path,
) -> None:
    workflow = TopicPptWorkflow(job_upload_dir, job_output_dir)
    job_manager.update(job_id, status="running", progress=6, stage="queued", message="后台任务已启动。")

    try:
        result = workflow.run(
            topic,
            saved_files,
            progress_callback=lambda progress, stage, message: job_manager.update(
                job_id,
                status="running",
                progress=progress,
                stage=stage,
                message=message,
            ),
        )
    except Exception as exc:
        job_manager.update(
            job_id,
            status="error",
            progress=100,
            stage="error",
            message=f"处理失败: {exc}",
            error=str(exc),
        )
        return

    job_manager.update(
        job_id,
        status="completed",
        progress=100,
        stage="completed",
        message="PPT 已生成完成。",
        result=_serialize_result(job_id, result),
        error=None,
    )


def _serialize_result(job_id: str, result: dict) -> dict:
    ppt_path = Path(result["ppt_path"])
    return {
        "message": "PPT 已生成完成。",
        "download_url": f"/download/{job_id}/{ppt_path.name}",
        "filename": ppt_path.name,
        "documents": result["documents"],
        "summary": result["summary"],
        "warnings": result["warnings"],
    }


def _save_uploaded_files(files, job_upload_dir: Path) -> list[Path]:
    saved_files: list[Path] = []
    for storage in files:
        if not storage.filename:
            continue
        original_name = Path(storage.filename).name
        extension = Path(original_name).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型: {storage.filename}")
        filename = _build_safe_filename(original_name, len(saved_files) + 1, job_upload_dir)
        target = job_upload_dir / filename
        storage.save(target)
        saved_files.append(target)
    return saved_files


def _build_safe_filename(original_name: str, index: int, directory: Path) -> str:
    original_path = Path(original_name)
    extension = original_path.suffix.lower()
    stem = secure_filename(original_path.stem)
    if not stem:
        stem = f"upload_{index}"

    candidate = f"{stem}{extension}"
    counter = 2
    while (directory / candidate).exists():
        candidate = f"{stem}_{counter}{extension}"
        counter += 1
    return candidate


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
