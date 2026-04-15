from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.agent_utils import get_latest_user_message
from ..core.models import ExcelSheet, FilenameSuggestion, PowerPointSlide
from ..core.llm_api import call_llm

if TYPE_CHECKING:
    from ..runtime import AgentRuntime


TEXT_FILE_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".html",
    ".htm",
    ".xml",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".py",
    ".java",
    ".css",
    ".scss",
    ".sql",
    ".yml",
    ".yaml",
    ".log",
    ".ini",
    ".toml",
}

KNOWN_FILE_SUFFIXES = TEXT_FILE_EXTENSIONS | {".docx", ".xlsx", ".pdf", ".pptx"}
SUPPORTED_CONVERSION_FORMATS = {".docx", ".txt", ".md", ".csv", ".xlsx", ".pdf", ".pptx"}
UNSUPPORTED_GENERATED_TEXT_SUFFIXES = {".json", ".html", ".htm", ".xml"}

def sanitize_filename_stem(value: str, fallback: str) -> str:
    cleaned = (value or "").strip()
    lowered = cleaned.lower()
    for suffix in sorted(KNOWN_FILE_SUFFIXES, key=len, reverse=True):
        if lowered.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._-")
    cleaned = cleaned[:80].rstrip(" .")
    return cleaned or fallback


def infer_text_file_suffix(latest_user_request: str) -> str:
    normalized = latest_user_request.lower()
    suffix_hints: list[tuple[str, str]] = [
        (r"(?:^|\W)\.md(?:$|\W)|\bmarkdown\b", ".md"),
        (r"(?:^|\W)\.txt(?:$|\W)|\bplain text\b|\btext file\b", ".txt"),
        (r"(?:^|\W)\.csv(?:$|\W)|\bcsv\b", ".csv"),
        (r"(?:^|\W)\.ya?ml(?:$|\W)|\byaml\b", ".yml"),
        (r"(?:^|\W)\.toml(?:$|\W)|\btoml\b", ".toml"),
        (r"(?:^|\W)\.sql(?:$|\W)|\bsql\b", ".sql"),
        (r"(?:^|\W)\.css(?:$|\W)|\bcss\b", ".css"),
        (r"(?:^|\W)\.py(?:$|\W)|\bpython\b", ".py"),
        (r"(?:^|\W)\.tsx?(?:$|\W)|\btypescript\b", ".ts"),
        (r"(?:^|\W)\.jsx?(?:$|\W)|\bjavascript\b", ".js"),
    ]

    for pattern, suffix in suffix_hints:
        if re.search(pattern, normalized):
            return suffix

    return ".md"


def build_fallback_filename_stem(
    file_action: str,
    *,
    title: str | None = None,
    content: str | None = None,
    paragraphs: list[str] | None = None,
    sheets: list[Any] | None = None,
    slides: list[Any] | None = None,
) -> str:
    candidate_parts: list[str] = []

    if isinstance(title, str) and title.strip():
        candidate_parts.append(title.strip())
    if isinstance(content, str) and content.strip():
        candidate_parts.append(content.strip().splitlines()[0])
    for paragraph in paragraphs or []:
        if isinstance(paragraph, str) and paragraph.strip():
            candidate_parts.append(paragraph.strip())
            break
    if sheets:
        first_sheet = sheets[0]
        if isinstance(first_sheet, ExcelSheet):
            candidate_parts.append(first_sheet.name)
        elif isinstance(first_sheet, dict):
            candidate_parts.append(str(first_sheet.get("name") or "").strip())
    if slides:
        first_slide = slides[0]
        if isinstance(first_slide, PowerPointSlide):
            candidate_parts.append(first_slide.title or first_slide.content or "")
        elif isinstance(first_slide, dict):
            candidate_parts.append(
                str(first_slide.get("title") or first_slide.get("content") or "").strip()
            )

    for candidate in candidate_parts:
        sanitized = sanitize_filename_stem(candidate, "")
        if sanitized:
            return sanitized

    fallback_map = {
        "write_txt_file": "Notes",
        "write_markdown_file": "Markdown Notes",
        "write_csv_file": "Data Table",
        "write_word_file": "Report",
        "write_excel_file": "Workbook",
        "write_pdf_file": "Document",
        "write_powerpoint_file": "Presentation",
        "write_text_file": "Text Output",
    }
    return sanitize_filename_stem(fallback_map.get(file_action, "Output"), "Output")


