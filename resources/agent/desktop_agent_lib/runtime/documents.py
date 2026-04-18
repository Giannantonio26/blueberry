from __future__ import annotations

import io
import json
import re
import textwrap
import time
import unicodedata
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from ..core.agent_utils import get_latest_user_message
from ..core.models import (
    ExcelSheet,
    GeneratedDocumentDraft,
    GeneratedPresentationDraft,
    GeneratedWorkbookDraft,
    PowerPointSlide,
    WriteExcelFileArgs,
    WritePdfFileArgs,
    WritePowerPointFileArgs,
    WriteTextFileArgs,
    WriteWordFileArgs,
)
from ..core.llm_api import call_llm


class DocumentFormatMixin:
    GROUNDED_WRITER_MAX_ATTEMPTS = 3

    def coerce_grounded_writer_payload(
        self,
        schema: type[GeneratedDocumentDraft]
        | type[GeneratedPresentationDraft]
        | type[GeneratedWorkbookDraft],
        payload: Any,
    ) -> Any:
        """
        Coerce grounded writer payload.
        Returns a `Any` result.
        """
        if not isinstance(payload, (dict, list)):
            return payload

        if isinstance(payload, dict):
            for wrapper_key in ("document", "draft", "result", "data"):
                wrapped_payload = payload.get(wrapper_key)
                if isinstance(wrapped_payload, (dict, list)):
                    return self.coerce_grounded_writer_payload(schema, wrapped_payload)

            if schema is GeneratedDocumentDraft:
                for wrapper_key in ("files", "documents", "items"):
                    wrapped_payload = payload.get(wrapper_key)
                    if isinstance(wrapped_payload, list):
                        return self.coerce_grounded_writer_payload(schema, wrapped_payload)
            return payload

        if schema is GeneratedDocumentDraft and payload:
            first_item = payload[0]
            if isinstance(first_item, dict):
                if any(
                    key in first_item for key in ("title", "content", "paragraphs")
                ):
                    return {
                        "title": first_item.get("title"),
                        "content": first_item.get("content"),
                        "paragraphs": first_item.get("paragraphs") or [],
                    }
                if "content" in first_item:
                    return {
                        "title": None,
                        "content": first_item.get("content"),
                        "paragraphs": [],
                    }

        return payload

    def format_specific_writer_guidance(self, output_format: str) -> str:
        """
        Format specific writer guidance.
        Returns the resulting text value.
        """
        normalized_format = (output_format or "").strip().lower()
        format_rules: dict[str, str] = {
            "txt": (
                "For .txt output, deliver a final document-quality draft in plain text only, "
                "with clear section labels, complete sentences, and readable paragraph spacing."
            ),
            "md": (
                "For .md output, use a clean heading hierarchy, short informative paragraphs, "
                "and focused bullet lists without filler."
            ),
            "csv": (
                "For .csv output, produce strict comma-separated rows with one header row, "
                "stable column ordering, and no commentary outside table cells."
            ),
            "json": (
                "For .json output, produce syntactically valid JSON content only, "
                "using double-quoted keys and strings, no trailing commas, and consistent key naming."
            ),
            "html": (
                "For .html output, produce valid semantic HTML with meaningful headings, "
                "well-structured sections, escaped text content, and no script tags unless explicitly requested."
            ),
            "xml": (
                "For .xml output, produce well-formed XML with a single root element, "
                "consistent child structure, and escaped special characters throughout."
            ),
            "word": (
                "For .docx output, produce publication-ready prose with a concise title, logical sections, "
                "clear transitions, and no markdown markers."
            ),
            "pdf": (
                "For .pdf output, produce a concise title and a substantive multi-paragraph body with strong section flow. "
                "Use PDF-safe characters: avoid emoji and uncommon symbols, use plain punctuation, and spell out symbols as words when needed."
            ),
            "powerpoint": (
                "For .pptx output, create a coherent deck with informative slide titles, "
                "concise bullets, one core idea per slide, and explicit takeaway wording."
            ),
            "excel": (
                "For .xlsx output, create practical tabular sheets with short sheet names, "
                "a header row in each sheet, and clear row-wise values that can be used directly."
            ),
        }
        return format_rules.get(
            normalized_format,
            "Use clean, structured, publication-ready output for the requested format.",
        )

    def normalize_document_text(
        self,
        value: str | None,
        *,
        strip_markdown: bool = False,
        ascii_punctuation: bool = True,
    ) -> str:
        """
        Normalize document text into a canonical form for downstream logic.
        Key behavior: applies regex-based parsing or normalization.
        Returns the resulting text value.
        """
        if not isinstance(value, str):
            return ""

        normalized = unicodedata.normalize("NFKC", value)
        replacements = {
            "\u00a0": " ",
            "\u200b": "",
            "\u200c": "",
            "\u200d": "",
            "\ufeff": "",
            "\u2022": "-",
            "\u2013": "-",
            "\u2014": "-",
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
            "\u2026": "...",
            "\u00c2 ": " ",
            "\u00c2": "",
        }
        for raw, clean in replacements.items():
            normalized = normalized.replace(raw, clean)

        if ascii_punctuation:
            punctuation_replacements = {
                "\u2022": "-",
                "\u2013": "-",
                "\u2014": "-",
                "\u2018": "'",
                "\u2019": "'",
                "\u201c": '"',
                "\u201d": '"',
                "\u2026": "...",
            }
            for raw, clean in punctuation_replacements.items():
                normalized = normalized.replace(raw, clean)

        if strip_markdown:
            normalized = re.sub(r"(?m)^\s{0,3}[-*_]{3,}\s*$", "", normalized)
            normalized = re.sub(r"\*\*(.+?)\*\*", r"\1", normalized)
            normalized = re.sub(r"__(.+?)__", r"\1", normalized)
            normalized = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", normalized)

        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"[ \t]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)

        cleaned_lines = [line.strip() for line in normalized.split("\n")]
        return "\n".join(cleaned_lines).strip()

    def normalize_document_paragraphs(
        self,
        paragraphs: list[str] | None,
        *,
        strip_markdown: bool = False,
        ascii_punctuation: bool = True,
    ) -> list[str]:
        """
        Normalize document paragraphs into a canonical form for downstream logic.
        Returns an ordered collection of computed items.
        """
        cleaned_paragraphs: list[str] = []
        for paragraph in paragraphs or []:
            cleaned = self.normalize_document_text(
                paragraph,
                strip_markdown=strip_markdown,
                ascii_punctuation=ascii_punctuation,
            )
            if cleaned:
                cleaned_paragraphs.append(cleaned)
        return cleaned_paragraphs

    def normalize_pdf_safe_text(self, value: str | None) -> str:
        """
        Normalize PDF safe text into a canonical form for downstream logic.
        Key behavior: applies regex-based parsing or normalization.
        Returns the resulting text value.
        """
        normalized = self.normalize_document_text(
            value,
            strip_markdown=True,
            ascii_punctuation=True,
        )
        if not normalized:
            return ""

        symbol_replacements = {
            "€": "EUR",
            "£": "GBP",
            "¥": "JPY",
            "₹": "INR",
            "₿": "BTC",
            "©": "(c)",
            "®": "(R)",
            "™": "TM",
            "°": " deg",
            "±": "+/-",
            "×": "x",
            "÷": "/",
            "≤": "<=",
            "≥": ">=",
            "→": "->",
            "←": "<-",
            "↔": "<->",
            "✅": "done",
            "❌": "not done",
        }
        for raw, clean in symbol_replacements.items():
            normalized = normalized.replace(raw, clean)

        normalized = unicodedata.normalize("NFKD", normalized)
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^\x20-\x7E\n]", " ", normalized)
        normalized = re.sub(r"[ \t]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        normalized_lines = [line.strip() for line in normalized.split("\n")]
        return "\n".join(normalized_lines).strip()

    def normalize_pdf_safe_paragraphs(
        self,
        paragraphs: list[str] | None,
    ) -> list[str]:
        """
        Normalize PDF safe paragraphs into a canonical form for downstream logic.
        Returns an ordered collection of computed items.
        """
        safe_paragraphs: list[str] = []
        for paragraph in paragraphs or []:
            safe_text = self.normalize_pdf_safe_text(paragraph)
            if safe_text:
                safe_paragraphs.append(safe_text)
        return safe_paragraphs

    def grounded_writer_style_rules(
        self,
        *,
        allow_markup: bool = False,
        pdf_safe: bool = False,
    ) -> str:
        """
        Handle grounded writer style rules for the current workflow.
        Returns the resulting text value.
        """
        format_rule = (
            "Markdown or markup syntax is allowed only when the requested target format explicitly needs it."
            if allow_markup
            else "Do not emit Markdown or markup syntax such as **bold**, # headings, or --- separators."
        )
        pdf_rule = (
            "For PDF-targeted drafts, keep text glyph-safe: avoid emoji and uncommon symbols, prefer plain ASCII punctuation, and replace symbols with words when needed."
            if pdf_safe
            else ""
        )
        return (
            "Write the final output in one coherent language throughout. "
            "Unless the user explicitly requested another language, use the same language as the latest user request. "
            "Translate or paraphrase foreign-language source material into the output language instead of mixing languages across the draft. "
            "Never copy garbled or mojibake source text into the result. If a source fragment contains corrupted characters, rewrite it into clean natural language or paraphrase it without the corruption. "
            f"{format_rule} "
            f"{pdf_rule} "
            "Use precise headings and complete paragraphs; avoid repetitive filler and unsupported claims. "
            "Prefer clean, publication-ready prose over article-by-article dumps or raw source excerpts."
        )

    def grounded_writer_source_rules(self, *, output_format: str | None = None) -> str:
        """
        Handle grounded writer source rules for the current workflow.
        Returns the resulting text value.
        """
        normalized_format = (output_format or "").strip().lower()
        if normalized_format == "excel":
            return (
                "Do not include source metadata in workbook output. "
                "Do not add source, citation, reference, or source URL/title/domain columns. "
                "Do not include inline citation keys like [S1] in Excel cell values."
            )

        if normalized_format == "csv":
            return (
                "Ground every factual data row with source metadata from retrieved chunks. "
                "Add a source column for each row and populate it with citation keys like [S1] or [S1,S3]. "
                "If useful, also include source title or source URL in dedicated columns. "
                "Use only citation keys present in retrieved chunks."
            )

        if normalized_format == "powerpoint":
            return (
                "Ground every factual sentence or bullet with inline citation keys using this format: [S1] or [S1,S3]. "
                "Append citation keys at the end of each factual sentence or bullet. "
                "Use only keys from retrieved chunks. "
                "Add a final Sources slide mapping every cited key to source_title and source_url."
            )

        return (
            "Ground every factual sentence with inline citation keys using this format: [S1] or [S1,S3]. "
            "Append citation keys at the end of each factual sentence. "
            "Use only keys from retrieved chunks. "
            "Include a final Sources section that maps every cited key to source_title and source_url."
        )

    def build_text_file_content(
        self,
        title: str | None = None,
        content: str | None = None,
        paragraphs: list[str] | None = None,
    ) -> str:
        """
        Build text file content.
        Returns the resulting text value.
        """
        segments: list[str] = []
        clean_title = self.normalize_document_text(title)
        clean_content = self.normalize_document_text(content)
        clean_paragraphs = self.normalize_document_paragraphs(paragraphs)
        if clean_title:
            segments.append(clean_title)
        if clean_content:
            segments.append(clean_content)
        segments.extend(clean_paragraphs)
        return "\n\n".join(segments).strip()

    def build_word_paragraphs(
        self,
        title: str | None = None,
        content: str | None = None,
        paragraphs: list[str] | None = None,
    ) -> list[str]:
        """
        Build word paragraphs.
        Returns an ordered collection of computed items.
        """
        compiled_paragraphs: list[str] = []
        clean_title = self.normalize_document_text(
            title,
            strip_markdown=True,
        )
        if clean_title:
            compiled_paragraphs.append(clean_title)

        clean_content = self.normalize_document_text(
            content,
            strip_markdown=True,
        )
        if clean_content:
            compiled_paragraphs.extend(
                [
                    segment.strip()
                    for segment in re.split(r"\r?\n+", clean_content)
                    if segment.strip()
                ]
            )

        compiled_paragraphs.extend(
            self.normalize_document_paragraphs(
                paragraphs,
                strip_markdown=True,
            )
        )
        return compiled_paragraphs

    def build_recent_conversation_excerpt(self, *, limit: int = 8) -> str:
        """
        Build recent conversation excerpt.
        Returns the resulting text value.
        """
        excerpt_lines: list[str] = []
        for message in self.agent_input.messages[-limit:]:
            content = message.content.strip()
            if not content:
                continue
            excerpt_lines.append(f"{message.role}: {content}")
        return "\n".join(excerpt_lines)

    def format_retrieved_chunks_for_prompt(self) -> str:
        """
        Format retrieved chunks for prompt.
        Returns the resulting text value.
        """
        if not self.retrieved_chunks:
            return "No retrieved chunks were available for this step."

        formatted_chunks: list[str] = []
        for index, chunk in enumerate(self.retrieved_chunks, start=1):
            citation_key = f"S{index}"
            similarity_text = (
                f"{chunk.similarity:.6f}" if chunk.similarity is not None else "unknown"
            )
            formatted_chunks.append(
                (
                    f"[Chunk {index} | CitationKey={citation_key}]\n"
                    f"chunk_id: {chunk.chunk_id}\n"
                    f"source_title: {chunk.source_title}\n"
                    f"source_url: {chunk.source_url}\n"
                    f"source_domain: {chunk.source_domain or 'unknown'}\n"
                    f"similarity: {similarity_text}\n"
                    f"text:\n{chunk.text}"
                )
            )
        return "\n\n".join(formatted_chunks)

    def resolve_writer_model(self) -> str:
        """
        Resolve writer model.
        Returns the resulting text value.
        """
        configured_writer_model = (self.agent_input.writer_model or "").strip()
        if configured_writer_model:
            return configured_writer_model
        return self.agent_input.model

    def has_nonempty_document_body(
        self,
        content: str | None,
        paragraphs: list[str] | None,
    ) -> bool:
        """
        Check whether nonempty document body.
        Returns `True` when the condition is satisfied, otherwise `False`.
        """
        normalized_content = self.normalize_document_text(
            content,
            strip_markdown=True,
        )
        normalized_paragraphs = self.normalize_document_paragraphs(
            paragraphs,
            strip_markdown=True,
        )
        return bool(normalized_content or normalized_paragraphs)

    def normalize_presentation_slides(
        self,
        slides: list[PowerPointSlide] | None,
    ) -> list[PowerPointSlide]:
        """
        Normalize presentation slides into a canonical form for downstream logic.
        Returns an ordered collection of computed items.
        """
        normalized_slides: list[PowerPointSlide] = []
        for slide in slides or []:
            normalized_title = self.normalize_document_text(
                slide.title,
                strip_markdown=True,
            )
            normalized_content = self.normalize_document_text(
                slide.content,
                strip_markdown=True,
            )
            normalized_bullets = self.normalize_document_paragraphs(
                slide.bullets,
                strip_markdown=True,
            )
            if normalized_title or normalized_content or normalized_bullets:
                normalized_slides.append(
                    PowerPointSlide(
                        title=normalized_title,
                        content=normalized_content,
                        bullets=normalized_bullets,
                    )
                )
        return normalized_slides

    def sanitize_workbook_sheets(
        self,
        sheets: list[ExcelSheet] | None,
    ) -> list[ExcelSheet]:
        """
        Sanitize workbook sheets into a safe, normalized representation.
        Key behavior: applies regex-based parsing or normalization.
        Returns an ordered collection of computed items.
        """
        citation_key_pattern = re.compile(
            r"\[(?:\s*S\d+\s*)(?:,\s*S\d+\s*)*\]",
            flags=re.IGNORECASE,
        )

        def strip_inline_citation_keys(cell_value: str) -> str:
            """
            Handle strip inline citation keys for the current workflow.
            Key behavior: applies regex-based parsing or normalization.
            Returns the resulting text value.
            """
            without_citations = citation_key_pattern.sub("", cell_value)
            without_citations = re.sub(r"\s+([,;:.])", r"\1", without_citations)
            return re.sub(r"\s{2,}", " ", without_citations).strip()

        source_like_header_pattern = re.compile(
            r"\b(source|citation|reference|provenance|evidence)\b",
            flags=re.IGNORECASE,
        )

        def is_source_like_header(header_value: str) -> bool:
            """
            Check whether source like header.
            Key behavior: applies regex-based parsing or normalization.
            Returns `True` when the condition is satisfied, otherwise `False`.
            """
            normalized_header = re.sub(
                r"[\s_\-]+",
                " ",
                (header_value or "").strip().lower(),
            )
            return bool(normalized_header and source_like_header_pattern.search(normalized_header))

        sanitized_sheets: list[ExcelSheet] = []
        for index, sheet in enumerate(sheets or [], start=1):
            sheet_name = self.normalize_document_text(sheet.name) or f"Sheet{index}"
            normalized_rows: list[list[str]] = []
            for row in sheet.rows:
                if not isinstance(row, list):
                    continue
                normalized_row = [
                    strip_inline_citation_keys(
                        self.normalize_document_text(str(cell))
                    )
                    if cell is not None
                    else ""
                    for cell in row
                ]
                if any(cell for cell in normalized_row):
                    normalized_rows.append(normalized_row)
            if normalized_rows:
                header_row = normalized_rows[0]
                source_column_indexes = {
                    column_index
                    for column_index, header_value in enumerate(header_row)
                    if is_source_like_header(header_value)
                }
                if source_column_indexes:
                    filtered_rows: list[list[str]] = []
                    for row in normalized_rows:
                        filtered_row = [
                            cell
                            for column_index, cell in enumerate(row)
                            if column_index not in source_column_indexes
                        ]
                        if any(cell for cell in filtered_row):
                            filtered_rows.append(filtered_row)
                    normalized_rows = filtered_rows
            if normalized_rows:
                sanitized_sheets.append(ExcelSheet(name=sheet_name, rows=normalized_rows))
        return sanitized_sheets

    def validate_pdf_file_args(self, args: WritePdfFileArgs) -> str | None:
        """
        Validate PDF file arguments against runtime rules and constraints.
        Returns a `str | None` result.
        """
        normalized_title = self.normalize_pdf_safe_text(args.title)
        normalized_content = self.normalize_pdf_safe_text(args.content)
        normalized_paragraphs = self.normalize_pdf_safe_paragraphs(args.paragraphs)
        if normalized_content or normalized_paragraphs:
            return None
        if normalized_title:
            return (
                "The PDF draft has a title but no document body. "
                "Provide non-empty content or paragraphs."
            )
        return (
            "The PDF draft must include at least one non-empty title, content block, "
            "or paragraph."
        )

    def validate_word_file_args(self, args: WriteWordFileArgs) -> str | None:
        """
        Validate word file arguments against runtime rules and constraints.
        Returns a `str | None` result.
        """
        normalized_title = self.normalize_document_text(
            args.title,
            strip_markdown=True,
        )
        if normalized_title or self.has_nonempty_document_body(args.content, args.paragraphs):
            return None
        return (
            "The Word draft must include at least one non-empty title, content block, "
            "or paragraph."
        )

    def validate_text_file_args(self, args: WriteTextFileArgs) -> str | None:
        """
        Validate text file arguments against runtime rules and constraints.
        Returns a `str | None` result.
        """
        normalized_content = self.normalize_document_text(args.content)
        if normalized_content:
            return None
        return "The text-based draft must include non-empty content."

    def validate_powerpoint_file_args(
        self,
        args: WritePowerPointFileArgs,
        *,
        minimum_slide_count: int = 1,
    ) -> str | None:
        """
        Validate powerpoint file arguments against runtime rules and constraints.
        Returns a `str | None` result.
        """
        normalized_slides = self.normalize_presentation_slides(args.slides)
        normalized_title = self.normalize_document_text(
            args.title,
            strip_markdown=True,
        )
        normalized_content = self.normalize_document_text(
            args.content,
            strip_markdown=True,
        )
        if normalized_title or normalized_content:
            return None
        if len(normalized_slides) < minimum_slide_count:
            if minimum_slide_count == 1:
                return "The PowerPoint draft must include at least one non-empty slide."
            return "The PowerPoint draft must include at least two non-empty slides when no slide payload was provided."
        return None

    def validate_excel_file_args(self, args: WriteExcelFileArgs) -> str | None:
        """
        Validate excel file arguments against runtime rules and constraints.
        Returns a `str | None` result.
        """
        sanitized_sheets = self.sanitize_workbook_sheets(args.sheets)
        if not sanitized_sheets:
            return None
        return None

    def extract_json_candidate_from_text(self, raw_content: str) -> str | None:
        """
        Extract JSON candidate from text.
        Key behavior: applies regex-based parsing or normalization.
        Returns a `str | None` result.
        """
        normalized = (raw_content or "").strip()
        if not normalized:
            return None

        fenced_match = re.search(
            r"```(?:json)?\s*(.*?)```",
            normalized,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if fenced_match:
            fenced_content = fenced_match.group(1).strip()
            if fenced_content:
                normalized = fenced_content

        for opener, closer in (("{", "}"), ("[", "]")):
            start_index = normalized.find(opener)
            if start_index < 0:
                continue
            depth = 0
            in_string = False
            escaping = False
            for index in range(start_index, len(normalized)):
                character = normalized[index]
                if in_string:
                    if escaping:
                        escaping = False
                    elif character == "\\":
                        escaping = True
                    elif character == '"':
                        in_string = False
                    continue

                if character == '"':
                    in_string = True
                    continue
                if character == opener:
                    depth += 1
                    continue
                if character == closer:
                    depth -= 1
                    if depth == 0:
                        return normalized[start_index : index + 1].strip()
            continue

        return None

    def parse_grounded_writer_payload(self, raw_content: str) -> Any:
        """
        Parse grounded writer payload.
        Key behavior: parses JSON payloads and raises explicit errors on invalid or unsupported states.
        Returns a `Any` result.
        """
        normalized = (raw_content or "").strip()
        if not normalized:
            raise ValueError("Writer response did not include a JSON payload.")

        candidate_payloads: list[str] = []
        primary_candidate = self.extract_json_candidate_from_text(normalized)
        if primary_candidate:
            candidate_payloads.append(primary_candidate)

        for opener in ("{", "["):
            start_index = -1
            while True:
                start_index = normalized.find(opener, start_index + 1)
                if start_index < 0:
                    break
                candidate = self.extract_json_candidate_from_text(normalized[start_index:])
                if candidate and candidate not in candidate_payloads:
                    candidate_payloads.append(candidate)

        if not candidate_payloads:
            raise ValueError("Writer response did not include a JSON payload.")

        last_error: json.JSONDecodeError | None = None
        for candidate in candidate_payloads:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as error:
                last_error = error
                continue

        if last_error is not None:
            raise ValueError(f"Writer returned invalid JSON: {last_error}") from last_error
        raise ValueError("Writer response did not include a JSON payload.")

    def build_writer_retry_feedback(self, issue: str) -> str:
        """
        Build writer retry feedback.
        Returns the resulting text value.
        """
        normalized_issue = " ".join((issue or "").split()).strip() or "unknown issue"
        return (
            "Return corrected JSON matching the schema exactly. "
            "Do not include markdown fences, prose, comments, or extra keys. "
            f"Issue to fix: {normalized_issue}"
        )

    def call_grounded_writer(
        self,
        *,
        schema: type[GeneratedDocumentDraft]
        | type[GeneratedPresentationDraft]
        | type[GeneratedWorkbookDraft],
        system_prompt: str,
        tool_payload: dict[str, Any],
        retry_feedback: str | None = None,
    ) -> GeneratedDocumentDraft | GeneratedPresentationDraft | GeneratedWorkbookDraft:
        """
        Handle call grounded writer for the current workflow.
        Key behavior: serializes JSON payloads and calls the configured LLM endpoint.
        Returns a `GeneratedDocumentDraft | GeneratedPresentationDraft | GeneratedWorkbookDraft` result.
        """
        latest_user_request = get_latest_user_message(self.agent_input.messages)
        recent_conversation = self.build_recent_conversation_excerpt()
        retrieved_context = self.format_retrieved_chunks_for_prompt()

        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if retry_feedback:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "The previous structured writer output was invalid. "
                        "Fix the specific issue below and return corrected JSON only.\n\n"
                        f"Correction:\n{retry_feedback}"
                    ),
                }
            )
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Latest user request:\n{latest_user_request or 'None'}\n\n"
                    f"Recent conversation:\n{recent_conversation or 'None'}\n\n"
                    f"Writing tool payload:\n{json.dumps(tool_payload, ensure_ascii=False)}\n\n"
                    f"Most relevant retrieved chunks (with source metadata and citation keys):\n{retrieved_context}"
                ),
            }
        )

        response = call_llm(
            self.agent_input.api_key,
            self.agent_input.base_url,
            {
                "model": self.resolve_writer_model(),
                "messages": messages,
                "stream": False,
                "format": schema.model_json_schema(),
            },
        )

        raw_content = (response.get("message", {}).get("content") or "").strip()
        parsed_content = self.parse_grounded_writer_payload(raw_content)
        normalized_payload = self.coerce_grounded_writer_payload(schema, parsed_content)
        return schema.model_validate(normalized_payload)

    def prepare_text_file_from_retrieved_chunks(
        self,
        args: WriteTextFileArgs,
        *,
        target_format: str | None = None,
    ) -> WriteTextFileArgs:
        """
        Prepare text file from retrieved chunks.
        Returns a `WriteTextFileArgs` result.
        """
        normalized_format = (target_format or "").strip().lower()
        allow_markup = normalized_format in {"md", "markdown", "html", "xml"}
        retry_feedback: str | None = None
        for _ in range(self.GROUNDED_WRITER_MAX_ATTEMPTS):
            try:
                generated = self.call_grounded_writer(
                    schema=GeneratedDocumentDraft,
                    system_prompt=(
                        "You generate grounded text-file drafts for a desktop agent. "
                        "Return JSON matching the schema. "
                        "You own the full content and structure of the output. "
                        "Use retrieved chunks as the factual source of truth. "
                        "Use the writing tool payload and conversation only for target format, tone, and output requirements. "
                        "Write a polished final draft, not planning notes. "
                        "Structure the content so it is immediately usable by a human reader. "
                        "If the retrieved chunks are empty, rely on the explicit user request and tool payload only, and do not invent unsupported external facts. "
                        f"{self.format_specific_writer_guidance(normalized_format)} "
                        f"{self.grounded_writer_source_rules(output_format=normalized_format)} "
                        f"{self.grounded_writer_style_rules(allow_markup=allow_markup)}"
                    ),
                    tool_payload={"path": args.path, "content": args.content},
                    retry_feedback=retry_feedback,
                )
            except Exception as error:
                retry_feedback = self.build_writer_retry_feedback(str(error))
                continue

            candidate = WriteTextFileArgs(
                path=args.path,
                content=self.build_text_file_content(
                    title=generated.title,
                    content=generated.content,
                    paragraphs=generated.paragraphs,
                ),
            )
            validation_error = self.validate_text_file_args(candidate)
            if not validation_error:
                return candidate
            retry_feedback = self.build_writer_retry_feedback(validation_error)

        return WriteTextFileArgs(
            path=args.path,
            content=self.normalize_document_text(args.content),
        )

    def prepare_word_file_from_retrieved_chunks(
        self, args: WriteWordFileArgs
    ) -> WriteWordFileArgs:
        """
        Prepare word file from retrieved chunks.
        Returns a `WriteWordFileArgs` result.
        """
        retry_feedback: str | None = None
        for _ in range(self.GROUNDED_WRITER_MAX_ATTEMPTS):
            try:
                generated = self.call_grounded_writer(
                    schema=GeneratedDocumentDraft,
                    system_prompt=(
                        "You generate grounded Word-document drafts for a desktop agent. "
                        "Return JSON matching the schema. "
                        "You own the full content and structure of the document. "
                        "Use retrieved chunks as the factual basis for the document. "
                        "Use tool payload hints only for path, title preference, tone, and scope. "
                        "Prefer a complete polished draft unless the user asked for brevity. "
                        "A title-only document is invalid; include a substantive body. "
                        "Use a clear intro, sectioned middle, and concise closing when appropriate for the request. "
                        "Do not invent unsupported facts. "
                        f"{self.format_specific_writer_guidance('word')} "
                        f"{self.grounded_writer_source_rules(output_format='word')} "
                        f"{self.grounded_writer_style_rules()}"
                    ),
                    tool_payload={
                        "path": args.path,
                        "title": args.title,
                        "content": args.content,
                        "paragraphs": args.paragraphs,
                    },
                    retry_feedback=retry_feedback,
                )
            except Exception as error:
                retry_feedback = self.build_writer_retry_feedback(str(error))
                continue

            candidate = WriteWordFileArgs(
                path=args.path,
                title=self.normalize_document_text(
                    generated.title or args.title,
                    strip_markdown=True,
                )
                or None,
                content=self.normalize_document_text(
                    generated.content,
                    strip_markdown=True,
                )
                or None,
                paragraphs=self.normalize_document_paragraphs(
                    generated.paragraphs,
                    strip_markdown=True,
                ),
            )
            validation_error = self.validate_word_file_args(candidate)
            if not validation_error:
                return candidate
            retry_feedback = self.build_writer_retry_feedback(validation_error)

        return WriteWordFileArgs(
            path=args.path,
            title=self.normalize_document_text(
                args.title,
                strip_markdown=True,
            )
            or None,
            content=self.normalize_document_text(
                args.content,
                strip_markdown=True,
            )
            or None,
            paragraphs=self.normalize_document_paragraphs(
                args.paragraphs,
                strip_markdown=True,
            ),
        )

    def prepare_pdf_file_from_retrieved_chunks(
        self, args: WritePdfFileArgs
    ) -> WritePdfFileArgs:
        """
        Prepare PDF file from retrieved chunks.
        Returns a `WritePdfFileArgs` result.
        """
        retry_feedback: str | None = None
        for _ in range(self.GROUNDED_WRITER_MAX_ATTEMPTS):
            try:
                generated = self.call_grounded_writer(
                    schema=GeneratedDocumentDraft,
                    system_prompt=(
                        "You generate grounded PDF-document drafts for a desktop agent. "
                        "Return JSON matching the schema. "
                        "You own the full content and structure of the document. "
                        "Use retrieved chunks as the factual basis. "
                        "Use the writing tool payload only as output-shape guidance. "
                        "Prefer clean prose and complete sections unless the user asked for brevity. "
                        "A title-only PDF is invalid; include a substantive body with multiple paragraphs. "
                        "Keep wording presentation-safe for PDF rendering: no emoji, no decorative symbols, and no mojibake fragments. "
                        "Do not invent unsupported facts. "
                        f"{self.format_specific_writer_guidance('pdf')} "
                        f"{self.grounded_writer_source_rules(output_format='pdf')} "
                        f"{self.grounded_writer_style_rules(pdf_safe=True)}"
                    ),
                    tool_payload={
                        "path": args.path,
                        "title": args.title,
                        "content": args.content,
                        "paragraphs": args.paragraphs,
                    },
                    retry_feedback=retry_feedback,
                )
            except Exception as error:
                retry_feedback = self.build_writer_retry_feedback(str(error))
                continue

            candidate = WritePdfFileArgs(
                path=args.path,
                title=self.normalize_pdf_safe_text(
                    generated.title or args.title,
                )
                or None,
                content=self.normalize_pdf_safe_text(
                    generated.content,
                )
                or None,
                paragraphs=self.normalize_pdf_safe_paragraphs(
                    generated.paragraphs,
                ),
            )
            validation_error = self.validate_pdf_file_args(candidate)
            if not validation_error:
                return candidate
            retry_feedback = self.build_writer_retry_feedback(validation_error)

        return WritePdfFileArgs(
            path=args.path,
            title=self.normalize_pdf_safe_text(args.title) or None,
            content=self.normalize_pdf_safe_text(args.content) or None,
            paragraphs=self.normalize_pdf_safe_paragraphs(args.paragraphs),
        )

    def prepare_powerpoint_file_from_retrieved_chunks(
        self, args: WritePowerPointFileArgs
    ) -> WritePowerPointFileArgs:
        """
        Prepare powerpoint file from retrieved chunks.
        Returns a `WritePowerPointFileArgs` result.
        """
        minimum_slide_count = 1
        retry_feedback: str | None = None
        for _ in range(self.GROUNDED_WRITER_MAX_ATTEMPTS):
            try:
                generated = self.call_grounded_writer(
                    schema=GeneratedPresentationDraft,
                    system_prompt=(
                        "You generate grounded PowerPoint slide decks for a desktop agent. "
                        "Return JSON matching the schema. "
                        "You own the full slide structure and wording. "
                        "Use retrieved chunks as the factual basis for the slides. "
                        "Use the writing tool payload only for structure, tone, and presentation hints. "
                        "Keep slides concise and informative. Generate a real deck with multiple non-empty slides unless the user explicitly asked for a one-slide output. "
                        "Each slide should communicate one strong point and avoid long dense paragraphs. "
                        "An empty slide list is invalid. Do not invent unsupported facts. "
                        f"{self.format_specific_writer_guidance('powerpoint')} "
                        f"{self.grounded_writer_source_rules(output_format='powerpoint')} "
                        f"{self.grounded_writer_style_rules()}"
                    ),
                    tool_payload={
                        "path": args.path,
                        "title": args.title,
                        "content": args.content,
                        "slides": [slide.model_dump(mode='json') for slide in args.slides],
                    },
                    retry_feedback=retry_feedback,
                )
            except Exception as error:
                retry_feedback = self.build_writer_retry_feedback(str(error))
                continue

            normalized_content = self.normalize_document_text(
                args.content,
                strip_markdown=True,
            )
            normalized_slides = self.normalize_presentation_slides(generated.slides)
            normalized_title = self.normalize_document_text(
                generated.title or args.title,
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

            candidate = WritePowerPointFileArgs(
                path=args.path,
                title=normalized_title or None,
                content=normalized_content or None,
                slides=normalized_slides,
            )
            validation_error = self.validate_powerpoint_file_args(
                candidate,
                minimum_slide_count=minimum_slide_count,
            )
            if not validation_error:
                return candidate
            retry_feedback = self.build_writer_retry_feedback(validation_error)

        fallback_title = self.normalize_document_text(
            args.title,
            strip_markdown=True,
        )
        fallback_content = self.normalize_document_text(
            args.content,
            strip_markdown=True,
        )
        fallback_slides = self.normalize_presentation_slides(args.slides)
        if not fallback_slides and fallback_content:
            fallback_slides = [
                PowerPointSlide(
                    title=fallback_title or None,
                    content=fallback_content,
                    bullets=[],
                )
            ]
        return WritePowerPointFileArgs(
            path=args.path,
            title=fallback_title or None,
            content=fallback_content or None,
            slides=fallback_slides,
        )

    def prepare_excel_file_from_retrieved_chunks(
        self, args: WriteExcelFileArgs
    ) -> WriteExcelFileArgs:
        """
        Prepare excel file from retrieved chunks.
        Returns a `WriteExcelFileArgs` result.
        """
        retry_feedback: str | None = None
        for _ in range(self.GROUNDED_WRITER_MAX_ATTEMPTS):
            try:
                generated = self.call_grounded_writer(
                    schema=GeneratedWorkbookDraft,
                    system_prompt=(
                        "You generate grounded Excel workbook payloads for a desktop agent. "
                        "Return JSON matching the schema. "
                        "You own the full workbook structure, headers, and rows. "
                        "Use retrieved chunks as the factual basis for every row. "
                        "Use the tool payload only as structural guidance. "
                        "Prefer compact, useful tables with a header row in each sheet. "
                        "Headers must be specific and rows must be consistent and directly usable. "
                        "Return at least one sheet with a header row and one or more data rows. "
                        "Do not invent unsupported facts. "
                        f"{self.format_specific_writer_guidance('excel')} "
                        f"{self.grounded_writer_source_rules(output_format='excel')}"
                    ),
                    tool_payload={
                        "path": args.path,
                        "sheets": [sheet.model_dump(mode='json') for sheet in args.sheets],
                    },
                    retry_feedback=retry_feedback,
                )
            except Exception as error:
                retry_feedback = self.build_writer_retry_feedback(str(error))
                continue

            candidate = WriteExcelFileArgs(
                path=args.path,
                sheets=self.sanitize_workbook_sheets(generated.sheets),
            )
            validation_error = self.validate_excel_file_args(candidate)
            if not validation_error:
                return candidate
            retry_feedback = self.build_writer_retry_feedback(validation_error)

        fallback_sheets = self.sanitize_workbook_sheets(args.sheets)
        if not fallback_sheets:
            fallback_sheets = [
                ExcelSheet(
                    name=self.normalize_document_text(sheet.name) or f"Sheet{index}",
                    rows=sheet.rows,
                )
                for index, sheet in enumerate(args.sheets, start=1)
            ]
        return WriteExcelFileArgs(
            path=args.path,
            sheets=fallback_sheets,
        )

    def write_docx_file(self, file_path: Path, paragraphs: list[str]) -> None:
        """
        Write DOCX file.
        Key behavior: builds or reads ZIP container content.
        Performs side effects and returns no value.
        """
        document_xml = self.build_docx_document_xml(paragraphs)

        with zipfile.ZipFile(file_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "[Content_Types].xml",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
            )
            archive.writestr(
                "_rels/.rels",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
            )
            archive.writestr("word/document.xml", document_xml)

    def read_docx_text(self, file_path: Path) -> str:
        """
        Read DOCX text.
        Key behavior: builds or reads ZIP container content and raises explicit errors on invalid or unsupported states.
        Returns the resulting text value.
        """
        try:
            with zipfile.ZipFile(file_path) as archive:
                document_xml = archive.read("word/document.xml")
        except KeyError as error:
            raise ValueError(f"The .docx file is missing word/document.xml: {file_path}") from error

        root = ET.fromstring(document_xml)
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraph_texts: list[str] = []

        for paragraph in root.findall(".//w:body/w:p", namespace):
            fragments: list[str] = []
            for node in paragraph.iter():
                if node.tag == "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t":
                    fragments.append(node.text or "")
                elif node.tag == "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}br":
                    fragments.append("\n")

            paragraph_text = "".join(fragments).strip()
            if paragraph_text:
                paragraph_texts.append(paragraph_text)

        return "\n\n".join(paragraph_texts)

    def read_pdf_text(self, file_path: Path) -> str:
        """
        Read PDF text.
        Key behavior: applies regex-based parsing or normalization and raises explicit errors on invalid or unsupported states.
        Returns the resulting text value.
        """
        raw_text = file_path.read_bytes().decode("latin-1", errors="ignore")
        fragments = re.findall(r"\((.*?)(?<!\\)\)\s*Tj", raw_text, flags=re.DOTALL)
        if not fragments:
            raise ValueError(f"The .pdf file does not contain readable text content: {file_path}")

        def unescape_fragment(value: str) -> str:
            """
            Handle unescape fragment for the current workflow.
            Returns the resulting text value.
            """
            restored = (
                value.replace("\\\\", "\\")
                .replace("\\(", "(")
                .replace("\\)", ")")
                .replace("\\r", " ")
                .replace("\\n", " ")
            )
            return restored.strip()

        text_lines = [unescape_fragment(fragment) for fragment in fragments]
        cleaned_lines = [line for line in text_lines if line]
        if not cleaned_lines:
            raise ValueError(f"The .pdf file does not contain readable text content: {file_path}")

        return "\n".join(cleaned_lines)

    def read_pptx_text(self, file_path: Path) -> str:
        """
        Read PPTX text.
        Key behavior: builds or reads ZIP container content and raises explicit errors on invalid or unsupported states.
        Returns the resulting text value.
        """
        slide_pattern = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
        slide_texts: list[str] = []

        with zipfile.ZipFile(file_path) as archive:
            slide_paths = []
            for name in archive.namelist():
                match = slide_pattern.match(name)
                if match:
                    slide_paths.append((int(match.group(1)), name))

            if not slide_paths:
                raise ValueError(f"The .pptx file does not contain readable slides: {file_path}")

            slide_paths.sort(key=lambda item: item[0])
            namespace = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}

            for slide_index, slide_path in slide_paths:
                slide_xml = archive.read(slide_path)
                root = ET.fromstring(slide_xml)
                text_fragments = [
                    (node.text or "").strip()
                    for node in root.findall(".//a:t", namespace)
                    if (node.text or "").strip()
                ]
                if not text_fragments:
                    continue
                slide_texts.append(
                    f"Slide {slide_index}\n" + "\n".join(text_fragments)
                )

        if not slide_texts:
            raise ValueError(f"The .pptx file does not contain readable text content: {file_path}")

        return "\n\n".join(slide_texts)

    def escape_pdf_text(self, value: str) -> str:
        """
        Handle escape PDF text for the current workflow.
        Returns the resulting text value.
        """
        ascii_text = (
            self.normalize_pdf_safe_text(value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        return (
            ascii_text.replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .replace("\r", " ")
            .replace("\n", " ")
        )

    def build_pdf_pages(
        self,
        title: str | None = None,
        content: str | None = None,
        paragraphs: list[str] | None = None,
    ) -> list[list[tuple[int, int, int, str]]]:
        """
        Build PDF pages.
        Returns an ordered collection of computed items.
        """
        pages: list[list[tuple[int, int, int, str]]] = [[]]
        current_page_index = 0
        current_y = 740

        clean_title = self.normalize_pdf_safe_text(title)
        if clean_title:
            pages[current_page_index].append((72, current_y, 20, clean_title))
            current_y -= 32

        body_paragraphs = [
            self.normalize_pdf_safe_text(paragraph)
            for paragraph in self.build_word_paragraphs(
                content=content,
                paragraphs=paragraphs,
            )
        ]
        body_paragraphs = [paragraph for paragraph in body_paragraphs if paragraph]
        line_width = 88
        paragraph_gap = 10
        line_height = 16

        for paragraph in body_paragraphs:
            wrapped_lines = textwrap.wrap(
                paragraph,
                width=line_width,
                replace_whitespace=False,
                drop_whitespace=False,
                break_long_words=True,
            ) or [paragraph]

            for line in wrapped_lines:
                if current_y < 72:
                    pages.append([])
                    current_page_index += 1
                    current_y = 740
                pages[current_page_index].append((72, current_y, 12, line))
                current_y -= line_height

            current_y -= paragraph_gap

        return pages

    def write_pdf_document(
        self,
        file_path: Path,
        title: str | None = None,
        content: str | None = None,
        paragraphs: list[str] | None = None,
    ) -> int:
        """
        Write PDF document.
        Returns a `int` result.
        """
        pages = self.build_pdf_pages(title=title, content=content, paragraphs=paragraphs)
        page_count = max(len(pages), 1)
        font_object_number = 3 + (page_count * 2)
        objects: dict[int, bytes] = {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
        }

        page_object_numbers: list[int] = []
        for page_index, page_operations in enumerate(pages, start=1):
            page_object_number = 1 + (page_index * 2)
            content_object_number = page_object_number + 1
            page_object_numbers.append(page_object_number)

            content_stream = "\n".join(
                (
                    f"BT /F1 {font_size} Tf 1 0 0 1 {x} {y} Tm "
                    f"({self.escape_pdf_text(text)}) Tj ET"
                )
                for x, y, font_size, text in page_operations
            ).encode("latin-1")

            objects[page_object_number] = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_object_number} 0 R >> >> "
                f"/Contents {content_object_number} 0 R >>"
            ).encode("latin-1")
            objects[content_object_number] = (
                f"<< /Length {len(content_stream)} >>\nstream\n".encode("latin-1")
                + content_stream
                + b"\nendstream"
            )

        page_references = " ".join(f"{number} 0 R" for number in page_object_numbers)
        objects[2] = (
            f"<< /Type /Pages /Kids [{page_references}] /Count {page_count} >>"
        ).encode("latin-1")
        objects[font_object_number] = (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
        )

        output = io.BytesIO()
        output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: dict[int, int] = {}
        highest_object_number = max(objects)

        for object_number in range(1, highest_object_number + 1):
            offsets[object_number] = output.tell()
            output.write(f"{object_number} 0 obj\n".encode("latin-1"))
            output.write(objects[object_number])
            output.write(b"\nendobj\n")

        xref_offset = output.tell()
        output.write(f"xref\n0 {highest_object_number + 1}\n".encode("latin-1"))
        output.write(b"0000000000 65535 f \n")
        for object_number in range(1, highest_object_number + 1):
            output.write(f"{offsets[object_number]:010} 00000 n \n".encode("latin-1"))
        output.write(
            (
                f"trailer\n<< /Size {highest_object_number + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF"
            ).encode("latin-1")
        )
        file_path.write_bytes(output.getvalue())
        return page_count

    def build_powerpoint_body_lines(self, slide: PowerPointSlide) -> list[str]:
        """
        Build powerpoint body lines.
        Returns an ordered collection of computed items.
        """
        body_lines: list[str] = []
        if isinstance(slide.content, str) and slide.content.strip():
            body_lines.extend(
                [
                    segment.strip()
                    for segment in re.split(r"\r?\n+", slide.content)
                    if segment.strip()
                ]
            )
        body_lines.extend(
            f"- {bullet.strip()}" for bullet in slide.bullets if bullet.strip()
        )
        return body_lines

    def build_powerpoint_text_paragraph_xml(
        self, lines: list[str], *, font_size: int, bold: bool = False
    ) -> str:
        """
        Build powerpoint text paragraph XML.
        Returns the resulting text value.
        """
        paragraphs = []
        for line in lines:
            paragraphs.append(
                "<a:p>"
                f'<a:r><a:rPr lang="en-US" sz="{font_size}"{" b=\"1\"" if bold else ""}/>'
                f"<a:t>{escape(line)}</a:t></a:r>"
                f'<a:endParaRPr lang="en-US" sz="{font_size}"/>'
                "</a:p>"
            )
        return "".join(paragraphs)

    def build_pptx_slide_xml(self, slide: PowerPointSlide, slide_index: int) -> str:
        """
        Build PPTX slide XML.
        Returns the resulting text value.
        """
        title = (slide.title or "").strip()
        body_lines = self.build_powerpoint_body_lines(slide)
        title_shape = ""
        body_shape = ""

        if title:
            title_shape = """
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="Title %s"/>
          <p:cNvSpPr/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm>
            <a:off x="685800" y="457200"/>
            <a:ext cx="7772400" cy="914400"/>
          </a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
          <a:noFill/>
          <a:ln><a:noFill/></a:ln>
        </p:spPr>
        <p:txBody>
          <a:bodyPr/>
          <a:lstStyle/>
          %s
        </p:txBody>
      </p:sp>""" % (
                slide_index,
                self.build_powerpoint_text_paragraph_xml(
                    [title],
                    font_size=2800,
                    bold=True,
                ),
            )

        if body_lines:
            body_y = "1600200" if title else "685800"
            body_height = "4114800" if title else "5029200"
            body_shape = """
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="3" name="Content %s"/>
          <p:cNvSpPr/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm>
            <a:off x="685800" y="%s"/>
            <a:ext cx="7772400" cy="%s"/>
          </a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
          <a:noFill/>
          <a:ln><a:noFill/></a:ln>
        </p:spPr>
        <p:txBody>
          <a:bodyPr wrap="square"/>
          <a:lstStyle/>
          %s
        </p:txBody>
      </p:sp>""" % (
                slide_index,
                body_y,
                body_height,
                self.build_powerpoint_text_paragraph_xml(body_lines, font_size=1800),
            )

        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld name="Slide %s">
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm>
          <a:off x="0" y="0"/>
          <a:ext cx="0" cy="0"/>
          <a:chOff x="0" y="0"/>
          <a:chExt cx="0" cy="0"/>
        </a:xfrm>
      </p:grpSpPr>%s%s
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr>
    <a:masterClrMapping/>
  </p:clrMapOvr>
