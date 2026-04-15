import { ipcMain, shell, WebContents } from "electron";
import { readdir, stat } from "node:fs/promises";
import { extname, isAbsolute, join, relative, resolve } from "node:path";
import {
  coerceConsultingAgentPathToDesktopRoot,
  getConsultingAgentDesktopFolderName,
  getConsultingAgentDesktopRootPath,
} from "./ConsultingAgentWorkspace";
import {
  focusOrCreateDesktopWindow,
  markDesktopWindowReady,
} from "./DesktopWindowManager";
import {
  appendDesktopAgentDebugLog,
  getDesktopAgentDebugLogPath,
} from "./DesktopAgentDebugLogger";
import type { Window } from "./Window";

export class EventManager {
  private mainWindow: Window;

  constructor(mainWindow: Window) {
    this.mainWindow = mainWindow;
    this.setupEventHandlers();
  }

  private setupEventHandlers(): void {
    // Tab management events
    this.handleTabEvents();

    // Sidebar events
    this.handleSidebarEvents();

    // Desktop events
    this.handleDesktopEvents();

    // Page content events
    this.handlePageContentEvents();

    // Dark mode events
    this.handleDarkModeEvents();

    // Debug events
    this.handleDebugEvents();
  }

  private handleTabEvents(): void {
    // Create new tab
    ipcMain.handle("create-tab", (_, url?: string) => {
      const newTab = this.mainWindow.createTab(url);
      return { id: newTab.id, title: newTab.title, url: newTab.url };
    });

    // Close tab
    ipcMain.handle("close-tab", (_, id: string) => {
      this.mainWindow.closeTab(id);
    });

    // Switch tab
    ipcMain.handle("switch-tab", (_, id: string) => {
      this.mainWindow.switchActiveTab(id);
    });

    // Get tabs
    ipcMain.handle("get-tabs", () => {
      const activeTabId = this.mainWindow.activeTab?.id;
      return this.mainWindow.allTabs.map((tab) => ({
        id: tab.id,
        title: tab.title,
        url: tab.url,
        isActive: activeTabId === tab.id,
      }));
    });

    // Navigation (for compatibility with existing code)
    ipcMain.handle("navigate-to", (_, url: string) => {
      if (this.mainWindow.activeTab) {
        this.mainWindow.activeTab.loadURL(url);
      }
    });

    ipcMain.handle("navigate-tab", async (_, tabId: string, url: string) => {
      const tab = this.mainWindow.getTab(tabId);
      if (tab) {
        await tab.loadURL(url);
        return true;
      }
      return false;
    });

    ipcMain.handle("go-back", () => {
      if (this.mainWindow.activeTab) {
        this.mainWindow.activeTab.goBack();
      }
    });

    ipcMain.handle("go-forward", () => {
      if (this.mainWindow.activeTab) {
        this.mainWindow.activeTab.goForward();
      }
    });

    ipcMain.handle("reload", () => {
      if (this.mainWindow.activeTab) {
        this.mainWindow.activeTab.reload();
      }
    });

    // Tab-specific navigation handlers
    ipcMain.handle("tab-go-back", (_, tabId: string) => {
      const tab = this.mainWindow.getTab(tabId);
      if (tab) {
        tab.goBack();
        return true;
      }
      return false;
    });

    ipcMain.handle("tab-go-forward", (_, tabId: string) => {
      const tab = this.mainWindow.getTab(tabId);
      if (tab) {
        tab.goForward();
        return true;
      }
      return false;
    });

    ipcMain.handle("tab-reload", (_, tabId: string) => {
      const tab = this.mainWindow.getTab(tabId);
      if (tab) {
        tab.reload();
        return true;
      }
      return false;
    });

    ipcMain.handle("tab-screenshot", async (_, tabId: string) => {
      const tab = this.mainWindow.getTab(tabId);
      if (tab) {
        const image = await tab.screenshot();
        return image.toDataURL();
      }
      return null;
    });

    ipcMain.handle("tab-run-js", async (_, tabId: string, code: string) => {
      const tab = this.mainWindow.getTab(tabId);
      if (tab) {
        return await tab.runJs(code);
      }
      return null;
    });

    // Tab info
    ipcMain.handle("get-active-tab-info", () => {
      const activeTab = this.mainWindow.activeTab;
      if (activeTab) {
        return {
          id: activeTab.id,
          url: activeTab.url,
          title: activeTab.title,
          canGoBack: activeTab.webContents.canGoBack(),
          canGoForward: activeTab.webContents.canGoForward(),
        };
      }
      return null;
    });
  }

