from __future__ import annotations

import json
import re
import sys
from typing import Any

from .core.agent_utils import get_latest_user_message, is_desktop_mutation_request
from .core.models import AgentFinal, AgentInput, ToolResult
from .core.llm_api import call_llm
from .core.prompt_config import SYSTEM_PROMPT, TOOLS
from .core.protocol import (
    emit_protocol_message,
    format_confirmation_paths,
    request_file_confirmation,
    tool_requires_file_confirmation,
)
from .core.tool_dispatch import execute_tool, normalize_tool_arguments
from .planning.desktop_plan_execution import prepare_tool_arguments_for_execution
from .runtime import AgentRuntime

DEFAULT_MAX_WEB_SEARCH_STEPS = 7
DEFAULT_MIN_WEB_SEARCH_STEPS = 4
STALL_NO_TOOL_TURNS_FOR_RECOVERY = 3
STALL_NO_TOOL_TURNS_FOR_FORCE_WRITE = 5
MAX_REACT_ITERATIONS = 24
MIN_ITERATION_CAP_RECOVERY_STEPS = 1
MAX_ITERATION_CAP_RECOVERY_STEPS = 8
MAX_SERVER_ERROR_REACT_RETRIES = 2
MAX_SERVER_ERROR_FINAL_RETRIES = 2
DIRECT_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
RESEARCH_INTENT_PATTERN = re.compile(
    r"\b("
    r"latest|recent|current|news|trend|trends|market|markets|"
    r"competitor|competitors|comparison|compare|collect information|"
    r"research|investigate|analysis|analyst|summary|summarize|"
    r"state of|landscape|overview"
    r")\b",
    re.IGNORECASE,
)
WRITE_TOOL_NAMES = {
    "write_text_file",
    "write_txt_file",
    "write_markdown_file",
    "write_csv_file",
    "write_word_file",
    "write_excel_file",
    "write_pdf_file",
    "write_powerpoint_file",
    "add_file_to_existing_folder",
}
RECOVERY_RESTRICTED_INSPECTION_TOOLS = {
    "list_desktop_entries",
    "read_desktop_file",
    "read_desktop_file_if_exists",
}

EXTENSION_TO_WRITE_TOOL = {
    "txt": "write_txt_file",
    "md": "write_markdown_file",
    "csv": "write_csv_file",
    "docx": "write_word_file",
    "xlsx": "write_excel_file",
    "pdf": "write_pdf_file",
    "pptx": "write_powerpoint_file",
}


def format_visited_websites_for_iteration(visited_websites: dict[str, str]) -> str:
    formatted_entries: list[str] = []
    for url, title in visited_websites.items():
        normalized_url = url.strip()
        if not normalized_url:
            continue
        normalized_title = " ".join(title.split()) or normalized_url
        formatted_entries.append(f"- {normalized_url} | {normalized_title}")

    return "\n".join(formatted_entries)


def resolve_configured_web_search_limits(agent_input: AgentInput) -> tuple[int, int]:
    configured_min = agent_input.web_search_limits.min_websites
    configured_max = agent_input.web_search_limits.max_websites

    normalized_min = (
        DEFAULT_MIN_WEB_SEARCH_STEPS
        if configured_min is None
        else max(0, min(50, int(configured_min)))
    )
    normalized_max = (
        DEFAULT_MAX_WEB_SEARCH_STEPS
        if configured_max is None
        else max(0, min(50, int(configured_max)))
    )

    if normalized_max < normalized_min:
        normalized_max = normalized_min

    return normalized_min, normalized_max


def build_react_iteration_messages(
    conversation_messages: list[dict[str, Any]],
    step_number: int,
    web_search_steps: int,
    min_web_search_steps: int,
    max_web_search_steps: int,
    visited_websites: dict[str, str],
    force_write_outputs: bool,
) -> list[dict[str, str | list[Any]]]:
    visited_websites_context = format_visited_websites_for_iteration(visited_websites)
    sections = [
        f"""You are in ReAct iteration {step_number}.
Web research calls used: {web_search_steps}/{max_web_search_steps}.

Decide the single best next step from the current context.""",
        f"""Decision order:
1. If the next step is document creation or update and retrieved chunks are missing or stale, call retrieve_relevant_chunks first.
2. Otherwise, if the task depends on the current page and the current page has not been inspected yet, prefer read_web_page.
3. Otherwise, if the task needs external information beyond the current page, conversation, and vector-store retrieval results, call google_search_and_collect.
4. Otherwise, execute the needed desktop or answer-producing tool.
5. If the current request is complete and no more tool work is needed, call close_agent_session.

Current constraints:
- Use exactly one tool call at most on this turn.
- Clarification questions are allowed only to confirm creating document files in Desktop view.
- Do not ask for sources, links, URLs, websites, article choices, search queries, filenames, folder creation preferences, or generic desktop follow-ups when you can choose them yourself or research yourself.
- Do not ask the user what information should go inside the document, what sections to include, or how to update the document when you already have enough task intent and retrieved context to proceed.
- For required tool parameters, decide explicit values and include them in the tool call instead of leaving them unspecified.
- For document updates, default to a coherent best-effort update based on the user request, retrieved chunks, and existing file context instead of asking for writing guidance.
- If the user provides additional info for document content, prioritize retrieving matching context from the vector store before doing new web search.
- If you feel tempted to ask the user for a source, article, website, URL, or link and the user did not explicitly require a named source, that means you should call google_search_and_collect yourself instead of asking.
- google_search_and_collect reads one new webpage per call and the visited-website cache already prevents revisiting prior URLs.
- For research-backed document creation, {min_web_search_steps} to {max_web_search_steps} good google_search_and_collect calls are usually enough. Prefer drafting after {min_web_search_steps} calls unless clearly material information is still missing. Never exceed {max_web_search_steps}.
- If the request includes a desktop file or folder mutation and you already have enough information, execute it instead of delaying.
- Open Desktop view only on the turn where you are about to execute a Desktop inspection or mutation tool call. Do not open Desktop view during web-search, page-read, or retrieval-only turns.
- If a coherent existing Desktop folder fits the requested output, reuse it instead of creating a new sibling folder.
- For document creation without an explicit destination path, establish the destination folder first (reuse a coherent existing folder or call create_folder) before the first write tool.
- If multiple requested files are about the same topic, prefer one shared folder for the whole set and establish that folder before the first write tool.
- For multi-file outputs without an explicit destination path, do not place files in the Desktop root; keep all outputs inside one dedicated folder.
- For update-existing-file requests, do a single focused target-selection pass (best folder and best file), then call edit_desktop_file. Do not loop on repeated list/read calls for the same candidates.
- If the next step writes files from research, the retrieved chunk cache is the factual basis for writing.
- If the retrieved chunk cache is already ready and no new web research has happened since retrieval, reuse that cache for the remaining requested outputs. Do not call retrieve_relevant_chunks repeatedly before each file.
- Create only the documents explicitly requested by the user. Do not create extra companion files or bonus outputs.
- Use only single-file write tools. Do not call create_multiple_files.
- For multi-file requests, create one requested file per write-tool call and continue until all pending extensions are completed.
- If the user did not explicitly specify output format, choose one explicit format and keep it consistent for this request.
- If using add_file_to_existing_folder, set file_type explicitly and ensure it matches the chosen output format or pending extension.
- If you include assistant text before a tool call, keep it to one short working note and do not present the final answer yet.""",
    ]

    if force_write_outputs:
        sections.append(
            "Forced write mode is active. Do not call google_search_and_collect or read_web_page. "
            "Do not ask clarification questions except explicit confirmation of creating document files in Desktop view. "
            "Immediately retrieve relevant chunks for the pending outputs, then call the appropriate "
            "single write tool to create one remaining requested document at a time. Do not add extra outputs. "
            "When all requested outputs are created, "
            "call close_agent_session."
        )

    if visited_websites_context:
        sections.append(
            "If you generate a new google_search_and_collect query, use the visited website session cache below only to avoid repeating source-specific queries. Do not explicitly reference URLs, domains, publishers, or article titles that already appear there unless the user explicitly asks to revisit them.\n\n"
            "Visited website session cache (URL -> article title):\n"
            f"{visited_websites_context}"
        )

    iteration_instruction = "\n\n".join(sections)

    return [
        *conversation_messages,
        {"role": "system", "content": iteration_instruction},
    ]