def infer_file_name(
    runtime: "AgentRuntime",
    file_action: str,
    *,
    title: str | None = None,
    content: str | None = None,
    paragraphs: list[str] | None = None,
    sheets: list[Any] | None = None,
    slides: list[Any] | None = None,
) -> str:
    history_excerpt = "\n".join(
        f"{message.role}: {message.content.strip()}"
        for message in runtime.agent_input.messages[-6:]
        if message.content.strip()
    )
    latest_user_request = get_latest_user_message(runtime.agent_input.messages)
    document_payload: dict[str, Any] = {"file_action": file_action}
    if isinstance(title, str) and title.strip():
        document_payload["title"] = title.strip()
    if isinstance(content, str) and content.strip():
        document_payload["content_preview"] = content.strip()[:4000]

    clean_paragraphs = [
        paragraph.strip()[:400] for paragraph in (paragraphs or []) if paragraph.strip()
    ]
    if clean_paragraphs:
        document_payload["paragraphs"] = clean_paragraphs[:8]

    if sheets:
        document_payload["sheets"] = [
            {
                "name": (
                    sheet.name
                    if isinstance(sheet, ExcelSheet)
                    else str(sheet.get("name") or "").strip()
                ),
                "rows": (
                    sheet.rows[:8]
                    if isinstance(sheet, ExcelSheet)
                    else list(sheet.get("rows") or [])[:8]
                ),
            }
            for sheet in sheets[:3]
        ]

    if slides:
        document_payload["slides"] = [
            {
                "title": (
                    (slide.title or "").strip()
                    if isinstance(slide, PowerPointSlide)
                    else str(slide.get("title") or "").strip()
                ),
                "content": (
                    (slide.content or "").strip()[:600]
                    if isinstance(slide, PowerPointSlide)
                    else str(slide.get("content") or "").strip()[:600]
                ),
                "bullets": (
                    slide.bullets[:8]
                    if isinstance(slide, PowerPointSlide)
                    else list(slide.get("bullets") or [])[:8]
                ),
            }
            for slide in slides[:6]
        ]
    if latest_user_request.strip():
        document_payload["latest_user_request"] = latest_user_request.strip()[:1200]

    cache_key = json.dumps(
        {
            "history": history_excerpt,
            "document": document_payload,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    if cache_key in runtime.filename_cache:
        return runtime.filename_cache[cache_key]

    system_prompt = (
        "Choose a short descriptive filename stem for a Desktop file. "
        "Use only the conversation and document payload. "
        "Do not use an extension or path. "
        "Prefer 2 to 6 words when possible. "
        "Avoid placeholders or generic names such as document, file, notes, data, output, result, untitled, or PDF_document."
    )
    user_prompt = (
        f"Recent conversation:\n{history_excerpt or 'None'}\n\n"
        f"Document payload:\n{json.dumps(document_payload, ensure_ascii=False)}"
    )

    for expect_json in (True, False):
        try:
            request_payload: dict[str, Any] = {
                "model": (runtime.agent_input.writer_model or runtime.agent_input.model),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
            }
            if expect_json:
                request_payload["format"] = FilenameSuggestion.model_json_schema()

            response = call_llm(
                runtime.agent_input.api_key,
                runtime.agent_input.base_url,
                request_payload,
            )
            raw_content = (response.get("message", {}).get("content") or "").strip()
            if not raw_content:
                continue

            if expect_json:
                try:
                    parsed = FilenameSuggestion.model_validate_json(raw_content)
                    candidate = parsed.stem
                except Exception:
                    candidate = raw_content
            else:
                candidate = raw_content

            filename = sanitize_filename_stem(candidate, "")
            if filename:
                runtime.filename_cache[cache_key] = filename
                return filename
        except Exception:
            continue

    fallback = build_fallback_filename_stem(
        file_action,
        title=title,
        content=content,
        paragraphs=paragraphs,
        sheets=sheets,
        slides=slides,
    )
    runtime.filename_cache[cache_key] = fallback
    return fallback


def build_automatic_file_path(
    runtime: "AgentRuntime",
    file_action: str,
    *,
    raw_path: str | None = None,
    destination_folder: str | None = None,
    title: str | None = None,
    content: str | None = None,
    paragraphs: list[str] | None = None,
    sheets: list[Any] | None = None,
    slides: list[Any] | None = None,
) -> str:
    def is_multi_file_output_request() -> bool:
        if runtime.required_desktop_action_kind != "write_output":
            return False
        if runtime.requested_output_count is not None:
            return runtime.requested_output_count > 1
        return len(runtime.expected_output_extensions) > 1

    def resolve_shared_output_folder(suggested_stem: str) -> str:
        cached_folder = (runtime.preferred_output_folder or "").strip()
        if cached_folder:
            return cached_folder

        for created_output_path in runtime.created_output_paths:
            try:
                created_parent = Path(created_output_path).resolve().parent
                if (
                    created_parent != runtime.desktop_root
                    and runtime.desktop_root in created_parent.parents
                ):
                    runtime.preferred_output_folder = str(
                        created_parent.relative_to(runtime.desktop_root)
                    )
                    return runtime.preferred_output_folder
            except Exception:
                continue

        folder_base_name = sanitize_filename_stem(
            f"{suggested_stem} Files", "Output Files"
        )
        folder_name = folder_base_name
        counter = 1
        while True:
            candidate_folder = runtime.resolve_desktop_path(folder_name)
            if not candidate_folder.exists() or candidate_folder.is_dir():
                runtime.preferred_output_folder = folder_name
                return folder_name
            folder_name = f"{folder_base_name} ({counter})"
            counter += 1

    def raw_path_needs_folder_placement(raw_value: str) -> bool:
        normalized = raw_value.strip()
        if not normalized:
            return False
        candidate_path = Path(normalized)
        if candidate_path.is_absolute():
            try:
                resolved_path = runtime.resolve_desktop_path(normalized)
            except Exception:
                return False
            return resolved_path.parent == runtime.desktop_root
        return candidate_path.parent == Path(".")

    normalized_raw_path = raw_path.strip() if isinstance(raw_path, str) else ""
    if normalized_raw_path:
        if (
            isinstance(destination_folder, str)
            and destination_folder.strip()
            and not Path(normalized_raw_path).is_absolute()
            and Path(normalized_raw_path).parent == Path(".")
        ):
            return str(Path(destination_folder.strip()) / Path(normalized_raw_path).name)

        if is_multi_file_output_request() and raw_path_needs_folder_placement(
            normalized_raw_path
        ):
            shared_folder = resolve_shared_output_folder(
                sanitize_filename_stem(Path(normalized_raw_path).stem, "Output Files")
            )
            return str(Path(shared_folder) / Path(normalized_raw_path).name)

        return normalized_raw_path

    latest_user_request = get_latest_user_message(runtime.agent_input.messages)
    if file_action == "write_txt_file":
        suffix = ".txt"
    elif file_action == "write_markdown_file":
        suffix = ".md"
    elif file_action == "write_csv_file":
        suffix = ".csv"
    elif file_action == "write_word_file":
        suffix = ".docx"
    elif file_action == "write_excel_file":
        suffix = ".xlsx"
    elif file_action == "write_pdf_file":
        suffix = ".pdf"
    elif file_action == "write_powerpoint_file":
        suffix = ".pptx"
    else:
        suffix = infer_text_file_suffix(latest_user_request)

    stem = infer_file_name(
        runtime,
        file_action,
        title=title,
        content=content,
        paragraphs=paragraphs,
        sheets=sheets,
        slides=slides,
    )
    filename = f"{stem}{suffix}"

    if isinstance(destination_folder, str) and destination_folder.strip():
        return str(Path(destination_folder) / filename)

    if is_multi_file_output_request():
        shared_folder = resolve_shared_output_folder(stem)
        return str(Path(shared_folder) / filename)

    return filename


def get_expected_suffix_for_file_action(file_action: str) -> str | None:
    if file_action == "write_txt_file":
        return ".txt"
    if file_action == "write_markdown_file":
        return ".md"
    if file_action == "write_csv_file":
        return ".csv"
    if file_action == "write_word_file":
        return ".docx"
    if file_action == "write_excel_file":
        return ".xlsx"
    if file_action == "write_pdf_file":
        return ".pdf"
    if file_action == "write_powerpoint_file":
        return ".pptx"
    return None


def file_type_to_file_action(file_type: str) -> str:
    mapping = {
        "text": "write_text_file",
        "txt": "write_txt_file",
        "markdown": "write_markdown_file",
        "csv": "write_csv_file",
        "word": "write_word_file",
        "excel": "write_excel_file",
        "pdf": "write_pdf_file",
        "powerpoint": "write_powerpoint_file",
    }
    if file_type not in mapping:
        raise ValueError(f"Unsupported multi-file type: {file_type}")
    return mapping[file_type]


def plan_output_path_for_file_action(
    runtime: "AgentRuntime",
    file_action: str,
    *,
    raw_path: str | None = None,
    destination_folder: str | None = None,
    title: str | None = None,
    content: str | None = None,
    paragraphs: list[str] | None = None,
    sheets: list[Any] | None = None,
    slides: list[Any] | None = None,
    reserved_paths: set[str] | None = None,
) -> str:
    planned_raw_path = build_automatic_file_path(
        runtime,
        file_action,
        raw_path=raw_path,
        destination_folder=destination_folder,
        title=title,
        content=content,
        paragraphs=paragraphs,
        sheets=sheets,
        slides=slides,
    )
    planned_suffix = Path(planned_raw_path).suffix.lower()
    if file_action in {
        "write_text_file",
        "write_txt_file",
        "write_markdown_file",
        "write_csv_file",
        "write_json_file",
        "write_html_file",
        "write_xml_file",
    } and planned_suffix in UNSUPPORTED_GENERATED_TEXT_SUFFIXES:
        raise ValueError(
            "JSON, HTML, and XML file creation is no longer supported by the Desktop write tools."
        )
    expected_suffix = get_expected_suffix_for_file_action(file_action)
    return str(
        runtime.get_unique_output_path(
            planned_raw_path,
            expected_suffix,
            reserved_paths=reserved_paths,
        )
    )