</p:sld>""" % (
            slide_index,
            title_shape,
            body_shape,
        )

    def build_presentation_core_xml(self, title: str) -> str:
        """
        Build presentation core XML.
        Returns the resulting text value.
        """
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/"
                   xmlns:dcmitype="http://purl.org/dc/dcmitype/"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>%s</dc:title>
  <dc:creator>Blueberry Desktop Agent</dc:creator>
  <cp:lastModifiedBy>Blueberry Desktop Agent</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>
</cp:coreProperties>""" % (
            escape(title),
            timestamp,
            timestamp,
        )

    def build_presentation_app_xml(
        self, slides: list[PowerPointSlide], presentation_title: str
    ) -> str:
        """
        Build presentation app XML.
        Returns the resulting text value.
        """
        part_titles = "".join(
            f"<vt:lpstr>{escape((slide.title or '').strip() or f'Slide {index}')}</vt:lpstr>"
            for index, slide in enumerate(slides, start=1)
        )
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
            xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Blueberry Browser</Application>
  <PresentationFormat>On-screen Show (4:3)</PresentationFormat>
  <Slides>%s</Slides>
  <Notes>0</Notes>
  <HiddenSlides>0</HiddenSlides>
  <MMClips>0</MMClips>
  <ScaleCrop>false</ScaleCrop>
  <HeadingPairs>
    <vt:vector size="2" baseType="variant">
      <vt:variant><vt:lpstr>Slides</vt:lpstr></vt:variant>
      <vt:variant><vt:i4>%s</vt:i4></vt:variant>
    </vt:vector>
  </HeadingPairs>
  <TitlesOfParts>
    <vt:vector size="%s" baseType="lpstr">%s</vt:vector>
  </TitlesOfParts>
  <Company>Blueberry</Company>
  <Manager>%s</Manager>
  <LinksUpToDate>false</LinksUpToDate>
  <SharedDoc>false</SharedDoc>
  <HyperlinksChanged>false</HyperlinksChanged>
  <AppVersion>1.0</AppVersion>
