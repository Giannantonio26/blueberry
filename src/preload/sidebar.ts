import { contextBridge } from "electron";
import { electronAPI } from "@electron-toolkit/preload";

interface ChatRequest {
  message: string;
  webSearchLimits?: {
    minWebsites: number;
    maxWebsites: number;
  };
  context: {
    url: string | null;
    content: string | null;
    text: string | null;
  };
  messageId: string;
}

interface ChatResponse {
  messageId: string;
  content: string;
  isComplete: boolean;
}

interface RetrievalSourceSelectionRequest {
  requestId: string;
  query: string;
  availableSourceDomains: string[];
  defaultSelectedSourceDomains: string[];
}

interface RetrievalSourceSelectionResponse {
  requestId: string;
  action: "confirm" | "cancel";
  selectedSourceDomains: string[];
}

// Sidebar specific APIs
const sidebarAPI = {
  // Chat functionality
  sendChatMessage: (request: Partial<ChatRequest>) =>
    electronAPI.ipcRenderer.invoke("sidebar-chat-message", request),

  clearChat: () => electronAPI.ipcRenderer.invoke("sidebar-clear-chat"),

  getMessages: () => electronAPI.ipcRenderer.invoke("sidebar-get-messages"),

  forceWriteDocuments: () =>
    electronAPI.ipcRenderer.invoke("sidebar-force-write-docs"),

  resetVectorStore: () =>
    electronAPI.ipcRenderer.invoke("sidebar-reset-vector-store"),

  viewVectorStoreChunks: () =>
    electronAPI.ipcRenderer.invoke("sidebar-view-vector-store-chunks"),

  onRetrievalSourceSelectionRequest: (
    callback: (data: RetrievalSourceSelectionRequest) => void
  ) => {
    electronAPI.ipcRenderer.on(
      "retrieval-source-selection-request",
      (_, data) => callback(data)
    );
  },

  respondToRetrievalSourceSelection: (
    payload: RetrievalSourceSelectionResponse
  ) => {
    electronAPI.ipcRenderer.send(
      "retrieval-source-selection-response",
      payload
    );
  },

  onChatResponse: (callback: (data: ChatResponse) => void) => {
    electronAPI.ipcRenderer.on("chat-response", (_, data) => callback(data));
  },

  onMessagesUpdated: (callback: (messages: any[]) => void) => {
    electronAPI.ipcRenderer.on("chat-messages-updated", (_, messages) =>
      callback(messages)
    );
  },

  removeChatResponseListener: () => {
    electronAPI.ipcRenderer.removeAllListeners("chat-response");
  },

  removeMessagesUpdatedListener: () => {
    electronAPI.ipcRenderer.removeAllListeners("chat-messages-updated");
  },

  removeRetrievalSourceSelectionRequestListener: () => {
    electronAPI.ipcRenderer.removeAllListeners(
      "retrieval-source-selection-request"
    );
  },

  // Page content access
  getPageContent: () => electronAPI.ipcRenderer.invoke("get-page-content"),
  getPageText: () => electronAPI.ipcRenderer.invoke("get-page-text"),
  getCurrentUrl: () => electronAPI.ipcRenderer.invoke("get-current-url"),

  // Tab information
  getActiveTabInfo: () => electronAPI.ipcRenderer.invoke("get-active-tab-info"),
};

// Use `contextBridge` APIs to expose Electron APIs to
// renderer only if context isolation is enabled, otherwise
// just add to the DOM global.
if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld("electron", electronAPI);
    contextBridge.exposeInMainWorld("sidebarAPI", sidebarAPI);
  } catch (error) {
    console.error(error);
  }
} else {
  // @ts-ignore (define in dts)
  window.electron = electronAPI;
  // @ts-ignore (define in dts)
  window.sidebarAPI = sidebarAPI;
}