  private handleSidebarEvents(): void {
    // Toggle sidebar
    ipcMain.handle("toggle-sidebar", () => {
      this.mainWindow.sidebar.toggle();
      this.mainWindow.updateAllBounds();
      return true;
    });

    // Chat message
    ipcMain.handle("sidebar-chat-message", async (_, request) => {
      // The LLMClient now handles getting the screenshot and context directly
      await this.mainWindow.sidebar.client.sendChatMessage(request);
    });

    // Clear chat
    ipcMain.handle("sidebar-clear-chat", () => {
      this.mainWindow.sidebar.client.clearMessages();
      return true;
    });

    // Get messages
    ipcMain.handle("sidebar-get-messages", () => {
      return this.mainWindow.sidebar.client.getMessages();
    });

    // Force agent to stop web search and finalize documents
    ipcMain.handle("sidebar-force-write-docs", async () => {
      await this.mainWindow.sidebar.client.forceWriteDocumentsNow();
      return true;
    });

    ipcMain.handle("sidebar-reset-vector-store", async () => {
      await this.mainWindow.sidebar.client.resetVectorStoreNow();
      return true;
    });

    ipcMain.handle("sidebar-view-vector-store-chunks", async () => {
      this.mainWindow.sidebar.client.openVectorStoreViewerNow();
      return true;
    });
  }

  private handleDesktopEvents(): void {
    ipcMain.on("desktop-window-ready", (event) => {
      appendDesktopAgentDebugLog("main", "desktop_window_ready", {
        senderId: event.sender.id,
      });
      markDesktopWindowReady(event.sender);
    });

    ipcMain.handle("desktop-chat-message", async (_, request) => {
      await this.mainWindow.sidebar.client.sendChatMessage(request);
    });

    ipcMain.handle("desktop-get-messages", () => {
      return this.mainWindow.sidebar.client.getMessages();
    });

    ipcMain.on("desktop-agent-debug-log", (event, payload) => {
      const details: Record<string, unknown> =
        payload && typeof payload === "object"
          ? {
              ...(payload as Record<string, unknown>),
              senderId: event.sender.id,
            }
          : { payload, senderId: event.sender.id };
      const debugEvent =
        typeof details.event === "string"
          ? details.event
          : "renderer_debug_message";

      appendDesktopAgentDebugLog("renderer", debugEvent, details);
    });

    ipcMain.handle("desktop-agent-get-debug-log-path", () => {
      return getDesktopAgentDebugLogPath();
    });

    ipcMain.handle("open-desktop-window", () => {
      appendDesktopAgentDebugLog("main", "open_desktop_window_request");
      focusOrCreateDesktopWindow();
      return true;
    });

    ipcMain.handle("get-desktop-entries", async (_, targetPath?: string) => {
      const desktopPath = this.getDesktopRootPath();
      const currentPath = this.resolveDesktopPath(targetPath) ?? desktopPath;
      appendDesktopAgentDebugLog("main", "get_desktop_entries_start", {
        targetPath: targetPath ?? null,
        resolvedPath: currentPath,
      });

      try {
        const entries = await readdir(currentPath, { withFileTypes: true });
        const desktopEntries = entries
          .filter((entry) => entry.isDirectory() || entry.isFile())
          .map((entry) => ({
            name: entry.name,
            path: join(currentPath, entry.name),
            kind: entry.isDirectory() ? "directory" : "file",
            extension: entry.isFile() ? extname(entry.name).replace(/^\./, "") : "",
          }))
          .sort((a, b) => {
            if (a.kind !== b.kind) {
              return a.kind === "directory" ? -1 : 1;
            }

            return a.name.localeCompare(b.name);
          });

        appendDesktopAgentDebugLog("main", "get_desktop_entries_result", {
          resolvedPath: currentPath,
          entryCount: desktopEntries.length,
          entriesPreview: desktopEntries.slice(0, 8).map((entry) => ({
            name: entry.name,
            kind: entry.kind,
          })),
        });

        return {
          desktopPath,
          currentPath,
          parentPath:
            currentPath === desktopPath
              ? null
              : this.resolveDesktopPath(join(currentPath, "..")),
          breadcrumbs: this.buildDesktopBreadcrumbs(desktopPath, currentPath),
          entries: desktopEntries,
        };
      } catch (error) {
        console.error("Error reading desktop entries:", error);
        appendDesktopAgentDebugLog("main", "get_desktop_entries_error", {
          targetPath: targetPath ?? null,
          resolvedPath: currentPath,
          error,
        });

        return {
          desktopPath,
          currentPath,
          parentPath:
            currentPath === desktopPath
              ? null
              : this.resolveDesktopPath(join(currentPath, "..")),
          breadcrumbs: this.buildDesktopBreadcrumbs(desktopPath, currentPath),
          entries: [],
        };
      }
    });

    ipcMain.handle("open-desktop-file", async (_, filePath: string) => {
      const resolvedFilePath = this.resolveDesktopPath(filePath);
      appendDesktopAgentDebugLog("main", "open_desktop_file_start", {
        requestedPath: filePath,
        resolvedPath: resolvedFilePath,
      });
      if (!resolvedFilePath) {
        return false;
      }

      try {
        const fileStats = await stat(resolvedFilePath);
        if (!fileStats.isFile()) {
          return false;
        }
      } catch (error) {
        console.error("Error reading desktop file metadata:", error);
        appendDesktopAgentDebugLog("main", "open_desktop_file_error", {
          requestedPath: filePath,
          resolvedPath: resolvedFilePath,
          error,
        });
        return false;
      }

      const result = await shell.openPath(resolvedFilePath);
      appendDesktopAgentDebugLog("main", "open_desktop_file_result", {
        requestedPath: filePath,
        resolvedPath: resolvedFilePath,
        success: result === "",
        shellResult: result,
      });
      return result === "";
    });
  }

