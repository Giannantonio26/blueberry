from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from ..core.models import ExcelSheet


class SpreadsheetFormatMixin:
    MIN_EXCEL_COLUMN_WIDTH = 8.0
    MAX_EXCEL_COLUMN_WIDTH = 80.0
    EXCEL_COLUMN_WIDTH_PADDING = 2.0

    def read_csv_rows(self, file_path: Path) -> list[list[str]]:
        """
        Read CSV rows.
        Key behavior: performs local file I/O.
        Returns an ordered collection of computed items.
        """
        raw_text = file_path.read_text(encoding="utf-8", errors="replace")
        return [row for row in csv.reader(io.StringIO(raw_text))]

    def parse_xlsx_shared_strings(self, archive: zipfile.ZipFile) -> list[str]:
        """
        Parse XLSX shared strings.
        Returns an ordered collection of computed items.
        """
        try:
            shared_strings_xml = archive.read("xl/sharedStrings.xml")
        except KeyError:
            return []

        root = ET.fromstring(shared_strings_xml)
        namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        shared_strings: list[str] = []
        for item in root.findall(".//main:si", namespace):
            fragments = [node.text or "" for node in item.findall(".//main:t", namespace)]
            shared_strings.append("".join(fragments))
        return shared_strings

    def column_index_from_reference(self, cell_reference: str) -> int:
        """
        Handle column index from reference for the current workflow.
        Key behavior: applies regex-based parsing or normalization.
        Returns a `int` result.
        """
        match = re.match(r"([A-Z]+)", cell_reference or "")
        if not match:
            return 0

        column_name = match.group(1)
        index = 0
        for character in column_name:
            index = (index * 26) + (ord(character) - 64)
        return index

    def read_xlsx_worksheet_rows(
        self,
        archive: zipfile.ZipFile,
        worksheet_path: str,
        shared_strings: list[str],
    ) -> list[list[str]]:
        """
        Read XLSX worksheet rows.
        Returns an ordered collection of computed items.
        """
        worksheet_xml = archive.read(worksheet_path)
        root = ET.fromstring(worksheet_xml)
        namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows: list[list[str]] = []

        for row in root.findall(".//main:sheetData/main:row", namespace):
            row_values: list[str] = []
            next_column_index = 1

            for cell in row.findall("main:c", namespace):
                cell_reference = cell.get("r") or ""
                column_index = self.column_index_from_reference(cell_reference) or next_column_index
                while len(row_values) < column_index - 1:
                    row_values.append("")

                cell_type = cell.get("t")
                if cell_type == "inlineStr":
                    fragments = [node.text or "" for node in cell.findall(".//main:t", namespace)]
                    cell_value = "".join(fragments)
                else:
                    value_node = cell.find("main:v", namespace)
                    raw_value = value_node.text if value_node is not None else ""
                    if cell_type == "s":
                        try:
                            shared_index = int(raw_value)
                            cell_value = shared_strings[shared_index]
                        except Exception:
                            cell_value = raw_value or ""
                    elif cell_type == "b":
                        cell_value = "TRUE" if raw_value == "1" else "FALSE"
                    else:
                        cell_value = raw_value or ""

                row_values.append(cell_value)
                next_column_index = column_index + 1

            rows.append(row_values)

        return rows

    def read_xlsx_sheets(self, file_path: Path) -> list[ExcelSheet]:
        """
        Read XLSX sheets.
        Key behavior: builds or reads ZIP container content.
        Returns an ordered collection of computed items.
        """
        with zipfile.ZipFile(file_path) as archive:
            shared_strings = self.parse_xlsx_shared_strings(archive)
            workbook_xml = archive.read("xl/workbook.xml")
            workbook_rels_xml = archive.read("xl/_rels/workbook.xml.rels")

            workbook_root = ET.fromstring(workbook_xml)
            workbook_rels_root = ET.fromstring(workbook_rels_xml)
            main_namespace = {
                "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
                "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
            }

            relationship_targets: dict[str, str] = {}
            for relationship in workbook_rels_root.findall(
                "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
            ):
                relationship_id = relationship.get("Id")
                target = relationship.get("Target") or ""
                if not relationship_id:
                    continue

                normalized_target = target.lstrip("/")
                if not normalized_target.startswith("xl/"):
                    normalized_target = f"xl/{normalized_target.lstrip('./')}"
                relationship_targets[relationship_id] = normalized_target

            sheets: list[ExcelSheet] = []
            for sheet in workbook_root.findall(".//main:sheets/main:sheet", main_namespace):
                sheet_name = sheet.get("name") or "Sheet"
                relationship_id = sheet.get(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                )
                worksheet_path = relationship_targets.get(relationship_id or "")
                if not worksheet_path:
                    continue

                rows = self.read_xlsx_worksheet_rows(
                    archive,
                    worksheet_path,
                    shared_strings,
                )
                sheets.append(ExcelSheet(name=sheet_name, rows=rows))

        return sheets

    def rows_to_csv_text(self, rows: list[list[Any]]) -> str:
        """
        Handle rows to CSV text for the current workflow.
        Returns the resulting text value.
        """
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for row in rows:
            writer.writerow(["" if cell is None else str(cell) for cell in row])
        return buffer.getvalue().strip()

    def rows_to_tabbed_text(self, rows: list[list[Any]]) -> str:
        """
        Handle rows to tabbed text for the current workflow.
        Returns the resulting text value.
        """
        return "\n".join(
            "\t".join("" if cell is None else str(cell) for cell in row)
            for row in rows
        ).strip()

    def rows_to_markdown_table(self, rows: list[list[Any]]) -> str:
        """
        Handle rows to markdown table for the current workflow.
        Returns the resulting text value.
        """
        if not rows:
            return ""

        column_count = max(len(row) for row in rows)
        normalized_rows = [
            ["" if cell is None else str(cell) for cell in row] + [""] * (column_count - len(row))
            for row in rows
        ]

        def format_row(row: list[str]) -> str:
            """
            Format row.
            Returns the resulting text value.
            """
            return "| " + " | ".join(row) + " |"

        header = normalized_rows[0]
        separator = ["---"] * column_count
        body = normalized_rows[1:]
        lines = [format_row(header), format_row(separator)]
        lines.extend(format_row(row) for row in body)
        return "\n".join(lines).strip()


    def build_xlsx_package(
        self, sheets: list[ExcelSheet]
    ) -> tuple[str, str, dict[str, str], str]:
        """
        Build XLSX package.
        Returns a `tuple[str, str, dict[str, str], str]` result.
        """
        workbook_sheet_xml = []
        workbook_rel_xml = []
        worksheet_files: dict[str, str] = {}
        content_type_overrides = [
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        ]

        for index, sheet in enumerate(sheets, start=1):
            safe_name = self.sanitize_sheet_name(sheet.name or f"Sheet{index}", index)
            workbook_sheet_xml.append(
                f'<sheet name="{escape(safe_name)}" sheetId="{index}" r:id="rId{index}"/>'
            )
            workbook_rel_xml.append(
                f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            )
            worksheet_files[f"xl/worksheets/sheet{index}.xml"] = self.build_worksheet_xml(sheet.rows)
            content_type_overrides.append(
                f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )

        workbook_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    %s
  </sheets>
