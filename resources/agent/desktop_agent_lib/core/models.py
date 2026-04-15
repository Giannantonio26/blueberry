from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class PageContext(BaseModel):
    url: str | None = None
    text: str | None = None


class WebSearchLimits(BaseModel):
    min_websites: int | None = Field(
        default=None,
        ge=0,
        le=50,
        description="Minimum desired number of web-search tool calls for the current agent session.",
    )
    max_websites: int | None = Field(
        default=None,
        ge=0,
        le=50,
        description="Maximum allowed number of web-search tool calls for the current agent session.",
    )


class AgentInput(BaseModel):
    api_key: str
    base_url: str
    model: str
    writer_model: str | None = None
    messages: list[HistoryMessage]
    page_context: PageContext = Field(default_factory=PageContext)
    desktop_root: str
    open_desktop_hint: bool = False
    visited_websites: dict[str, str] = Field(default_factory=dict)
    web_search_steps_used: int = Field(default=0, ge=0)
    web_search_limits: WebSearchLimits = Field(default_factory=WebSearchLimits)
    force_write_outputs: bool = False


class ToolResult(BaseModel):
    content: str
    filesystem_changed: bool = False
    changed_paths: list[str] = Field(default_factory=list)
    should_open_desktop_view: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentFinal(BaseModel):
    message: str = ""
    requires_clarification: bool = False
    should_open_desktop_view: bool = False
    filesystem_changed: bool = False
    created_or_updated_paths: list[str] = Field(default_factory=list)
    close_agent_session: bool = False


class FilenameSuggestion(BaseModel):
    stem: str = Field(
        default="",
        description="Short descriptive filename stem without an extension or path.",
    )


class ReadWebPageArgs(BaseModel):
    purpose: str = Field(
        ...,
        description="Why the page content is needed for the current task.",
    )


class GoogleSearchAndCollectArgs(BaseModel):
    query: str = Field(
        ...,
        description="The Google query to type into the search bar before gathering web information.",
    )
    purpose: str = Field(
        ...,
        description="Why the web search is needed for the current task.",
    )


class CloseAgentSessionArgs(BaseModel):
    reason: str = Field(
        ...,
        description="Brief reason why the current agent session can be closed.",
    )


class RetrieveRelevantChunksArgs(BaseModel):
    query: str = Field(
        ...,
        description="A focused semantic query describing the information needed for the next writing step.",
    )
    top_k: int = Field(
        default=12,
        ge=1,
        le=12,
        description=(
            "Fixed multi-query retrieval. The runtime generates 3 retrieval queries, "
            "retrieves top 5 chunks per query, merges and deduplicates them, and "
            "returns up to 12 final chunks. Any provided value is ignored."
        ),
    )


class ListDesktopEntriesArgs(BaseModel):
    path: str | None = Field(
        default=None,
        description="Optional path within the Desktop root. Use null for the Desktop root.",
    )


class ReadDesktopFileArgs(BaseModel):
    path: str = Field(..., description="Path to a file inside the Desktop root.")


class ReadDesktopFileIfExistsArgs(BaseModel):
    path: str = Field(
        ...,
        description="Path to a file inside the Desktop root. If the file does not exist, return a missing result instead of failing.",
    )


class CreateFolderArgs(BaseModel):
    path: str = Field(
        ...,
        description="Folder path to create inside the Desktop root.",
    )


class WriteTextFileArgs(BaseModel):
    path: str = Field(
        ...,
        description="Path to the text-based file to create inside the Desktop root. If the path already exists, a unique sibling filename will be used automatically.",
    )
    content: str = Field(
        ...,
        description="The complete final text content to write. Must be clean, readable, and publication-ready for the target format.",
    )


class WriteTxtFileArgs(WriteTextFileArgs):
    path: str = Field(
        ...,
        description="Path to the .txt file to create inside the Desktop root. If the path already exists, a unique sibling filename will be used automatically.",
    )


class WriteMarkdownFileArgs(WriteTextFileArgs):
    path: str = Field(
        ...,
        description="Path to the .md file to create inside the Desktop root. If the path already exists, a unique sibling filename will be used automatically.",
    )