def build_final_messages(conversation_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    final_instruction = """
Return only JSON matching the provided schema.

Guidance:
- message is required and must always be a concise plain-language response for the user.
- Set requires_clarification to true only for explicit confirmation of creating document files in Desktop view.
- Do not ask the user to provide sources, article choices, websites, URLs, links, references, or a generic desktop action for open-ended research or file work that the agent should have handled itself.
- Do not ask the user what information to put inside a document or how to update a document when the request already implies the writing objective.
- Never end with a request for a source, article, website, URL, or link unless the user explicitly required a named source and has not provided it.
- If the user asked for a desktop file or folder mutation and no tool result shows that the action happened, do not present the request as completed. Set requires_clarification to true instead.
- Do not claim extra files were created beyond what the user requested.
- If the only thing that happened was opening or preparing the Desktop view, do not use that as the final user-facing message unless the user explicitly asked to open the Desktop view. Summarize the actual completed work instead.
- For research steps, summarize the research progress or retrieved context instead of mentioning Desktop view readiness.
- Set should_open_desktop_view to true when the task concerns files, folders, or desktop actions.
- Set filesystem_changed to true when files or folders were created or updated.
- Include created_or_updated_paths for any created or modified files/folders.
- Set close_agent_session to true when the current request is complete and the session should end.
- Never mention deleting files.
""".strip()

    return [
        *conversation_messages,
        {"role": "user", "content": final_instruction},
    ]


def build_pending_desktop_action_user_message(runtime: AgentRuntime) -> str:
    required_action = runtime.required_desktop_action_kind
    if required_action == "write_output":
        return "The requested Desktop output file has not been created yet."
    if required_action == "edit_file":
        return "The requested Desktop file has not been updated yet."
    if required_action == "convert_file":
        return "The requested Desktop file conversion has not been completed yet."
    if required_action == "create_folder":
        return "The requested Desktop folder has not been created yet."
    return "The requested Desktop file or folder action has not been completed yet."


def format_pending_write_tool_guidance(runtime: AgentRuntime) -> str:
    pending_extensions = sorted(runtime.expected_output_extensions)
    if not pending_extensions:
        return (
            " pending_extensions=unspecified. "
            "Decide one explicit output format now, then call the matching single-file write tool."
        )

    mapped_tools = [
        EXTENSION_TO_WRITE_TOOL[extension]
        for extension in pending_extensions
        if extension in EXTENSION_TO_WRITE_TOOL
    ]
    unique_tools = sorted(set(mapped_tools))
    if unique_tools:
        return (
            f" pending_extensions={','.join(pending_extensions)}. "
            f"Call one matching write tool next: {', '.join(unique_tools)}."
        )

    return (
        f" pending_extensions={','.join(pending_extensions)}. "
        "Call one matching single-file write tool next."
    )


def plan_iteration_cap_recovery_steps(runtime: AgentRuntime) -> int:
    remaining_output_count = runtime.remaining_requested_output_count()
    if remaining_output_count is None:
        remaining_output_count = (
            len(runtime.expected_output_extensions)
            if runtime.expected_output_extensions
            else 1
        )

    return max(
        MIN_ITERATION_CAP_RECOVERY_STEPS,
        min(MAX_ITERATION_CAP_RECOVERY_STEPS, remaining_output_count + 2),
    )


def build_iteration_cap_recovery_system_message(
    runtime: AgentRuntime, steps_left: int
) -> str:
    return (
        f"Iteration-cap recovery mode is active ({steps_left} turn(s) left). "
        "Execution only: no web search, no exploratory loops, and no repeated inspection of the same folder or file. "
        "Decide one best destination folder now (reuse coherent existing folder or create one new folder), lock that choice, "
        "and create the remaining files inside it. "
        "Allowed flow per turn: establish or enter the chosen folder if needed; retrieve_relevant_chunks only if missing; "
        "then call one matching single-file write tool for one pending output. "
        "Repeat write calls until all requested outputs are complete, then call close_agent_session. "
        "Do not re-decide the folder unless a write attempt fails or the user changes scope."
    ) + format_pending_write_tool_guidance(runtime)


def build_pending_desktop_action_system_message(runtime: AgentRuntime) -> str:
    required_action = runtime.required_desktop_action_kind
    if required_action == "write_output":
        if runtime.retrieval_ready_for_write:
            return (
                "The latest user request still requires creating or updating the requested "
                "Desktop output file. The retrieved chunk cache is already ready for writing. "
                "If no destination folder has been established for this output set, establish it first. "
                "Then continue the ReAct loop by calling one appropriate single-file write tool now. Do not end "
                "the turn with text only."
            ) + format_pending_write_tool_guidance(runtime)
        if runtime.visited_websites or runtime.retrieved_chunks:
            return (
                "The latest user request still requires creating or updating the requested "
                "Desktop output file. Continue the ReAct loop. If the retrieved chunk cache is "
                "missing or stale for the exact output you need, call retrieve_relevant_chunks "
                "next. If no destination folder has been established for this output set, establish "
                "it first. Otherwise call one appropriate single-file write tool. Do not end the turn with text only."
            ) + format_pending_write_tool_guidance(runtime)
        return (
            "The latest user request still requires creating or updating the requested Desktop "
            "output file. Continue the ReAct loop by gathering any still-missing research context, "
            "then retrieve relevant chunks, establish the destination folder if needed, then call "
            "one appropriate single-file write tool. Do not end the turn with text only."
        ) + format_pending_write_tool_guidance(runtime)
    if required_action == "edit_file":
        missing_outputs = sorted(runtime.expected_output_extensions)
        suffix = (
            f" Missing outputs: {', '.join(missing_outputs)}."
            if missing_outputs
            else ""
        )
        return (
            "The latest user request still requires editing the target Desktop file. Continue the "
            "ReAct loop by calling edit_desktop_file. If the target path is not fixed yet, choose the "
            "best matching existing file in one focused pass, optionally preview once, then edit it. "
            "Do not keep re-listing or re-reading the same folders/files to re-decide the target unless "
            "an edit attempt failed. Ask one concise clarification question only if an essential edit "
            "detail is genuinely missing."
        ) + suffix
    if required_action == "convert_file":
        missing_outputs = sorted(runtime.expected_output_extensions)
        suffix = (
            f" Missing outputs: {', '.join(missing_outputs)}."
            if missing_outputs
            else ""
        )
        return (
            "The latest user request still requires converting the target Desktop file. Continue "
            "the ReAct loop by calling convert_desktop_file_format, or ask one concise clarification "
            "question only if an essential conversion detail is genuinely missing."
        ) + suffix
    if required_action == "create_folder":
        missing_outputs = sorted(runtime.expected_output_extensions)
        suffix = (
            f" Missing outputs: {', '.join(missing_outputs)}."
            if missing_outputs
            else ""
        )
        return (
            "The latest user request still requires creating the target Desktop folder. Continue "
            "the ReAct loop by calling create_folder, or ask one concise clarification question "
            "only if an essential folder detail is genuinely missing."
        ) + suffix
    missing_outputs = sorted(runtime.expected_output_extensions)
    suffix = (
        f" Missing outputs: {', '.join(missing_outputs)}."
        if missing_outputs
        else ""
    )
    return (
        "The latest user request still requires a real Desktop file or folder action. Continue "
        "the ReAct loop by performing the needed tool action, or ask one concise clarification "
        "question only if an essential requirement is genuinely missing."
    ) + suffix


def looks_like_clarification_question(message_content: str) -> bool:
    normalized = message_content.strip()
    if not normalized:
        return False

    if "?" in normalized:
        return True

    lowered = normalized.lower()
    clarification_markers = (
        "please clarify",
        "please confirm",
        "can you confirm",
        "i need more detail",
        "i need a bit more detail",
        "which ",
        "what ",
        "where ",
        "when ",
        "do you want",
        "should i",
    )
    return any(marker in lowered for marker in clarification_markers)


def looks_like_source_request_clarification(message_content: str) -> bool:
    normalized = " ".join(message_content.split()).strip()
    if not normalized:
        return False

    lowered = normalized.lower()
    source_pattern = re.compile(
        r"\b(source|sources|url|urls|link|links|website|websites|reference|references|article|articles|publisher|publishers|news site|news sites|news source|news sources)\b"
    )
    request_markers = (
        "provide",
        "share",
        "send",
        "give",
        "specify",
        "pick",
        "choose",
        "which",
        "what",
        "another",
        "specific",
        "preferred",
        "paste",
        "tell me",
        "let me know",
        "i need",
        "could you",
        "can you",
        "you'd like",
        "you would like",
    )
    return bool(source_pattern.search(lowered) and any(marker in lowered for marker in request_markers))


def is_recoverable_write_error_message(message: str) -> bool:
    normalized = " ".join((message or "").split()).lower()
    if not normalized:
        return False
    recoverable_markers = (
        "unrequested output formats",
        "planned write action includes unrequested output formats",
        "more files than the user requested",
        "requires non-empty content",
        "could not produce a valid",
        "writer returned invalid json",
        "writer response did not include a json payload",
        "must include at least one non-empty",
    )
    return any(marker in normalized for marker in recoverable_markers)


def is_allowed_desktop_creation_confirmation(message_content: str) -> bool:
    normalized = " ".join(message_content.split()).strip().lower()
    if not normalized or "?" not in normalized:
        return False

    confirmation_markers = (
        "confirm",
        "confirmation",
        "approve",
        "allow",
        "proceed",
    )
    document_markers = (
        "document",
        "file",
        "pdf",
        "docx",
        "xlsx",
        "pptx",
        "report",
        "presentation",
        "spreadsheet",
    )
    desktop_markers = ("desktop", "desktop view")
    create_markers = ("create", "write", "generate", "save")

    return (
        any(marker in normalized for marker in confirmation_markers)
        and any(marker in normalized for marker in document_markers)
        and any(marker in normalized for marker in desktop_markers)
        and any(marker in normalized for marker in create_markers)
    )


def user_explicitly_requires_named_source(user_request: str) -> bool:
    normalized = " ".join(user_request.split()).strip()
    if not normalized:
        return False

    lowered = normalized.lower()
    if DIRECT_URL_PATTERN.search(normalized):
        return True

    explicit_patterns = (
        r"\buse (this|that|the following) (source|sources|url|urls|link|links|website|websites|article|articles)\b",
        r"\bfrom (this|that|the following) (source|url|link|website|article)\b",
        r"\bsummarize (this|that|the following) (source|url|link|website|article)\b",
        r"\buse a specific (source|article|url|website|publisher)\b",
        r"\bmust use\b.*\b(source|article|url|website|publisher)\b",
        r"\bonly use\b.*\b(source|article|url|website|publisher)\b",
        r"\binclude\b.*\b(source|article|url|website|publisher)\b.*\bI gave\b",
        r"\bprovided\b.*\b(source|article|url|website|link)\b",
    )
    return any(re.search(pattern, lowered) for pattern in explicit_patterns)


def request_likely_requires_web_research(user_request: str) -> bool:
    normalized = " ".join(user_request.split()).strip().lower()
    if not normalized:
        return False

    if DIRECT_URL_PATTERN.search(normalized):
        return False

    return bool(RESEARCH_INTENT_PATTERN.search(normalized))


def build_stall_recovery_search_query(user_request: str) -> str:
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "into",
        "from",
        "that",
        "this",
        "your",
        "you",
        "about",
        "create",
        "build",
        "make",
        "generate",
        "write",
        "page",
        "pdf",
        "summary",
    }
    normalized = re.sub(r"[^\w\s-]", " ", user_request)
    tokens = [
        token
        for token in normalized.split()
        if len(token) >= 3 and token.lower() not in stop_words
    ]
    if not tokens:
        fallback = " ".join(user_request.split()).strip()
        return fallback[:160] if fallback else "latest market and competitor news"

    return " ".join(tokens[:12])


