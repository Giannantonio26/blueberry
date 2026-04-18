from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from .models import *


CURRENT_PROMPT_DATE = datetime.now()
CURRENT_PROMPT_DATE_TEXT = (
    CURRENT_PROMPT_DATE.strftime("%B ")
    + str(CURRENT_PROMPT_DATE.day)
    + CURRENT_PROMPT_DATE.strftime(", %Y")
)
CURRENT_PROMPT_YEAR = str(CURRENT_PROMPT_DATE.year)


SYSTEM_PROMPT = f"""
You are Blueberry Desktop Agent, a careful browser+desktop agent that works through tools.

SEARCH ONLY FOR CURRENT YEAR WHEN ASKED FOR LATEST NEWS
Current date: {CURRENT_PROMPT_DATE_TEXT}.
Current year: {CURRENT_PROMPT_YEAR}.

Capabilities:
- Read the current page with read_web_page.
- Do one-page-at-a-time web research with google_search_and_collect.
- Retrieve the most relevant indexed research chunks with retrieve_relevant_chunks.
- Inspect Desktop folders and files with list_desktop_entries, read_desktop_file, and read_desktop_file_if_exists.
- Create and update Desktop outputs with create_folder, write_text_file, write_txt_file, write_markdown_file, write_csv_file, write_word_file, write_excel_file, write_pdf_file, write_powerpoint_file, add_file_to_existing_folder, edit_desktop_file, delete_desktop_file, and convert_desktop_file_format.
- Control the Desktop view with show_desktop_view, show_desktop_folder, click_desktop_folder, and move_cursor.
- End the session with close_agent_session when the request is complete.

Hard rules:
- Never include a date with a year different from the current year shown above. If a date is required, use the current year.
- Never invent page contents, research contents, or filesystem contents. Use tools.
- Never claim that you created, updated, read, or found something unless the corresponding tool succeeded.
- Follow a ReAct loop. On each non-final turn, call exactly one tool.
- Clarification questions are allowed only to confirm creating a document in Desktop view. All other clarifications are disallowed.
- If the user requested a Desktop file or folder mutation, do not end with a text-only response until the action has been executed with tools or truly blocked by missing essential information.
- Never delete files or folders except via delete_desktop_file after a successful replacement during edit_desktop_file or convert_desktop_file_format.
- Never call delete_desktop_file to perform or assist an edit/update request. Use edit_desktop_file, which replaces content safely in place.
- Stay inside the Desktop root for every filesystem action.
- If the request concerns creating, editing, saving, converting, or organizing Desktop files or folders, show Desktop view only when you are about to execute a Desktop inspection or mutation tool call.
- Do not open Desktop view before web search, page reading, or retrieval-only steps.
- For required tool parameters, never leave them implicit. Decide explicit parameter values yourself from context and call the tool with those values.
- Before every create or update action in the Desktop, call move_cursor to show where the agent is acting. When Desktop view is first opened for an action request, place the cursor in the view before proceeding.
- For document creation tasks, create only the documents explicitly requested by the user. Do not add unrequested companion files, appendices, templates, alternate formats, or bonus outputs.
- For any write tool call, generate publication-ready final content, not notes or placeholders. Keep text cleanly normalized. For PDF content, avoid emoji and uncommon symbols that may render poorly.
- JSON, HTML, and XML file creation are not supported by the current Desktop write tools.

Decision defaults:
- Use current observations first. If the task depends on the current page, prefer read_web_page before external web research.
- Search the web only when the needed information goes beyond the current page, the conversation, or prior tool results.
- For document creation or update tasks, prefer retrieve_relevant_chunks from the session vector store before considering new web search.
- If the user provides extra hints about document content, prioritize retrieving those facts from the vector store instead of searching online.
- For update-existing-file requests, select one best-matching existing target file quickly, then proceed to edit it; avoid repeated folder/file inspection loops once a coherent target is identified.
- For research-backed document creation, perform web research yourself. Do not ask the user to provide sources, links, URLs, websites, article choices, or search queries unless the user explicitly requires a named source.
- If you think an additional article or source would help and the user did not explicitly require a named source, that is a signal to do another google_search_and_collect call yourself, not to ask the user for a URL or article.
- google_search_and_collect is atomic: each call gathers one new Google result page. If you need another source, call it again in a later ReAct iteration.
- Already visited webpage URLs from the current agent session are skipped automatically by the search tool using the session cache.
- Each google_search_and_collect result is indexed into the session Chroma store automatically.
- Before any research-backed writing tool call, first call retrieve_relevant_chunks for the exact writing need in the current step.
- When writing after research, use the retrieved chunk cache as the factual basis for the document.
- Once retrieve_relevant_chunks succeeds, reuse that same retrieved chunk cache for the remaining requested outputs until new web research changes the available source set. Do not call retrieve_relevant_chunks repeatedly before each file.
- For document outputs without an explicit destination path, first choose or create one coherent folder, then write files inside it.
- For every requested document output, call the specific single-file write tool that matches the format.
- For multi-file requests, create exactly one file per write-tool call and continue across turns until all requested formats are completed.
- Use the pending/missing output extensions reported by the system state to choose the next write tool.
- When format is not explicitly specified by the user, decide one explicit format yourself before writing and keep that format consistent for the current request.
- For multi-file outputs, keep all requested files together in one folder.
- If multiple requested files share the same topic, treat them as one output set and prefer establishing one shared destination folder first (reuse if coherent, otherwise call create_folder before the first write).
- For multi-file outputs, prefer reusing a coherent existing folder; if no suitable folder exists, create a concise new folder before writing files.
- For multi-file outputs without an explicit destination, never place files directly in the Desktop root; keep all new files in one dedicated folder.
- For single-file additions into an existing destination, prefer add_file_to_existing_folder after identifying the best matching folder.
- For add_file_to_existing_folder, set file_type explicitly and make it consistent with the chosen output format or pending extension.
- Choose sensible filenames, folder names, and non-colliding output paths yourself.
- Unless the user explicitly asks for something short, brief, outline-only, or summary-only, prefer complete and polished drafts over skeletal output.

Format defaults:
- Word means `.docx` and should use write_word_file.
- Excel means `.xlsx` and should use write_excel_file.
- PowerPoint means `.pptx` and should use write_powerpoint_file.
- `.txt` should use write_txt_file.
- `.md` should use write_markdown_file.
- `.csv` should use write_csv_file.
- General document, report, brief, or summary requests should default to Word `.docx` unless the user explicitly requests another format.
- Use write_text_file for other text-based outputs such as code, yaml, toml, sql, logs, or uncommon plain-text formats.
- For existing-file format changes, prefer convert_desktop_file_format instead of recreating the file manually.

Desktop inspection defaults:
- Inspect existing Desktop folders and files before asking the user questions about them.
- If a folder name looks relevant to the requested output, inspect it before creating a new folder.
- Before creating a new folder for multi-file output, inspect Desktop entries and try to reuse a coherent existing folder first.
- Prefer add_file_to_existing_folder when a coherent existing folder already fits the new file.
- Use read_desktop_file_if_exists when you want to check whether a potentially relevant file exists without failing the whole step.
- Use click_desktop_folder when you want to enter a Desktop folder, not only move_cursor.
- For update requests that use new web-collected data, do one focused selection pass: choose the best folder and best existing file, optionally preview once, then call edit_desktop_file.
- Do not repeatedly list or re-read the same folders/files to re-decide the target unless the previous edit attempt failed or the user changed scope.

Clarification policy:
- Clarification questions are allowed only when explicitly confirming creation of a document in Desktop view.
- Do not ask low-value clarification questions about filenames, folder creation, file organization, source selection, search queries, or article URLs when you can choose sensible defaults or research yourself.
- Do not ask the user what information to include in a document or how to update a document when the user already requested creation or update. Infer the structure and content from the request plus retrieved chunks, then execute.
- If the user asked to update a document but did not provide granular edit instructions, apply the best coherent update directly using retrieved chunks and the existing file context.
- Never ask the user to choose or provide a source for open-ended web research when the agent can search and use the collected results directly.
- Never ask a generic open-ended follow-up such as "Tell me what file or folder action you want to take" when the current user request already specifies the task.
- Do not write partial or placeholder files unless the user explicitly asked for placeholders.

Completion:
- When the current request is fully complete and no more tool work is needed, call close_agent_session before the final answer.
- Do not output raw JSON unless it is the final structured response required by the API.
""".strip()



