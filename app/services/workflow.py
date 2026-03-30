from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from app.services.document_parser import DocumentParseError, parse_document
from app.services.ppt_generator import build_ppt
from app.services.topic_extractor import analyze_documents, build_global_summary


class TopicPptWorkflow:
    def __init__(self, job_root: Path, output_root: Path) -> None:
        self.job_root = job_root
        self.asset_root = job_root / "assets"
        self.output_root = output_root
        self.asset_root.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        topic: str,
        files: list[Path],
        progress_callback: Callable[[int, str, str], None] | None = None,
    ) -> dict:
        parsed_documents = []
        warnings: list[str] = []
        total_files = max(len(files), 1)

        _report_progress(progress_callback, 8, "upload", "文件已接收，准备解析文档。")

        for index, file_path in enumerate(files, start=1):
            per_file_asset_dir = self.asset_root / file_path.stem
            _report_progress(
                progress_callback,
                12 + int(((index - 1) / total_files) * 48),
                "parsing",
                f"正在解析第 {index}/{total_files} 个文件: {file_path.name}",
            )
            try:
                parsed_documents.append(parse_document(file_path, per_file_asset_dir))
            except DocumentParseError as exc:
                warnings.append(f"{file_path.name}: {exc}")
            _report_progress(
                progress_callback,
                12 + int((index / total_files) * 48),
                "parsing",
                f"已完成第 {index}/{total_files} 个文件解析。",
            )

        if not parsed_documents:
            raise RuntimeError("所有文件都解析失败，无法生成 PPT。")

        _report_progress(progress_callback, 66, "analyzing", "正在计算主题相关内容并整理摘要。")
        analyzed_documents = analyze_documents(parsed_documents, topic)
        global_summary = build_global_summary(topic, analyzed_documents)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = self.output_root / f"topic_ppt_{timestamp}.pptx"
        _report_progress(progress_callback, 78, "generating", "正在生成 PPT 页面与排版。")
        ppt_warnings = build_ppt(
            topic,
            analyzed_documents,
            global_summary,
            output_path,
            progress_callback=lambda progress, message: _report_progress(
                progress_callback, progress, "generating", message
            ),
        )
        _report_progress(progress_callback, 100, "completed", "PPT 已生成完成。")

        return {
            "ppt_path": output_path,
            "warnings": warnings + ppt_warnings,
            "documents": [
                {
                    "filename": item["document"].filename,
                    "title": item["document"].title,
                    "authors": item["document"].authors,
                    "images": len(item["document"].images),
                    "score": item["score"],
                    "overview": item["overview"],
                    "bullets": item["bullets"],
                }
                for item in analyzed_documents
            ],
            "summary": global_summary,
        }


def _report_progress(
    callback: Callable[[int, str, str], None] | None,
    progress: int,
    stage: str,
    message: str,
) -> None:
    if callback is None:
        return
    callback(max(0, min(progress, 100)), stage, message)