def normalize_error_message(error: Exception, *, max_length: int = 260) -> str:
    normalized = " ".join(str(error).split()).strip()
    if not normalized:
        return "unknown error"
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 3]}..."


def is_llm_server_error(error: Exception) -> bool:
    normalized = normalize_error_message(error, max_length=500).lower()
    server_error_markers = (
        "llm api returned a server error",
        "legacy llm provider returned a server error",
        "gemini api returned a server error",
        "internal server error",
        "status 500",
        "status 502",
        "status 503",
        "status 504",
    )
    return any(marker in normalized for marker in server_error_markers)


def build_server_error_retry_system_message(
    error: Exception,
    *,
    retry_number: int,
    max_retries: int,
) -> str:
    return (
        "The latest request could not be completed due to a server error from the LLM API. "
        "Start a new iteration now and continue from the current context. "
        "Keep successful prior tool results; do not redo completed file mutations unless necessary. "
        f"Retry {retry_number}/{max_retries}. Last error: {normalize_error_message(error)}"
    )


def build_final_retry_messages(
    conversation_messages: list[dict[str, Any]],
    forbidden_message: str,
) -> list[dict[str, Any]]:
    correction = (
        "The previous final response asked the user to provide a source, article, website, URL, or link. "
        "That is not allowed here because the user did not explicitly require a named source. "
        "Respond again using the gathered tool results and collected research context already in the conversation. "
        "Do not ask for a source. If some detail is still missing, ask only about essential scope, audience, format, or destination constraints.\n\n"
        f"Forbidden response to replace:\n{forbidden_message}"
    )
    return build_final_messages(
        [
            *conversation_messages,
            {"role": "system", "content": correction},
        ]
    )