class WriteCsvFileArgs(WriteTextFileArgs):
    path: str = Field(
        ...,
        description="Path to the .csv file to create inside the Desktop root. If the path already exists, a unique sibling filename will be used automatically.",
    )


class WriteJsonFileArgs(WriteTextFileArgs):
    path: str = Field(
        ...,
        description="Path to the .json file to create inside the Desktop root. If the path already exists, a unique sibling filename will be used automatically.",
    )


class WriteHtmlFileArgs(WriteTextFileArgs):
    path: str = Field(
        ...,
        description="Path to the .html file to create inside the Desktop root. If the path already exists, a unique sibling filename will be used automatically.",
    )


class WriteXmlFileArgs(WriteTextFileArgs):
    path: str = Field(
        ...,
        description="Path to the .xml file to create inside the Desktop root. If the path already exists, a unique sibling filename will be used automatically.",
    )


class WriteWordFileArgs(BaseModel):
    path: str = Field(
        ...,
        description="Path to the .docx file to create inside the Desktop root. If the path already exists, a unique sibling filename will be used automatically.",
    )
    title: str | None = Field(
        default=None,
        description="Optional document title. Keep concise and publication-ready.",
    )
    content: str | None = Field(
        default=None,
        description="Optional body content. Line breaks will be converted to paragraphs. Provide polished prose, not notes.",
    )
    paragraphs: list[str] = Field(
        default_factory=list,
        description="Optional ordered paragraphs for the document body.",
    )


class ExcelSheet(BaseModel):
    name: str = Field(..., description="Worksheet name.")
    rows: list[list[Any]] = Field(
        default_factory=list,
        description="Tabular worksheet rows. Each inner list is a row.",
    )


class PowerPointSlide(BaseModel):
    title: str | None = Field(
        default=None,
        description="Optional slide title.",
    )
    content: str | None = Field(
        default=None,
        description="Optional slide body text. Line breaks will be converted into separate text paragraphs.",
    )
    bullets: list[str] = Field(
        default_factory=list,
        description="Optional bullet points for the slide body.",
    )


class RetrievedChunk(BaseModel):
    chunk_id: str = Field(..., description="Unique identifier for the retrieved chunk.")
    text: str = Field(..., description="Chunk text content.")
    source_url: str = Field(..., description="Source URL for the chunk.")
    source_title: str = Field(..., description="Source article title for the chunk.")
    source_domain: str | None = Field(
        default=None,
        description="Optional source domain for the chunk.",
    )
    similarity: float | None = Field(
        default=None,
        description="Optional semantic similarity score returned by retrieval.",
    )


class RetrievalQueryBatch(BaseModel):
    queries: list[str] = Field(
        default_factory=list,
        min_length=3,
        max_length=3,
        description="Exactly three distinct retrieval queries for multi-query vector search.",
    )


class GeneratedDocumentDraft(BaseModel):
    title: str | None = Field(default=None, description="Optional generated title.")
    content: str | None = Field(
        default=None,
        description="Optional generated body content.",
    )
    paragraphs: list[str] = Field(
        default_factory=list,
        description="Generated ordered paragraphs.",
    )


class GeneratedPresentationDraft(BaseModel):
    title: str | None = Field(default=None, description="Optional presentation title.")
    slides: list[PowerPointSlide] = Field(
        default_factory=list,
        description="Generated slides.",
    )


class GeneratedWorkbookDraft(BaseModel):
    sheets: list[ExcelSheet] = Field(
        default_factory=list,
        description="Generated spreadsheet sheets.",
    )


