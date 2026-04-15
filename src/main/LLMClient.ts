import {
  dialog,
  ipcMain,
  WebContents,
  type IpcMainEvent,
  type MessageBoxOptions,
} from "electron";
import { basename, dirname, isAbsolute, resolve } from "node:path";
import { streamText, type LanguageModel, type CoreMessage } from "ai";
import { anthropic } from "@ai-sdk/anthropic";
import { runGoogleSearchAndCollect } from "./BrowserResearchTool";
import {
  clearBrowserCompanion,
  showBrowserCompanion,
} from "./BrowserCompanionOverlay";
import {
  focusOrCreateDesktopWindow,
  sendDesktopWindowEvent,
} from "./DesktopWindowManager";
import { appendDesktopAgentDebugLog } from "./DesktopAgentDebugLogger";
import {
  dumpDesktopAgentChromaStore,
  resetDesktopAgentChromaStore,
  runDesktopAgent,
  type AgentReactIterationEvent,
  type AgentConfirmationRequestEvent,
  type AgentRunResult,
  type ChromaStoreDumpResult,
  type AgentHostToolRequest,
  type AgentHostToolResponse,
  type AgentToolCallEvent,
  type AgentHistoryMessage,
} from "./DesktopAgent";
import type { Window } from "./Window";
import {
  coerceConsultingAgentPathToDesktopRoot,
  getConsultingAgentDesktopRootPath,
} from "./ConsultingAgentWorkspace";
import { openVectorStoreViewerWindow } from "./VectorStoreViewerWindow";

interface ChatRequest {
  message: string;
  messageId: string;
  webSearchLimits?: {
    minWebsites?: number;
    maxWebsites?: number;
  };
}

interface WebSearchLimits {
  minWebsites: number;
  maxWebsites: number;
}

interface StreamChunk {
  content: string;
  isComplete: boolean;
}

type DesktopCursorTarget =
  | "desktop-center"
  | "folder-grid"
  | "inspector-panel"
  | "header-controls"
  | "taskbar"
  | "current-folder-card"
  | "files-end";

type DesktopCursorAction =
  | "move_cursor"
  | "click_folder"
  | "move_to_folder"
  | "show_folder"
  | "move_to_file"
  | "read_file";

interface DesktopCursorMovePayload {
  eventId?: string;
  action?: DesktopCursorAction;
  target: DesktopCursorTarget;
  reason: string;
  click?: boolean;
  label?: string;
  loading?: boolean;
  path?: string;
  navigate?: boolean;
}

interface DesktopActionNotificationPayload {
  kind: "folder" | "file" | "update" | "conversion" | "batch";
  title: string;
  description: string;
  path?: string;
}

interface DesktopActionFeedbackPayload {
  clearCursor?: boolean;
  notifications?: DesktopActionNotificationPayload[];
}

interface RetrievalSourceSelectionRequestPayload {
  requestId: string;
  query: string;
  availableSourceDomains: string[];
  defaultSelectedSourceDomains: string[];
}

interface RetrievalSourceSelectionResponsePayload {
  requestId?: string;
  action?: "confirm" | "cancel";
  selectedSourceDomains?: string[];
}

type LLMProvider = "gemini" | "anthropic";

const DEFAULT_MODELS: Record<LLMProvider, string> = {
  gemini: "gemini-3-flash-preview",
  anthropic: "claude-3-5-sonnet-20241022",
};

const MAX_CONTEXT_LENGTH = 4000;
const DEFAULT_TEMPERATURE = 0.7;
const PENDING_AGENT_ASSISTANT_MESSAGE = "Working on it. I will update you shortly.";
const DEFAULT_GEMINI_CHAT_COMPLETIONS_URL =
  "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions";
const DEFAULT_MIN_WEBSITE_VISITS = 4;
const DEFAULT_MAX_WEBSITE_VISITS = 7;
const MIN_WEBSITE_VISITS_LIMIT = 0;
const MAX_WEBSITE_VISITS_LIMIT = 20;

export class LLMClient {
  private readonly webContents: WebContents;
  private window: Window | null = null;
  private readonly provider: LLMProvider;
  private readonly modelName: string;
  private readonly model: LanguageModel | null;
  private messages: CoreMessage[] = [];
  private agentSessionActive = false;
  private forceWriteModeActive = false;
  private stopWebSearchRequested = false;
  private agentRunInProgress = false;
  private pendingForceWriteAfterRun = false;
  private readonly agentSessionVisitedWebsites = new Map<string, string>();
  private agentSessionWebSearchCalls = 0;
  private webSearchLimits: WebSearchLimits = {
    minWebsites: DEFAULT_MIN_WEBSITE_VISITS,
    maxWebsites: DEFAULT_MAX_WEBSITE_VISITS,
  };

  constructor(webContents: WebContents) {
    this.webContents = webContents;
    this.provider = this.getProvider();
    this.modelName = this.getModelName();
    this.model = this.initializeModel();

    this.logInitializationStatus();
  }

  // Set the window reference after construction to avoid circular dependencies
  setWindow(window: Window): void {
    this.window = window;
  }

  private getProvider(): LLMProvider {
    const provider = process.env.LLM_PROVIDER?.toLowerCase();
    if (provider === "anthropic") return "anthropic";
    return "gemini";
  }

  private getModelName(): string {
    const configuredModel = process.env.LLM_MODEL?.trim();
    if (!configuredModel) {
      return DEFAULT_MODELS[this.provider];
    }

    if (this.provider !== "gemini") {
      return configuredModel;
    }

    const normalizedGeminiModel = this.normalizeGeminiModelName(configuredModel);
    if (this.isGeminiModelName(normalizedGeminiModel)) {
      return normalizedGeminiModel;
    }

    const fallbackModel = DEFAULT_MODELS.gemini;
    console.warn(
      `[LLM] LLM_MODEL "${configuredModel}" is not a Gemini model. Falling back to "${fallbackModel}".`
    );
    return fallbackModel;
  }

  private normalizeGeminiModelName(modelName: string): string {
    const trimmed = modelName.trim();
    if (!trimmed) {
      return trimmed;
    }

    if (trimmed.toLowerCase().startsWith("models/")) {
      return trimmed.slice("models/".length);
    }

    return trimmed;
  }

  private isGeminiModelName(modelName: string): boolean {
    const normalized = modelName.toLowerCase();
    return normalized.startsWith("gemini-");
  }

  private initializeModel(): LanguageModel | null {
    const apiKey = this.getApiKey();
    if (!apiKey) return null;

    switch (this.provider) {
      case "anthropic":
        return anthropic(this.modelName);
      case "gemini":
        return null;
      default:
        return null;
    }
  }

  private getApiKey(): string | undefined {
    switch (this.provider) {
      case "anthropic":
        return process.env.ANTHROPIC_API_KEY;
      case "gemini":
        return process.env.GEMINI_API_KEY;
      default:
        return undefined;
    }
  }

  private logInitializationStatus(): void {
    if (this.provider === "gemini" ? !!this.getApiKey() : !!this.model) {
      console.log(
        `✅ LLM Client initialized with ${this.provider} provider using model: ${this.modelName}`
      );
    } else {
      const keyName =
        this.provider === "anthropic"
          ? "ANTHROPIC_API_KEY"
          : "GEMINI_API_KEY";
      console.error(
        `❌ LLM Client initialization failed: ${keyName} not found in environment variables.\n` +
          `Please add your API key to the .env file in the project root.`
      );
    }
  }

