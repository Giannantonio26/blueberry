from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Sequence

from ..core.agent_utils import (
    DesktopRequiredActionKind,
    get_latest_user_message,
    infer_required_desktop_action_kind,
    infer_requested_output_count,
    infer_requested_output_extensions,
)
from ..core.models import (
    AgentInput,
    MultiFileSpec,
    RetrievalQueryBatch,
    RetrievedChunk,
    ToolResult,
)
from ..core.llm_api import call_llm
from ..planning.file_planning import (
    file_type_to_file_action,
    plan_output_path_for_file_action,
)
from ..vector_store import ProjectChromaResearchStore

DESKTOP_ROOT_CANONICAL_FOLDER = "bluebarry"
DESKTOP_ROOT_ALIAS_FOLDER = "blueberry"


def _sanitize_utf8_text(value: Any) -> str:
    raw_value = str(value or "")
    return "".join(
        character
        for character in raw_value
        if not (0xD800 <= ord(character) <= 0xDFFF)
    )


class AgentRuntimeBase:
    def __init__(self, agent_input: AgentInput) -> None:
        self.agent_input = agent_input
        self.latest_user_request = get_latest_user_message(agent_input.messages)
        self.desktop_root = Path(agent_input.desktop_root).resolve()
        self.filesystem_changed = False
        self.changed_paths: list[str] = []
        self.filename_cache: dict[str, str] = {}
        self.visited_websites: dict[str, str] = {
            str(url): str(title)
            for url, title in agent_input.visited_websites.items()
            if str(url).strip()
        }
        self.session_should_close = False
        self.should_open_desktop_view = bool(agent_input.open_desktop_hint)
        self.force_write_outputs = bool(agent_input.force_write_outputs)
        self.research_store = ProjectChromaResearchStore(
            api_key=agent_input.api_key,
            base_url=agent_input.base_url,
            guard_model=agent_input.model,
        )
        self.retrieved_chunks: list[RetrievedChunk] = []
        self.last_retrieval_query: str = ""
        self.retrieval_ready_for_write = False
        self.required_desktop_action_kind = infer_required_desktop_action_kind(
            self.latest_user_request
        )
        self.completed_desktop_action_kinds: set[DesktopRequiredActionKind] = set()
        self.last_terminal_action_tool: str = ""
        self.created_output_paths: list[str] = []
        self.preferred_output_folder: str | None = None
        self.expected_output_extensions: set[str] = infer_requested_output_extensions(
            self.latest_user_request
        )
        self.requested_output_count: int | None = infer_requested_output_count(
            self.latest_user_request
        )
        if (
            self.requested_output_count is None
            and self.required_desktop_action_kind == "write_output"
            and self.expected_output_extensions
        ):
            self.requested_output_count = max(1, len(self.expected_output_extensions))
        if not self.required_desktop_action_kind and self.expected_output_extensions:
            self.required_desktop_action_kind = "write_output"

    def coerce_alias_path_to_desktop_root(self, resolved_path: Path) -> Path:
        if self.desktop_root.name.lower() != DESKTOP_ROOT_CANONICAL_FOLDER:
            return resolved_path

        alias_root = self.desktop_root.parent / DESKTOP_ROOT_ALIAS_FOLDER
        try:
            alias_relative_path = resolved_path.relative_to(alias_root)
        except ValueError:
            return resolved_path

        return (self.desktop_root / alias_relative_path).resolve()

    def resolve_desktop_path(self, raw_path: str | None) -> Path:
        if not raw_path:
            return self.desktop_root

        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = self.desktop_root / candidate

        resolved = self.coerce_alias_path_to_desktop_root(candidate.resolve())

        if resolved != self.desktop_root and self.desktop_root not in resolved.parents:
            raise ValueError("The requested path is outside the Desktop root.")

        return resolved

    def format_entry(self, path: Path) -> dict[str, Any]:
        return {
            "name": path.name,
            "path": str(path),
            "kind": "directory" if path.is_dir() else "file",
            "extension": path.suffix.lstrip("."),
        }

    def record_visited_website(self, url: str, title: str) -> None:
        normalized_url = url.strip()
        if not normalized_url:
            return

        normalized_title = title.strip() or normalized_url
        self.visited_websites[normalized_url] = normalized_title

    def record_changed_path(self, path: Path) -> None:
        self.filesystem_changed = True
        normalized = str(path)
        if normalized not in self.changed_paths:
            self.changed_paths.append(normalized)
        self.should_open_desktop_view = True

    def forget_changed_path(self, path: Path) -> None:
        normalized = str(path)
        self.changed_paths = [
            changed_path
            for changed_path in self.changed_paths
            if changed_path != normalized
        ]
        self.filesystem_changed = bool(self.changed_paths)

    def record_completed_desktop_action(
        self,
        tool_name: str,
        result: ToolResult,
    ) -> None:
        if not result.changed_paths:
            return

        action_kind_by_tool: dict[str, DesktopRequiredActionKind] = {
            "create_folder": "create_folder",
            "write_text_file": "write_output",
            "write_txt_file": "write_output",
            "write_markdown_file": "write_output",
            "write_csv_file": "write_output",
            "write_word_file": "write_output",
            "write_excel_file": "write_output",
            "write_pdf_file": "write_output",
            "write_powerpoint_file": "write_output",
            "add_file_to_existing_folder": "write_output",
            "edit_desktop_file": "edit_file",
            "delete_desktop_file": "mutation",
            "convert_desktop_file_format": "convert_file",
        }

        action_kind = action_kind_by_tool.get(tool_name)
        if action_kind is None:
            return

        self.completed_desktop_action_kinds.add(action_kind)
        self.completed_desktop_action_kinds.add("mutation")
        self.last_terminal_action_tool = tool_name
        output_producing_tools = {
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
        for changed_path in result.changed_paths:
            ext = Path(changed_path).suffix.lower().lstrip(".")
            if tool_name in output_producing_tools and changed_path not in self.created_output_paths:
                self.created_output_paths.append(changed_path)
            if ext in self.expected_output_extensions:
                self.expected_output_extensions.discard(ext)

    def required_desktop_action_satisfied(self) -> bool:
        required_action = self.required_desktop_action_kind
        if required_action is None:
            return True

        if required_action == "mutation":
            return bool(self.changed_paths or self.completed_desktop_action_kinds)

        satisfied = required_action in self.completed_desktop_action_kinds
        if required_action == "write_output":
            if not satisfied:
                return False
            if self.has_pending_output_extensions():
                return False
            remaining_output_count = self.remaining_requested_output_count()
            if remaining_output_count is not None and remaining_output_count > 0:
                return False
            return True
        if satisfied and self.has_pending_output_extensions():
            return False
        return satisfied

    def has_pending_output_extensions(self) -> bool:
        return bool(self.expected_output_extensions)

    def created_output_count(self) -> int:
        return len(self.created_output_paths)

    def remaining_requested_output_count(self) -> int | None:
        if self.requested_output_count is None:
            return None
        return max(0, self.requested_output_count - self.created_output_count())

    def invalidate_retrieved_chunks(self) -> None:
        self.retrieved_chunks = []
        self.last_retrieval_query = ""
        self.retrieval_ready_for_write = False

    def record_retrieved_chunks(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
    ) -> None:
        self.retrieved_chunks = list(chunks)
        self.last_retrieval_query = query.strip()
        self.retrieval_ready_for_write = True

    def require_retrieved_chunks_for_write(self, tool_name: str) -> None:
        if self.retrieval_ready_for_write:
            return

        raise ValueError(
            f"{tool_name} requires retrieve_relevant_chunks to be called first in the current ReAct flow."
        )

    def consume_retrieved_chunks_for_write(self) -> None:
        # Keep retrieval context available for the remaining document outputs until
        # new web research or an explicit retrieval refresh invalidates it.
        self.retrieval_ready_for_write = bool(self.retrieved_chunks)

    def ingest_research_source(self, source_payload: dict[str, Any]) -> dict[str, Any]:
        content = source_payload.get("text_content")
        source_url = _sanitize_utf8_text(source_payload.get("url")).strip()
        source_title = _sanitize_utf8_text(source_payload.get("title")).strip()
        normalized_headings: list[str] | None = None
        if isinstance(source_payload.get("headings"), list):
            normalized_headings = []
            for heading in source_payload.get("headings", []):
                if not isinstance(heading, str):
                    continue
                cleaned_heading = _sanitize_utf8_text(heading).strip()
                if cleaned_heading:
                    normalized_headings.append(cleaned_heading)

        print(
            "[vector-store] ingest_research_source_received "
            f"url={source_url or 'missing'} "
            f"title={source_title or 'missing'} "
            f"text_chars={len(content) if isinstance(content, str) else 0}",
            file=sys.stderr,
        )
        if not isinstance(content, str) or not content.strip():
            print(
                "[vector-store] ingest_research_source_skipped "
                f"url={source_url or 'missing'} reason=missing_text_content",
                file=sys.stderr,
            )
            return {
                "status": "skipped",
                "reason": "The tool result did not include indexable web page content.",
            }

        ingestion_result = self.research_store.ingest_web_page(
            source_url=source_url,
            source_title=source_title,
            content=_sanitize_utf8_text(content) if isinstance(content, str) else "",
            source_domain=(
                _sanitize_utf8_text(source_payload.get("domain")).strip() or None
            ),
            source_query=(
                _sanitize_utf8_text(source_payload.get("query")).strip() or None
            ),
            headings=normalized_headings,
            meta_description=(
                _sanitize_utf8_text(source_payload.get("meta_description")).strip()
                or None
            ),
        )
        print(
            "[vector-store] ingest_research_source_result "
            f"url={source_url or 'missing'} result={ingestion_result.get('status')}",
            file=sys.stderr,
        )
        if ingestion_result.get("status") == "ok":
            self.invalidate_retrieved_chunks()
        return ingestion_result

    def build_fallback_retrieval_queries(self, query: str) -> list[str]:
        normalized_query = _sanitize_utf8_text(query).strip()
        fallback_queries = [
            normalized_query,
            f"{normalized_query} key facts",
            f"{normalized_query} detailed context",
        ]
        unique_queries: list[str] = []
        seen_queries: set[str] = set()
        for fallback_query in fallback_queries:
            dedupe_key = fallback_query.casefold()
            if not fallback_query or dedupe_key in seen_queries:
                continue
            seen_queries.add(dedupe_key)
            unique_queries.append(fallback_query)

        while len(unique_queries) < 3 and normalized_query:
            unique_queries.append(normalized_query)

        return unique_queries[:3]

    def extract_retrieval_queries_from_raw_content(self, raw_content: str) -> list[str]:
        normalized_raw = _sanitize_utf8_text(raw_content).strip()
        if not normalized_raw:
            return []

        extracted_queries: list[str] = []
        try:
            parsed_payload = json.loads(normalized_raw)
        except json.JSONDecodeError:
            parsed_payload = None

        if isinstance(parsed_payload, dict):
            raw_queries = parsed_payload.get("queries")
            if isinstance(raw_queries, list):
                extracted_queries.extend(
                    item for item in raw_queries if isinstance(item, str)
                )
        elif isinstance(parsed_payload, list):
            extracted_queries.extend(
                item for item in parsed_payload if isinstance(item, str)
            )

        if extracted_queries:
            return extracted_queries

        for raw_line in normalized_raw.splitlines():
            candidate = raw_line.strip()
            if not candidate:
                continue
            candidate = candidate.lstrip("-*• ").strip()
            if (
                len(candidate) > 2
                and candidate[0].isdigit()
                and "." in candidate[:4]
            ):
                prefix, _separator, tail = candidate.partition(".")
                if prefix.isdigit() and tail.strip():
                    candidate = tail.strip()
            if candidate.startswith('"') and candidate.endswith('"') and len(candidate) > 1:
                candidate = candidate[1:-1].strip()
            if candidate:
                extracted_queries.append(candidate)

        return extracted_queries

    def generate_retrieval_queries(self, query: str) -> list[str]:
        normalized_query = _sanitize_utf8_text(query).strip()
        if not normalized_query:
            return []

        raw_content = ""
        try:
            response = call_llm(
                self.agent_input.api_key,
                self.agent_input.base_url,
                {
                    "model": self.agent_input.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Generate exactly 3 distinct semantic retrieval queries for a "
                                "vector store. Keep them short, concrete, and tightly focused on "
                                "the same user need. Each query should explore a slightly different "
                                "angle or wording. Return JSON only that matches the schema."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                "Original retrieval need:\n"
                                f"{normalized_query}"
                            ),
                        },
                    ],
                    "stream": False,
                    "format": RetrievalQueryBatch.model_json_schema(),
                },
            )
            raw_content = (response.get("message", {}).get("content") or "").strip()
            parsed_batch = RetrievalQueryBatch.model_validate_json(raw_content)
            raw_queries = parsed_batch.queries
        except Exception as error:
            recovered_queries = self.extract_retrieval_queries_from_raw_content(raw_content)
            if recovered_queries:
                print(
                    "[vector-store] retrieval_query_generation_recovered "
                    f"query_count={len(recovered_queries)}",
                    file=sys.stderr,
                )
                raw_queries = recovered_queries
            else:
                print(
                    "[vector-store] retrieval_query_generation_fallback "
                    f"reason={error}",
                    file=sys.stderr,
                )
                return self.build_fallback_retrieval_queries(normalized_query)

        unique_queries: list[str] = []
        seen_queries: set[str] = set()
        for raw_query in raw_queries:
            cleaned_query = _sanitize_utf8_text(raw_query).strip()
            dedupe_key = cleaned_query.casefold()
            if not cleaned_query or dedupe_key in seen_queries:
                continue
            seen_queries.add(dedupe_key)
            unique_queries.append(cleaned_query)

        for fallback_query in self.build_fallback_retrieval_queries(normalized_query):
            dedupe_key = fallback_query.casefold()
            if dedupe_key in seen_queries:
                continue
            seen_queries.add(dedupe_key)
            unique_queries.append(fallback_query)
            if len(unique_queries) >= 3:
                break

        return unique_queries[:3]

    def list_retrieval_source_domains(self) -> list[str]:
        return self.research_store.list_source_domains()

    def retrieve_relevant_chunks_from_store(
        self,
        query: str,
        top_k: int,
        *,
        selected_source_domains: Sequence[str] | None = None,
    ) -> tuple[list[RetrievedChunk], list[str]]:
        retrieval_queries = self.generate_retrieval_queries(query)
        effective_retrieval_queries = retrieval_queries or [_sanitize_utf8_text(query).strip()]
        chunks = self.research_store.retrieve_top_k_for_queries(
            effective_retrieval_queries,
            per_query_top_k=5,
            final_top_k=top_k,
            source_domains=selected_source_domains,
        )
        self.record_retrieved_chunks(query, chunks)
        return chunks, effective_retrieval_queries

    def resolve_unique_file_path(
        self, file_path: Path, reserved_paths: set[str] | None = None
    ) -> Path:
        normalized_path = str(file_path)
        if not file_path.exists() and (
            reserved_paths is None or normalized_path not in reserved_paths
        ):
            return file_path

        suffix = "".join(file_path.suffixes)
        base_name = file_path.name[: -len(suffix)] if suffix else file_path.name
        counter = 1

        while True:
            candidate_name = f"{base_name} ({counter}){suffix}"
            candidate_path = file_path.with_name(candidate_name)
            normalized_candidate = str(candidate_path)
            if not candidate_path.exists() and (
                reserved_paths is None or normalized_candidate not in reserved_paths
            ):
                return candidate_path
            counter += 1

    def get_unique_output_path(
        self,
        raw_path: str,
        expected_suffix: str | None = None,
        *,
        reserved_paths: set[str] | None = None,
    ) -> Path:
        file_path = self.resolve_desktop_path(raw_path)
        if expected_suffix and file_path.suffix.lower() != expected_suffix:
            file_path = file_path.with_suffix(expected_suffix)
        return self.resolve_unique_file_path(file_path, reserved_paths=reserved_paths)

    def plan_multiple_file_specs(
        self,
        files: list[MultiFileSpec],
        *,
        destination_folder: str | None = None,
    ) -> list[MultiFileSpec]:
        planned_files: list[MultiFileSpec] = []
        reserved_paths: set[str] = set()

        for file_spec in files:
            file_action = file_type_to_file_action(file_spec.file_type)
            file_destination_folder = file_spec.destination_folder or destination_folder
            planned_path = plan_output_path_for_file_action(
                self,
                file_action,
                raw_path=file_spec.path,
                destination_folder=file_destination_folder,
                title=file_spec.title,
                content=file_spec.content,
                paragraphs=file_spec.paragraphs,
                sheets=file_spec.sheets,
                slides=file_spec.slides,
                reserved_paths=reserved_paths,
            )
            reserved_paths.add(planned_path)
            planned_files.append(file_spec.model_copy(update={"path": planned_path}))

        return planned_files
