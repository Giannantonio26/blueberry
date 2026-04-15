import { ElectronAPI } from "@electron-toolkit/preload";

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

interface DesktopAPI {
  getDesktopEntries: (directoryPath?: string) => Promise<DesktopEntriesResponse>;
  openDesktopFile: (filePath: string) => Promise<boolean>;
  respondToAgentFileConfirmation: (
    requestId: string,
    approved: boolean
  ) => void;
  signalReady: () => void;
  acknowledgeCursorMove: (eventId: string) => void;
  logDebug: (event: string, details?: Record<string, unknown>) => void;
  sendChatMessage: (request: DesktopChatRequest) => Promise<void>;
  getMessages: () => Promise<any[]>;
  onMessagesUpdated: (callback: (messages: any[]) => void) => void;
  removeMessagesUpdatedListener: () => void;
  getDebugLogPath: () => Promise<string>;
}

declare global {
  interface Window {
    electron: ElectronAPI;
    desktopAPI: DesktopAPI;
  }
}