  async sendChatMessage(request: ChatRequest): Promise<void> {
    try {
      if (this.provider === "gemini") {
        await this.sendGeminiAgentMessage(request);
        return;
      }

      // Get screenshot from active tab if available
      let screenshot: string | null = null;
      if (this.window) {
        const activeTab = this.window.activeTab;
        if (activeTab) {
          try {
            const image = await activeTab.screenshot();
            screenshot = image.toDataURL();
          } catch (error) {
            console.error("Failed to capture screenshot:", error);
          }
        }
      }

      // Build user message content with screenshot first, then text
      const userContent: any[] = [];
      
      // Add screenshot as the first part if available
      if (screenshot) {
        userContent.push({
          type: "image",
          image: screenshot,
        });
      }
      
      // Add text content
      userContent.push({
        type: "text",
        text: request.message,
      });

      // Create user message in CoreMessage format
      const userMessage: CoreMessage = {
        role: "user",
        content: userContent.length === 1 ? request.message : userContent,
      };
      
      this.messages.push(userMessage);

      // Send updated messages to renderer
      this.sendMessagesToRenderer();

      if (!this.model) {
        this.sendErrorMessage(
          request.messageId,
          "LLM service is not configured. Please add the provider API key to the .env file."
        );
        return;
      }

      const messages = await this.prepareMessagesWithContext(request);
      await this.streamResponse(messages, request.messageId);
    } catch (error) {
      console.error("Error in LLM request:", error);
      this.closeAgentSession();
      this.handleStreamError(error, request.messageId);
    }
  }

  private async sendGeminiAgentMessage(request: ChatRequest): Promise<void> {
    if (this.agentRunInProgress) {
      this.sendErrorMessage(
        request.messageId,
        "The agent is already running. Please wait or use Stop web search."
      );
      return;
    }

    this.agentRunInProgress = true;
    const normalizedWebSearchLimits = this.normalizeWebSearchLimits(
      request.webSearchLimits
    );
    if (normalizedWebSearchLimits) {
      this.webSearchLimits = normalizedWebSearchLimits;
    }
    this.appendUserTextMessage(request.message);
    let openDesktopHint = false;
    let usedDesktopViewTool = false;
    const desktopMutationEvents: AgentToolCallEvent[] = [];
    let didSendDesktopActionFeedback = false;

    try {
      const apiKey = this.getApiKey();
      if (!apiKey) {
        this.sendErrorMessage(
          request.messageId,
          "LLM service is not configured. Please add the provider API key to the .env file."
        );
        return;
      }

      openDesktopHint = this.isDesktopActionRequest(request.message);
      const shouldRequestMutationConfirmation =
        this.isDesktopMutationRequest(request.message) &&
        !this.isDesktopChatRequest(request.messageId);
      if (shouldRequestMutationConfirmation) {
        const isConfirmed = await this.confirmDesktopAction(request.message);
        if (!isConfirmed) {
          const cancellationMessage =
            "Desktop action cancelled. Tell me what to create or change when you're ready.";

          this.appendOrReplaceAssistantMessage(cancellationMessage);
          this.sendStreamChunk(request.messageId, {
            content: cancellationMessage,
            isComplete: true,
          });
          return;
        }
      }

      this.upsertPendingAssistantMessage();
      this.startAgentSession();
      const announcedReactIterationSteps = new Set<number>();

      const agentResult = await runDesktopAgent({
        apiKey,
        baseUrl:
          process.env.GEMINI_BASE_URL || DEFAULT_GEMINI_CHAT_COMPLETIONS_URL,
        model: this.modelName,
        messages: this.buildAgentHistory(),
        pageContext: await this.getCurrentPageContext(),
        desktopRoot: getConsultingAgentDesktopRootPath(),
        openDesktopHint,
        visitedWebsites: this.getAgentSessionVisitedWebsites(),
        webSearchStepsUsed: this.getAgentSessionWebSearchCalls(),
        webSearchLimits: this.webSearchLimits,
      }, {
        onToolCall: (event) => {
          if (this.isDesktopViewTool(event.toolName)) {
            usedDesktopViewTool = true;
          }
          if (this.isDesktopMutationTool(event.toolName)) {
            desktopMutationEvents.push(event);
          }
          this.handleAgentToolCall(event);
        },
        onReactIteration: (event) => {
          this.handleReactIterationCompanionUpdate(
            event,
            announcedReactIterationSteps
          );
        },
        onConfirmationRequest: async (event) => {
          return await this.requestDesktopFileConfirmation(event);
        },
        onHostToolRequest: async (event) => {
          return await this.executeHostToolRequest(event);
        },
      });

      const shouldKeepDesktopView =
        usedDesktopViewTool ||
        agentResult.filesystem_changed ||
        agentResult.created_or_updated_paths.length > 0;

      if (shouldKeepDesktopView) {
        focusOrCreateDesktopWindow();
      } else {
        this.focusBrowserWindow();
      }

      if (agentResult.filesystem_changed) {
        this.sendDesktopWindowEvent("desktop-filesystem-updated", {
          changedPaths: agentResult.created_or_updated_paths,
        });
        this.sendDesktopWindowEvent(
          "desktop-action-feedback",
          this.buildDesktopActionFeedbackPayload(
            agentResult,
            desktopMutationEvents
          )
        );
        this.moveCursorInsideLatestCreatedFolder(
          agentResult,
          desktopMutationEvents
        );
        didSendDesktopActionFeedback = true;
      }

      this.appendOrReplaceAssistantMessage(agentResult.message);

      this.sendStreamChunk(request.messageId, {
        content: agentResult.message,
        isComplete: true,
      });

      if (agentResult.close_agent_session) {
        this.closeAgentSession();
      }
    } finally {
      await this.clearBrowserCompanionOnActiveTab();
      if (
        (usedDesktopViewTool || desktopMutationEvents.length > 0) &&
        !didSendDesktopActionFeedback
      ) {
        this.sendDesktopWindowEvent("desktop-action-feedback", {
          clearCursor: true,
        });
      }
      this.agentRunInProgress = false;
      if (this.pendingForceWriteAfterRun) {
        this.pendingForceWriteAfterRun = false;
        void this.forceWriteDocumentsNow();
      }
    }
  }

  async forceWriteDocumentsNow(): Promise<void> {
    if (this.forceWriteModeActive) {
      return;
    }
    this.stopWebSearchRequested = true;
    if (this.agentRunInProgress) {
      this.pendingForceWriteAfterRun = true;
      return;
    }

    let openDesktopHint = false;
    let usedDesktopViewTool = false;
    const desktopMutationEvents: AgentToolCallEvent[] = [];
    let didSendDesktopActionFeedback = false;

    try {
      this.forceWriteModeActive = true;
      if (this.provider !== "gemini") {
        const assistantMessage: CoreMessage = {
          role: "assistant",
          content:
            "This action is only available when the Desktop Agent is enabled.",
        };
        this.messages.push(assistantMessage);
        this.sendMessagesToRenderer();
        return;
      }

      const apiKey = this.getApiKey();
      if (!apiKey) {
        const assistantMessage: CoreMessage = {
          role: "assistant",
          content:
            "LLM service is not configured. Please add the provider API key to the .env file.",
        };
        this.messages.push(assistantMessage);
        this.sendMessagesToRenderer();
        return;
      }

      const latestUserRequest = this.getLatestUserTextMessage();
      if (!latestUserRequest) {
        const assistantMessage: CoreMessage = {
          role: "assistant",
          content: "There is no pending document request to finalize yet.",
        };
        this.messages.push(assistantMessage);
        this.sendMessagesToRenderer();
        return;
      }

      openDesktopHint = this.isDesktopActionRequest(latestUserRequest);

      this.startAgentSession();
      const announcedReactIterationSteps = new Set<number>();

      const agentResult = await runDesktopAgent(
        {
          apiKey,
          baseUrl:
            process.env.GEMINI_BASE_URL || DEFAULT_GEMINI_CHAT_COMPLETIONS_URL,
          model: this.modelName,
          messages: this.buildAgentHistory(),
          pageContext: await this.getCurrentPageContext(),
          desktopRoot: getConsultingAgentDesktopRootPath(),
          openDesktopHint,
          visitedWebsites: this.getAgentSessionVisitedWebsites(),
          webSearchStepsUsed: this.getAgentSessionWebSearchCalls(),
          webSearchLimits: this.webSearchLimits,
          forceWriteOutputs: true,
        },
        {
          onToolCall: (event) => {
            if (this.isDesktopViewTool(event.toolName)) {
              usedDesktopViewTool = true;
            }
            if (this.isDesktopMutationTool(event.toolName)) {
              desktopMutationEvents.push(event);
            }
            this.handleAgentToolCall(event);
          },
          onReactIteration: (event) => {
            this.handleReactIterationCompanionUpdate(
              event,
              announcedReactIterationSteps
            );
          },
          onConfirmationRequest: async (event) => {
            return await this.requestDesktopFileConfirmation(event);
          },
          onHostToolRequest: async (event) => {
            return await this.executeHostToolRequest(event);
          },
        }
      );

      const shouldKeepDesktopView =
        usedDesktopViewTool ||
        agentResult.filesystem_changed ||
        agentResult.created_or_updated_paths.length > 0;

      if (shouldKeepDesktopView) {
        focusOrCreateDesktopWindow();
      } else {
        this.focusBrowserWindow();
      }

      if (agentResult.filesystem_changed) {
        this.sendDesktopWindowEvent("desktop-filesystem-updated", {
          changedPaths: agentResult.created_or_updated_paths,
        });
        this.sendDesktopWindowEvent(
          "desktop-action-feedback",
          this.buildDesktopActionFeedbackPayload(
            agentResult,
            desktopMutationEvents
          )
        );
        this.moveCursorInsideLatestCreatedFolder(
          agentResult,
          desktopMutationEvents
        );
        didSendDesktopActionFeedback = true;
      }

      const assistantMessage: CoreMessage = {
        role: "assistant",
        content: agentResult.message,
      };

      this.messages.push(assistantMessage);
      this.sendMessagesToRenderer();

      if (agentResult.close_agent_session) {
        this.closeAgentSession();
      }
    } catch (error) {
      console.error("Error in force-write request:", error);
      const assistantMessage: CoreMessage = {
        role: "assistant",
        content:
          "I could not finalize the documents. Please retry in a moment.",
      };
      this.messages.push(assistantMessage);
      this.sendMessagesToRenderer();
    } finally {
      await this.clearBrowserCompanionOnActiveTab();
      if (
        (usedDesktopViewTool || desktopMutationEvents.length > 0) &&
        !didSendDesktopActionFeedback
      ) {
        this.sendDesktopWindowEvent("desktop-action-feedback", {
          clearCursor: true,
        });
      }
      this.forceWriteModeActive = false;
    }
  }

