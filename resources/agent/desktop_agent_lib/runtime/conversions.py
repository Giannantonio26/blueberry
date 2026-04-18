from __future__ import annotations

import re
from pathlib import Path

from ..core.models import ExcelSheet, PowerPointSlide
from ..planning.file_planning import SUPPORTED_CONVERSION_FORMATS


class ConversionPathMixin:
    def normalize_conversion_target_format(self, target_format: str) -> str:
        """
        Normalize conversion target format into a canonical form for downstream logic.
        Key behavior: raises explicit errors on invalid or unsupported states.
        Returns the resulting text value.
        """
        normalized = target_format.strip().lower().lstrip(".")
        aliases = {
            "word": "docx",
            "document": "docx",
            "markdown": "md",
            "text": "txt",
            "plain": "txt",
            "plain-text": "txt",
            "excel": "xlsx",
            "spreadsheet": "xlsx",
            "pdf": "pdf",
            "powerpoint": "pptx",
            "presentation": "pptx",
            "slides": "pptx",
            "slide-deck": "pptx",
        }
        normalized = aliases.get(normalized, normalized)
        suffix = f".{normalized}"
        if suffix not in SUPPORTED_CONVERSION_FORMATS:
            raise ValueError(
                "convert_desktop_file_format only supports target formats docx, txt, md, csv, xlsx, pdf, and pptx."
            )
        return suffix

    def get_conversion_output_path(
        self,
        source_path: str,
        target_format: str,
        output_path: str | None = None,
    ) -> tuple[Path, str]:
        """
        Return conversion output path.
        Key behavior: raises explicit errors on invalid or unsupported states.
        Returns a resolved filesystem path value.
        """
        source_file_path = self.resolve_desktop_path(source_path)
        target_suffix = self.normalize_conversion_target_format(target_format)

        if source_file_path.suffix.lower() == target_suffix:
            raise ValueError(
                f"The source file is already in {target_suffix} format. Choose a different target format."
            )

        if output_path and output_path.strip():
            output_file_path = self.resolve_desktop_path(output_path.strip())
            if output_file_path.suffix.lower() != target_suffix:
                output_file_path = output_file_path.with_suffix(target_suffix)
        else:
            output_file_path = source_file_path.with_suffix(target_suffix)

        return self.resolve_unique_file_path(output_file_path), target_suffix

    def build_conversion_text_from_sheets(self, sheets: list[ExcelSheet]) -> str:
        """
        Build conversion text from sheets.
        Returns the resulting text value.
        """
        sections: list[str] = []
        include_sheet_headings = len(sheets) > 1

        for index, sheet in enumerate(sheets, start=1):
            rows = sheet.rows or []
            table_text = self.rows_to_tabbed_text(rows)
            sheet_name = (sheet.name or f"Sheet{index}").strip() or f"Sheet{index}"

            if include_sheet_headings:
                sections.append(f"Sheet: {sheet_name}")
            if table_text:
                sections.append(table_text)

        return "\n\n".join(section for section in sections if section.strip()).strip()

    def build_conversion_markdown_from_sheets(self, sheets: list[ExcelSheet]) -> str:
        """
        Build conversion markdown from sheets.
        Returns the resulting text value.
        """
        sections: list[str] = []
        include_sheet_headings = len(sheets) > 1

        for index, sheet in enumerate(sheets, start=1):
            rows = sheet.rows or []
            table_markdown = self.rows_to_markdown_table(rows)
            sheet_name = (sheet.name or f"Sheet{index}").strip() or f"Sheet{index}"

            if include_sheet_headings:
                sections.append(f"## {sheet_name}")
            if table_markdown:
                sections.append(table_markdown)

        return "\n\n".join(section for section in sections if section.strip()).strip()

    def chunk_conversion_lines(
        self, lines: list[str], *, max_lines_per_chunk: int
    ) -> list[list[str]]:
        """
        Handle chunk conversion lines for the current workflow.
        Returns an ordered collection of computed items.
        """
        cleaned_lines = [line.strip() for line in lines if line.strip()]
        if not cleaned_lines:
            return [[]]

        return [
            cleaned_lines[index : index + max_lines_per_chunk]
            for index in range(0, len(cleaned_lines), max_lines_per_chunk)
        ]

    def build_conversion_slides_from_text(
        self,
        presentation_title: str,
        source_text: str,
    ) -> list[PowerPointSlide]:
        """
        Build conversion slides from text.
        Returns an ordered collection of computed items.
        """
        raw_lines = [
            segment.strip()
            for segment in re.split(r"\r?\n+", source_text)
            if segment.strip()
        ]
        slide_chunks = self.chunk_conversion_lines(raw_lines, max_lines_per_chunk=6)
        slides: list[PowerPointSlide] = []

        for index, chunk in enumerate(slide_chunks, start=1):
            slide_title = presentation_title if index == 1 else f"{presentation_title} ({index})"
            slides.append(
                PowerPointSlide(
                    title=slide_title,
                    content="\n".join(chunk).strip() or presentation_title,
                )
            )

        return slides or [PowerPointSlide(title=presentation_title, content=presentation_title)]

    def build_conversion_slides_from_sheets(
        self,
        sheets: list[ExcelSheet],
        presentation_title: str,
    ) -> list[PowerPointSlide]:
        """
        Build conversion slides from sheets.
        Returns an ordered collection of computed items.
        """
        slides: list[PowerPointSlide] = []
        include_sheet_names = len(sheets) > 1

        for index, sheet in enumerate(sheets, start=1):
            sheet_name = (sheet.name or f"Sheet{index}").strip() or f"Sheet{index}"
            table_lines = [
                line.strip()
                for line in self.rows_to_markdown_table(sheet.rows or []).splitlines()
                if line.strip()
            ]
            slide_chunks = self.chunk_conversion_lines(
                table_lines or ["(Empty sheet)"],
                max_lines_per_chunk=8,
            )

            for chunk_index, chunk in enumerate(slide_chunks, start=1):
                if include_sheet_names:
                    slide_title = sheet_name
                else:
                    slide_title = presentation_title
                if chunk_index > 1:
                    slide_title = f"{slide_title} ({chunk_index})"

                slides.append(
                    PowerPointSlide(
                        title=slide_title,
                        content="\n".join(chunk),
                    )
                )

        return slides or [PowerPointSlide(title=presentation_title, content=presentation_title)]
