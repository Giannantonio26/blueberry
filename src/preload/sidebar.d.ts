import { ElectronAPI } from "@electron-toolkit/preload";

interface ChatRequest {
  message: string;
  webSearchLimits?: {
    minWebsites: number;
    maxWebsites: number;
  };
  context?: {
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

interface TabInfo {
  id: string;
  title: string;
  url: string;
  isActive: boolean;
  canGoBack?: boolean;
  canGoForward?: boolean;
}

interface SidebarAPI {
  // Chat functionality
  sendChatMessage: (request: Partial<ChatRequest>) => Promise<void>;
  clearChat: () => Promise<boolean>;
  getMessages: () => Promise<any[]>;
  forceWriteDocuments: () => Promise<boolean>;
  resetVectorStore: () => Promise<boolean>;
  viewVectorStoreChunks: () => Promise<boolean>;
  onRetrievalSourceSelectionRequest: (
    callback: (data: RetrievalSourceSelectionRequest) => void
  ) => void;
  respondToRetrievalSourceSelection: (
    payload: RetrievalSourceSelectionResponse
  ) => void;
  onChatResponse: (callback: (data: ChatResponse) => void) => void;
  onMessagesUpdated: (callback: (messages: any[]) => void) => void;
  removeChatResponseListener: () => void;
  removeMessagesUpdatedListener: () => void;
  removeRetrievalSourceSelectionRequestListener: () => void;

  // Page content access
  getPageContent: () => Promise<string | null>;
  getPageText: () => Promise<string | null>;
  getCurrentUrl: () => Promise<string | null>;

  // Tab information
  getActiveTabInfo: () => Promise<TabInfo | null>;
}

declare global {
  interface Window {
    electron: ElectronAPI;
    sidebarAPI: SidebarAPI;
  }
}