  async resetVectorStoreNow(): Promise<void> {
    if (this.agentRunInProgress) {
      const assistantMessage: CoreMessage = {
        role: "assistant",
        content:
          "Vector store reset is blocked while the agent is running. Wait for completion, then retry.",
      };
      this.messages.push(assistantMessage);
      this.sendMessagesToRenderer();
      return;
    }

    try {
      resetDesktopAgentChromaStore();
      const assistantMessage: CoreMessage = {
        role: "assistant",
        content:
          "Vector store reset completed. Retrieval now requires freshly indexed web content.",
      };
      this.messages.push(assistantMessage);
      this.sendMessagesToRenderer();
    } catch (error) {
      console.error("Failed to reset vector store:", error);
      const assistantMessage: CoreMessage = {
        role: "assistant",
        content:
          "I could not reset the vector store. Please retry in a moment.",
      };
      this.messages.push(assistantMessage);
      this.sendMessagesToRenderer();
    }
  }

  getVectorStoreChunkDumpNow(): ChromaStoreDumpResult {
    if (this.agentRunInProgress) {
      throw new Error(
        "Vector store inspection is blocked while the agent is running. Wait for completion, then retry."
      );
    }

    return dumpDesktopAgentChromaStore();
  }

  openVectorStoreViewerNow(): void {
    const storeDump = this.getVectorStoreChunkDumpNow();
    openVectorStoreViewerWindow(storeDump);
  }

  private appendUserTextMessage(content: string): void {
    this.messages.push({
      role: "user",
      content,
    });
    this.sendMessagesToRenderer();
  }

  private isDesktopChatRequest(messageId: string): boolean {
    return messageId.startsWith("desktop-chat-");
  }

  private isPendingAssistantMessageContent(content: string): boolean {
    return content.trim() === PENDING_AGENT_ASSISTANT_MESSAGE;
  }

  private upsertPendingAssistantMessage(): void {
    const lastMessage = this.messages[this.messages.length - 1];
    if (
      lastMessage?.role === "assistant" &&
      typeof lastMessage.content === "string" &&
      this.isPendingAssistantMessageContent(lastMessage.content)
    ) {
      return;
    }

    this.messages.push({
      role: "assistant",
      content: PENDING_AGENT_ASSISTANT_MESSAGE,
    });
    this.sendMessagesToRenderer();
  }

  private appendOrReplaceAssistantMessage(content: string): void {
    const normalizedContent = content.trim() || content;
    const lastMessage = this.messages[this.messages.length - 1];
    if (
      lastMessage?.role === "assistant" &&
      typeof lastMessage.content === "string" &&
      this.isPendingAssistantMessageContent(lastMessage.content)
    ) {
      lastMessage.content = normalizedContent;
    } else {
      this.messages.push({
        role: "assistant",
        content: normalizedContent,
      });
    }

    this.sendMessagesToRenderer();
  }

  private buildAgentHistory(): AgentHistoryMessage[] {
    return this.messages.flatMap((message) => {
      if (message.role !== "user" && message.role !== "assistant") {
        return [];
      }

      if (typeof message.content === "string") {
        const content = message.content.trim();
        if (
          message.role === "assistant" &&
          this.isPendingAssistantMessageContent(content)
        ) {
          return [];
        }
        return content
          ? [
              {
                role: message.role,
                content,
              },
            ]
          : [];
      }

      if (!Array.isArray(message.content)) {
        return [];
      }

      const textContent = message.content
        .filter(
          (
            part
          ): part is {
            type: "text";
            text: string;
          } =>
            !!part &&
            typeof part === "object" &&
            "type" in part &&
            part.type === "text" &&
            typeof part.text === "string"
        )
        .map((part) => part.text)
        .join("\n")
        .trim();

      return textContent
        ? [
            {
              role: message.role,
              content: textContent,
            },
          ]
        : [];
    });
  }

  private getLatestUserTextMessage(): string {
    for (let i = this.messages.length - 1; i >= 0; i--) {
      const message = this.messages[i];
      if (message.role !== "user") {
        continue;
      }
      if (typeof message.content === "string") {
        const trimmed = message.content.trim();
        if (trimmed) {
          return trimmed;
        }
        continue;
      }

      if (!Array.isArray(message.content)) {
        continue;
      }

      const textContent = message.content
        .filter(
          (
            part
          ): part is {
            type: "text";
            text: string;
          } =>
            !!part &&
            typeof part === "object" &&
            "type" in part &&
            part.type === "text" &&
            typeof part.text === "string"
        )
        .map((part) => part.text)
        .join("\n")
        .trim();

      if (textContent) {
        return textContent;
      }
    }

    return "";
  }

  private async getCurrentPageContext(): Promise<{
    url: string | null;
    text: string | null;
  }> {
    let pageUrl: string | null = null;
    let pageText: string | null = null;

    if (this.window) {
      const activeTab = this.window.activeTab;
      if (activeTab) {
        pageUrl = activeTab.url;
        try {
          pageText = await activeTab.getTabText();
        } catch (error) {
          console.error("Failed to get page text:", error);
        }
      }
    }

    return {
      url: pageUrl,
      text: pageText,
    };
  }

  private isDesktopActionRequest(message: string): boolean {
    return /(?:create|write|save|export|generate|build|draft|make|edit|update).*(?:file|files|folder|document|report|spreadsheet|excel|xlsx|csv|word|docx|pdf|powerpoint|presentation|slide|slides|ppt|pptx|desktop)|(?:file|files|folder|document|report|spreadsheet|excel|xlsx|csv|word|docx|pdf|powerpoint|presentation|slide|slides|ppt|pptx|desktop).*(?:create|write|save|export|generate|build|draft|make|edit|update)/i.test(
      message
    );
  }

  private isDesktopMutationRequest(message: string): boolean {
    return this.isDesktopActionRequest(message);
  }

