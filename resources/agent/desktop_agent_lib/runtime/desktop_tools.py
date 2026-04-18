from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from ..core.models import *
from ..planning.file_planning import (
    TEXT_FILE_EXTENSIONS,
    UNSUPPORTED_GENERATED_TEXT_SUFFIXES,
    file_type_to_file_action,
    plan_output_path_for_file_action,
)


class DesktopToolMixin:
    RETRIEVAL_QUERY_COUNT = 3
    RETRIEVAL_TOP_K_PER_QUERY = 5
    RETRIEVAL_FINAL_TOP_K = 12

    def ensure_supported_generated_text_path(self, raw_path: str) -> None:
        """
        Ensure supported generated text path.
        Key behavior: raises explicit errors on invalid or unsupported states.
        Performs side effects and returns no value.
        """
        if Path(raw_path).suffix.lower() in UNSUPPORTED_GENERATED_TEXT_SUFFIXES:
            raise ValueError(
                "JSON, HTML, and XML file creation is no longer supported by the Desktop write tools."
            )

    def infer_text_target_format(
        self, raw_path: str, expected_suffix: str | None = None
    ) -> str | None:
        """
        Infer text target format.
        Returns a `str | None` result.
        """
        if expected_suffix:
            return expected_suffix.lstrip(".")
        suffix = Path(raw_path).suffix.lower().lstrip(".")
        return suffix or None

    def prepare_text_creation_args(
        self,
        *,
        file_type: str,
        path: str,
        title: str | None = None,
        content: str | None = None,
        paragraphs: list[str] | None = None,
    ) -> tuple[WriteTextFileArgs, str | None]:
        """
        Prepare text creation arguments.
        Returns a `tuple[WriteTextFileArgs, str | None]` result.
        """
        expected_suffix: str | None = None
        if file_type == "txt":
            expected_suffix = ".txt"
        elif file_type == "markdown":
            expected_suffix = ".md"
        elif file_type == "csv":
            expected_suffix = ".csv"

        if file_type == "text":
            self.ensure_supported_generated_text_path(path)

        prepared_args = self.prepare_text_file_from_retrieved_chunks(
            WriteTextFileArgs(
                path=path,
                content=self.build_text_file_content(
                    title=title if file_type != "csv" else None,
                    content=content,
                    paragraphs=paragraphs,
                ),
            ),
            target_format=self.infer_text_target_format(path, expected_suffix),
        )
        return prepared_args, expected_suffix

    def read_web_page(self, args: ReadWebPageArgs) -> ToolResult:
        """
        Read web page.
        Key behavior: serializes JSON payloads and wraps outcomes in runtime tool-result objects.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        page_text = (self.agent_input.page_context.text or "").strip()
        if not self.agent_input.page_context.url and not page_text:
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "unavailable",
                        "reason": "No active page context is available.",
                    },
                    ensure_ascii=False,
                )
            )

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "purpose": args.purpose,
                    "url": self.agent_input.page_context.url,
                    "text": page_text,
                },
                ensure_ascii=False,
            )
        )

    def list_desktop_entries(self, args: ListDesktopEntriesArgs) -> ToolResult:
        """
        List desktop entries.
        Key behavior: serializes JSON payloads, wraps outcomes in runtime tool-result objects, and raises explicit errors on invalid or unsupported states.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        directory = self.resolve_desktop_path(args.path)
        if not directory.exists():
            raise ValueError(f"Directory does not exist: {directory}")
        if not directory.is_dir():
            raise ValueError(f"Path is not a directory: {directory}")

        entries = [
            self.format_entry(path)
            for path in sorted(
                directory.iterdir(),
                key=lambda item: (0 if item.is_dir() else 1, item.name.lower()),
            )
        ]

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "directory": str(directory),
                    "entries": entries,
                },
                ensure_ascii=False,
            ),
            should_open_desktop_view=True,
        )

    def read_desktop_file(self, args: ReadDesktopFileArgs) -> ToolResult:
        """
        Read desktop file.
        Key behavior: serializes JSON payloads, performs local file I/O, wraps outcomes in runtime tool-result objects, and raises explicit errors on invalid or unsupported states.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        file_path = self.resolve_desktop_path(args.path)
        if not file_path.exists():
            raise ValueError(f"File does not exist: {file_path}")
        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")

        if file_path.suffix.lower() == ".docx":
            raw_text = self.read_docx_text(file_path)
            file_kind = "docx"
        elif file_path.suffix.lower() in TEXT_FILE_EXTENSIONS:
            raw_text = file_path.read_text(encoding="utf-8", errors="replace")
            file_kind = "text"
        else:
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "unsupported",
                        "path": str(file_path),
                        "reason": "Only text-based files and .docx documents can be read directly by this tool.",
                    },
                    ensure_ascii=False,
                ),
                should_open_desktop_view=True,
            )

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "path": str(file_path),
                    "file_kind": file_kind,
                    "content": raw_text,
                },
                ensure_ascii=False,
            ),
            should_open_desktop_view=True,
        )

    def read_desktop_file_if_exists(self, args: ReadDesktopFileIfExistsArgs) -> ToolResult:
        """
        Read desktop file if exists.
        Key behavior: serializes JSON payloads and wraps outcomes in runtime tool-result objects.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        file_path = self.resolve_desktop_path(args.path)
        if not file_path.exists():
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "missing",
                        "path": str(file_path),
                        "exists": False,
                    },
                    ensure_ascii=False,
                ),
                should_open_desktop_view=True,
            )
        if not file_path.is_file():
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "invalid",
                        "path": str(file_path),
                        "reason": "Path exists but is not a file.",
                    },
                    ensure_ascii=False,
                ),
                should_open_desktop_view=True,
            )

        return self.read_desktop_file(ReadDesktopFileArgs(path=str(file_path)))

    def create_folder(self, args: CreateFolderArgs) -> ToolResult:
        """
        Create folder.
        Key behavior: serializes JSON payloads and wraps outcomes in runtime tool-result objects.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        folder_path = self.resolve_desktop_path(args.path)
        folder_path.mkdir(parents=True, exist_ok=True)
        self.record_changed_path(folder_path)

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "path": str(folder_path),
                    "created": True,
                },
                ensure_ascii=False,
            ),
            filesystem_changed=True,
            changed_paths=[str(folder_path)],
            should_open_desktop_view=True,
        )

    def retrieve_relevant_chunks(
        self,
        args: RetrieveRelevantChunksArgs,
        *,
        selected_source_domains: list[str] | None = None,
    ) -> ToolResult:
        """
        Handle retrieve relevant chunks for the current workflow.
        Key behavior: serializes JSON payloads and wraps outcomes in runtime tool-result objects.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        retrieved_chunks, retrieval_queries = self.retrieve_relevant_chunks_from_store(
            args.query,
            self.RETRIEVAL_FINAL_TOP_K,
            selected_source_domains=selected_source_domains,
        )
        retrieval_results = [
            {
                "source_title": chunk.source_title,
                "source_url": chunk.source_url,
                "source_domain": chunk.source_domain,
                "similarity": chunk.similarity,
                "text": chunk.text,
            }
            for chunk in retrieved_chunks
        ]

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "query": args.query,
                    "retrieval_query_count": self.RETRIEVAL_QUERY_COUNT,
                    "retrieval_queries": retrieval_queries,
                    "per_query_top_k": self.RETRIEVAL_TOP_K_PER_QUERY,
                    "top_k": self.RETRIEVAL_FINAL_TOP_K,
                    "selected_source_domains": selected_source_domains or [],
                    "result_count": len(retrieved_chunks),
                    "results": retrieval_results,
                },
                ensure_ascii=False,
            )
        )

    def _write_text_file_direct(
        self,
        args: WriteTextFileArgs,
        expected_suffix: str | None = None,
    ) -> ToolResult:
        """
        Write text file direct.
        Key behavior: serializes JSON payloads, performs local file I/O, and wraps outcomes in runtime tool-result objects.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        file_path = self.get_unique_output_path(args.path, expected_suffix)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(args.content, encoding="utf-8")
        self.record_changed_path(file_path)

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "path": str(file_path),
                    "bytes_written": len(args.content.encode("utf-8")),
                },
                ensure_ascii=False,
            ),
            filesystem_changed=True,
            changed_paths=[str(file_path)],
            should_open_desktop_view=True,
        )

    def write_text_file(self, args: WriteTextFileArgs) -> ToolResult:
        """
        Write text file.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        self.require_retrieved_chunks_for_write("write_text_file")
        self.ensure_supported_generated_text_path(args.path)
        prepared_args = self.prepare_text_file_from_retrieved_chunks(
            args,
            target_format=args.path.rsplit(".", 1)[-1] if "." in args.path else None,
        )
        result = self._write_text_file_direct(prepared_args)
        self.consume_retrieved_chunks_for_write()
        return result

    def _write_text_variant_file(
        self,
        args: WriteTextFileArgs,
        *,
        tool_name: str,
        expected_suffix: str,
    ) -> ToolResult:
        """
        Write text variant file.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        self.require_retrieved_chunks_for_write(tool_name)
        prepared_args = self.prepare_text_file_from_retrieved_chunks(
            args,
            target_format=expected_suffix.lstrip("."),
        )
        result = self._write_text_file_direct(
            prepared_args,
            expected_suffix=expected_suffix,
        )
        self.consume_retrieved_chunks_for_write()
        return result

    def write_txt_file(self, args: WriteTxtFileArgs) -> ToolResult:
        """
        Write text file.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        return self._write_text_variant_file(
            args,
            tool_name="write_txt_file",
            expected_suffix=".txt",
        )

    def write_markdown_file(self, args: WriteMarkdownFileArgs) -> ToolResult:
        """
        Write markdown file.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        return self._write_text_variant_file(
            args,
            tool_name="write_markdown_file",
            expected_suffix=".md",
        )

    def write_csv_file(self, args: WriteCsvFileArgs) -> ToolResult:
        """
        Write CSV file.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        return self._write_text_variant_file(
            args,
            tool_name="write_csv_file",
            expected_suffix=".csv",
        )

    def write_json_file(self, args: WriteJsonFileArgs) -> ToolResult:
        """
        Write JSON file.
        Key behavior: raises explicit errors on invalid or unsupported states.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        raise ValueError(
            "JSON file creation is no longer supported by the Desktop write tools."
        )

    def write_html_file(self, args: WriteHtmlFileArgs) -> ToolResult:
        """
        Write html file.
        Key behavior: raises explicit errors on invalid or unsupported states.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        raise ValueError(
            "HTML file creation is no longer supported by the Desktop write tools."
        )

    def write_xml_file(self, args: WriteXmlFileArgs) -> ToolResult:
        """
        Write XML file.
        Key behavior: raises explicit errors on invalid or unsupported states.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        raise ValueError(
            "XML file creation is no longer supported by the Desktop write tools."
        )

    def _write_word_file_direct(self, args: WriteWordFileArgs) -> ToolResult:
        """
        Write word file direct.
        Key behavior: serializes JSON payloads and wraps outcomes in runtime tool-result objects.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        file_path = self.get_unique_output_path(args.path, ".docx")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        paragraphs = self.build_word_paragraphs(
            title=args.title,
            content=args.content,
            paragraphs=args.paragraphs,
        )

        self.write_docx_file(file_path, paragraphs)
        self.record_changed_path(file_path)

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "path": str(file_path),
                    "paragraph_count": len(paragraphs),
                },
                ensure_ascii=False,
            ),
            filesystem_changed=True,
            changed_paths=[str(file_path)],
            should_open_desktop_view=True,
        )

    def write_word_file(self, args: WriteWordFileArgs) -> ToolResult:
        """
        Write word file.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        self.require_retrieved_chunks_for_write("write_word_file")
        prepared_args = self.prepare_word_file_from_retrieved_chunks(args)
        result = self._write_word_file_direct(prepared_args)
        self.consume_retrieved_chunks_for_write()
        return result

    def _write_pdf_file_direct(self, args: WritePdfFileArgs) -> ToolResult:
        """
        Write PDF file direct.
        Key behavior: serializes JSON payloads and wraps outcomes in runtime tool-result objects.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        file_path = self.get_unique_output_path(args.path, ".pdf")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        page_count = self.write_pdf_document(
            file_path,
            title=args.title,
            content=args.content,
            paragraphs=args.paragraphs,
        )
        self.record_changed_path(file_path)

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "path": str(file_path),
                    "page_count": page_count,
                },
                ensure_ascii=False,
            ),
            filesystem_changed=True,
            changed_paths=[str(file_path)],
            should_open_desktop_view=True,
        )

    def write_pdf_file(self, args: WritePdfFileArgs) -> ToolResult:
        """
        Write PDF file.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        self.require_retrieved_chunks_for_write("write_pdf_file")
        prepared_args = self.prepare_pdf_file_from_retrieved_chunks(args)
        result = self._write_pdf_file_direct(prepared_args)
        self.consume_retrieved_chunks_for_write()
        return result

    def _write_powerpoint_file_direct(self, args: WritePowerPointFileArgs) -> ToolResult:
        """
        Write powerpoint file direct.
        Key behavior: serializes JSON payloads and wraps outcomes in runtime tool-result objects.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        normalized_slides = self.normalize_presentation_slides(args.slides)
        normalized_content = self.normalize_document_text(
            args.content,
            strip_markdown=True,
        )
        normalized_title = self.normalize_document_text(
            args.title,
            strip_markdown=True,
        )
        if not normalized_slides and normalized_content:
            normalized_slides = [
                PowerPointSlide(
                    title=normalized_title or None,
                    content=normalized_content,
                    bullets=[],
                )
            ]

        file_path = self.get_unique_output_path(args.path, ".pptx")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        presentation_title = (
            normalized_title
            or next(
                (
                    (slide.title or "").strip()
                    for slide in normalized_slides
                    if (slide.title or "").strip()
                ),
                file_path.stem,
            )
        )
        self.write_pptx_file(file_path, normalized_slides, presentation_title)
        self.record_changed_path(file_path)

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "path": str(file_path),
                    "slide_count": len(normalized_slides),
                },
                ensure_ascii=False,
            ),
            filesystem_changed=True,
            changed_paths=[str(file_path)],
            should_open_desktop_view=True,
        )

    def write_powerpoint_file(self, args: WritePowerPointFileArgs) -> ToolResult:
        """
        Write powerpoint file.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        self.require_retrieved_chunks_for_write("write_powerpoint_file")
        prepared_args = self.prepare_powerpoint_file_from_retrieved_chunks(args)
        result = self._write_powerpoint_file_direct(prepared_args)
        self.consume_retrieved_chunks_for_write()
        return result

    def _delete_desktop_file_path(
        self,
        file_path: Path,
        *,
        reason: str,
        include_in_changed_paths: bool,
    ) -> dict[str, Any]:
        """
        Delete desktop file path.
        Key behavior: raises explicit errors on invalid or unsupported states.
        Returns a structured mapping with operation details.
        """
        if not file_path.exists():
            raise ValueError(f"File does not exist: {file_path}")
        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")

        try:
            bytes_deleted = file_path.stat().st_size
        except OSError:
            bytes_deleted = 0

        file_path.unlink()
        if include_in_changed_paths:
            self.record_changed_path(file_path)

        return {
            "status": "ok",
            "path": str(file_path),
            "deleted": True,
            "bytes_deleted": bytes_deleted,
            "reason": reason,
        }

    def _replace_desktop_file_with_prepared_output(
        self,
        *,
        original_path: Path,
        replacement_path: Path,
    ) -> None:
        """
        Handle replace desktop file with prepared output for the current workflow.
        Key behavior: raises explicit errors on invalid or unsupported states.
        Performs side effects and returns no value.
        """
        if not replacement_path.exists():
            raise RuntimeError(
                f"The prepared replacement file is missing: {replacement_path}"
            )
        if not replacement_path.is_file():
            raise RuntimeError(
                f"The prepared replacement path is not a file: {replacement_path}"
            )

        try:
            # Atomic same-directory replace: if this fails, the original file stays in place.
            replacement_path.replace(original_path)
        except Exception as error:  # noqa: BLE001
            raise RuntimeError(
                "The replacement draft was prepared, but replacing the original file failed. "
                f"original={original_path} replacement={replacement_path} error={error}"
            ) from error

    def delete_desktop_file(self, args: DeleteDesktopFileArgs) -> ToolResult:
        """
        Delete desktop file.
        Key behavior: serializes JSON payloads and wraps outcomes in runtime tool-result objects.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        file_path = self.resolve_desktop_path(args.path)
        result_payload = self._delete_desktop_file_path(
            file_path,
            reason=args.reason,
            include_in_changed_paths=True,
        )
        return ToolResult(
            content=json.dumps(result_payload, ensure_ascii=False),
            filesystem_changed=True,
            changed_paths=[str(file_path)],
            should_open_desktop_view=True,
        )

    def edit_desktop_file(self, args: EditDesktopFileArgs) -> ToolResult:
        """
        Edit desktop file.
        Key behavior: serializes JSON payloads, performs local file I/O, wraps outcomes in runtime tool-result objects, and raises explicit errors on invalid or unsupported states.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        file_path = self.resolve_desktop_path(args.path)
        if not file_path.exists():
            raise ValueError(f"File does not exist: {file_path}")
        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")

        suffix = file_path.suffix.lower()
        if suffix == ".docx":
            paragraphs = self.build_word_paragraphs(
                title=args.title,
                content=args.content,
                paragraphs=args.paragraphs,
            )
            if not paragraphs:
                raise ValueError("edit_desktop_file requires replacement Word content for .docx edits.")
            replacement_path = self.resolve_unique_file_path(
                file_path.with_name(f"{file_path.stem} (replacement){file_path.suffix}")
            )
            self.write_docx_file(replacement_path, paragraphs)
            self._replace_desktop_file_with_prepared_output(
                original_path=file_path,
                replacement_path=replacement_path,
            )
            self.record_changed_path(file_path)
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "ok",
                        "path": str(file_path),
                        "edited": True,
                        "replaced": True,
                        "source_deleted": True,
                        "source_deleted_via_tool": "atomic_replace",
                        "file_kind": "docx",
                        "paragraph_count": len(paragraphs),
                    },
                    ensure_ascii=False,
                ),
                filesystem_changed=True,
                changed_paths=[str(file_path)],
                should_open_desktop_view=True,
            )

        if suffix in TEXT_FILE_EXTENSIONS:
            new_content = self.build_text_file_content(
                title=args.title,
                content=args.content,
                paragraphs=args.paragraphs,
            )
            if not new_content:
                raise ValueError("edit_desktop_file requires replacement text content for text-based file edits.")
            replacement_path = self.resolve_unique_file_path(
                file_path.with_name(f"{file_path.stem} (replacement){file_path.suffix}")
            )
            replacement_path.write_text(new_content, encoding="utf-8")
            self._replace_desktop_file_with_prepared_output(
                original_path=file_path,
                replacement_path=replacement_path,
            )
            self.record_changed_path(file_path)
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "ok",
                        "path": str(file_path),
                        "edited": True,
                        "replaced": True,
                        "source_deleted": True,
                        "source_deleted_via_tool": "atomic_replace",
                        "file_kind": "text",
                        "bytes_written": len(new_content.encode("utf-8")),
                    },
                    ensure_ascii=False,
                ),
                filesystem_changed=True,
                changed_paths=[str(file_path)],
                should_open_desktop_view=True,
            )

        raise ValueError("edit_desktop_file only supports text-based files and .docx documents.")

    def convert_desktop_file_format(self, args: ConvertDesktopFileFormatArgs) -> ToolResult:
        """
        Convert desktop file format.
        Key behavior: serializes JSON payloads, builds or reads ZIP container content, performs local file I/O, wraps outcomes in runtime tool-result objects, and raises explicit errors on invalid or unsupported states.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        source_file_path = self.resolve_desktop_path(args.source_path)
        if not source_file_path.exists():
            raise ValueError(f"File does not exist: {source_file_path}")
        if not source_file_path.is_file():
            raise ValueError(f"Path is not a file: {source_file_path}")

        output_file_path, target_suffix = self.get_conversion_output_path(
            args.source_path,
            args.target_format,
            args.output_path,
        )
        output_file_path.parent.mkdir(parents=True, exist_ok=True)

        source_suffix = source_file_path.suffix.lower()
        conversion_title = source_file_path.stem or "Converted File"

        def write_text_output(content: str) -> None:
            """
            Write text output.
            Key behavior: performs local file I/O.
            Performs side effects and returns no value.
            """
            output_file_path.write_text(content, encoding="utf-8")

        def write_docx_output(content: str) -> None:
            """
            Write DOCX output.
            Key behavior: raises explicit errors on invalid or unsupported states.
            Performs side effects and returns no value.
            """
            paragraphs = self.build_word_paragraphs(
                title=conversion_title,
                content=content,
            )
            if not paragraphs:
                raise ValueError("The source file does not contain convertible text content.")
            self.write_docx_file(output_file_path, paragraphs)

        def write_pdf_output(content: str) -> None:
            """
            Write PDF output.
            Performs side effects and returns no value.
            """
            self.write_pdf_document(
                output_file_path,
                title=conversion_title,
                content=content,
            )

        def write_pptx_output_from_text(content: str) -> None:
            """
            Write PPTX output from text.
            Performs side effects and returns no value.
            """
            slides = self.build_conversion_slides_from_text(conversion_title, content)
            self.write_pptx_file(output_file_path, slides, conversion_title)

        def write_pptx_output_from_sheets(sheets: list[ExcelSheet]) -> None:
            """
            Write PPTX output from sheets.
            Performs side effects and returns no value.
            """
            slides = self.build_conversion_slides_from_sheets(sheets, conversion_title)
            self.write_pptx_file(output_file_path, slides, conversion_title)

        if source_suffix == ".docx":
            source_text = self.read_docx_text(source_file_path)
            if target_suffix in {".txt", ".md"}:
                write_text_output(source_text)
            elif target_suffix == ".pdf":
                write_pdf_output(source_text)
            elif target_suffix == ".pptx":
                write_pptx_output_from_text(source_text)
            else:
                raise ValueError(
                    "Supported conversions from .docx are .txt, .md, .pdf, and .pptx."
                )
        elif source_suffix == ".pdf":
            source_text = self.read_pdf_text(source_file_path)
            if target_suffix in {".txt", ".md"}:
                write_text_output(source_text)
            elif target_suffix == ".docx":
                write_docx_output(source_text)
            elif target_suffix == ".pptx":
                write_pptx_output_from_text(source_text)
            else:
                raise ValueError(
                    "Supported conversions from .pdf are .txt, .md, .docx, and .pptx."
                )
        elif source_suffix == ".pptx":
            source_text = self.read_pptx_text(source_file_path)
            if target_suffix in {".txt", ".md"}:
                write_text_output(source_text)
            elif target_suffix == ".docx":
                write_docx_output(source_text)
            elif target_suffix == ".pdf":
                write_pdf_output(source_text)
            else:
                raise ValueError(
                    "Supported conversions from .pptx are .txt, .md, .docx, and .pdf."
                )
        elif source_suffix == ".csv":
            rows = self.read_csv_rows(source_file_path)
            sheet_payload = [ExcelSheet(name="Sheet1", rows=rows)]
            tabbed_text = self.rows_to_tabbed_text(rows)
            markdown_text = self.rows_to_markdown_table(rows)
            if target_suffix == ".xlsx":
                workbook_xml, workbook_rels_xml, worksheet_files, content_types_xml = self.build_xlsx_package(
                    sheet_payload
                )
                with zipfile.ZipFile(output_file_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("[Content_Types].xml", content_types_xml)
                    archive.writestr(
                        "_rels/.rels",
                        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
                    )
                    archive.writestr("xl/workbook.xml", workbook_xml)
                    archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
                    for path, content in worksheet_files.items():
                        archive.writestr(path, content)
            elif target_suffix == ".txt":
                write_text_output(tabbed_text)
            elif target_suffix == ".md":
                write_text_output(markdown_text)
            elif target_suffix == ".docx":
                write_docx_output(tabbed_text)
            elif target_suffix == ".pdf":
                write_pdf_output(tabbed_text)
            elif target_suffix == ".pptx":
                write_pptx_output_from_sheets(sheet_payload)
            else:
                raise ValueError(
                    "Supported conversions from .csv are .xlsx, .txt, .md, .docx, .pdf, and .pptx."
                )
        elif source_suffix == ".xlsx":
            sheets = self.read_xlsx_sheets(source_file_path)
            if not sheets:
                raise ValueError(f"The spreadsheet does not contain any readable sheets: {source_file_path}")
            primary_rows = sheets[0].rows
            combined_text = self.build_conversion_text_from_sheets(sheets)
            combined_markdown = self.build_conversion_markdown_from_sheets(sheets)
            if target_suffix == ".csv":
                write_text_output(self.rows_to_csv_text(primary_rows))
            elif target_suffix == ".txt":
                write_text_output(combined_text)
            elif target_suffix == ".md":
                write_text_output(combined_markdown)
            elif target_suffix == ".docx":
                write_docx_output(combined_text)
            elif target_suffix == ".pdf":
                write_pdf_output(combined_text)
            elif target_suffix == ".pptx":
                write_pptx_output_from_sheets(sheets)
            else:
                raise ValueError(
                    "Supported conversions from .xlsx are .csv, .txt, .md, .docx, .pdf, and .pptx."
                )
        elif source_suffix in TEXT_FILE_EXTENSIONS:
            source_text = source_file_path.read_text(encoding="utf-8", errors="replace")
            if target_suffix == ".docx":
                write_docx_output(source_text)
            elif target_suffix in {".txt", ".md"}:
                write_text_output(source_text)
            elif target_suffix == ".pdf":
                write_pdf_output(source_text)
            elif target_suffix == ".pptx":
                write_pptx_output_from_text(source_text)
            else:
                raise ValueError(
                    "Supported conversions from text-based files are .docx, .txt, .md, .pdf, and .pptx."
                )
        else:
            raise ValueError(
                "convert_desktop_file_format only supports source files in docx, text-based, csv, xlsx, pdf, or pptx formats."
            )

        self.record_changed_path(output_file_path)

        try:
            self._delete_desktop_file_path(
                source_file_path,
                reason="Removing source file after successful conversion.",
                include_in_changed_paths=False,
            )
        except Exception as error:  # noqa: BLE001
            raise RuntimeError(
                f"The converted file was created at {output_file_path}, but the original source file could not be removed: {error}"
            ) from error

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "source_path": str(source_file_path),
                    "path": str(output_file_path),
                    "converted": True,
                    "source_deleted": True,
                    "source_deleted_via_tool": "delete_desktop_file",
                    "target_format": target_suffix.lstrip("."),
                },
                ensure_ascii=False,
            ),
            filesystem_changed=True,
            changed_paths=[str(output_file_path)],
            should_open_desktop_view=True,
        )

    def _write_excel_file_direct(self, args: WriteExcelFileArgs) -> ToolResult:
        """
        Write excel file direct.
        Key behavior: serializes JSON payloads, builds or reads ZIP container content, and wraps outcomes in runtime tool-result objects.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        file_path = self.get_unique_output_path(args.path, ".xlsx")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        workbook_xml, workbook_rels_xml, worksheet_files, content_types_xml = self.build_xlsx_package(
            args.sheets
        )

        with zipfile.ZipFile(file_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types_xml)
            archive.writestr(
                "_rels/.rels",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
            )
            archive.writestr("xl/workbook.xml", workbook_xml)
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)

            for path, content in worksheet_files.items():
                archive.writestr(path, content)

        self.record_changed_path(file_path)

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "path": str(file_path),
                    "sheet_count": len(args.sheets),
                },
                ensure_ascii=False,
            ),
            filesystem_changed=True,
            changed_paths=[str(file_path)],
            should_open_desktop_view=True,
        )

    def write_excel_file(self, args: WriteExcelFileArgs) -> ToolResult:
        """
        Write excel file.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        self.require_retrieved_chunks_for_write("write_excel_file")
        prepared_args = self.prepare_excel_file_from_retrieved_chunks(args)
        result = self._write_excel_file_direct(prepared_args)
        self.consume_retrieved_chunks_for_write()
        return result

    def create_multiple_files(self, args: CreateMultipleFilesArgs) -> ToolResult:
        """
        Create multiple files.
        Key behavior: serializes JSON payloads, wraps outcomes in runtime tool-result objects, and raises explicit errors on invalid or unsupported states.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        self.require_retrieved_chunks_for_write("create_multiple_files")
        planned_files = self.plan_multiple_file_specs(args.files)
        prepared_operations: list[tuple[str, Any, str | None]] = []
        created_paths: list[str] = []

        for file_spec in planned_files:
            if not file_spec.path:
                raise ValueError("Each multi-file item must resolve to a file path.")

            if file_spec.file_type in {"text", "txt", "markdown", "csv"}:
                prepared_args, expected_suffix = self.prepare_text_creation_args(
                    file_type=file_spec.file_type,
                    path=file_spec.path,
                    title=file_spec.title,
                    content=file_spec.content,
                    paragraphs=file_spec.paragraphs,
                )
                prepared_operations.append(("text", prepared_args, expected_suffix))
            elif file_spec.file_type == "word":
                prepared_args = self.prepare_word_file_from_retrieved_chunks(
                    WriteWordFileArgs(
                        path=file_spec.path,
                        title=file_spec.title,
                        content=file_spec.content,
                        paragraphs=file_spec.paragraphs,
                    )
                )
                prepared_operations.append(("word", prepared_args, None))
            elif file_spec.file_type == "excel":
                prepared_args = self.prepare_excel_file_from_retrieved_chunks(
                    WriteExcelFileArgs(path=file_spec.path, sheets=file_spec.sheets)
                )
                prepared_operations.append(("excel", prepared_args, None))
            elif file_spec.file_type == "pdf":
                prepared_args = self.prepare_pdf_file_from_retrieved_chunks(
                    WritePdfFileArgs(
                        path=file_spec.path,
                        title=file_spec.title,
                        content=file_spec.content,
                        paragraphs=file_spec.paragraphs,
                    )
                )
                prepared_operations.append(("pdf", prepared_args, None))
            elif file_spec.file_type == "powerpoint":
                prepared_args = self.prepare_powerpoint_file_from_retrieved_chunks(
                    WritePowerPointFileArgs(
                        path=file_spec.path,
                        title=file_spec.title,
                        content=file_spec.content,
                        slides=file_spec.slides,
                    )
                )
                prepared_operations.append(("powerpoint", prepared_args, None))
            else:
                raise ValueError(f"Unsupported multi-file item type: {file_spec.file_type}")

        try:
            for operation_kind, prepared_args, expected_suffix in prepared_operations:
                if operation_kind == "text":
                    result = self._write_text_file_direct(
                        prepared_args,
                        expected_suffix=expected_suffix,
                    )
                elif operation_kind == "word":
                    result = self._write_word_file_direct(prepared_args)
                elif operation_kind == "excel":
                    result = self._write_excel_file_direct(prepared_args)
                elif operation_kind == "pdf":
                    result = self._write_pdf_file_direct(prepared_args)
                elif operation_kind == "powerpoint":
                    result = self._write_powerpoint_file_direct(prepared_args)
                else:
                    raise ValueError(f"Unsupported prepared multi-file operation: {operation_kind}")

                for changed_path in result.changed_paths:
                    if changed_path not in created_paths:
                        created_paths.append(changed_path)
        except Exception as error:
            rolled_back_paths: list[str] = []
            for created_path in reversed(created_paths):
                try:
                    resolved_path = self.resolve_desktop_path(created_path)
                    if resolved_path.exists() and resolved_path.is_file():
                        resolved_path.unlink()
                        rolled_back_paths.append(str(resolved_path))
                    self.forget_changed_path(resolved_path)
                except OSError:
                    continue

            rollback_suffix = (
                f" Rolled back {len(rolled_back_paths)} created file(s)."
                if rolled_back_paths
                else ""
            )
            raise RuntimeError(
                "create_multiple_files could not complete all requested outputs."
                f" {str(error)}{rollback_suffix}"
            ) from error

        self.consume_retrieved_chunks_for_write()

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "file_count": len(created_paths),
                    "paths": created_paths,
                },
                ensure_ascii=False,
            ),
            filesystem_changed=bool(created_paths),
            changed_paths=created_paths,
            should_open_desktop_view=True,
        )

    def add_file_to_existing_folder(self, args: AddFileToExistingFolderArgs) -> ToolResult:
        """
        Handle add file to existing folder for the current workflow.
        Key behavior: parses JSON payloads, serializes JSON payloads, wraps outcomes in runtime tool-result objects, and raises explicit errors on invalid or unsupported states.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        self.require_retrieved_chunks_for_write("add_file_to_existing_folder")
        folder_path = self.resolve_desktop_path(args.folder_path)
        if not folder_path.exists():
            raise ValueError(f"Folder does not exist: {folder_path}")
        if not folder_path.is_dir():
            raise ValueError(f"Path is not a directory: {folder_path}")

        file_action = file_type_to_file_action(args.file_type)
        planned_file_path = plan_output_path_for_file_action(
            self,
            file_action,
            raw_path=args.file_name,
            destination_folder=args.folder_path,
            title=args.title,
            content=args.content,
            paragraphs=args.paragraphs,
            sheets=args.sheets,
            slides=args.slides,
        )

        if args.file_type in {"text", "txt", "markdown", "csv"}:
            prepared_args, expected_suffix = self.prepare_text_creation_args(
                file_type=args.file_type,
                path=planned_file_path,
                title=args.title,
                content=args.content,
                paragraphs=args.paragraphs,
            )
            result = self._write_text_file_direct(
                prepared_args,
                expected_suffix=expected_suffix,
            )
        elif args.file_type == "word":
            prepared_args = self.prepare_word_file_from_retrieved_chunks(
                WriteWordFileArgs(
                    path=planned_file_path,
                    title=args.title,
                    content=args.content,
                    paragraphs=args.paragraphs,
                )
            )
            result = self._write_word_file_direct(prepared_args)
        elif args.file_type == "excel":
            prepared_args = self.prepare_excel_file_from_retrieved_chunks(
                WriteExcelFileArgs(path=planned_file_path, sheets=args.sheets)
            )
            result = self._write_excel_file_direct(prepared_args)
        elif args.file_type == "pdf":
            prepared_args = self.prepare_pdf_file_from_retrieved_chunks(
                WritePdfFileArgs(
                    path=planned_file_path,
                    title=args.title,
                    content=args.content,
                    paragraphs=args.paragraphs,
                )
            )
            result = self._write_pdf_file_direct(prepared_args)
        elif args.file_type == "powerpoint":
            prepared_args = self.prepare_powerpoint_file_from_retrieved_chunks(
                WritePowerPointFileArgs(
                    path=planned_file_path,
                    title=args.title,
                    content=args.content,
                    slides=args.slides,
                )
            )
            result = self._write_powerpoint_file_direct(prepared_args)
        else:
            raise ValueError(f"Unsupported file type: {args.file_type}")

        try:
            result_payload = json.loads(result.content)
        except json.JSONDecodeError:
            result_payload = {"status": "ok", "path": planned_file_path}

        if not isinstance(result_payload, dict):
            result_payload = {"status": "ok", "path": planned_file_path}

        result_payload["folder_path"] = str(folder_path)
        result_payload["added_to_existing_folder"] = True
        self.consume_retrieved_chunks_for_write()

        return ToolResult(
            content=json.dumps(result_payload, ensure_ascii=False),
            filesystem_changed=result.filesystem_changed,
            changed_paths=result.changed_paths,
            should_open_desktop_view=True,
        )

    def show_desktop_view(self, args: ShowDesktopViewArgs) -> ToolResult:
        """
        Show desktop view.
        Key behavior: serializes JSON payloads, wraps outcomes in runtime tool-result objects, and updates instance state for subsequent workflow steps.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        self.should_open_desktop_view = True
        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "reason": args.reason,
                },
                ensure_ascii=False,
            ),
            should_open_desktop_view=True,
        )

    def close_agent_session(self, args: CloseAgentSessionArgs) -> ToolResult:
        """
        Close agent session.
        Key behavior: serializes JSON payloads, wraps outcomes in runtime tool-result objects, and updates instance state for subsequent workflow steps.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        self.session_should_close = True
        self.invalidate_retrieved_chunks()
        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "closed": True,
                    "retrieved_chunks_cleared": True,
                    "reason": args.reason,
                },
                ensure_ascii=False,
            )
        )

    def show_desktop_folder(self, args: ShowDesktopFolderArgs) -> ToolResult:
        """
        Show desktop folder.
        Key behavior: serializes JSON payloads, wraps outcomes in runtime tool-result objects, updates instance state for subsequent workflow steps, and raises explicit errors on invalid or unsupported states.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        folder_path = self.resolve_desktop_path(args.path)
        if not folder_path.exists():
            raise ValueError(f"Folder does not exist: {folder_path}")
        if not folder_path.is_dir():
            raise ValueError(f"Path is not a directory: {folder_path}")

        self.should_open_desktop_view = True
        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "path": str(folder_path),
                    "current_folder": str(folder_path),
                    "reason": args.reason,
                },
                ensure_ascii=False,
            ),
            should_open_desktop_view=True,
        )

    def click_desktop_folder(self, args: ClickDesktopFolderArgs) -> ToolResult:
        """
        Click desktop folder.
        Key behavior: serializes JSON payloads, wraps outcomes in runtime tool-result objects, updates instance state for subsequent workflow steps, and raises explicit errors on invalid or unsupported states.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        folder_path = self.resolve_desktop_path(args.path)
        if not folder_path.exists():
            raise ValueError(f"Folder does not exist: {folder_path}")
        if not folder_path.is_dir():
            raise ValueError(f"Path is not a directory: {folder_path}")

        self.should_open_desktop_view = True
        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "path": str(folder_path),
                    "reason": args.reason,
                    "opened": True,
                },
                ensure_ascii=False,
            ),
            should_open_desktop_view=True,
        )

    def move_cursor(self, args: MoveCursorArgs) -> ToolResult:
        """
        Move cursor.
        Key behavior: serializes JSON payloads, wraps outcomes in runtime tool-result objects, and updates instance state for subsequent workflow steps.
        Returns a `ToolResult` payload for the runtime tool pipeline.
        """
        self.should_open_desktop_view = True
        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "target": args.target,
                    "reason": args.reason,
                    "click": args.click,
                },
                ensure_ascii=False,
            ),
            should_open_desktop_view=True,
        )