class MultiFileSpec(BaseModel):
    file_type: Literal[
        "text", "txt", "markdown", "csv", "word", "excel", "pdf", "powerpoint"
    ] = Field(
        ...,
        description=(
            'The type of file to create: "txt" creates a .txt file, '
            '"markdown" creates a .md file, "csv" creates a .csv file, '
            '"word" creates a .docx file, "excel" creates a .xlsx file, '
            '"powerpoint" creates a .pptx file, "pdf" creates a .pdf file, '
            'and "text" creates another supported text-based file.'
        ),
    )
    destination_folder: str | None = Field(
        default=None,
        description="Optional destination folder inside the Desktop root for this specific file item. Used when path is not provided.",
    )
    path: str | None = Field(
        default=None,
        description="Optional path to create inside the Desktop root. If omitted, a descriptive filename will be chosen automatically.",
    )
    title: str | None = Field(
        default=None,
        description="Optional document or presentation title.",
    )
    content: str | None = Field(
        default=None,
        description="Optional body content for text, Word, PDF, or PowerPoint files. For PDF, prefer plain PDF-safe characters and avoid emoji/uncommon symbols.",
    )
    paragraphs: list[str] = Field(
        default_factory=list,
        description="Optional ordered paragraphs for Word or PDF files.",
    )
    sheets: list[ExcelSheet] = Field(
        default_factory=list,
        description="Optional worksheet payload for Excel files.",
    )
    slides: list[PowerPointSlide] = Field(
        default_factory=list,
        description="Optional slide payload for PowerPoint files.",
    )


class WriteExcelFileArgs(BaseModel):
    path: str = Field(
        ...,
        description="Path to the .xlsx file to create inside the Desktop root. If the path already exists, a unique sibling filename will be used automatically.",
    )
    sheets: list[ExcelSheet] = Field(
        ...,
        description="One or more worksheets with tabular rows.",
    )


class WritePdfFileArgs(BaseModel):
    path: str = Field(
        ...,
        description="Path to the .pdf file to create inside the Desktop root. If the path already exists, a unique sibling filename will be used automatically.",
    )
    title: str | None = Field(
        default=None,
        description="Optional PDF title. Keep concise and clear.",
    )
    content: str | None = Field(
        default=None,
        description="Optional PDF body content. Line breaks will be converted to paragraphs. Use PDF-safe characters and avoid emoji or uncommon symbols.",
    )
    paragraphs: list[str] = Field(
        default_factory=list,
        description="Optional ordered paragraphs for the PDF body.",
    )


class WritePowerPointFileArgs(BaseModel):
    path: str = Field(
        ...,
        description="Path to the .pptx file to create inside the Desktop root. If the path already exists, a unique sibling filename will be used automatically.",
    )
    title: str | None = Field(
        default=None,
        description="Optional presentation title.",
    )
    content: str | None = Field(
        default=None,
        description="Optional presentation brief or content hint used only to guide slide generation.",
    )
    slides: list[PowerPointSlide] = Field(
        ...,
        description="One or more slides for the PowerPoint presentation.",
    )


class CreateMultipleFilesArgs(BaseModel):
    files: list[MultiFileSpec] = Field(
        ...,
        min_length=2,
        description=(
            "The exact set of files to create in a single tool call. Mixed-format "
            "batches are supported across txt, markdown, csv, docx, xlsx, pdf, "
            "pptx, and other supported text outputs. If the user requested a "
            "specific number of files, include exactly that many items."
        ),
    )


class AddFileToExistingFolderArgs(BaseModel):
    folder_path: str = Field(
        ...,
        description="Path to an existing folder inside the Desktop root where the new file should be added.",
    )
    file_type: Literal[
        "text", "txt", "markdown", "csv", "word", "excel", "pdf", "powerpoint"
    ] = Field(
        ...,
        description=(
            'The type of file to add: "txt" creates a .txt file, '
            '"markdown" creates a .md file, "csv" creates a .csv file, '
            '"word" creates a .docx file, "excel" creates a .xlsx file, '
            '"powerpoint" creates a .pptx file, "pdf" creates a .pdf file, '
            'and "text" creates another supported text-based file.'
        ),
    )
    file_name: str | None = Field(
        default=None,
        description="Optional file name to use inside the chosen existing folder. If omitted, a descriptive filename will be chosen automatically.",
    )
    title: str | None = Field(
        default=None,
        description="Optional document or presentation title.",
    )
    content: str | None = Field(
        default=None,
        description="Optional body content for text, Word, PDF, or PowerPoint files. For PDF, prefer plain PDF-safe characters and avoid emoji/uncommon symbols.",
    )
    paragraphs: list[str] = Field(
        default_factory=list,
        description="Optional ordered paragraphs for Word or PDF files.",
    )
    sheets: list[ExcelSheet] = Field(
        default_factory=list,
        description="Optional worksheet payload for Excel files.",
    )
    slides: list[PowerPointSlide] = Field(
        default_factory=list,
        description="Optional slide payload for PowerPoint files.",
    )