  private async confirmDesktopAction(message: string): Promise<boolean> {
    const options: MessageBoxOptions = {
      type: "question",
      buttons: ["Continue", "Cancel"],
      defaultId: 0,
      cancelId: 1,
      noLink: true,
      title: "Confirm Desktop Action",
      message: "Allow Blueberry to take action in the Desktop view?",
      detail:
        `Request:\n${this.truncateText(message, 220)}\n\n` +
        "The agent may create folders or create/update files on your Desktop. It will never delete files.",
    };

    const response = this.window
      ? await dialog.showMessageBox(this.window.baseWindow, options)
      : await dialog.showMessageBox(options);

    return response.response === 0;
  }

  private handleAgentToolCall(event: AgentToolCallEvent): void {
    appendDesktopAgentDebugLog("main", "desktop_agent_tool_call", {
      toolName: event.toolName,
      arguments: event.arguments,
    });

    if (event.toolName === "list_desktop_entries") {
      const requestedPath =
        this.resolveDesktopCursorPath(event.arguments.path) ??
        getConsultingAgentDesktopRootPath();
      focusOrCreateDesktopWindow();
      this.sendDesktopCursorMove({
        action: "show_folder",
        target: "current-folder-card",
        reason: "Change the desktop view to the selected folder.",
        label: `Open ${basename(requestedPath) || "BLUEBARRY"}`,
        path: requestedPath,
        click: true,
      });
      return;
    }

    if (event.toolName === "show_desktop_folder") {
      const requestedPath = this.resolveDesktopCursorPath(event.arguments.path);
      const reason =
        typeof event.arguments.reason === "string"
          ? event.arguments.reason
          : "Change the current Desktop folder in the UI.";

      if (!requestedPath) {
        return;
      }

      focusOrCreateDesktopWindow();
      this.sendDesktopCursorMove({
        action: "show_folder",
        target: "current-folder-card",
        reason,
        label: `Open ${basename(requestedPath) || "BLUEBARRY"}`,
        path: requestedPath,
        click: true,
      });
      return;
    }

    if (event.toolName === "click_desktop_folder") {
      const requestedPath = this.resolveDesktopCursorPath(event.arguments.path);
      const reason =
        typeof event.arguments.reason === "string"
          ? event.arguments.reason
          : "Open the selected folder in the desktop view.";

      if (!requestedPath) {
        return;
      }

      focusOrCreateDesktopWindow();
      this.sendDesktopCursorMove({
        action: "click_folder",
        target: "folder-grid",
        reason,
        label: `Open ${basename(requestedPath) || "folder"}`,
        path: requestedPath,
        click: true,
      });
      return;
    }

    if (event.toolName === "read_desktop_file") {
      const requestedPath = this.resolveDesktopCursorPath(event.arguments.path);
      focusOrCreateDesktopWindow();
      if (requestedPath) {
        const requestedFolderPath = dirname(requestedPath);
        this.sendDesktopCursorMove({
          action: "show_folder",
          target: "current-folder-card",
          reason: "Change the desktop view to the folder that contains the selected file.",
          label: `Open ${basename(requestedFolderPath) || "BLUEBARRY"}`,
          path: requestedFolderPath,
          click: true,
        });
        this.sendDesktopCursorMove({
          action: "move_to_file",
          target: "folder-grid",
          reason: "Move the cursor onto the selected file.",
          label: `Inspect ${basename(requestedPath)}`,
          path: requestedPath,
          click: true,
        });
        this.sendDesktopCursorMove({
          action: "read_file",
          target: "inspector-panel",
          reason: "Read the selected file in the current desktop folder.",
          label: `Read ${basename(requestedPath)}`,
          path: requestedPath,
          click: true,
        });
        return;
      }

      this.sendDesktopCursorMove({
        target: "folder-grid",
        reason: "Reading consulting template",
        label: requestedPath
          ? `Read ${basename(requestedPath)}`
          : "Reading consulting template",
        path: requestedPath,
        click: true,
      });
      return;
    }

    if (event.toolName === "edit_desktop_file") {
      const requestedPath = this.resolveDesktopCursorPath(event.arguments.path);
      focusOrCreateDesktopWindow();
      if (requestedPath) {
        const requestedFolderPath = dirname(requestedPath);
        this.sendDesktopCursorMove({
          action: "show_folder",
          target: "current-folder-card",
          reason: "Change the desktop view to the folder that contains the file being edited.",
          label: `Open ${basename(requestedFolderPath) || "BLUEBARRY"}`,
          path: requestedFolderPath,
          click: true,
        });
        this.sendDesktopCursorMove({
          action: "move_to_file",
          target: "folder-grid",
          reason: "Move the cursor onto the file that will be edited.",
          label: `Edit ${basename(requestedPath)}`,
          path: requestedPath,
          click: true,
        });
        this.sendDesktopCursorMove({
          action: "read_file",
          target: "inspector-panel",
          reason: "Open the selected file before editing it in the current desktop folder.",
          label: `Edit ${basename(requestedPath)}`,
          path: requestedPath,
          click: true,
        });
      }
      return;
    }

    if (event.toolName === "convert_desktop_file_format") {
      const sourcePath = this.resolveDesktopCursorPath(event.arguments.source_path);
      focusOrCreateDesktopWindow();
      if (sourcePath) {
        const sourceFolderPath = dirname(sourcePath);
        this.sendDesktopCursorMove({
          action: "show_folder",
          target: "current-folder-card",
          reason: "Change the desktop view to the folder that contains the file being converted.",
          label: `Open ${basename(sourceFolderPath) || "BLUEBARRY"}`,
          path: sourceFolderPath,
          click: true,
        });
        this.sendDesktopCursorMove({
          action: "move_to_file",
          target: "folder-grid",
          reason: "Move the cursor onto the source file that will be converted.",
          label: `Convert ${basename(sourcePath)}`,
          path: sourcePath,
          click: true,
        });
      }
      this.sendDesktopCursorMove({
        target: "files-end",
        reason: this.getFileToolDescription(event.toolName, event.arguments),
        label: this.getFileToolLabel(event.toolName, event.arguments),
        click: true,
        loading: true,
      });
      return;
    }

    if (event.toolName !== "move_cursor") {
      if (event.toolName === "create_folder") {
        const label = this.getFileToolLabel(event.toolName, event.arguments);
        const reason = this.getFileToolDescription(event.toolName, event.arguments);
        focusOrCreateDesktopWindow();
        this.sendDesktopCursorMove({
          target: "folder-grid",
          reason,
          label,
          click: true,
          loading: true,
        });
      } else if (
        event.toolName === "write_text_file" ||
        event.toolName === "write_txt_file" ||
        event.toolName === "write_markdown_file" ||
        event.toolName === "write_csv_file" ||
        event.toolName === "write_word_file" ||
        event.toolName === "write_excel_file" ||
        event.toolName === "write_pdf_file" ||
        event.toolName === "write_powerpoint_file" ||
        event.toolName === "create_multiple_files" ||
        event.toolName === "add_file_to_existing_folder"
      ) {
        const label = this.getFileToolLabel(event.toolName, event.arguments);
        const reason = this.getFileToolDescription(event.toolName, event.arguments);
        focusOrCreateDesktopWindow();
        this.sendDesktopCursorMove({
          target: "files-end",
          reason,
          label,
          click: true,
          loading: true,
        });
      }
      return;
    }

    const target =
      typeof event.arguments.target === "string"
        ? (event.arguments.target as DesktopCursorTarget)
        : "desktop-center";
    const reason =
      typeof event.arguments.reason === "string"
        ? event.arguments.reason
        : "Working in Desktop view";
    const click = event.arguments.click === true;
    const label =
      typeof event.arguments.label === "string" ? event.arguments.label : undefined;
    const action =
      typeof event.arguments.action === "string"
        ? (event.arguments.action as DesktopCursorAction)
        : undefined;

    focusOrCreateDesktopWindow();
    this.sendDesktopCursorMove({ action, target, reason, click, label });
  }