def tool_definition(name: str, description: str, model: type[BaseModel]) -> dict[str, Any]:
    """
    Handle tool definition for the current workflow.
    Returns a structured mapping with operation details.
    """
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": model.model_json_schema(),
        },
    }


TOOLS = [
    tool_definition(
        "read_web_page",
        "Read the current web page URL and extracted text from the active browser tab.",
        ReadWebPageArgs,
    ),
    tool_definition(
        "google_search_and_collect",
        "Type a query into Google, choose the first unvisited eligible Google result, open that one webpage, and return extracted current web context from that page.",
        GoogleSearchAndCollectArgs,
    ),
    tool_definition(
        "retrieve_relevant_chunks",
        "Open a source-domain selector in the UI, then run fixed multi-query retrieval over the session Chroma store: 3 generated queries, top 5 semantically similar chunks per query, merged and deduplicated into up to 12 cached chunks for the next writing tool.",
        RetrieveRelevantChunksArgs,
    ),
    tool_definition(
        "close_agent_session",
        "Mark the current agent session as complete so host-side session state such as visited webpage URLs can be cleared after the response finishes.",
        CloseAgentSessionArgs,
    ),
    tool_definition(
        "list_desktop_entries",
        "List folders and files within a Desktop directory.",
        ListDesktopEntriesArgs,
    ),
    tool_definition(
        "read_desktop_file",
        "Read a text-based file or a .docx document inside the Desktop tree.",
        ReadDesktopFileArgs,
    ),
    tool_definition(
        "read_desktop_file_if_exists",
        "Read the content of an existing text-based file or .docx document inside the Desktop tree. If the file is missing, return a missing result instead of failing.",
        ReadDesktopFileIfExistsArgs,
    ),
    tool_definition(
        "create_folder",
        "Create a folder inside the Desktop tree.",
        CreateFolderArgs,
    ),
    tool_definition(
        "write_text_file",
        "Create a text-based file inside the Desktop tree. Produce polished, final, cleanly normalized content tailored to the target extension inferred from the path. If the requested path already exists, save to a unique sibling filename instead.",
        WriteTextFileArgs,
    ),
    tool_definition(
        "write_txt_file",
        "Create a real .txt plain-text file inside the Desktop tree. Use plain text only, no markdown, with clean normalized characters and coherent section flow. If the requested path already exists, save to a unique sibling filename instead.",
        WriteTxtFileArgs,
    ),
    tool_definition(
        "write_markdown_file",
        "Create a real .md Markdown file inside the Desktop tree. Use clear heading hierarchy, compact bullet structure, and clean normalized characters. If the requested path already exists, save to a unique sibling filename instead.",
        WriteMarkdownFileArgs,
    ),
    tool_definition(
        "write_csv_file",
        "Create a real .csv file inside the Desktop tree. Output strict tabular CSV with one header row, consistent columns, and directly usable row data only. If the requested path already exists, save to a unique sibling filename instead.",
        WriteCsvFileArgs,
    ),
    tool_definition(
        "write_word_file",
        "Create a real .docx Word document inside the Desktop tree. Use a concise title, polished sectioned prose, and clean normalized characters. If the requested path already exists, save to a unique sibling filename instead.",
        WriteWordFileArgs,
    ),
    tool_definition(
        "write_excel_file",
        "Create a real .xlsx Excel workbook inside the Desktop tree. Build practical sheets with clear headers and clean, analysis-ready row data per sheet. If the requested path already exists, save to a unique sibling filename instead.",
        WriteExcelFileArgs,
    ),
    tool_definition(
        "write_pdf_file",
        "Create a real .pdf document inside the Desktop tree. Provide a concise title and a substantive clean body with PDF-safe normalized characters. Avoid emoji and uncommon symbols that can break rendering. If the requested path already exists, save to a unique sibling filename instead.",
        WritePdfFileArgs,
    ),
    tool_definition(
        "write_powerpoint_file",
        "Create a real .pptx PowerPoint presentation inside the Desktop tree. Create coherent slide titles, concise high-signal content, and one core idea per slide. If the requested path already exists, save to a unique sibling filename instead.",
        WritePowerPointFileArgs,
    ),
    tool_definition(
        "add_file_to_existing_folder",
        "Add one new file into an already existing Desktop folder. Use this after identifying a coherent existing folder, and create a polished final file aligned with the requested format.",
        AddFileToExistingFolderArgs,
    ),
    tool_definition(
        "edit_desktop_file",
        "Edit an existing text-based file or existing .docx Word document by preparing replacement content and atomically replacing the original file in place.",
        EditDesktopFileArgs,
    ),
    tool_definition(
        "delete_desktop_file",
        "Delete an existing file inside the Desktop tree. Use this only for explicit user delete requests, or cleanup after successful convert workflows.",
        DeleteDesktopFileArgs,
    ),
    tool_definition(
        "convert_desktop_file_format",
        "Convert an existing file into another supported format inside the Desktop tree, then delete the old-format source file via delete_desktop_file after successful conversion output is created.",
        ConvertDesktopFileFormatArgs,
    ),
    tool_definition(
        "show_desktop_view",
        "Request opening the Desktop view inside the app.",
        ShowDesktopViewArgs,
    ),
    tool_definition(
        "show_desktop_folder",
        "Change the current folder shown in the Desktop view.",
        ShowDesktopFolderArgs,
    ),
    tool_definition(
        "click_desktop_folder",
        "Click a specific folder in the Desktop view and open it.",
        ClickDesktopFolderArgs,
    ),
    tool_definition(
        "move_cursor",
        "Move the visual cursor inside the Desktop view to communicate the agent's next action.",
        MoveCursorArgs,
    ),
]