def append_tool_result_message(
    messages: list[dict[str, Any]],
    *,
    tool_name: str,
    content: str,
    tool_call_id: str | None = None,
) -> None:
    normalized_content = content if isinstance(content, str) else str(content)
    if tool_call_id and tool_call_id.strip():
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id.strip(),
                "content": normalized_content,
            }
        )
        return

    messages.append(
        {
            "role": "system",
            "content": f"Tool result ({tool_name}):\n{normalized_content}",
        }
    )


def parse_tool_result_payload(result: ToolResult) -> dict[str, Any]:
    try:
        parsed_payload = json.loads(result.content)
    except json.JSONDecodeError:
        return {}
    return parsed_payload if isinstance(parsed_payload, dict) else {}


def coerce_final_payload(final_content: str) -> dict[str, Any]:
    if not final_content:
        return {}

    try:
        parsed_payload = json.loads(final_content)
    except json.JSONDecodeError:
        return {"message": final_content}

    if isinstance(parsed_payload, str):
        return {"message": parsed_payload}

    if isinstance(parsed_payload, dict):
        return parsed_payload

    return {}


def synthesize_final_message(
    parsed_payload: dict[str, Any], runtime: AgentRuntime
) -> str:
    latest_user_request = get_latest_user_message(runtime.agent_input.messages)

    if not runtime.required_desktop_action_satisfied():
        return build_pending_desktop_action_user_message(runtime)

    if parsed_payload.get("requires_clarification"):
        return (
            "I need a bit more detail before I can act. Please clarify the "
            "format, destination, or content."
        )

    if runtime.changed_paths:
        if len(runtime.changed_paths) == 1:
            latest_path = runtime.changed_paths[-1]
            return f"I completed the requested Desktop action and updated {latest_path}."
        return (
            f"I completed the requested Desktop action and updated {len(runtime.changed_paths)} items."
        )

    if runtime.retrieved_chunks:
        if runtime.last_retrieval_query:
            return (
                "I retrieved the most relevant research context for "
                f"\"{runtime.last_retrieval_query}\"."
            )
        return "I retrieved the most relevant research context for the next step."

    if runtime.visited_websites:
        source_count = len(runtime.visited_websites)
        if source_count == 1:
            return "I completed the web research step and collected one source."
        return f"I completed the web research step and collected {source_count} sources."

    if is_desktop_mutation_request(latest_user_request):
        return "I could not complete the requested Desktop action."

    if runtime.should_open_desktop_view:
        return "I opened the Desktop view."

    return "I completed the requested step."


def update_runtime_research_state_from_tool_result(
    runtime: AgentRuntime, tool_name: str, result: ToolResult
) -> None:
    if tool_name != "google_search_and_collect":
        return

    try:
        parsed_payload = json.loads(result.content)
    except json.JSONDecodeError:
        parsed_payload = {}

    indexed_sources = result.metadata.get("indexed_sources")
    metadata_sources = indexed_sources if isinstance(indexed_sources, list) else []
    content_sources = (
        parsed_payload.get("sources")
        if isinstance(parsed_payload, dict)
        and isinstance(parsed_payload.get("sources"), list)
        else []
    )

    print(
        "[vector-store] ingest_candidates "
        f"tool={tool_name} metadata_sources={len(metadata_sources)} "
        f"content_sources={len(content_sources)}",
        file=sys.stderr,
    )

    seen_source_keys: set[str] = set()
    ingestion_attempts = 0
    ingestion_successes = 0

    def ingest_source_payload(
        payload: dict[str, Any], *, query: str | None = None, purpose: str | None = None
    ) -> None:
        nonlocal ingestion_attempts, ingestion_successes

        text_content = payload.get("text_content")
        if not isinstance(text_content, str) or not text_content.strip():
            return

        source_url = str(payload.get("url") or "").strip()
        source_key = f"{source_url}|{len(text_content)}|{text_content[:120]}"
        if source_key in seen_source_keys:
            return
        seen_source_keys.add(source_key)

        ingestion_attempts += 1
        ingestion_result = runtime.ingest_research_source(
            {
                "title": payload.get("title"),
                "url": payload.get("url"),
                "domain": payload.get("domain"),
                "meta_description": payload.get("meta_description"),
                "headings": payload.get("headings"),
                "text_content": text_content,
                "text_truncated": payload.get("text_truncated"),
                "query": query,
                "purpose": purpose,
            }
        )
        if ingestion_result.get("status") == "ok":
            ingestion_successes += 1

    for source_payload in metadata_sources:
        if isinstance(source_payload, dict):
            ingest_source_payload(
                source_payload,
                query=(
                    str(source_payload.get("query"))
                    if isinstance(source_payload.get("query"), str)
                    else None
                ),
                purpose=(
                    str(source_payload.get("purpose"))
                    if isinstance(source_payload.get("purpose"), str)
                    else None
                ),
            )

    if not metadata_sources and content_sources:
        print(
            "[vector-store] ingest_fallback_from_content "
            f"tool={tool_name}",
            file=sys.stderr,
        )

    for source_payload in content_sources:
        if isinstance(source_payload, dict):
            ingest_source_payload(
                source_payload,
                query=(
                    str(parsed_payload.get("query"))
                    if isinstance(parsed_payload, dict)
                    and isinstance(parsed_payload.get("query"), str)
                    else None
                ),
                purpose=(
                    str(parsed_payload.get("purpose"))
                    if isinstance(parsed_payload, dict)
                    and isinstance(parsed_payload.get("purpose"), str)
                    else None
                ),
            )

    print(
        "[vector-store] ingest_summary "
        f"tool={tool_name} attempts={ingestion_attempts} successes={ingestion_successes}",
        file=sys.stderr,
    )

    if not isinstance(parsed_payload, dict):
        return

    visited_url = parsed_payload.get("visited_website_url")
    visited_title = parsed_payload.get("visited_website_title")

    if not isinstance(visited_url, str) or not visited_url.strip():
        return

    if not isinstance(visited_title, str) or not visited_title.strip():
        visited_title = visited_url

    runtime.record_visited_website(visited_url, visited_title)