  private sendDesktopCursorMove(payload: DesktopCursorMovePayload): void {
    appendDesktopAgentDebugLog("main", "desktop_cursor_move_dispatch", {
      payload,
    });
    this.sendDesktopWindowEvent("desktop-agent-cursor-move", payload);
  }

  private sendDesktopWindowEvent(channel: string, payload: unknown): void {
    sendDesktopWindowEvent(channel, payload);
  }

  private isDesktopMutationTool(toolName: string): boolean {
    return (
      toolName === "create_folder" ||
      toolName === "write_text_file" ||
      toolName === "write_txt_file" ||
      toolName === "write_markdown_file" ||
      toolName === "write_csv_file" ||
      toolName === "write_word_file" ||
      toolName === "write_excel_file" ||
      toolName === "write_pdf_file" ||
      toolName === "write_powerpoint_file" ||
      toolName === "create_multiple_files" ||
      toolName === "add_file_to_existing_folder" ||
      toolName === "edit_desktop_file" ||
      toolName === "convert_desktop_file_format"
    );
  }

  private getDesktopFolderLabel(folderPath?: string): string {
    const desktopRootName =
      basename(getConsultingAgentDesktopRootPath()) || "Desktop root";
    if (!folderPath) {
      return desktopRootName;
    }

    return basename(folderPath) || desktopRootName;
  }

  private getDesktopParentLabelForPath(filePath?: string): string {
    if (!filePath) {
      return this.getDesktopFolderLabel();
    }

    return this.getDesktopFolderLabel(dirname(filePath));
  }

  private getDocumentTypeLabel(toolName: string): string {
    switch (toolName) {
      case "write_txt_file":
        return "TXT file";
      case "write_markdown_file":
        return "Markdown file";
      case "write_csv_file":
        return "CSV file";
      case "write_word_file":
        return "Word document";
      case "write_excel_file":
        return "Excel workbook";
      case "write_pdf_file":
        return "PDF file";
      case "write_powerpoint_file":
        return "PowerPoint deck";
      case "write_text_file":
        return "text file";
      default:
        return "file";
    }
  }

  private getMultiFileCount(arguments_: Record<string, unknown>): number {
    return Array.isArray(arguments_.files) ? arguments_.files.length : 0;
  }

  private resolveDesktopOutputPath(
    toolName: string,
    arguments_: Record<string, unknown>
  ): string | undefined {
    if (
      toolName === "write_text_file" ||
      toolName === "write_txt_file" ||
      toolName === "write_markdown_file" ||
      toolName === "write_csv_file" ||
      toolName === "write_word_file" ||
      toolName === "write_excel_file" ||
      toolName === "write_pdf_file" ||
      toolName === "write_powerpoint_file" ||
      toolName === "edit_desktop_file"
    ) {
      return this.resolveDesktopCursorPath(arguments_.path);
    }

    if (toolName === "create_folder") {
      return this.resolveDesktopCursorPath(arguments_.path);
    }

    if (toolName === "add_file_to_existing_folder") {
      const folderPath = this.resolveDesktopCursorPath(arguments_.folder_path);
      const fileName =
        typeof arguments_.file_name === "string" ? arguments_.file_name.trim() : "";
      if (folderPath && fileName) {
        return resolve(folderPath, fileName);
      }
      return undefined;
    }

    if (toolName === "convert_desktop_file_format") {
      const explicitOutputPath = this.resolveDesktopCursorPath(arguments_.output_path);
      if (explicitOutputPath) {
        return explicitOutputPath;
      }

      const sourcePath = this.resolveDesktopCursorPath(arguments_.source_path);
      const targetFormat =
        typeof arguments_.target_format === "string"
          ? arguments_.target_format.trim().replace(/^\./, "").toLowerCase()
          : "";
      if (!sourcePath || !targetFormat) {
        return undefined;
      }

      const sourceName = basename(sourcePath);
      const sourceStem = sourceName.includes(".")
        ? sourceName.slice(0, sourceName.lastIndexOf("."))
        : sourceName;
      return resolve(dirname(sourcePath), `${sourceStem}.${targetFormat}`);
    }

    return undefined;
  }

  private getFileToolLabel(
    toolName: string,
    arguments_: Record<string, unknown> = {}
  ): string {
    const resolvedPath = this.resolveDesktopOutputPath(toolName, arguments_);
    const fileName = resolvedPath ? basename(resolvedPath) : null;
    const multiFileCount = this.getMultiFileCount(arguments_);

    if (toolName === "convert_desktop_file_format" && fileName) {
      return `Convert to ${fileName}`;
    }

    if (toolName === "edit_desktop_file" && fileName) {
      return `Update ${fileName}`;
    }

    if (toolName === "create_multiple_files" && multiFileCount > 0) {
      return `Create ${multiFileCount} ${multiFileCount === 1 ? "file" : "files"}`;
    }

    if (toolName === "add_file_to_existing_folder" && fileName) {
      return `Add ${fileName}`;
    }

    if (resolvedPath && fileName) {
      if (toolName === "create_folder") {
        return `Create ${fileName}`;
      }
      return `Save ${fileName}`;
    }

    switch (toolName) {
      case "create_folder":
        return "Creating folder";
      case "write_txt_file":
        return "Creating TXT file";
      case "write_markdown_file":
        return "Creating Markdown file";
      case "write_csv_file":
        return "Creating CSV file";
      case "write_word_file":
        return "Creating Word file";
      case "write_excel_file":
        return "Creating Excel file";
      case "write_pdf_file":
        return "Creating PDF file";
      case "write_powerpoint_file":
        return "Creating PowerPoint file";
      case "create_multiple_files":
        return "Creating multiple files";
      case "add_file_to_existing_folder":
        return "Adding file to folder";
      case "write_text_file":
        return "Creating text file";
      case "edit_desktop_file":
        return "Editing file";
      case "convert_desktop_file_format":
        return "Converting file format and replacing original file";
      default:
        return "Creating file";
    }
  }

  private getFileToolDescription(
    toolName: string,
    arguments_: Record<string, unknown> = {}
  ): string {
    const resolvedPath = this.resolveDesktopOutputPath(toolName, arguments_);
    const fileName = resolvedPath ? basename(resolvedPath) : null;
    const folderLabel = this.getDesktopParentLabelForPath(resolvedPath);
    const multiFileCount = this.getMultiFileCount(arguments_);

    if (toolName === "create_folder" && resolvedPath && fileName) {
      return `Create the folder "${fileName}" inside "${folderLabel}".`;
    }

    if (toolName === "convert_desktop_file_format" && resolvedPath && fileName) {
      return `Create "${fileName}" and remove the original source file only after the converted file is ready.`;
    }

    if (toolName === "edit_desktop_file" && resolvedPath && fileName) {
      return `Apply the requested edits and save "${fileName}" in place inside "${folderLabel}".`;
    }

    if (toolName === "create_multiple_files" && multiFileCount > 0) {
      return `Create the requested set of ${multiFileCount} ${
        multiFileCount === 1 ? "file" : "files"
      } in their selected Desktop destination folders.`;
    }

    if (toolName === "add_file_to_existing_folder" && resolvedPath && fileName) {
      return `Create "${fileName}" and place it inside "${folderLabel}".`;
    }

    if (resolvedPath && fileName) {
      return `Create the ${this.getDocumentTypeLabel(toolName)} "${fileName}" in "${folderLabel}".`;
    }

    switch (toolName) {
      case "write_txt_file":
        return "Writing the requested TXT file into the current Desktop folder.";
      case "write_markdown_file":
        return "Writing the requested Markdown file into the current Desktop folder.";
      case "write_csv_file":
        return "Writing the requested CSV file into the current Desktop folder.";
      case "write_word_file":
        return "Drafting the Word document and saving it into the current Desktop folder.";
      case "write_excel_file":
        return "Building the spreadsheet sheets and saving the workbook into the current Desktop folder.";
      case "write_pdf_file":
        return "Rendering the PDF document and saving it into the current Desktop folder.";
      case "write_powerpoint_file":
        return "Preparing the slides and saving the PowerPoint deck into the current Desktop folder.";
      case "create_multiple_files":
        return "Generating the requested set of files and saving them together in the selected Desktop location.";
      case "add_file_to_existing_folder":
        return "Creating the new file and placing it inside the selected existing Desktop folder.";
      case "write_text_file":
        return "Writing the requested text file into the current Desktop folder.";
      default:
        return "Creating the requested file in the current Desktop location.";
    }
  }

