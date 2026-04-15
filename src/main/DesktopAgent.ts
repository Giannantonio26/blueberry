import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";

export interface AgentHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export interface AgentPageContext {
  url: string | null;
  text: string | null;
}

export interface AgentWebSearchLimits {
  minWebsites: number;
  maxWebsites: number;
}

export interface AgentRunInput {
  apiKey: string;
  baseUrl: string;
  model: string;
  writerModel?: string;
  messages: AgentHistoryMessage[];
  pageContext: AgentPageContext;
  desktopRoot: string;
  openDesktopHint: boolean;
  visitedWebsites?: Record<string, string>;
  webSearchStepsUsed?: number;
  webSearchLimits?: AgentWebSearchLimits;
  forceWriteOutputs?: boolean;
}

export interface AgentRunResult {
  message: string;
  requires_clarification: boolean;
  should_open_desktop_view: boolean;
  filesystem_changed: boolean;
  created_or_updated_paths: string[];
  close_agent_session?: boolean;
}

export interface AgentToolCallEvent {
  toolName: string;
  arguments: Record<string, unknown>;
}

export interface AgentConfirmationRequestEvent {
  toolName: string;
  path: string;
  message: string;
}

export interface AgentReactIterationEvent {
  step: number;
  webSearchSteps: number;
  maxWebSearchSteps: number;
}

export interface AgentHostToolRequest {
  requestId: string;
  toolName: string;
  arguments: Record<string, unknown>;
}

export interface AgentHostToolResponse {
  content: string;
  filesystem_changed?: boolean;
  changed_paths?: string[];
  should_open_desktop_view?: boolean;
  metadata?: Record<string, unknown>;
}

export interface ChromaChunkDumpEntry {
  id: string;
  document: string;
  metadata: Record<string, unknown>;
  embedding: number[];
  relative_embedding: number[];
  embedding_dimensions: number;
  relative_embedding_scale: number;
}

export interface ChromaCollectionDump {
  name: string;
  chunk_count: number;
  chunks: ChromaChunkDumpEntry[];
}

export interface ChromaStoreDumpResult {
  status: string;
  action: string;
  path: string;
  default_collection: string;
  collection_count: number;
  total_chunks: number;
  collections: ChromaCollectionDump[];
}

interface AgentProtocolEvent {
  type: "event" | "host_tool_request";
  event: "tool_call" | "confirmation_request" | "react_iteration";
  tool_name?: string;
  arguments?: Record<string, unknown>;
  path?: string;
  message?: string;
  request_id?: string;
  step_number?: number;
  web_search_steps?: number;
  max_web_search_steps?: number;
}

interface AgentProtocolResult {
  type: "result";
  data: AgentRunResult;
}

const resolveAgentSupportScriptPath = (filename: string): string => {
  const candidatePaths = [
    resolve(process.cwd(), "resources", "agent", filename),
    resolve(
      process.resourcesPath,
      "agent",
      filename
    ),
    resolve(
      process.resourcesPath,
      "resources",
      "agent",
      filename
    ),
    resolve(
      process.resourcesPath,
      "app.asar.unpacked",
      "resources",
      "agent",
      filename
    ),
  ];

  for (const candidatePath of candidatePaths) {
    if (existsSync(candidatePath)) {
      return candidatePath;
    }
  }

  throw new Error(`Agent support script not found: ${filename}`);
};

const resolveAgentScriptPath = (): string =>
  resolveAgentSupportScriptPath("desktop_agent.py");

const resolveChromaSetupScriptPath = (): string =>
  resolveAgentSupportScriptPath("chroma_setup.py");

const resolvePythonCommand = (): string => {
  const configuredPython = process.env.BLUEBERRY_AGENT_PYTHON?.trim();
  if (configuredPython) {
    return configuredPython;
  }

  const candidatePaths = [
    resolve(process.cwd(), ".venv", "Scripts", "python.exe"),
    resolve(process.cwd(), ".venv", "bin", "python"),
  ];

  for (const candidatePath of candidatePaths) {
    if (existsSync(candidatePath)) {
      return candidatePath;
    }
  }

  return "python";
};

const resolveAgentRunTimeoutMs = (): number => {
  const DEFAULT_AGENT_RUN_TIMEOUT_MS = 10 * 60 * 1000;
  const configuredTimeoutRaw = process.env.BLUEBERRY_AGENT_RUN_TIMEOUT_MS?.trim();
  if (!configuredTimeoutRaw) {
    return DEFAULT_AGENT_RUN_TIMEOUT_MS;
  }

  const configuredTimeout = Number.parseInt(configuredTimeoutRaw, 10);
  if (!Number.isFinite(configuredTimeout) || configuredTimeout < 30_000) {
    return DEFAULT_AGENT_RUN_TIMEOUT_MS;
  }

  return configuredTimeout;
};

const DEFAULT_FAST_GEMINI_WRITER_MODEL = "gemini-2.5-flash";

const normalizeModelName = (modelName: string | undefined): string => {
  const trimmed = (modelName || "").trim();
  if (!trimmed) {
    return "";
  }
  if (trimmed.toLowerCase().startsWith("models/")) {
    return trimmed.slice("models/".length);
  }
  return trimmed;
};