def build_runtime_error_result(error: Exception, runtime: AgentRuntime | None) -> AgentFinal:
    if runtime and runtime.changed_paths:
        if len(runtime.changed_paths) == 1:
            progress_message = f"I updated {runtime.changed_paths[-1]}"
        else:
            progress_message = f"I updated {len(runtime.changed_paths)} items"
        return AgentFinal(
            message=(
                f"{progress_message}, but the request could not finish because "
                f"{str(error)} Please retry."
            ),
            requires_clarification=False,
            should_open_desktop_view=runtime.should_open_desktop_view,
            filesystem_changed=runtime.filesystem_changed,
            created_or_updated_paths=list(runtime.changed_paths),
        )

    return AgentFinal(
        message=(
            f"I could not finish the request because {str(error)} "
            "Please retry in a moment."
        ),
        requires_clarification=False,
        should_open_desktop_view=runtime.should_open_desktop_view if runtime else False,
        filesystem_changed=runtime.filesystem_changed if runtime else False,
        created_or_updated_paths=list(runtime.changed_paths) if runtime else [],
    )


def parse_final_result(final_content: str, runtime: AgentRuntime) -> AgentFinal:
    parsed_payload = coerce_final_payload(final_content)

    message = parsed_payload.get("message")
    if not isinstance(message, str) or not message.strip():
        parsed_payload["message"] = synthesize_final_message(parsed_payload, runtime)

    final_result = AgentFinal.model_validate(parsed_payload)
    if final_result.requires_clarification and not is_allowed_desktop_creation_confirmation(
        final_result.message
    ):
        final_result.requires_clarification = False
        final_result.close_agent_session = False
        final_result.message = synthesize_final_message(parsed_payload, runtime)

    if not runtime.required_desktop_action_satisfied() and not final_result.requires_clarification:
        final_result.requires_clarification = True
        final_result.close_agent_session = False
        final_result.message = build_pending_desktop_action_user_message(runtime)

    if final_result.requires_clarification:
        final_result.close_agent_session = False
    elif runtime.session_should_close:
        final_result.close_agent_session = True

    return final_result


