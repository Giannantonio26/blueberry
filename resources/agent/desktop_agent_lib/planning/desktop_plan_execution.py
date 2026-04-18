from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.models import AddFileToExistingFolderArgs
from ..runtime import AgentRuntime
from .file_planning import (
    file_type_to_file_action,
    plan_output_path_for_file_action,
)

def _normalize_output_extension(raw_path: str) -> str:
    """
    Normalize output extension into a canonical form for downstream logic.
    Returns the resulting text value.
    """
    return Path(raw_path).suffix.lower().lstrip(".")


def _validate_output_targets_against_request(
    runtime: AgentRuntime,
    planned_paths: list[str],
) -> None:
    """
    Validate output targets against request against runtime rules and constraints.
    Key behavior: raises explicit errors on invalid or unsupported states.
    Performs side effects and returns no value.
    """
    if not planned_paths:
        return

    remaining_output_count = runtime.remaining_requested_output_count()
    if remaining_output_count is not None:
        if len(planned_paths) > remaining_output_count:
            raise ValueError(
                "The planned write action would create more files than the user requested."
            )

    if not runtime.expected_output_extensions:
        return

    planned_extensions = {
        _normalize_output_extension(path)
        for path in planned_paths
        if _normalize_output_extension(path)
    }
    unexpected_extensions = sorted(
        extension
        for extension in planned_extensions
        if extension not in runtime.expected_output_extensions
    )
    if unexpected_extensions:
        raise ValueError(
            "The planned write action includes unrequested output formats: "
            + ", ".join(unexpected_extensions)
            + "."
        )


def get_tool_output_path(
    runtime: AgentRuntime, tool_name: str, arguments: dict[str, Any]
) -> str | None:
    """
    Return tool output path.
    Returns a `str | None` result.
    """
    raw_path = arguments.get("path") if isinstance(arguments.get("path"), str) else None
    if tool_name == "write_word_file":
        return plan_output_path_for_file_action(
            runtime,
            "write_word_file",
            raw_path=raw_path,
            title=arguments.get("title") if isinstance(arguments.get("title"), str) else None,
            content=arguments.get("content") if isinstance(arguments.get("content"), str) else None,
            paragraphs=arguments.get("paragraphs")
            if isinstance(arguments.get("paragraphs"), list)
            else None,
        )
    if tool_name == "write_excel_file":
        return plan_output_path_for_file_action(
            runtime,
            "write_excel_file",
            raw_path=raw_path,
            sheets=arguments.get("sheets") if isinstance(arguments.get("sheets"), list) else None,
        )
    if tool_name == "write_pdf_file":
        return plan_output_path_for_file_action(
            runtime,
            "write_pdf_file",
            raw_path=raw_path,
            title=arguments.get("title") if isinstance(arguments.get("title"), str) else None,
            content=arguments.get("content") if isinstance(arguments.get("content"), str) else None,
            paragraphs=arguments.get("paragraphs")
            if isinstance(arguments.get("paragraphs"), list)
            else None,
        )
    if tool_name == "write_powerpoint_file":
        return plan_output_path_for_file_action(
            runtime,
            "write_powerpoint_file",
            raw_path=raw_path,
            title=arguments.get("title") if isinstance(arguments.get("title"), str) else None,
            slides=arguments.get("slides") if isinstance(arguments.get("slides"), list) else None,
        )
    if tool_name == "write_text_file":
        return plan_output_path_for_file_action(
            runtime,
            "write_text_file",
            raw_path=raw_path,
            content=arguments.get("content") if isinstance(arguments.get("content"), str) else None,
        )
    if tool_name == "write_txt_file":
        return plan_output_path_for_file_action(
            runtime,
            "write_txt_file",
            raw_path=raw_path,
            content=arguments.get("content") if isinstance(arguments.get("content"), str) else None,
        )
    if tool_name == "write_markdown_file":
        return plan_output_path_for_file_action(
            runtime,
            "write_markdown_file",
            raw_path=raw_path,
            content=arguments.get("content") if isinstance(arguments.get("content"), str) else None,
        )
    if tool_name == "write_csv_file":
        return plan_output_path_for_file_action(
            runtime,
            "write_csv_file",
            raw_path=raw_path,
            content=arguments.get("content") if isinstance(arguments.get("content"), str) else None,
        )
    if tool_name == "edit_desktop_file":
        return str(runtime.resolve_desktop_path(raw_path)) if raw_path else None
    if tool_name == "delete_desktop_file":
        return str(runtime.resolve_desktop_path(raw_path)) if raw_path else None
    if tool_name == "add_file_to_existing_folder":
        try:
            validated_arguments = AddFileToExistingFolderArgs.model_validate(arguments)
            file_action = file_type_to_file_action(validated_arguments.file_type)
        except Exception:
            return None
        return plan_output_path_for_file_action(
            runtime,
            file_action,
            raw_path=validated_arguments.file_name,
            destination_folder=validated_arguments.folder_path,
            title=validated_arguments.title,
            content=validated_arguments.content,
            paragraphs=validated_arguments.paragraphs,
            sheets=validated_arguments.sheets,
            slides=validated_arguments.slides,
        )
    if tool_name == "convert_desktop_file_format":
        source_path = (
            arguments.get("source_path")
            if isinstance(arguments.get("source_path"), str)
            else None
        )
        target_format = (
            arguments.get("target_format")
            if isinstance(arguments.get("target_format"), str)
            else None
        )
        output_path = (
            arguments.get("output_path")
            if isinstance(arguments.get("output_path"), str)
            else None
        )
        if not source_path or not target_format:
            return None
        output_file_path, _ = runtime.get_conversion_output_path(
            source_path,
            target_format,
            output_path,
        )
        return str(output_file_path)

    return None


def prepare_tool_arguments_for_execution(
    runtime: AgentRuntime, tool_name: str, arguments: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """
    Prepare tool arguments for execution.
    Returns a `tuple[dict[str, Any], list[str]]` result.
    """
    updated_arguments = dict(arguments)

    target_path = get_tool_output_path(runtime, tool_name, arguments)
    if not target_path:
        return updated_arguments, []

    if tool_name in {
        "write_text_file",
        "write_txt_file",
        "write_markdown_file",
        "write_csv_file",
        "write_word_file",
        "write_excel_file",
        "write_pdf_file",
        "write_powerpoint_file",
        "add_file_to_existing_folder",
    }:
        _validate_output_targets_against_request(runtime, [target_path])

    if tool_name == "convert_desktop_file_format":
        updated_arguments["output_path"] = target_path
    elif tool_name == "add_file_to_existing_folder":
        folder_path = (
            arguments.get("folder_path")
            if isinstance(arguments.get("folder_path"), str)
            else None
        )
        if folder_path:
            folder = runtime.resolve_desktop_path(folder_path)
            try:
                relative_name = str(Path(target_path).relative_to(folder))
            except ValueError:
                relative_name = Path(target_path).name
            updated_arguments["file_name"] = relative_name
    else:
        updated_arguments["path"] = target_path
    return updated_arguments, [target_path]