</Properties>""" % (
            len(slides),
            len(slides),
            len(slides),
            part_titles,
            escape(presentation_title),
        )

    def build_presentation_xml(self, slide_count: int) -> str:
        """
        Build presentation XML.
        Returns the resulting text value.
        """
        slide_entries = "\n    ".join(
            f'<p:sldId id="{255 + index}" r:id="rId{index + 1}"/>'
            for index in range(1, slide_count + 1)
        )
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst>
    <p:sldMasterId id="2147483648" r:id="rId1"/>
  </p:sldMasterIdLst>
  <p:sldIdLst>
    %s
  </p:sldIdLst>
  <p:sldSz cx="9144000" cy="6858000"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>""" % slide_entries

    def build_presentation_rels_xml(self, slide_count: int) -> str:
        """
        Build presentation rels XML.
        Returns the resulting text value.
        """
        relationships = [
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
        ]
        relationships.extend(
            f'<Relationship Id="rId{index + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{index}.xml"/>'
            for index in range(1, slide_count + 1)
        )
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  %s
</Relationships>""" % "\n  ".join(relationships)

    def build_slide_master_xml(self) -> str:
        """
        Build slide master XML.
        Returns the resulting text value.
        """
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" preserve="1">
  <p:cSld name="Blueberry Master">
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm>
          <a:off x="0" y="0"/>
          <a:ext cx="0" cy="0"/>
          <a:chOff x="0" y="0"/>
          <a:chExt cx="0" cy="0"/>
        </a:xfrm>
      </p:grpSpPr>
    </p:spTree>
  </p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2"
            accent1="accent1" accent2="accent2" accent3="accent3"
            accent4="accent4" accent5="accent5" accent6="accent6"
            hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst>
    <p:sldLayoutId id="2147483649" r:id="rId1"/>
  </p:sldLayoutIdLst>
  <p:txStyles>
    <p:titleStyle/>
    <p:bodyStyle/>
    <p:otherStyle/>
  </p:txStyles>
</p:sldMaster>"""

    def build_slide_master_rels_xml(self) -> str:
        """
        Build slide master rels XML.
        Returns the resulting text value.
        """
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>"""

    def build_slide_layout_xml(self) -> str:
        """
        Build slide layout XML.
        Returns the resulting text value.
        """
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
             type="titleAndContent" preserve="1">
  <p:cSld name="Title and Content">
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm>
          <a:off x="0" y="0"/>
          <a:ext cx="0" cy="0"/>
          <a:chOff x="0" y="0"/>
          <a:chExt cx="0" cy="0"/>
        </a:xfrm>
      </p:grpSpPr>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr>
    <a:masterClrMapping/>
  </p:clrMapOvr>
</p:sldLayout>"""

    def build_slide_layout_rels_xml(self) -> str:
        """
        Build slide layout rels XML.
        Returns the resulting text value.
        """
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""

    def build_presentation_theme_xml(self) -> str:
        """
        Build presentation theme XML.
        Returns the resulting text value.
        """
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Blueberry Theme">
  <a:themeElements>
    <a:clrScheme name="Blueberry">
      <a:dk1><a:srgbClr val="172033"/></a:dk1>
      <a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="0F172A"/></a:dk2>
      <a:lt2><a:srgbClr val="F8FAFC"/></a:lt2>
      <a:accent1><a:srgbClr val="2563EB"/></a:accent1>
      <a:accent2><a:srgbClr val="0F766E"/></a:accent2>
      <a:accent3><a:srgbClr val="D97706"/></a:accent3>
      <a:accent4><a:srgbClr val="DC2626"/></a:accent4>
      <a:accent5><a:srgbClr val="7C3AED"/></a:accent5>
      <a:accent6><a:srgbClr val="1D4ED8"/></a:accent6>
      <a:hlink><a:srgbClr val="2563EB"/></a:hlink>
      <a:folHlink><a:srgbClr val="7C3AED"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="Blueberry">
      <a:majorFont>
        <a:latin typeface="Aptos Display"/>
        <a:ea typeface=""/>
        <a:cs typeface=""/>
      </a:majorFont>
      <a:minorFont>
        <a:latin typeface="Aptos"/>
        <a:ea typeface=""/>
        <a:cs typeface=""/>
      </a:minorFont>
    </a:fontScheme>
    <a:fmtScheme name="Blueberry">
      <a:fillStyleLst>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
        <a:solidFill><a:schemeClr val="lt1"/></a:solidFill>
        <a:solidFill><a:schemeClr val="accent1"/></a:solidFill>
      </a:fillStyleLst>
      <a:lnStyleLst>
        <a:ln w="9525"><a:solidFill><a:schemeClr val="dk1"/></a:solidFill></a:ln>
        <a:ln w="25400"><a:solidFill><a:schemeClr val="accent1"/></a:solidFill></a:ln>
        <a:ln w="38100"><a:solidFill><a:schemeClr val="accent2"/></a:solidFill></a:ln>
      </a:lnStyleLst>
      <a:effectStyleLst>
        <a:effectStyle><a:effectLst/></a:effectStyle>
        <a:effectStyle><a:effectLst/></a:effectStyle>
        <a:effectStyle><a:effectLst/></a:effectStyle>
      </a:effectStyleLst>
      <a:bgFillStyleLst>
        <a:solidFill><a:schemeClr val="lt1"/></a:solidFill>
        <a:solidFill><a:schemeClr val="lt2"/></a:solidFill>
        <a:solidFill><a:schemeClr val="dk1"/></a:solidFill>
      </a:bgFillStyleLst>
    </a:fmtScheme>
  </a:themeElements>
  <a:objectDefaults/>
  <a:extraClrSchemeLst/>