const resolveDefaultWriterModel = (reactModel: string): string | undefined => {
  const normalizedReactModel = normalizeModelName(reactModel);
  if (!normalizedReactModel) {
    return undefined;
  }

  if (!normalizedReactModel.toLowerCase().startsWith("gemini-")) {
    return undefined;
  }

  return DEFAULT_FAST_GEMINI_WRITER_MODEL;
};

export const runDesktopAgent = (
  input: AgentRunInput,
  handlers?: {
    onToolCall?: (event: AgentToolCallEvent) => void;
    onReactIteration?: (event: AgentReactIterationEvent) => void;
    onConfirmationRequest?: (
      event: AgentConfirmationRequestEvent
    ) => Promise<boolean> | boolean;
    onHostToolRequest?: (
      event: AgentHostToolRequest
    ) => Promise<AgentHostToolResponse> | AgentHostToolResponse;
  }
): Promise<AgentRunResult> => {
  const scriptPath = resolveAgentScriptPath();
  const pythonCommand = resolvePythonCommand();
  const explicitWriterModel =
    input.writerModel?.trim() ||
    process.env.BLUEBERRY_AGENT_WRITER_MODEL?.trim() ||
    undefined;
  const writerModel =
    normalizeModelName(explicitWriterModel) ||
    resolveDefaultWriterModel(input.model) ||
    undefined;
  const agentRunTimeoutMs = resolveAgentRunTimeoutMs();

  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(pythonCommand, [scriptPath], {
      cwd: dirname(scriptPath),
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    let didSettle = false;
    let agentRunTimeout: NodeJS.Timeout | null = null;

    let stdout = "";
    let stderr = "";
    let stderrLogBuffer = "";
    let buffer = "";
    let result: AgentRunResult | null = null;

    const clearAgentRunTimeout = (): void => {
      if (agentRunTimeout) {
        clearTimeout(agentRunTimeout);
        agentRunTimeout = null;
      }
    };

    const armAgentRunTimeout = (): void => {
      clearAgentRunTimeout();
      agentRunTimeout = setTimeout(() => {
        settleReject(
          new Error(
            `Desktop agent timed out after ${Math.round(
              agentRunTimeoutMs / 1000
            )} seconds of inactivity. Increase BLUEBERRY_AGENT_RUN_TIMEOUT_MS if needed.`
          )
        );
      }, agentRunTimeoutMs);
    };

    const markAgentActivity = (): void => {
      if (didSettle) {
        return;
      }
      armAgentRunTimeout();
    };

    const settleResolve = (value: AgentRunResult): void => {
      if (didSettle) {
        return;
      }
      didSettle = true;
      clearAgentRunTimeout();
      resolvePromise(value);
    };

    const settleReject = (error: Error): void => {
      if (didSettle) {
        return;
      }
      didSettle = true;
      clearAgentRunTimeout();

      if (!child.killed) {
        try {
          child.kill();
        } catch {
          // Ignore kill errors while rejecting the run.
        }
      }

      rejectPromise(error);
    };

    armAgentRunTimeout();

    const writeProtocolMessage = (payload: Record<string, unknown>): void => {
      if (!child.stdin.destroyed && child.stdin.writable) {
        child.stdin.write(`${JSON.stringify(payload)}\n`);
        markAgentActivity();
      }
    };

    const handleProtocolLine = (line: string): void => {
      if (!line.trim()) {
        return;
      }

      let parsed: AgentProtocolEvent | AgentProtocolResult;
      try {
        parsed = JSON.parse(line) as AgentProtocolEvent | AgentProtocolResult;
      } catch {
        console.log(`[desktop-agent-python] non-protocol stdout: ${line.trim()}`);
        return;
      }

      if (parsed.type === "event" && parsed.event === "tool_call") {
        handlers?.onToolCall?.({
          toolName: parsed.tool_name ?? "",
          arguments: parsed.arguments ?? {},
        });
        return;
      }

      if (parsed.type === "event" && parsed.event === "react_iteration") {
        handlers?.onReactIteration?.({
          step: Number(parsed.step_number) || 0,
          webSearchSteps: Number(parsed.web_search_steps) || 0,
          maxWebSearchSteps: Number(parsed.max_web_search_steps) || 0,
        });
        return;
      }

      if (parsed.type === "event" && parsed.event === "confirmation_request") {
        void Promise.resolve(
          handlers?.onConfirmationRequest?.({
            toolName: parsed.tool_name ?? "",
            path: parsed.path ?? "",
            message: parsed.message ?? "",
          }) ?? false
        )
          .then((approved) => {
            writeProtocolMessage({
              type: "confirmation_response",
              approved,
            });
          })
          .catch(() => {
            writeProtocolMessage({
              type: "confirmation_response",
              approved: false,
            });
          });
        return;
      }

      if (parsed.type === "host_tool_request") {
        const hostToolName = parsed.tool_name ?? "";
        void Promise.resolve(
          handlers?.onHostToolRequest?.({
            requestId: parsed.request_id ?? "",
            toolName: hostToolName,
            arguments: parsed.arguments ?? {},
          }) ?? {
            content: JSON.stringify({
              status: "error",
              tool_name: hostToolName,
              message: "No host tool handler was configured.",
            }),
          }
        )
          .then((toolResponse) => {
            writeProtocolMessage({
              type: "host_tool_response",
              request_id: parsed.request_id,
              ...toolResponse,
            });
          })
          .catch((error) => {
            writeProtocolMessage({
              type: "host_tool_response",
              request_id: parsed.request_id,
              content: JSON.stringify({
                status: "error",
                tool_name: parsed.tool_name,
                message:
                  error instanceof Error
                    ? error.message
                    : "Host tool execution failed.",
              }),
            });
          });
        return;
      }

      if (parsed.type === "result") {
        result = parsed.data;
      }
    };

    child.stdout.on("data", (chunk) => {
      const chunkText = chunk.toString();
      if (chunkText.length > 0) {
        markAgentActivity();
      }
      stdout += chunkText;
      buffer += chunkText;

      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        handleProtocolLine(line);
      }
    });

    child.stderr.on("data", (chunk) => {
      const chunkText = chunk.toString();
      if (chunkText.length > 0) {
        markAgentActivity();
      }
      stderr += chunkText;
      stderrLogBuffer += chunkText;

      const lines = stderrLogBuffer.split(/\r?\n/);
      stderrLogBuffer = lines.pop() ?? "";

      for (const line of lines) {
        const normalized = line.trim();
        if (!normalized) {
          continue;
        }
        console.log(`[desktop-agent-python] ${normalized}`);
      }
    });

    child.on("error", (error) => {
      settleReject(error instanceof Error ? error : new Error(String(error)));
    });

    child.on("close", (code) => {
      if (didSettle) {
        return;
      }

      const trailingStderrLine = stderrLogBuffer.trim();
      if (trailingStderrLine) {
        console.log(`[desktop-agent-python] ${trailingStderrLine}`);
      }

      if (code !== 0) {
        settleReject(
          new Error(
            `Python agent exited with code ${code}.${
              stderr ? `\n${stderr.trim()}` : ""
            }`
          )
        );
        return;
      }

      try {
        if (buffer.trim()) {
          handleProtocolLine(buffer.trim());
        }

        if (!result) {
          throw new Error("Agent did not return a final result.");
        }

        settleResolve(result);
      } catch (error) {
        settleReject(
          new Error(
            `Failed to parse Python agent output.${
              stderr ? `\n${stderr.trim()}` : ""
            }`
          )
        );
      }
    });

    writeProtocolMessage({
        api_key: input.apiKey,
        base_url: input.baseUrl,
        model: input.model,
        writer_model: writerModel,
        messages: input.messages,
        page_context: input.pageContext,
        desktop_root: input.desktopRoot,
        open_desktop_hint: input.openDesktopHint,
        visited_websites: input.visitedWebsites ?? {},
        web_search_steps_used: Number.isFinite(input.webSearchStepsUsed)
          ? Math.max(0, Math.floor(input.webSearchStepsUsed ?? 0))
          : 0,
        web_search_limits: input.webSearchLimits
          ? {
              min_websites: input.webSearchLimits.minWebsites,
              max_websites: input.webSearchLimits.maxWebsites,
            }
          : undefined,
        force_write_outputs: input.forceWriteOutputs ?? false,
      });
  });
};