def main() -> None:
    runtime: AgentRuntime | None = None

    try:
        raw_input = sys.stdin.readline()
        if not raw_input.strip():
            raise ValueError("Agent received empty stdin input.")

        parsed_input = json.loads(raw_input)
        agent_input = AgentInput.model_validate(parsed_input)
        runtime = AgentRuntime(agent_input)

        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for message in agent_input.messages:
            messages.append({"role": message.role, "content": message.content})

        latest_user_request = get_latest_user_message(agent_input.messages)
        min_web_search_steps, max_web_search_steps = resolve_configured_web_search_limits(
            agent_input
        )
        web_search_steps = max(0, int(agent_input.web_search_steps_used))
        if web_search_steps > max_web_search_steps:
            web_search_steps = max_web_search_steps
        step_index = 0
        consecutive_no_tool_turns = 0
        server_error_react_retries = 0
        approved_file_confirmations: set[tuple[str, str]] = set()
        iteration_cap_recovery_started = False
        iteration_cap_recovery_steps_left = 0
        recovery_seen_inspections: set[tuple[str, str]] = set()
        while True:
            step_index += 1
            emit_protocol_message(
                {
                    "type": "event",
                    "event": "react_iteration",
                    "step_number": step_index,
                    "web_search_steps": web_search_steps,
                    "max_web_search_steps": max_web_search_steps,
                }
            )
            if (
                runtime.required_desktop_action_kind == "write_output"
                and not runtime.required_desktop_action_satisfied()
                and not runtime.force_write_outputs
            ):
                if web_search_steps >= max_web_search_steps:
                    runtime.force_write_outputs = True

            if step_index > MAX_REACT_ITERATIONS:
                if (
                    runtime.required_desktop_action_kind == "write_output"
                    and not runtime.required_desktop_action_satisfied()
                ):
                    if not iteration_cap_recovery_started:
                        iteration_cap_recovery_started = True
                        iteration_cap_recovery_steps_left = (
                            plan_iteration_cap_recovery_steps(runtime)
                        )
                    if iteration_cap_recovery_steps_left <= 0:
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "Iteration-cap recovery window is exhausted and required outputs are still not complete. "
                                    "Stop the ReAct loop and return a concise clarification or failure message "
                                    "explaining what blocked completion."
                                ),
                            }
                        )
                        break
                    runtime.force_write_outputs = True
                    messages.append(
                        {
                            "role": "system",
                            "content": build_iteration_cap_recovery_system_message(
                                runtime, iteration_cap_recovery_steps_left
                            ),
                        }
                    )
                    iteration_cap_recovery_steps_left -= 1
                else:
                    break

            try:
                response = call_llm(
                    agent_input.api_key,
                    agent_input.base_url,
                    {
                        "model": agent_input.model,
                        "messages": build_react_iteration_messages(
                            messages,
                            step_index,
                            web_search_steps,
                            min_web_search_steps,
                            max_web_search_steps,
                            runtime.visited_websites,
                            runtime.force_write_outputs,
                        ),
                        "stream": False,
                        "tools": TOOLS,
                    },
                )
                server_error_react_retries = 0
            except Exception as error:  # noqa: BLE001
                if (
                    is_llm_server_error(error)
                    and server_error_react_retries < MAX_SERVER_ERROR_REACT_RETRIES
                ):
                    server_error_react_retries += 1
                    consecutive_no_tool_turns = 0
                    messages.append(
                        {
                            "role": "system",
                            "content": build_server_error_retry_system_message(
                                error,
                                retry_number=server_error_react_retries,
                                max_retries=MAX_SERVER_ERROR_REACT_RETRIES,
                            ),
                        }
                    )
                    continue
                raise

            message = response.get("message", {})
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": (message.get("content") or "").strip(),
            }
            raw_tool_calls = message.get("tool_calls") or []
            tool_calls = raw_tool_calls[:1] if raw_tool_calls else []
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls

            messages.append(assistant_message)

            if not tool_calls:
                consecutive_no_tool_turns += 1

                if (
                    consecutive_no_tool_turns >= 2
                    and runtime.required_desktop_action_kind == "write_output"
                    and not runtime.required_desktop_action_satisfied()
                    and not runtime.force_write_outputs
                    and web_search_steps < max_web_search_steps
                    and not runtime.visited_websites
                    and request_likely_requires_web_research(latest_user_request)
                ):
                    recovery_query = build_stall_recovery_search_query(
                        latest_user_request
                    )
                    recovery_arguments = {
                        "query": recovery_query,
                        "purpose": (
                            "Stall recovery: collect external web context required to "
                            "complete the requested outputs."
                        ),
                    }
                    emit_protocol_message(
                        {
                            "type": "event",
                            "event": "tool_call",
                            "tool_name": "google_search_and_collect",
                            "arguments": recovery_arguments,
                        }
                    )
                    try:
                        recovery_result = execute_tool(
                            runtime, "google_search_and_collect", recovery_arguments
                        )
                    except Exception as error:  # noqa: BLE001
                        recovery_result = ToolResult(
                            content=json.dumps(
                                {
                                    "status": "error",
                                    "tool_name": "google_search_and_collect",
                                    "message": str(error),
                                },
                                ensure_ascii=False,
                            )
                        )

                    update_runtime_research_state_from_tool_result(
                        runtime,
                        "google_search_and_collect",
                        recovery_result,
                    )
                    append_tool_result_message(
                        messages,
                        tool_name="google_search_and_collect",
                        content=recovery_result.content,
                    )
                    web_search_steps += 1
                    consecutive_no_tool_turns = 0
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                            "Stall recovery: web research was triggered automatically. "
                            "Now continue with retrieve_relevant_chunks and then the "
                            "required single-file write tools."
                        ),
                    }
                )
                    continue

                if (
                    consecutive_no_tool_turns >= STALL_NO_TOOL_TURNS_FOR_FORCE_WRITE
                    and runtime.required_desktop_action_kind == "write_output"
                    and not runtime.required_desktop_action_satisfied()
                ):
                    runtime.force_write_outputs = True
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                            "Stall recovery: too many non-action turns. "
                            "Forced write mode is now enabled. Stop web search. "
                            "Retrieve relevant chunks if needed, then execute the required "
                            "single-file write tools and close the session after all outputs are created."
                        ),
                    }
                )
                    continue

                if (
                    consecutive_no_tool_turns >= STALL_NO_TOOL_TURNS_FOR_RECOVERY
                    and runtime.required_desktop_action_kind == "write_output"
                    and not runtime.required_desktop_action_satisfied()
                    and runtime.retrieval_ready_for_write
                ):
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "Stall recovery: call a write tool now using the retrieved chunk cache. "
                                "Do not return text-only on this turn."
                            ),
                        }
                    )
                    continue

                if looks_like_clarification_question(
                    assistant_message.get("content", "")
                ):
                    if is_allowed_desktop_creation_confirmation(
                        assistant_message.get("content", "")
                    ):
                        break
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "Clarification questions are allowed only for explicit confirmation of creating documents in Desktop view. "
                                "The previous clarification is not allowed. Continue the ReAct loop with one tool call. "
                                "For document work, retrieve from the vector store first, then execute write tools."
                            ),
                        }
                    )
                    continue
                if (
                    runtime.required_desktop_action_kind == "write_output"
                    and runtime.retrieval_ready_for_write
                    and not runtime.required_desktop_action_satisfied()
                ):
                    messages.append(
                        {
                            "role": "system",
                            "content": build_pending_desktop_action_system_message(
                                runtime
                            ),
                        }
                    )
                    continue
                if looks_like_source_request_clarification(
                    assistant_message.get("content", "")
                ) and not user_explicitly_requires_named_source(latest_user_request):
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "The previous assistant message asked the user to provide "
                                "a source, article, website, link, or URL. That is not "
                                "allowed for open-ended research-backed work. Continue the "
                                "ReAct loop without asking for sources. "
                                + (
                                    "If more external information is needed, call "
                                "google_search_and_collect yourself. Otherwise use "
                                    "the gathered context and retrieved chunks to draft, "
                                    "or ask only for missing scope, audience, format, or "
                                    "destination details."
                                    if web_search_steps < max_web_search_steps
                                    else
                                    "The web-search limit is already reached, so proceed "
                                    "using the gathered context and retrieved chunks, or "
                                    "ask only for missing scope, audience, format, or "
                                    "destination details."
                                )
                            ),
                        }
                    )
                    continue
                if (
                    not runtime.required_desktop_action_satisfied()
                    and not looks_like_clarification_question(
                        assistant_message.get("content", "")
                    )
                ):
                    messages.append(
                        {
                            "role": "system",
                            "content": build_pending_desktop_action_system_message(
                                runtime
                            ),
                        }
                    )
                    continue
                break

            call = tool_calls[0]
            consecutive_no_tool_turns = 0
            raw_tool_call_id = call.get("id")
            tool_call_id = (
                raw_tool_call_id.strip()
                if isinstance(raw_tool_call_id, str) and raw_tool_call_id.strip()
                else None
            )
            function_payload = call.get("function", {})
            tool_name = function_payload.get("name")
            if not tool_name:
                continue

            if tool_name == "create_multiple_files":
                pending_guidance = format_pending_write_tool_guidance(runtime)
                result = ToolResult(
                    content=json.dumps(
                        {
                            "status": "blocked",
                            "tool_name": tool_name,
                            "message": (
                                "create_multiple_files is disabled. Use one specific single-file "
                                "write tool per turn until all pending outputs are complete."
                                + pending_guidance
                            ),
                        },
                        ensure_ascii=False,
                    )
                )
                append_tool_result_message(
                    messages,
                    tool_name=tool_name,
                    content=result.content,
                    tool_call_id=tool_call_id,
                )
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Do not call create_multiple_files. Call one specific single-file "
                            "write tool that matches a pending extension."
                            + pending_guidance
                        ),
                    }
                )
                continue

            if (
                tool_name == "delete_desktop_file"
                and runtime.required_desktop_action_kind != "mutation"
            ):
                result = ToolResult(
                    content=json.dumps(
                        {
                            "status": "blocked",
                            "tool_name": tool_name,
                            "message": (
                                "Direct delete_desktop_file calls are blocked for this request. "
                                "Use edit_desktop_file for updates or convert_desktop_file_format "
                                "for format changes so replacement output is created safely."
                            ),
                        },
                        ensure_ascii=False,
                    )
                )
                append_tool_result_message(
                    messages,
                    tool_name=tool_name,
                    content=result.content,
                    tool_call_id=tool_call_id,
                )
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Do not call delete_desktop_file directly for this task. "
                            "Call edit_desktop_file or convert_desktop_file_format instead."
                        ),
                    }
                )
                continue

            if (
                tool_name == "retrieve_relevant_chunks"
                and runtime.required_desktop_action_kind == "write_output"
                and runtime.retrieval_ready_for_write
                and not runtime.required_desktop_action_satisfied()
            ):
                result = ToolResult(
                    content=json.dumps(
                        {
                            "status": "blocked",
                            "tool_name": tool_name,
                            "message": (
                                "The retrieved chunk cache is already ready for the remaining "
                                "write steps. Reuse the current retrieval results and call the "
                                "appropriate single-file write tool now."
                            ),
                        },
                        ensure_ascii=False,
                    )
                )
                append_tool_result_message(
                    messages,
                    tool_name=tool_name,
                    content=result.content,
                    tool_call_id=tool_call_id,
                )
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "retrieve_relevant_chunks is already ready for writing. Do not call "
                            "it again unless new web research changed the available context. "
                            "Use the current retrieved chunk cache and write the remaining "
                            "requested outputs now with single-file write tools."
                        ),
                    }
                )
                continue

            if (
                tool_name in WRITE_TOOL_NAMES
                and runtime.required_desktop_action_satisfied()
            ):
                result = ToolResult(
                    content=json.dumps(
                        {
                            "status": "blocked",
                            "tool_name": tool_name,
                            "message": (
                                "The requested document outputs are already complete. Do not "
                                "create extra files. Close the agent session instead."
                            ),
                        },
                        ensure_ascii=False,
                    )
                )
                append_tool_result_message(
                    messages,
                    tool_name=tool_name,
                    content=result.content,
                    tool_call_id=tool_call_id,
                )
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "The requested outputs are already complete. Do not call more write "
                            "tools. Call close_agent_session now."
                        ),
                    }
                )
                continue

            if (
                (
                    tool_name in WRITE_TOOL_NAMES
                    or tool_name == "close_agent_session"
                )
                and runtime.required_desktop_action_kind == "write_output"
                and not runtime.required_desktop_action_satisfied()
                and not runtime.force_write_outputs
                and max_web_search_steps > 0
                and request_likely_requires_web_research(latest_user_request)
                and web_search_steps < min_web_search_steps
            ):
                result = ToolResult(
                    content=json.dumps(
                        {
                            "status": "blocked",
                            "tool_name": tool_name,
                            "message": (
                                "Minimum web research count not reached. "
                                f"Complete at least {min_web_search_steps} google_search_and_collect calls "
                                f"before writing outputs (current: {web_search_steps})."
                            ),
                        },
                        ensure_ascii=False,
                    )
                )
                append_tool_result_message(
                    messages,
                    tool_name=tool_name,
                    content=result.content,
                    tool_call_id=tool_call_id,
                )
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"Minimum web research requirement is {min_web_search_steps} call(s). "
                            "Call google_search_and_collect now unless the user explicitly provided a named source."
                        ),
                    }
                )
                continue

            if tool_name == "google_search_and_collect":
                if runtime.force_write_outputs:
                    result = ToolResult(
                        content=json.dumps(
                            {
                                "status": "blocked",
                                "tool_name": tool_name,
                                "message": (
                                    "Forced write mode is active. Web search is disabled. "
                                    "Retrieve relevant chunks and write the requested outputs."
                                ),
                            },
                            ensure_ascii=False,
                        )
                    )
                    append_tool_result_message(
                        messages,
                        tool_name=tool_name,
                        content=result.content,
                        tool_call_id=tool_call_id,
                    )
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "Forced write mode is active. Do not call google_search_and_collect. "
                                "Retrieve relevant chunks and proceed to writing the requested outputs."
                            ),
                        }
                    )
                    continue
                if (
                    runtime.required_desktop_action_kind == "write_output"
                    and not runtime.required_desktop_action_satisfied()
                    and web_search_steps >= max_web_search_steps
                ):
                    result = ToolResult(
                        content=json.dumps(
                            {
                                "status": "blocked",
                                "tool_name": tool_name,
                                "message": (
                                    "Research soft target reached for writing task. "
                                    "Proceed with retrieve_relevant_chunks and write tools."
                                ),
                            },
                            ensure_ascii=False,
                        )
                    )
                    append_tool_result_message(
                        messages,
                        tool_name=tool_name,
                        content=result.content,
                        tool_call_id=tool_call_id,
                    )
                    runtime.force_write_outputs = True
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "For this writing request, web research is sufficient. "
                                "Do not call google_search_and_collect again. "
                                "Retrieve relevant chunks and create all remaining requested outputs."
                            ),
                        }
                    )
                    continue
                if web_search_steps >= max_web_search_steps:
                    result = ToolResult(
                        content=json.dumps(
                            {
                                "status": "limit_reached",
                                "tool_name": tool_name,
                                "message": (
                                    f"google_search_and_collect already reached the per-session limit "
                                    f"of {max_web_search_steps} calls. Proceed using the gathered "
                                    "context, or ask only for missing task scope details if the "
                                    "document requirements themselves are still unclear."
                                ),
                            },
                            ensure_ascii=False,
                        )
                    )
                    append_tool_result_message(
                        messages,
                        tool_name=tool_name,
                        content=result.content,
                        tool_call_id=tool_call_id,
                    )
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "The web-search limit for this agent session has been reached. "
                                "Use the gathered context to draft the requested output if it is "
                                "sufficient, or ask only for genuinely missing scope/content constraints."
                            ),
                        }
                    )
                    continue
                web_search_steps += 1
                if (
                    runtime.required_desktop_action_kind == "write_output"
                    and not runtime.required_desktop_action_satisfied()
                    and web_search_steps >= max_web_search_steps
                ):
                    runtime.force_write_outputs = True
            elif (
                tool_name in WRITE_TOOL_NAMES
                and not runtime.retrieval_ready_for_write
            ):
                result = ToolResult(
                    content=json.dumps(
                        {
                            "status": "blocked",
                            "tool_name": tool_name,
                            "message": (
                                "Write action blocked: retrieve_relevant_chunks must be called "
                                "immediately before any write tool."
                            ),
                        },
                        ensure_ascii=False,
                    )
                )
                append_tool_result_message(
                    messages,
                    tool_name=tool_name,
                    content=result.content,
                    tool_call_id=tool_call_id,
                )
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Before any write action, call retrieve_relevant_chunks with a focused query "
                            "for the exact output to generate. Then call the write tool."
                        ),
                    }
                )
                continue
            elif (
                tool_name == "close_agent_session"
                and not runtime.required_desktop_action_satisfied()
            ):
                result = ToolResult(
                    content=json.dumps(
                        {
                            "status": "blocked",
                            "tool_name": tool_name,
                            "message": build_pending_desktop_action_user_message(
                                runtime
                            ),
                        },
                        ensure_ascii=False,
                    )
                )
                append_tool_result_message(
                    messages,
                    tool_name=tool_name,
                    content=result.content,
                    tool_call_id=tool_call_id,
                )
                messages.append(
                    {
                        "role": "system",
                        "content": build_pending_desktop_action_system_message(runtime),
                    }
                )
                continue

            try:
                arguments = normalize_tool_arguments(function_payload.get("arguments"))
                arguments, confirmation_paths = prepare_tool_arguments_for_execution(
                    runtime,
                    tool_name,
                    arguments,
                )
                if (
                    iteration_cap_recovery_started
                    and runtime.required_desktop_action_kind == "write_output"
                    and not runtime.required_desktop_action_satisfied()
                    and tool_name in RECOVERY_RESTRICTED_INSPECTION_TOOLS
                ):
                    raw_path = (
                        arguments.get("path")
                        if isinstance(arguments, dict)
                        else None
                    )
                    try:
                        inspected_path = str(runtime.resolve_desktop_path(raw_path))
                    except Exception:  # noqa: BLE001
                        inspected_path = str(raw_path or runtime.desktop_root)
                    inspection_key = (tool_name, inspected_path.casefold())
                    if inspection_key in recovery_seen_inspections:
                        result = ToolResult(
                            content=json.dumps(
                                {
                                    "status": "blocked",
                                    "tool_name": tool_name,
                                    "message": (
                                        "Iteration-cap recovery mode blocks repeated inspection of the same folder/file path. "
                                        "Keep one folder decision and proceed with retrieval/write tools."
                                    ),
                                },
                                ensure_ascii=False,
                            )
                        )
                        append_tool_result_message(
                            messages,
                            tool_name=tool_name,
                            content=result.content,
                            tool_call_id=tool_call_id,
                        )
                        messages.append(
                            {
                                "role": "system",
                                "content": build_iteration_cap_recovery_system_message(
                                    runtime,
                                    max(1, iteration_cap_recovery_steps_left),
                                ),
                            }
                        )
                        continue
                    recovery_seen_inspections.add(inspection_key)
                confirmation_target = format_confirmation_paths(confirmation_paths)
                if tool_requires_file_confirmation(tool_name) and confirmation_target:
                    confirmation_key = (tool_name, confirmation_target)
                    if confirmation_key not in approved_file_confirmations:
                        print(
                            "[desktop-agent] file_confirmation_requested "
                            f"tool={tool_name} target={confirmation_target}",
                            file=sys.stderr,
                        )
                        if not request_file_confirmation(tool_name, confirmation_target):
                            print(
                                "[desktop-agent] file_confirmation_cancelled "
                                f"tool={tool_name} target={confirmation_target}",
                                file=sys.stderr,
                            )
                            result = ToolResult(
                                content=json.dumps(
                                    {
                                        "status": "cancelled",
                                        "tool_name": tool_name,
                                        "path": confirmation_target,
                                        "message": f"User cancelled {tool_name} for {confirmation_target}.",
                                    },
                                    ensure_ascii=False,
                                ),
                                should_open_desktop_view=True,
                            )
                            append_tool_result_message(
                                messages,
                                tool_name=tool_name,
                                content=result.content,
                                tool_call_id=tool_call_id,
                            )
                            continue
                        approved_file_confirmations.add(confirmation_key)
                        print(
                            "[desktop-agent] file_confirmation_approved "
                            f"tool={tool_name} target={confirmation_target}",
                            file=sys.stderr,
                        )
                    else:
                        print(
                            "[desktop-agent] file_confirmation_reused "
                            f"tool={tool_name} target={confirmation_target}",
                            file=sys.stderr,
                        )
                emit_protocol_message(
                    {
                        "type": "event",
                        "event": "tool_call",
                        "tool_name": tool_name,
                        "arguments": arguments,
                    }
                )
                result = execute_tool(runtime, tool_name, arguments)
            except Exception as error:  # noqa: BLE001
                result = ToolResult(
                    content=json.dumps(
                        {
                            "status": "error",
                            "tool_name": tool_name,
                            "message": str(error),
                        },
                        ensure_ascii=False,
                    )
                )

            if result.filesystem_changed:
                runtime.filesystem_changed = True
            for changed_path in result.changed_paths:
                if changed_path not in runtime.changed_paths:
                    runtime.changed_paths.append(changed_path)
            if result.should_open_desktop_view:
                runtime.should_open_desktop_view = True
            runtime.record_completed_desktop_action(tool_name, result)
            update_runtime_research_state_from_tool_result(runtime, tool_name, result)
            if runtime.session_should_close:
                web_search_steps = 0

            result_payload = parse_tool_result_payload(result)
            result_status = (
                result_payload.get("status")
                if isinstance(result_payload.get("status"), str)
                else "unknown"
            )
            result_message = (
                result_payload.get("message")
                if isinstance(result_payload.get("message"), str)
                else ""
            )
            print(
                "[desktop-agent] tool_result "
                f"tool={tool_name} status={result_status} "
                f"changed_paths={len(result.changed_paths)} "
                f"required_action_satisfied={runtime.required_desktop_action_satisfied()} "
                f"remaining_output_count={runtime.remaining_requested_output_count()} "
                f"pending_extensions={','.join(sorted(runtime.expected_output_extensions)) or 'none'} "
                f"message={result_message or 'none'}",
                file=sys.stderr,
            )

            append_tool_result_message(
                messages,
                tool_name=tool_name,
                content=result.content,
                tool_call_id=tool_call_id,
            )

            if (
                tool_name in WRITE_TOOL_NAMES
                and result_status == "error"
                and not result.changed_paths
            ):
                if is_recoverable_write_error_message(result_message):
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "The previous write attempt failed due to argument/format mismatch. "
                                "Continue the ReAct loop: decide one explicit output format that fits the user request, "
                                "keep it consistent for this request, and call the matching single-file write tool next. "
                                "If using add_file_to_existing_folder, set file_type to match that chosen format."
                            )
                            + format_pending_write_tool_guidance(runtime),
                        }
                    )
                    continue
                raise RuntimeError(
                    f"Write tool {tool_name} failed after confirmation: "
                    f"{result_message or 'unknown write error'}"
                )

        final_server_error_retries = 0
        while True:
            try:
                final_response = call_llm(
                    agent_input.api_key,
                    agent_input.base_url,
                    {
                        "model": agent_input.model,
                        "messages": build_final_messages(messages),
                        "stream": False,
                        "format": AgentFinal.model_json_schema(),
                    },
                )
                break
            except Exception as error:  # noqa: BLE001
                if (
                    is_llm_server_error(error)
                    and final_server_error_retries < MAX_SERVER_ERROR_FINAL_RETRIES
                ):
                    final_server_error_retries += 1
                    messages.append(
                        {
                            "role": "system",
                            "content": build_server_error_retry_system_message(
                                error,
                                retry_number=final_server_error_retries,
                                max_retries=MAX_SERVER_ERROR_FINAL_RETRIES,
                            ),
                        }
                    )
                    continue
                raise

        final_content = (final_response.get("message", {}).get("content") or "").strip()
        final_result = parse_final_result(final_content, runtime)
        if final_result.close_agent_session:
            web_search_steps = 0

        if (
            final_result.requires_clarification
            and looks_like_source_request_clarification(final_result.message)
            and not user_explicitly_requires_named_source(latest_user_request)
            and not is_desktop_mutation_request(latest_user_request)
        ):
            repaired_server_error_retries = 0
            while True:
                try:
                    repaired_final_response = call_llm(
                        agent_input.api_key,
                        agent_input.base_url,
                        {
                            "model": agent_input.model,
                            "messages": build_final_retry_messages(
                                messages, final_result.message
                            ),
                            "stream": False,
                            "format": AgentFinal.model_json_schema(),
                        },
                    )
                    break
                except Exception as error:  # noqa: BLE001
                    if (
                        is_llm_server_error(error)
                        and repaired_server_error_retries
                        < MAX_SERVER_ERROR_FINAL_RETRIES
                    ):
                        repaired_server_error_retries += 1
                        messages.append(
                            {
                                "role": "system",
                                "content": build_server_error_retry_system_message(
                                    error,
                                    retry_number=repaired_server_error_retries,
                                    max_retries=MAX_SERVER_ERROR_FINAL_RETRIES,
                                ),
                            }
                        )
                        continue
                    raise
            repaired_final_content = (
                repaired_final_response.get("message", {}).get("content") or ""
            ).strip()
            repaired_result = parse_final_result(repaired_final_content, runtime)
            if not (
                repaired_result.requires_clarification
                and looks_like_source_request_clarification(repaired_result.message)
            ):
                final_result = repaired_result

        final_result.should_open_desktop_view = (
            final_result.should_open_desktop_view or runtime.should_open_desktop_view
        )
        final_result.filesystem_changed = (
            final_result.filesystem_changed or runtime.filesystem_changed
        )

        for path in runtime.changed_paths:
            if path not in final_result.created_or_updated_paths:
                final_result.created_or_updated_paths.append(path)

        emit_protocol_message(
            {
                "type": "result",
                "data": final_result.model_dump(mode="json"),
            }
        )
    except Exception as error:  # noqa: BLE001
        final_result = build_runtime_error_result(
            error if isinstance(error, Exception) else Exception(str(error)),
            runtime,
        )
        emit_protocol_message(
            {
                "type": "result",
                "data": final_result.model_dump(mode="json"),
            }
        )

