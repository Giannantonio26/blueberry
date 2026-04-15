import { contextBridge } from "electron";
import { electronAPI } from "@electron-toolkit/preload";

interface DesktopEntry {
  name: string;
  path: string;
  kind: "directory" | "file";
  extension: string;
}

interface DesktopBreadcrumb {
  name: string;
  path: string;
}

interface DesktopEntriesResponse {
  desktopPath: string;
  currentPath: string;
  parentPath: string | null;
  breadcrumbs: DesktopBreadcrumb[];
  entries: DesktopEntry[];
}

interface DesktopChatRequest {
  message: string;
  messageId: string;
}

const desktopAPI = {
  getDesktopEntries: (
    directoryPath?: string
  ): Promise<DesktopEntriesResponse> =>
    electronAPI.ipcRenderer.invoke("get-desktop-entries", directoryPath),
  openDesktopFile: (filePath: string): Promise<boolean> =>
    electronAPI.ipcRenderer.invoke("open-desktop-file", filePath),
  respondToAgentFileConfirmation: (
    requestId: string,
    approved: boolean
  ): void => {
    electronAPI.ipcRenderer.send("desktop-agent-file-confirmation-response", {
      requestId,
      approved,
    });
  },
  signalReady: (): void => {
    electronAPI.ipcRenderer.send("desktop-window-ready");
  },
  acknowledgeCursorMove: (eventId: string): void => {
    electronAPI.ipcRenderer.send("desktop-agent-cursor-move-complete", {
      eventId,
    });
  },
  logDebug: (event: string, details?: Record<string, unknown>): void => {
    electronAPI.ipcRenderer.send("desktop-agent-debug-log", {
      event,
      details: details ?? {},
    });
  },
  sendChatMessage: (request: DesktopChatRequest) =>
    electronAPI.ipcRenderer.invoke("desktop-chat-message", request),
  getMessages: () => electronAPI.ipcRenderer.invoke("desktop-get-messages"),
  onMessagesUpdated: (callback: (messages: any[]) => void) => {
    electronAPI.ipcRenderer.on("chat-messages-updated", (_, messages) =>
      callback(messages)
    );
  },
  removeMessagesUpdatedListener: () => {
    electronAPI.ipcRenderer.removeAllListeners("chat-messages-updated");
  },
  getDebugLogPath: (): Promise<string> =>
    electronAPI.ipcRenderer.invoke("desktop-agent-get-debug-log-path"),
};

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld("electron", electronAPI);
    contextBridge.exposeInMainWorld("desktopAPI", desktopAPI);
  } catch (error) {
    console.error(error);
  }
} else {
  // @ts-ignore (define in dts)
  window.electron = electronAPI;
  // @ts-ignore (define in dts)
  window.desktopAPI = desktopAPI;
}
