from __future__ import annotations

import re
from typing import Literal

from .models import HistoryMessage


DesktopRequiredActionKind = Literal[
    "write_output",
    "edit_file",
    "convert_file",
    "create_folder",
    "mutation",
]

OUTPUT_FILE_TERMS_PATTERN = (
    r"(file|files|document|documents|report|reports|spreadsheet|spreadsheets|excel|xlsx|csv|word|docx|pdf|powerpoint|presentation|presentations|slide|slides|ppt|pptx|markdown|md|txt|json|html|xml)"
)

NUMBER_WORDS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

EXPLICIT_OUTPUT_FORMAT_PATTERN = re.compile(
    r"\b("
    r"docx|word|pdf|xlsx|xls|excel|spreadsheet|workbook|"
    r"pptx|ppt|powerpoint|presentation|deck|slides?|"
    r"csv|markdown|md|txt|plain text"
    r")\b",
    flags=re.IGNORECASE,
)
EXPLICIT_FILE_EXTENSION_PATTERN = re.compile(
    r"\b[\w\-\s]+\.[a-z0-9]{1,8}\b",
    flags=re.IGNORECASE,
)
NON_DOCUMENT_TEXT_OUTPUT_HINT_PATTERN = re.compile(
    r"\b("
    r"code|script|python|javascript|typescript|java|sql|yaml|yml|toml|"
    r"json|xml|html|css|scss|config|env|bash|shell|powershell|ts|tsx|js|jsx|py"
    r")\b",
    flags=re.IGNORECASE,
)


def get_latest_user_message(messages: list[HistoryMessage]) -> str:
    """
    Return latest user message.
    Returns the resulting text value.
    """
    for message in reversed(messages):
        if message.role == "user":
            return message.content.strip()
    return ""


def is_desktop_mutation_request(user_request: str) -> bool:
    """
    Check whether desktop mutation request.
    Key behavior: applies regex-based parsing or normalization.
    Returns `True` when the condition is satisfied, otherwise `False`.
    """
    return bool(
        re.search(
            r"(create|write|save|export|generate|build|draft|make|edit|update|convert|reformat|transform).*(file|files|folder|document|report|spreadsheet|excel|xlsx|csv|word|docx|pdf|powerpoint|presentation|slide|slides|ppt|pptx|desktop|markdown|md|txt|json|html|xml|format)"
            r"|"
            r"(file|files|folder|document|report|spreadsheet|excel|xlsx|csv|word|docx|pdf|powerpoint|presentation|slide|slides|ppt|pptx|desktop|markdown|md|txt|json|html|xml|format).*(create|write|save|export|generate|build|draft|make|edit|update|convert|reformat|transform)"
            r"|"
            r"(delete|remove).*(file|files|document|documents|desktop)"
            r"|"
            r"(file|files|document|documents|desktop).*(delete|remove)",
            user_request,
            flags=re.IGNORECASE,
        )
    )


def infer_required_desktop_action_kind(
    user_request: str,
) -> DesktopRequiredActionKind | None:
    """
    Infer required desktop action kind.
    Key behavior: applies regex-based parsing or normalization.
    Returns a `DesktopRequiredActionKind | None` result.
    """
    normalized_request = " ".join(user_request.split()).strip()
    if not normalized_request:
        return None

    lowered_request = normalized_request.lower()

    if re.search(r"\b(convert|reformat|transform)\b", lowered_request) and re.search(
        OUTPUT_FILE_TERMS_PATTERN, lowered_request
    ):
        return "convert_file"

    if re.search(r"\b(delete|remove)\b", lowered_request) and re.search(
        OUTPUT_FILE_TERMS_PATTERN, lowered_request
    ):
        return "mutation"

    if (
        re.search(r"\b(edit|update|revise|rewrite|modify)\b", lowered_request)
        and re.search(OUTPUT_FILE_TERMS_PATTERN, lowered_request)
        and not re.search(
            r"\b(create|write|save|export|generate|build|draft|make)\b",
            lowered_request,
        )
    ):
        return "edit_file"

    if re.search(r"\b(create|make|build|generate)\b", lowered_request) and re.search(
        r"\b(folder|directory)\b", lowered_request
    ) and not re.search(OUTPUT_FILE_TERMS_PATTERN, lowered_request):
        return "create_folder"

    if re.search(
        r"\b(create|write|save|export|generate|build|draft|make)\b",
        lowered_request,
    ) and re.search(OUTPUT_FILE_TERMS_PATTERN, lowered_request):
        return "write_output"

    if is_desktop_mutation_request(normalized_request):
        return "mutation"

    return None


