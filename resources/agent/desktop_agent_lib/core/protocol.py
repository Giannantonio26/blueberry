from __future__ import annotations

import json
import sys
from typing import Any


def emit_protocol_message(payload: dict[str, Any]) -> None:
    """
    Handle emit protocol message for the current workflow.
    Key behavior: serializes JSON payloads.
    Performs side effects and returns no value.
    """
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def read_protocol_message() -> dict[str, Any]:
    """
    Read protocol message.
    Key behavior: parses JSON payloads.
    Returns a structured mapping with operation details.
    """
    line = sys.stdin.readline()
    if not line:
        return {}

    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def get_file_creation_label(tool_name: str) -> str:
    """
    Return file creation label.
    Returns the resulting text value.
    """
    if tool_name == "write_txt_file":
        return "Creating TXT file"
    if tool_name == "write_markdown_file":
        return "Creating Markdown file"
    if tool_name == "write_csv_file":
        return "Creating CSV file"
    if tool_name == "write_word_file":
        return "Creating Word file"
    if tool_name == "write_excel_file":
        return "Creating Excel file"
    if tool_name == "write_pdf_file":
        return "Creating PDF file"
    if tool_name == "write_powerpoint_file":
        return "Creating PowerPoint file"
    if tool_name == "add_file_to_existing_folder":
        return "Adding file to existing folder"
    if tool_name == "write_text_file":
        return "Creating text file"
    if tool_name == "edit_desktop_file":
        return "Replacing file with updated content"
    if tool_name == "delete_desktop_file":
        return "Deleting file"
    if tool_name == "convert_desktop_file_format":
        return "Converting file format and replacing original file"
    return "Creating file"


def request_file_confirmation(tool_name: str, path: str) -> bool:
    """
    Request file confirmation.
    Key behavior: exchanges protocol messages with the host runtime.
    Returns a boolean status for the requested check or operation.
    """
    emit_protocol_message(
        {
            "type": "event",
            "event": "confirmation_request",
            "tool_name": tool_name,
            "path": path,
            "message": get_file_creation_label(tool_name),
        }
    )

    response = read_protocol_message()
    return response.get("type") == "confirmation_response" and bool(response.get("approved"))



def emit_tool_call(tool_name: str, arguments: dict[str, Any]) -> None:
    """
    Handle emit tool call for the current workflow.
    Key behavior: exchanges protocol messages with the host runtime.
    Performs side effects and returns no value.
    """
    emit_protocol_message(
        {
            "type": "event",
            "event": "tool_call",
            "tool_name": tool_name,
            "arguments": arguments,
        }
    )


def tool_requires_file_confirmation(tool_name: str) -> bool:
    """
    Handle tool requires file confirmation for the current workflow.
    Returns a boolean status for the requested check or operation.
    """
    return tool_name in {
        "write_text_file",
        "write_txt_file",
        "write_markdown_file",
        "write_csv_file",
        "write_word_file",
        "write_excel_file",
        "write_pdf_file",
        "write_powerpoint_file",
        "add_file_to_existing_folder",
        "edit_desktop_file",
        "delete_desktop_file",
        "convert_desktop_file_format",
    }


def format_confirmation_paths(paths: list[str]) -> str:
    """
    Format confirmation paths.
    Returns the resulting text value.
    """
    if not paths:
        return ""
    if len(paths) == 1:
        return paths[0]

    preview = "\n".join(
        f"{index}. {path}" for index, path in enumerate(paths[:8], start=1)
    )
    if len(paths) > 8:
        preview += f"\n... and {len(paths) - 8} more."
    return preview