</a:theme>"""

    def build_pptx_package(
        self, slides: list[PowerPointSlide], presentation_title: str
    ) -> dict[str, str]:
        """
        Build PPTX package.
        Returns a structured mapping with operation details.
        """
        slide_count = len(slides)
        slide_overrides = "\n  ".join(
            f'<Override PartName="/ppt/slides/slide{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            for index in range(1, slide_count + 1)
        )
        content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  %s
</Types>""" % slide_overrides
        package = {
            "[Content_Types].xml": content_types_xml,
            "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>""",
            "docProps/core.xml": self.build_presentation_core_xml(presentation_title),
            "docProps/app.xml": self.build_presentation_app_xml(
                slides, presentation_title
            ),
            "ppt/presentation.xml": self.build_presentation_xml(slide_count),
            "ppt/_rels/presentation.xml.rels": self.build_presentation_rels_xml(
                slide_count
            ),
            "ppt/slideMasters/slideMaster1.xml": self.build_slide_master_xml(),
            "ppt/slideMasters/_rels/slideMaster1.xml.rels": self.build_slide_master_rels_xml(),
            "ppt/slideLayouts/slideLayout1.xml": self.build_slide_layout_xml(),
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels": self.build_slide_layout_rels_xml(),
            "ppt/theme/theme1.xml": self.build_presentation_theme_xml(),
        }

        for index, slide in enumerate(slides, start=1):
            package[f"ppt/slides/slide{index}.xml"] = self.build_pptx_slide_xml(
                slide, index
            )
            package[f"ppt/slides/_rels/slide{index}.xml.rels"] = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>"""

        return package

    def write_pptx_file(
        self,
        file_path: Path,
        slides: list[PowerPointSlide],
        presentation_title: str,
    ) -> None:
        """
        Write PPTX file.
        Key behavior: builds or reads ZIP container content.
        Performs side effects and returns no value.
        """
        package = self.build_pptx_package(slides, presentation_title)
        with zipfile.ZipFile(file_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for internal_path, content in package.items():
                archive.writestr(internal_path, content)


    def build_docx_document_xml(self, paragraphs: list[str]) -> str:
        """
        Build DOCX document XML.
        Returns the resulting text value.
        """
        paragraph_xml = []
        for paragraph in paragraphs:
            runs = paragraph.split("\n")
            if not runs:
                runs = [paragraph]

            line_runs = []
            for index, line in enumerate(runs):
                line_runs.append(f'<w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r>')
                if index < len(runs) - 1:
                    line_runs.append("<w:r><w:br/></w:r>")

            paragraph_xml.append(f"<w:p>{''.join(line_runs)}</w:p>")

        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    %s
    <w:sectPr>
      <w:pgSz w:w="12240" w:h="15840"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>""" % ("\n    ".join(paragraph_xml))