def infer_requested_output_extensions(user_request: str) -> set[str]:
    """
    Infer requested output extensions.
    Returns a `set[str]` result.
    """
    normalized = " ".join(user_request.lower().split())
    if not normalized:
        return set()

    extension_map = {
        "pdf": "pdf",
        "xlsx": "xlsx",
        "xls": "xlsx",
        "excel": "xlsx",
        "spreadsheet": "xlsx",
        "spreadsheets": "xlsx",
        "workbook": "xlsx",
        "workbooks": "xlsx",
        "powerpoint": "pptx",
        "presentation": "pptx",
        "presentations": "pptx",
        "deck": "pptx",
        "decks": "pptx",
        "slide": "pptx",
        "slides": "pptx",
        "pptx": "pptx",
        "ppt": "pptx",
        "docx": "docx",
        "word": "docx",
        "txt": "txt",
        "markdown": "md",
        "md": "md",
        "csv": "csv",
    }
    found: set[str] = set()

    for term, ext in extension_map.items():
        if term in normalized:
            found.add(ext)

    return found


def user_explicitly_mentions_known_output_format(user_request: str) -> bool:
    """
    Handle user explicitly mentions known output format for the current workflow.
    Returns a boolean status for the requested check or operation.
    """
    normalized = " ".join(user_request.split())
    if not normalized:
        return False
    return bool(EXPLICIT_OUTPUT_FORMAT_PATTERN.search(normalized))


def request_mentions_explicit_file_extension(user_request: str) -> bool:
    """
    Request mentions explicit file extension.
    Returns a boolean status for the requested check or operation.
    """
    normalized = " ".join(user_request.split())
    if not normalized:
        return False
    return bool(EXPLICIT_FILE_EXTENSION_PATTERN.search(normalized))


def request_likely_non_document_text_output(user_request: str) -> bool:
    """
    Request likely non document text output.
    Returns a boolean status for the requested check or operation.
    """
    normalized = " ".join(user_request.split())
    if not normalized:
        return False
    return bool(NON_DOCUMENT_TEXT_OUTPUT_HINT_PATTERN.search(normalized))


def parse_requested_output_count(raw_count: str) -> int | None:
    """
    Parse requested output count.
    Returns a `int | None` result.
    """
    normalized = raw_count.strip().lower()
    if not normalized:
        return None
    if normalized.isdigit():
        parsed = int(normalized)
        return parsed if parsed >= 0 else None
    return NUMBER_WORDS.get(normalized)


def infer_requested_output_count(user_request: str) -> int | None:
    """
    Infer requested output count.
    Key behavior: applies regex-based parsing or normalization.
    Returns a `int | None` result.
    """
    normalized = " ".join(user_request.lower().split())
    if not normalized:
        return None

    explicit_count_match = re.search(
        r"\b(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
        r"(?:(?:new|separate|different|requested|desktop|output)\s+)*"
        r"(?:files?|documents?|reports?|briefs?|summaries?|spreadsheets?|workbooks?|"
        r"pdfs?|presentations?|decks?|slides?|powerpoints?)\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if explicit_count_match:
        parsed_count = parse_requested_output_count(
            explicit_count_match.group("count")
        )
        if parsed_count is not None:
            return parsed_count

    inferred_extensions = infer_requested_output_extensions(normalized)
    if len(inferred_extensions) > 1:
        return len(inferred_extensions)

    if re.search(
        r"\b(a|an|one)\s+(?:new\s+)?(?:file|document|report|brief|summary|"
        r"spreadsheet|workbook|presentation|deck|pdf|powerpoint|txt|markdown|csv)\b",
        normalized,
        flags=re.IGNORECASE,
    ):
        return 1

    return None