  private buildDesktopActionFeedbackPayload(
    agentResult: AgentRunResult,
    mutationEvents: AgentToolCallEvent[]
  ): DesktopActionFeedbackPayload {
    return {
      clearCursor: true,
      notifications: this.buildDesktopActionNotifications(
        agentResult,
        mutationEvents
      ),
    };
  }

  private normalizeDesktopPathForComparison(pathValue: string): string {
    return pathValue.replace(/\//g, "\\").toLowerCase();
  }

  private resolveLatestCreatedFolderPath(
    agentResult: AgentRunResult,
    mutationEvents: AgentToolCallEvent[]
  ): string | undefined {
    const changedPaths = agentResult.created_or_updated_paths.filter(
      (path): path is string => typeof path === "string" && path.trim().length > 0
    );
    if (changedPaths.length === 0) {
      return undefined;
    }

    const changedPathSet = new Set(
      changedPaths.map((path) => this.normalizeDesktopPathForComparison(path))
    );
    for (const event of [...mutationEvents].reverse()) {
      if (event.toolName !== "create_folder") {
        continue;
      }

      const resolvedFolderPath = this.resolveDesktopOutputPath(
        "create_folder",
        event.arguments
      );
      if (!resolvedFolderPath) {
        continue;
      }

      if (
        changedPathSet.has(
          this.normalizeDesktopPathForComparison(resolvedFolderPath)
        )
      ) {
        return resolvedFolderPath;
      }
    }

    return undefined;
  }

  private moveCursorInsideLatestCreatedFolder(
    agentResult: AgentRunResult,
    mutationEvents: AgentToolCallEvent[]
  ): void {
    const createdFolderPath = this.resolveLatestCreatedFolderPath(
      agentResult,
      mutationEvents
    );
    if (!createdFolderPath) {
      return;
    }

    focusOrCreateDesktopWindow();
    this.sendDesktopCursorMove({
      action: "click_folder",
      target: "folder-grid",
      reason: "Open the newly created folder in the desktop view.",
      label: `Inside ${basename(createdFolderPath) || "folder"}`,
      path: createdFolderPath,
      click: true,
    });
  }

  private buildDesktopActionNotifications(
    agentResult: AgentRunResult,
    mutationEvents: AgentToolCallEvent[]
  ): DesktopActionNotificationPayload[] {
    const changedPaths = agentResult.created_or_updated_paths.filter(
      (path): path is string => typeof path === "string" && path.trim().length > 0
    );
    if (changedPaths.length === 0) {
      return [];
    }

    const lastMutationEvent = [...mutationEvents]
      .reverse()
      .find((event) => this.isDesktopMutationTool(event.toolName));
    const lastToolName = lastMutationEvent?.toolName;

    if (lastToolName === "create_folder") {
      const path = changedPaths[0];
      return [
        {
          kind: "folder",
          title: `Created folder ${basename(path) || "folder"}`,
          description: `The new folder is now available in "${this.getDesktopParentLabelForPath(
            path
          )}".`,
          path,
        },
      ];
    }

    if (lastToolName === "convert_desktop_file_format") {
      const path = changedPaths[0];
      return [
        {
          kind: "conversion",
          title: `Converted to ${basename(path) || "new file"}`,
          description:
            "The converted file is ready and the original source file has been replaced.",
          path,
        },
      ];
    }

    if (lastToolName === "edit_desktop_file") {
      const path = changedPaths[0];
      return [
        {
          kind: "update",
          title: `Updated ${basename(path) || "file"}`,
          description: `Saved the requested edits in "${this.getDesktopParentLabelForPath(
            path
          )}".`,
          path,
        },
      ];
    }

    if (changedPaths.length > 1 || lastToolName === "create_multiple_files") {
      const preview = changedPaths
        .slice(0, 3)
        .map((path) => basename(path))
        .filter(Boolean);
      const remainingCount = changedPaths.length - preview.length;
      const previewText =
        preview.length > 0
          ? `Saved ${preview.join(", ")}${remainingCount > 0 ? `, and ${remainingCount} more.` : "."}`
          : "The requested files are now available in the Desktop workspace.";
      return [
        {
          kind: "batch",
          title: `Created ${changedPaths.length} ${
            changedPaths.length === 1 ? "file" : "files"
          }`,
          description: previewText,
        },
      ];
    }

    const path = changedPaths[0];
    return [
      {
        kind: "file",
        title:
          lastToolName === "add_file_to_existing_folder"
            ? `Added ${basename(path) || "file"}`
            : `Saved ${basename(path) || "file"}`,
        description: `The file is now available in "${this.getDesktopParentLabelForPath(
          path
        )}".`,
        path,
      },
    ];
  }

  private resolveDesktopCursorPath(rawPath: unknown): string | undefined {
    if (typeof rawPath !== "string" || !rawPath.trim()) {
      return undefined;
    }

    const desktopRootPath = getConsultingAgentDesktopRootPath();
    if (isAbsolute(rawPath)) {
      return coerceConsultingAgentPathToDesktopRoot(rawPath, desktopRootPath);
    }

    return resolve(desktopRootPath, rawPath);
  }

  private async requestDesktopFileConfirmation(
    event: AgentConfirmationRequestEvent
  ): Promise<boolean> {
    focusOrCreateDesktopWindow();

    const requestId = `desktop-file-confirm-${Date.now()}-${Math.random()
      .toString(36)
      .slice(2, 10)}`;
    const confirmationPath =
      typeof event.path === "string" && event.path.trim().length > 0
        ? event.path
        : undefined;
    const label = confirmationPath
      ? `Confirm ${basename(confirmationPath)}`
      : event.message || this.getFileToolLabel(event.toolName);
    const reason = confirmationPath
      ? `Confirm the creation of "${basename(
          confirmationPath
        )}" in "${this.getDesktopParentLabelForPath(confirmationPath)}".`
      : event.message || this.getFileToolDescription(event.toolName);

    this.sendDesktopCursorMove({
      target: "files-end",
      reason,
      label,
    });

    return await new Promise<boolean>((resolve) => {
      const timeout = setTimeout(() => {
        ipcMain.removeListener(
          "desktop-agent-file-confirmation-response",
          handleResponse
        );
        resolve(false);
      }, 300000);

      const handleResponse = (
        _event: IpcMainEvent,
        payload: { requestId?: string; approved?: boolean }
      ) => {
        if (payload?.requestId !== requestId) {
          return;
        }

        clearTimeout(timeout);
        ipcMain.removeListener(
          "desktop-agent-file-confirmation-response",
          handleResponse
        );
        resolve(payload.approved === true);
      };

      ipcMain.on("desktop-agent-file-confirmation-response", handleResponse);
      this.sendDesktopWindowEvent("desktop-agent-file-confirmation-request", {
        requestId,
        toolName: event.toolName,
        path: event.path,
        message: label,
      });
    });
  }

  private async requestRetrievalSourceSelection(
    query: string,
    availableSourceDomains: string[]
  ): Promise<{
    status: "ok" | "cancelled";
    selectedSourceDomains: string[];
  }> {
    if (!this.window) {
      return {
        status: "cancelled",
        selectedSourceDomains: [],
      };
    }

    const uniqueDomains = [...new Set(
      availableSourceDomains
        .filter((domain): domain is string => typeof domain === "string")
        .map((domain) => domain.trim())
        .filter((domain) => domain.length > 0)
    )].sort((left, right) => left.localeCompare(right));
    const requestId = `retrieval-source-selection-${Date.now()}-${Math.random()
      .toString(36)
      .slice(2, 10)}`;

    this.window.sidebar.show();
    this.window.updateAllBounds();
    this.window.show();
    this.window.focus();

    const payload: RetrievalSourceSelectionRequestPayload = {
      requestId,
      query: query.trim(),
      availableSourceDomains: uniqueDomains,
      defaultSelectedSourceDomains: uniqueDomains,
    };

    return await new Promise((resolve) => {
      const timeout = setTimeout(() => {
        ipcMain.removeListener(
          "retrieval-source-selection-response",
          handleResponse
        );
        resolve({
          status: "cancelled",
          selectedSourceDomains: [],
        });
      }, 300000);

      const handleResponse = (
        _event: IpcMainEvent,
        responsePayload: RetrievalSourceSelectionResponsePayload
      ) => {
        if (responsePayload?.requestId !== requestId) {
          return;
        }

        clearTimeout(timeout);
        ipcMain.removeListener(
          "retrieval-source-selection-response",
          handleResponse
        );

        const selectedSourceDomains = Array.isArray(
          responsePayload?.selectedSourceDomains
        )
          ? [
              ...new Set(
                responsePayload.selectedSourceDomains
                  .filter((domain): domain is string => typeof domain === "string")
                  .map((domain) => domain.trim())
                  .filter((domain) => domain.length > 0)
              ),
            ]
          : [];

        resolve({
          status: responsePayload?.action === "cancel" ? "cancelled" : "ok",
          selectedSourceDomains,
        });
      };

      ipcMain.on("retrieval-source-selection-response", handleResponse);
      this.webContents.send("retrieval-source-selection-request", payload);
    });
  }

  private async executeHostToolRequest(
    event: AgentHostToolRequest
  ): Promise<AgentHostToolResponse> {
    if (!this.window) {
      return {
        content: JSON.stringify({
          status: "error",
          tool_name: event.toolName,
          message: "Browser window is not available.",
        }),
      };
    }

    if (event.toolName === "google_search_and_collect") {
      if (this.stopWebSearchRequested) {
        return {
          content: JSON.stringify({
            status: "blocked",
            tool_name: event.toolName,
            message:
              "Web search is disabled for this session because Stop web search was triggered.",
          }),
        };
      }
      if (this.getAgentSessionWebSearchCalls() >= this.webSearchLimits.maxWebsites) {
        console.log(
          `[browser-research] web_search_session_limit_reached used=${this.getAgentSessionWebSearchCalls()} max=${this.webSearchLimits.maxWebsites}`
        );
        return {
          content: JSON.stringify({
            status: "limit_reached",
            tool_name: event.toolName,
            message: `Web search session cap reached (${this.getAgentSessionWebSearchCalls()}/${this.webSearchLimits.maxWebsites}). Continue with retrieved context and writing tools.`,
          }),
          metadata: {
            web_search_calls_used: this.getAgentSessionWebSearchCalls(),
            web_search_calls_limit: this.webSearchLimits.maxWebsites,
          },
        };
      }
      this.recordAgentSessionWebSearchCall();
      const query =
        typeof event.arguments.query === "string" ? event.arguments.query : "";
      const purpose =
        typeof event.arguments.purpose === "string"
          ? event.arguments.purpose
          : "Gather current web context before answering the user.";
      console.log(
        `[browser-research] web_search_session_call used=${this.getAgentSessionWebSearchCalls()} max=${this.webSearchLimits.maxWebsites} query=${query || "missing"}`
      );
      const result = await runGoogleSearchAndCollect(this.window, {
        query,
        purpose,
        visited_websites: this.getAgentSessionVisitedWebsites(),
      });
      if (result.visited_website) {
        this.recordAgentSessionVisitedWebsite(
          result.visited_website.url,
          result.visited_website.title
        );
      }
      return {
        ...result,
        metadata: {
          ...(result.metadata ?? {}),
          web_search_calls_used: this.getAgentSessionWebSearchCalls(),
          web_search_calls_limit: this.webSearchLimits.maxWebsites,
        },
      };
    }

    if (event.toolName === "select_retrieval_sources") {
      const query =
        typeof event.arguments.query === "string" ? event.arguments.query : "";
      const availableSourceDomains = Array.isArray(
        event.arguments.available_source_domains
      )
        ? event.arguments.available_source_domains.filter(
            (domain): domain is string =>
              typeof domain === "string" && domain.trim().length > 0
          )
        : [];

      await this.showBrowserCompanionOnActiveTab({
        label: "Vector retrieval",
        sentence:
          availableSourceDomains.length > 0
            ? "I found indexed source domains. Choose the ones I should use in the sidebar, then I will retrieve the strongest matching chunks."
            : "I am preparing vector retrieval. There are no indexed source filters yet, so I will search across all stored chunks.",
        mood: "speaking",
        target: "viewport-center",
      });

      const selection = await this.requestRetrievalSourceSelection(
        query,
        availableSourceDomains
      );

      if (selection.status === "cancelled") {
        await this.clearBrowserCompanionOnActiveTab();
      } else {
        await this.showBrowserCompanionOnActiveTab({
          label: "Ranking chunks",
          sentence:
            availableSourceDomains.length > 0
              ? "I am generating three retrieval queries and ranking the most similar chunks from the selected sources."
              : "I am generating three retrieval queries and ranking the most similar chunks from the full vector store.",
          mood: "thinking",
          target: "page-content",
        });
      }

      return {
        content: JSON.stringify({
          status: selection.status,
          query,
          available_source_domains: availableSourceDomains,
          selected_source_domains: selection.selectedSourceDomains,
        }),
      };
    }

    return {
      content: JSON.stringify({
        status: "error",
        tool_name: event.toolName,
        message: "Unknown host tool requested.",
      }),
    };
  }

  clearMessages(): void {
    this.messages = [];
    this.closeAgentSession();
    this.sendMessagesToRenderer();
  }

  getMessages(): CoreMessage[] {
    return this.messages;
  }

  private sendMessagesToRenderer(): void {
    this.webContents.send("chat-messages-updated", this.messages);
    this.sendDesktopWindowEvent("chat-messages-updated", this.messages);
  }

  private focusBrowserWindow(): void {
    if (!this.window) {
      return;
    }

    this.window.show();
    this.window.focus();
  }

  private async showBrowserCompanionOnActiveTab(payload: {
    label: string;
    sentence?: string;
    mood?: "speaking" | "thinking" | "success";
    target?: "search-bar" | "results-list" | "page-content" | "viewport-center";
    click?: boolean;
  }): Promise<void> {
    if (!this.window?.activeTab) {
      return;
    }

    await showBrowserCompanion(this.window.activeTab, payload);
  }

  private async clearBrowserCompanionOnActiveTab(): Promise<void> {
    if (!this.window?.activeTab) {
      return;
    }

    await clearBrowserCompanion(this.window.activeTab);
  }

  private handleReactIterationCompanionUpdate(
    event: AgentReactIterationEvent,
    announcedSteps: Set<number>
  ): void {
    const step = Math.max(0, Math.floor(event.step));
    if (step < 1 || announcedSteps.has(step)) {
      return;
    }

    announcedSteps.add(step);
    const sentence = `I'm thinking. Iteration ${step} is in progress.`;
    const maxSteps = Math.max(0, Math.floor(event.maxWebSearchSteps));
    const webSearchSteps = Math.max(0, Math.floor(event.webSearchSteps));
    const limitSuffix =
      maxSteps > 0
        ? ` Web research usage: ${webSearchSteps}/${maxSteps}.`
        : "";

    void this.showBrowserCompanionOnActiveTab({
      label: `Blueberry - Iteration ${step}`,
      sentence: `${sentence}${limitSuffix}`,
      mood: "thinking",
      target: "viewport-center",
    });
  }

  private isDesktopViewTool(toolName: string): boolean {
    switch (toolName) {
      case "list_desktop_entries":
      case "read_desktop_file":
      case "read_desktop_file_if_exists":
      case "create_folder":
      case "write_text_file":
      case "write_txt_file":
      case "write_markdown_file":
      case "write_csv_file":
      case "write_word_file":
      case "write_excel_file":
      case "write_pdf_file":
      case "write_powerpoint_file":
      case "create_multiple_files":
      case "add_file_to_existing_folder":
      case "edit_desktop_file":
      case "convert_desktop_file_format":
      case "show_desktop_view":
      case "show_desktop_folder":
      case "click_desktop_folder":
      case "move_cursor":
        return true;
      default:
        return false;
    }
  }

  private startAgentSession(): void {
    if (this.agentSessionActive) {
      return;
    }

    this.agentSessionActive = true;
    this.agentSessionVisitedWebsites.clear();
    this.agentSessionWebSearchCalls = 0;
  }

  private closeAgentSession(): void {
    this.agentSessionActive = false;
    this.stopWebSearchRequested = false;
    this.pendingForceWriteAfterRun = false;
    this.agentSessionVisitedWebsites.clear();
    this.agentSessionWebSearchCalls = 0;
  }

  private clampWebsiteLimit(rawValue: number, fallback: number): number {
    if (!Number.isFinite(rawValue)) {
      return fallback;
    }

    return Math.max(
      MIN_WEBSITE_VISITS_LIMIT,
      Math.min(MAX_WEBSITE_VISITS_LIMIT, Math.floor(rawValue))
    );
  }

  private normalizeWebSearchLimits(rawLimits: unknown): WebSearchLimits | null {
    if (!rawLimits || typeof rawLimits !== "object") {
      return null;
    }

    const candidate = rawLimits as {
      minWebsites?: number;
      maxWebsites?: number;
    };
    const normalizedMin = this.clampWebsiteLimit(
      Number(candidate.minWebsites),
      this.webSearchLimits.minWebsites
    );
    const normalizedMax = this.clampWebsiteLimit(
      Number(candidate.maxWebsites),
      this.webSearchLimits.maxWebsites
    );

    return {
      minWebsites: normalizedMin,
      maxWebsites: Math.max(normalizedMin, normalizedMax),
    };
  }

  private normalizeAgentSessionVisitedWebsiteUrl(rawUrl: string): string | null {
    const trimmed = rawUrl.trim();
    if (!trimmed) {
      return null;
    }

    try {
      return new URL(trimmed).toString();
    } catch {
      return trimmed;
    }
  }

  private getAgentSessionVisitedWebsites(): Record<string, string> {
    return Object.fromEntries(this.agentSessionVisitedWebsites);
  }

  private getAgentSessionWebSearchCalls(): number {
    return Math.max(0, Math.floor(this.agentSessionWebSearchCalls));
  }

  private recordAgentSessionWebSearchCall(): void {
    this.agentSessionWebSearchCalls += 1;
  }

  private recordAgentSessionVisitedWebsite(rawUrl: string, rawTitle: string): void {
    const normalizedUrl = this.normalizeAgentSessionVisitedWebsiteUrl(rawUrl);
    if (!normalizedUrl) {
      return;
    }

    const title = rawTitle.trim() || normalizedUrl;
    this.agentSessionVisitedWebsites.set(normalizedUrl, title);
  }

  private async prepareMessagesWithContext(_request: ChatRequest): Promise<CoreMessage[]> {
    // Get page context from active tab
    let pageUrl: string | null = null;
    let pageText: string | null = null;
    
    if (this.window) {
      const activeTab = this.window.activeTab;
      if (activeTab) {
        pageUrl = activeTab.url;
        try {
          pageText = await activeTab.getTabText();
        } catch (error) {
          console.error("Failed to get page text:", error);
        }
      }
    }

    // Build system message
    const systemMessage: CoreMessage = {
      role: "system",
      content: this.buildSystemPrompt(pageUrl, pageText),
    };

    // Include all messages in history (system + conversation)
    return [systemMessage, ...this.messages];
  }

  private buildSystemPrompt(url: string | null, pageText: string | null): string {
    const parts: string[] = [
      "You are a helpful AI assistant integrated into a web browser.",
      "You can analyze and discuss web pages with the user.",
      "The user's messages may include screenshots of the current page as the first image.",
    ];

    if (url) {
      parts.push(`\nCurrent page URL: ${url}`);
    }

    if (pageText) {
      const truncatedText = this.truncateText(pageText, MAX_CONTEXT_LENGTH);
      parts.push(`\nPage content (text):\n${truncatedText}`);
    }

    parts.push(
      "\nPlease provide helpful, accurate, and contextual responses about the current webpage.",
      "If the user asks about specific content, refer to the page content and/or screenshot provided."
    );

    return parts.join("\n");
  }

  private truncateText(text: string, maxLength: number): string {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + "...";
  }

  private async streamResponse(
    messages: CoreMessage[],
    messageId: string
  ): Promise<void> {
    if (!this.model) {
      throw new Error("Model not initialized");
    }

    try {
      const result = await streamText({
        model: this.model,
        messages,
        temperature: DEFAULT_TEMPERATURE,
        maxRetries: 3,
        abortSignal: undefined, // Could add abort controller for cancellation
      });

      await this.processStream(result.textStream, messageId);
    } catch (error) {
      throw error; // Re-throw to be handled by the caller
    }
  }

  private async processStream(
    textStream: AsyncIterable<string>,
    messageId: string
  ): Promise<void> {
    let accumulatedText = "";

    // Create a placeholder assistant message
    const assistantMessage: CoreMessage = {
      role: "assistant",
      content: "",
    };
    
    // Keep track of the index for updates
    const messageIndex = this.messages.length;
    this.messages.push(assistantMessage);

    for await (const chunk of textStream) {
      accumulatedText += chunk;

      // Update assistant message content
      this.messages[messageIndex] = {
        role: "assistant",
        content: accumulatedText,
      };
      this.sendMessagesToRenderer();

      this.sendStreamChunk(messageId, {
        content: chunk,
        isComplete: false,
      });
    }

    // Final update with complete content
    this.messages[messageIndex] = {
      role: "assistant",
      content: accumulatedText,
    };
    this.sendMessagesToRenderer();

    // Send the final complete signal
    this.sendStreamChunk(messageId, {
      content: accumulatedText,
      isComplete: true,
    });
  }

  private handleStreamError(error: unknown, messageId: string): void {
    console.error("Error streaming from LLM:", error);

    const errorMessage = this.getErrorMessage(error);
    this.sendErrorMessage(messageId, errorMessage);
  }

  private getErrorMessage(error: unknown): string {
    if (!(error instanceof Error)) {
      return "An unexpected error occurred. Please try again.";
    }

    const message = error.message.toLowerCase();

    if (message.includes("401") || message.includes("unauthorized")) {
      return "Authentication error: Please check your API key in the .env file.";
    }

    if (message.includes("429") || message.includes("rate limit")) {
      return "Rate limit exceeded. Please try again in a few moments.";
    }

    if (
      message.includes("402") ||
      message.includes("quota") ||
      message.includes("credits") ||
      message.includes("insufficient") ||
      message.includes("payment required")
    ) {
      return "API quota/credits exhausted. Please check your Gemini billing/quota and try again.";
    }

    if (
      message.includes("network") ||
      message.includes("fetch") ||
      message.includes("econnrefused")
    ) {
      return "Network error: Please check your internet connection.";
    }

    if (message.includes("desktop agent timed out")) {
      return "Desktop agent timed out due to inactivity before completion. Try reducing web-search scope or increase BLUEBERRY_AGENT_RUN_TIMEOUT_MS.";
    }

    if (message.includes("timeout")) {
      return "Request timeout: The service took too long to respond. Please try again.";
    }

    return "Sorry, I encountered an error while processing your request. Please try again.";
  }

  private sendErrorMessage(messageId: string, errorMessage: string): void {
    this.appendOrReplaceAssistantMessage(errorMessage);

    this.sendStreamChunk(messageId, {
      content: errorMessage,
      isComplete: true,
    });
  }

  private sendStreamChunk(messageId: string, chunk: StreamChunk): void {
    const payload = {
      messageId,
      content: chunk.content,
      isComplete: chunk.isComplete,
    };
    this.webContents.send("chat-response", payload);
  }
}

