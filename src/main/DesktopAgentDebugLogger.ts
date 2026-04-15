import { app } from "electron";
import { appendFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";

type DesktopAgentDebugDetails = Record<string, unknown> | undefined;

interface DesktopAgentDebugEntry {
  timestamp: string;
  source: string;
  event: string;
  details?: Record<string, unknown>;
}

let writeQueue = Promise.resolve();

const sanitizeValue = (value: unknown): unknown => {
  if (value instanceof Error) {
    return {
      name: value.name,
      message: value.message,
      stack: value.stack,
    };
  }

  if (Array.isArray(value)) {
    return value.map((item) => sanitizeValue(item));
  }

  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        sanitizeValue(item),
      ])
    );
  }

  return value;
};

export const getDesktopAgentDebugLogPath = (): string => {
  return join(app.getPath("userData"), "logs", "desktop-agent-debug.log");
};

export const appendDesktopAgentDebugLog = (
  source: string,
  event: string,
  details?: DesktopAgentDebugDetails
): void => {
  const entry: DesktopAgentDebugEntry = {
    timestamp: new Date().toISOString(),
    source,
    event,
    details: details
      ? (sanitizeValue(details) as Record<string, unknown>)
      : undefined,
  };
  const logLine = `${JSON.stringify(entry)}\n`;
  const logPath = getDesktopAgentDebugLogPath();

  writeQueue = writeQueue
    .catch(() => undefined)
    .then(async () => {
      await mkdir(dirname(logPath), { recursive: true });
      await appendFile(logPath, logLine, "utf8");
    })
    .catch((error) => {
      console.error("Failed to write desktop agent debug log:", error);
    });
};