class EditDesktopFileArgs(BaseModel):
    path: str = Field(
        ...,
        description="Path to an existing text-based file or .docx document inside the Desktop root that should be edited in place.",
    )
    title: str | None = Field(
        default=None,
        description="Optional replacement title. Mainly used for .docx edits.",
    )
    content: str | None = Field(
        default=None,
        description="Replacement body content for the file.",
    )
    paragraphs: list[str] = Field(
        default_factory=list,
        description="Optional ordered paragraphs for the replacement document body.",
    )


class DeleteDesktopFileArgs(BaseModel):
    path: str = Field(
        ...,
        description="Path to the existing file inside the Desktop root that should be deleted.",
    )
    reason: str = Field(
        ...,
        description="Brief reason for deleting the file.",
    )


class ConvertDesktopFileFormatArgs(BaseModel):
    source_path: str = Field(
        ...,
        description="Path to the existing source file inside the Desktop root that should be converted.",
    )
    target_format: str = Field(
        ...,
        description="Target format such as docx, txt, md, csv, xlsx, pdf, or pptx.",
    )
    output_path: str | None = Field(
        default=None,
        description="Optional output path for the converted file. If omitted, create a non-conflicting sibling file with the new extension.",
    )


class ShowDesktopViewArgs(BaseModel):
    reason: str = Field(
        ...,
        description="Brief reason for showing the desktop view.",
    )


class ShowDesktopFolderArgs(BaseModel):
    path: str = Field(
        ...,
        description="Path to the folder inside the Desktop root that should become the current folder in the Desktop view.",
    )
    reason: str = Field(
        ...,
        description="Brief reason for changing the current folder in the Desktop view.",
    )


class ClickDesktopFolderArgs(BaseModel):
    path: str = Field(
        ...,
        description="Path to the folder inside the Desktop root that should be clicked and opened.",
    )
    reason: str = Field(
        ...,
        description="Brief reason for clicking and opening the folder.",
    )


class MoveCursorArgs(BaseModel):
    target: Literal[
        "desktop-center",
        "folder-grid",
        "inspector-panel",
        "header-controls",
        "taskbar",
        "current-folder-card",
    ] = Field(
        ...,
        description="Named target area in the Desktop view where the visual cursor should move.",
    )
    reason: str = Field(
        ...,
        description="Brief reason for the cursor movement.",
    )
    click: bool = Field(
        default=False,
        description="Whether the cursor should show a click ripple at the destination.",
    )


for _model in (
    HistoryMessage,
    PageContext,
    WebSearchLimits,
    AgentInput,
    ToolResult,
    AgentFinal,
    FilenameSuggestion,
    ReadWebPageArgs,
    GoogleSearchAndCollectArgs,
    CloseAgentSessionArgs,
    RetrieveRelevantChunksArgs,
    ListDesktopEntriesArgs,
    ReadDesktopFileArgs,
    ReadDesktopFileIfExistsArgs,
    CreateFolderArgs,
    WriteTextFileArgs,
    WriteWordFileArgs,
    ExcelSheet,
    PowerPointSlide,
    RetrievedChunk,
    RetrievalQueryBatch,
    GeneratedDocumentDraft,
    GeneratedPresentationDraft,
    GeneratedWorkbookDraft,
    MultiFileSpec,
    WriteExcelFileArgs,
    WritePdfFileArgs,
    WritePowerPointFileArgs,
    CreateMultipleFilesArgs,
    AddFileToExistingFolderArgs,
    EditDesktopFileArgs,
    DeleteDesktopFileArgs,
    ConvertDesktopFileFormatArgs,
    ShowDesktopViewArgs,
    ShowDesktopFolderArgs,
    ClickDesktopFolderArgs,
    MoveCursorArgs,
):
    _model.model_rebuild()



