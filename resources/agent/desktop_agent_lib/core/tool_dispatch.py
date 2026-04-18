from __future__ import annotations

import json
from typing import Any

from .models import *
from .protocol import emit_protocol_message, read_protocol_message
from ..runtime import AgentRuntime


def normalize_tool_arguments(arguments: Any) -> dict[str, Any]:
    """
    Normalize tool arguments into a canonical form for downstream logic.
    Key behavior: parses JSON payloads and raises explicit errors on invalid or unsupported states.
    Returns a structured mapping with operation details.
    """
    if arguments is None:
        return {}

    if isinstance(arguments, dict):
        return arguments

    if isinstance(arguments, str):
        parsed = json.loads(arguments)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("Tool arguments must resolve to an object.")

    raise ValueError("Tool arguments were not in a supported format.")


def execute_host_tool_request(tool_name: str, arguments: dict[str, Any]) -> ToolResult:
    """
    Execute host tool request.
    Key behavior: serializes JSON payloads, exchanges protocol messages with the host runtime, wraps outcomes in runtime tool-result objects, and raises explicit errors on invalid or unsupported states.
    Returns a `ToolResult` payload for the runtime tool pipeline.
    """
    request_id = f"host-tool-{tool_name}-{abs(hash(json.dumps(arguments, sort_keys=True, ensure_ascii=True))) % 10_000_000}"
    emit_protocol_message(
        {
            "type": "host_tool_request",
            "request_id": request_id,
            "tool_name": tool_name,
            "arguments": arguments,
        }
    )

    response = read_protocol_message()
    if response.get("type") != "host_tool_response":
        raise ValueError(f"Host tool {tool_name} returned an invalid response payload.")

    if response.get("request_id") != request_id:
        raise ValueError(f"Host tool {tool_name} returned a mismatched response id.")

    content = response.get("content")
    if not isinstance(content, str):
        raise ValueError(f"Host tool {tool_name} did not return string content.")

    changed_paths = response.get("changed_paths")
    normalized_paths = (
        [path for path in changed_paths if isinstance(path, str)]
        if isinstance(changed_paths, list)
        else []
    )
    metadata = response.get("metadata")
    normalized_metadata = metadata if isinstance(metadata, dict) else {}

    return ToolResult(
        content=content,
        filesystem_changed=bool(response.get("filesystem_changed")),
        changed_paths=normalized_paths,
        should_open_desktop_view=bool(response.get("should_open_desktop_view")),
        metadata=normalized_metadata,
    )


def parse_tool_result_content(content: str) -> dict[str, Any]:
    """
    Parse tool result content.
    Key behavior: parses JSON payloads.
    Returns a structured mapping with operation details.
    """
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def execute_tool(runtime: AgentRuntime, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
    """
    Execute tool.
    Key behavior: exchanges protocol messages with the host runtime and raises explicit errors on invalid or unsupported states.
    Returns a `ToolResult` payload for the runtime tool pipeline.
    """
    if tool_name == "read_web_page":
        return runtime.read_web_page(ReadWebPageArgs.model_validate(arguments))
    if tool_name == "google_search_and_collect":
        validated_arguments = GoogleSearchAndCollectArgs.model_validate(arguments)
        return execute_host_tool_request(
            "google_search_and_collect",
            validated_arguments.model_dump(mode="json"),
        )
    if tool_name == "retrieve_relevant_chunks":
        validated_arguments = RetrieveRelevantChunksArgs.model_validate(arguments)
        selection_result = execute_host_tool_request(
            "select_retrieval_sources",
            {
                "query": validated_arguments.query,
                "available_source_domains": runtime.list_retrieval_source_domains(),
            },
        )
        selection_payload = parse_tool_result_content(selection_result.content)
        if selection_payload.get("status") == "cancelled":
            return selection_result

        raw_selected_source_domains = selection_payload.get("selected_source_domains")
        selected_source_domains = (
            [
                source_domain.strip()
                for source_domain in raw_selected_source_domains
                if isinstance(source_domain, str) and source_domain.strip()
            ]
            if isinstance(raw_selected_source_domains, list)
            else None
        )
        return runtime.retrieve_relevant_chunks(
            validated_arguments,
            selected_source_domains=selected_source_domains,
        )
    if tool_name == "close_agent_session":
        return runtime.close_agent_session(CloseAgentSessionArgs.model_validate(arguments))
    if tool_name == "list_desktop_entries":
        return runtime.list_desktop_entries(ListDesktopEntriesArgs.model_validate(arguments))
    if tool_name == "read_desktop_file":
        return runtime.read_desktop_file(ReadDesktopFileArgs.model_validate(arguments))
    if tool_name == "read_desktop_file_if_exists":
        return runtime.read_desktop_file_if_exists(
            ReadDesktopFileIfExistsArgs.model_validate(arguments)
        )
    if tool_name == "create_folder":
        return runtime.create_folder(CreateFolderArgs.model_validate(arguments))
    if tool_name == "write_text_file":
        return runtime.write_text_file(WriteTextFileArgs.model_validate(arguments))
    if tool_name == "write_txt_file":
        return runtime.write_txt_file(WriteTxtFileArgs.model_validate(arguments))
    if tool_name == "write_markdown_file":
        return runtime.write_markdown_file(
            WriteMarkdownFileArgs.model_validate(arguments)
        )
    if tool_name == "write_csv_file":
        return runtime.write_csv_file(WriteCsvFileArgs.model_validate(arguments))
    if tool_name == "write_word_file":
        return runtime.write_word_file(WriteWordFileArgs.model_validate(arguments))
    if tool_name == "write_excel_file":
        return runtime.write_excel_file(WriteExcelFileArgs.model_validate(arguments))
    if tool_name == "write_pdf_file":
        return runtime.write_pdf_file(WritePdfFileArgs.model_validate(arguments))
    if tool_name == "write_powerpoint_file":
        return runtime.write_powerpoint_file(
            WritePowerPointFileArgs.model_validate(arguments)
        )
    if tool_name == "add_file_to_existing_folder":
        return runtime.add_file_to_existing_folder(
            AddFileToExistingFolderArgs.model_validate(arguments)
        )
    if tool_name == "edit_desktop_file":
        return runtime.edit_desktop_file(EditDesktopFileArgs.model_validate(arguments))
    if tool_name == "delete_desktop_file":
        return runtime.delete_desktop_file(DeleteDesktopFileArgs.model_validate(arguments))
    if tool_name == "convert_desktop_file_format":
        return runtime.convert_desktop_file_format(
            ConvertDesktopFileFormatArgs.model_validate(arguments)
        )
    if tool_name == "show_desktop_view":
        return runtime.show_desktop_view(ShowDesktopViewArgs.model_validate(arguments))
    if tool_name == "show_desktop_folder":
        return runtime.show_desktop_folder(ShowDesktopFolderArgs.model_validate(arguments))
    if tool_name == "click_desktop_folder":
        return runtime.click_desktop_folder(ClickDesktopFolderArgs.model_validate(arguments))
    if tool_name == "move_cursor":
        return runtime.move_cursor(MoveCursorArgs.model_validate(arguments))

    raise ValueError(f"Unknown tool: {tool_name}")



