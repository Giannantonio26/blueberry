import { DesktopWindow } from "./DesktopWindow";
import type { WebContents } from "electron";
import { appendDesktopAgentDebugLog } from "./DesktopAgentDebugLogger";

let desktopWindow: DesktopWindow | null = null;
let isDesktopWindowReady = false;
let pendingDesktopEvents: Array<{ channel: string; payload: unknown }> = [];

export const focusOrCreateDesktopWindow = (): DesktopWindow => {
  if (desktopWindow && !desktopWindow.browserWindow.isDestroyed()) {
    appendDesktopAgentDebugLog("main", "desktop_window_focus_existing", {
      webContentsId: desktopWindow.browserWindow.webContents.id,
    });
    desktopWindow.focus();
    return desktopWindow;
  }

  const window = new DesktopWindow();
  appendDesktopAgentDebugLog("main", "desktop_window_created", {
    webContentsId: window.browserWindow.webContents.id,
  });
  window.onClosed(() => {
    if (desktopWindow === window) {
      appendDesktopAgentDebugLog("main", "desktop_window_closed", {
        webContentsId: window.browserWindow.webContents.id,
      });
      desktopWindow = null;
      isDesktopWindowReady = false;
      pendingDesktopEvents = [];
    }
  });
  window.browserWindow.webContents.on("did-start-loading", () => {
    if (desktopWindow === window) {
      appendDesktopAgentDebugLog("main", "desktop_window_did_start_loading", {
        webContentsId: window.browserWindow.webContents.id,
      });
      isDesktopWindowReady = false;
    }
  });

  isDesktopWindowReady = false;
  pendingDesktopEvents = [];
  desktopWindow = window;
  return window;
};

export const getDesktopWindow = (): DesktopWindow | null => {
  if (!desktopWindow || desktopWindow.browserWindow.isDestroyed()) {
    desktopWindow = null;
    return null;
  }

  return desktopWindow;
};

export const markDesktopWindowReady = (sender: WebContents): void => {
  const currentDesktopWindow = getDesktopWindow();
  if (!currentDesktopWindow) {
    appendDesktopAgentDebugLog("main", "desktop_window_ready_ignored_no_window", {
      senderId: sender.id,
    });
    return;
  }

  const currentWebContents = currentDesktopWindow.browserWindow.webContents;
  if (currentWebContents.isDestroyed() || currentWebContents.id !== sender.id) {
    appendDesktopAgentDebugLog("main", "desktop_window_ready_ignored_wrong_sender", {
      senderId: sender.id,
      currentWebContentsId: currentWebContents.isDestroyed()
        ? null
        : currentWebContents.id,
    });
    return;
  }

  isDesktopWindowReady = true;
  appendDesktopAgentDebugLog("main", "desktop_window_marked_ready", {
    senderId: sender.id,
    pendingEventCount: pendingDesktopEvents.length,
  });

  const eventsToFlush = pendingDesktopEvents;
  pendingDesktopEvents = [];
  for (const event of eventsToFlush) {
    if (!currentWebContents.isDestroyed()) {
      appendDesktopAgentDebugLog("main", "desktop_window_flush_event", {
        channel: event.channel,
        payload: event.payload,
      });
      currentWebContents.send(event.channel, event.payload);
    }
  }
};

export const sendDesktopWindowEvent = (
  channel: string,
  payload: unknown
): boolean => {
  const currentDesktopWindow = getDesktopWindow();
  if (!currentDesktopWindow) {
    appendDesktopAgentDebugLog("main", "desktop_window_send_failed_no_window", {
      channel,
      payload,
    });
    return false;
  }

  const currentWebContents = currentDesktopWindow.browserWindow.webContents;
  if (currentWebContents.isDestroyed()) {
    appendDesktopAgentDebugLog("main", "desktop_window_send_failed_destroyed", {
      channel,
      payload,
    });
    return false;
  }

  if (currentWebContents.isLoading() || !isDesktopWindowReady) {
    pendingDesktopEvents.push({ channel, payload });
    appendDesktopAgentDebugLog("main", "desktop_window_event_queued", {
      channel,
      payload,
      isLoading: currentWebContents.isLoading(),
      isReady: isDesktopWindowReady,
      pendingEventCount: pendingDesktopEvents.length,
    });
    return false;
  }

  appendDesktopAgentDebugLog("main", "desktop_window_event_sent", {
    channel,
    payload,
    webContentsId: currentWebContents.id,
  });
  currentWebContents.send(channel, payload);
  return true;
};