export const resetDesktopAgentChromaStore = (): void => {
  const pythonCommand = resolvePythonCommand();
  const scriptPath = resolveChromaSetupScriptPath();
  const result = spawnSync(pythonCommand, [scriptPath, "--reset"], {
    cwd: dirname(scriptPath),
    stdio: "ignore",
    windowsHide: true,
  });

  if (result.error) {
    throw result.error;
  }

  if (result.status !== 0) {
    throw new Error(
      `Failed to reset the Chroma vector store. Exit code: ${result.status ?? "unknown"}.`
    );
  }
};

export const dumpDesktopAgentChromaStore = (): ChromaStoreDumpResult => {
  const pythonCommand = resolvePythonCommand();
  const scriptPath = resolveChromaSetupScriptPath();
  const result = spawnSync(pythonCommand, [scriptPath, "--dump"], {
    cwd: dirname(scriptPath),
    encoding: "utf-8",
    windowsHide: true,
  });

  if (result.error) {
    throw result.error;
  }

  if (result.status !== 0) {
    const stderr = result.stderr?.trim();
    throw new Error(
      `Failed to dump the Chroma vector store. Exit code: ${result.status ?? "unknown"}.${
        stderr ? ` ${stderr}` : ""
      }`
    );
  }

  const stdout = result.stdout?.trim();
  if (!stdout) {
    throw new Error("Failed to dump the Chroma vector store. No output was returned.");
  }

  let parsedOutput: unknown;
  try {
    parsedOutput = JSON.parse(stdout);
  } catch {
    throw new Error("Failed to parse Chroma vector store dump output.");
  }

  if (!parsedOutput || typeof parsedOutput !== "object") {
    throw new Error("Invalid Chroma vector store dump payload.");
  }

  return parsedOutput as ChromaStoreDumpResult;
};