  private getDesktopRootPath(): string {
    return getConsultingAgentDesktopRootPath();
  }

  private resolveDesktopPath(targetPath?: string): string | null {
    const desktopPath = this.getDesktopRootPath();
    const resolvedTargetPath = coerceConsultingAgentPathToDesktopRoot(
      resolve(targetPath ?? desktopPath),
      desktopPath
    );
    const relativePath = relative(desktopPath, resolvedTargetPath);

    if (relativePath.startsWith("..") || isAbsolute(relativePath)) {
      return null;
    }

    return resolvedTargetPath;
  }

  private buildDesktopBreadcrumbs(
    desktopPath: string,
    currentPath: string
  ): Array<{ name: string; path: string }> {
    const relativePath = relative(desktopPath, currentPath);
    const segments = relativePath
      .split(/[\\/]+/)
      .filter(Boolean);

    const breadcrumbs = [
      {
        name: getConsultingAgentDesktopFolderName(),
        path: desktopPath,
      },
    ];

    let accumulatedPath = desktopPath;

    for (const segment of segments) {
      accumulatedPath = join(accumulatedPath, segment);
      breadcrumbs.push({
        name: segment,
        path: accumulatedPath,
      });
    }

    return breadcrumbs;
  }

  private handlePageContentEvents(): void {
    // Get page content
    ipcMain.handle("get-page-content", async () => {
      if (this.mainWindow.activeTab) {
        try {
          return await this.mainWindow.activeTab.getTabHtml();
        } catch (error) {
          console.error("Error getting page content:", error);
          return null;
        }
      }
      return null;
    });

    // Get page text
    ipcMain.handle("get-page-text", async () => {
      if (this.mainWindow.activeTab) {
        try {
          return await this.mainWindow.activeTab.getTabText();
        } catch (error) {
          console.error("Error getting page text:", error);
          return null;
        }
      }
      return null;
    });

    // Get current URL
    ipcMain.handle("get-current-url", () => {
      if (this.mainWindow.activeTab) {
        return this.mainWindow.activeTab.url;
      }
      return null;
    });
  }

  private handleDarkModeEvents(): void {
    // Dark mode broadcasting
    ipcMain.on("dark-mode-changed", (event, isDarkMode) => {
      this.broadcastDarkMode(event.sender, isDarkMode);
    });
  }

  private handleDebugEvents(): void {
    // Ping test
    ipcMain.on("ping", () => console.log("pong"));
  }

  private broadcastDarkMode(sender: WebContents, isDarkMode: boolean): void {
    // Send to topbar
    if (this.mainWindow.topBar.view.webContents !== sender) {
      this.mainWindow.topBar.view.webContents.send(
        "dark-mode-updated",
        isDarkMode
      );
    }

    // Send to sidebar
    if (this.mainWindow.sidebar.view.webContents !== sender) {
      this.mainWindow.sidebar.view.webContents.send(
        "dark-mode-updated",
        isDarkMode
      );
    }

    // Send to all tabs
    this.mainWindow.allTabs.forEach((tab) => {
      if (tab.webContents !== sender) {
        tab.webContents.send("dark-mode-updated", isDarkMode);
      }
    });
  }

  // Clean up event listeners
  public cleanup(): void {
    ipcMain.removeAllListeners();
  }
}