</workbook>""" % ("\n    ".join(workbook_sheet_xml))

        workbook_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  %s
</Relationships>""" % ("\n  ".join(workbook_rel_xml))

        content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  %s
</Types>""" % ("\n  ".join(content_type_overrides))

        return workbook_xml, workbook_rels_xml, worksheet_files, content_types_xml

    def _cell_text_for_width(self, value: Any) -> str:
        """
        Handle cell text for width for the current workflow.
        Returns the resulting text value.
        """
        if value is None:
            return ""
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        return str(value)

    def estimate_excel_column_widths(self, rows: list[list[Any]]) -> list[float]:
        """
        Handle estimate excel column widths for the current workflow.
        Returns an ordered collection of computed items.
        """
        if not rows:
            return []

        column_count = max((len(row) for row in rows), default=0)
        if column_count <= 0:
            return []

        column_widths: list[float] = []
        for column_index in range(column_count):
            max_line_length = 0
            for row in rows:
                if column_index >= len(row):
                    continue

                text_value = self._cell_text_for_width(row[column_index])
                line_lengths = [len(line) for line in text_value.splitlines()] or [0]
                max_line_length = max(max_line_length, max(line_lengths))

            estimated_width = max_line_length + self.EXCEL_COLUMN_WIDTH_PADDING
            clamped_width = min(
                self.MAX_EXCEL_COLUMN_WIDTH,
                max(self.MIN_EXCEL_COLUMN_WIDTH, float(estimated_width)),
            )
            column_widths.append(round(clamped_width, 2))

        return column_widths

    def build_worksheet_xml(self, rows: list[list[Any]]) -> str:
        """
        Build worksheet XML.
        Returns the resulting text value.
        """
        row_xml = []
        column_widths = self.estimate_excel_column_widths(rows)

        for row_index, row in enumerate(rows, start=1):
            cells = []
            for column_index, value in enumerate(row, start=1):
                cell_ref = f"{self.column_letter(column_index)}{row_index}"
                cells.append(self.build_cell_xml(cell_ref, value))
            row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')

        cols_xml = ""
        if column_widths:
            cols_entries = [
                f'<col min="{column_index}" max="{column_index}" width="{width:.2f}" customWidth="1"/>'
                for column_index, width in enumerate(column_widths, start=1)
            ]
            cols_xml = "  <cols>\n    " + "\n    ".join(cols_entries) + "\n  </cols>\n"

        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
%s  <sheetData>
    %s
  </sheetData>
</worksheet>""" % (cols_xml, "\n    ".join(row_xml))

    def build_cell_xml(self, cell_ref: str, value: Any) -> str:
        """
        Build cell XML.
        Returns the resulting text value.
        """
        if value is None:
            return f'<c r="{cell_ref}"/>'

        if isinstance(value, bool):
            return f'<c r="{cell_ref}" t="b"><v>{1 if value else 0}</v></c>'

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f'<c r="{cell_ref}"><v>{value}</v></c>'

        return (
            f'<c r="{cell_ref}" t="inlineStr"><is><t xml:space="preserve">'
            f"{escape(str(value))}"
            "</t></is></c>"
        )

    def column_letter(self, index: int) -> str:
        """
        Handle column letter for the current workflow.
        Returns the resulting text value.
        """
        result = ""
        current = index
        while current > 0:
            current, remainder = divmod(current - 1, 26)
            result = chr(65 + remainder) + result
        return result

    def sanitize_sheet_name(self, name: str, index: int) -> str:
        """
        Sanitize sheet name into a safe, normalized representation.
        Key behavior: applies regex-based parsing or normalization.
        Returns the resulting text value.
        """
        sanitized = re.sub(r"[\[\]:*?/\\]", "_", name).strip() or f"Sheet{index}"
        return sanitized[:31]

