import { is } from "@electron-toolkit/utils";
import { BrowserWindow } from "electron";
import { join } from "path";

export class DesktopWindow {
  private readonly window: BrowserWindow;

  constructor() {
    this.window = this.createWindow();
  }

  private createWindow(): BrowserWindow {
    const browserWindow = new BrowserWindow({
      width: 1360,
      height: 860,
      minWidth: 1040,
      minHeight: 680,
      show: false,
      autoHideMenuBar: true,
      backgroundColor: "#081120",
      title: "Blueberry Desktop",
      titleBarStyle: "hidden",
      ...(process.platform !== "darwin"
        ? {
            titleBarOverlay: {
              color: "#081120",
              symbolColor: "#f8fafc",
              height: 40,
            },
          }
        : {}),
      webPreferences: {
        preload: join(__dirname, "../preload/desktop.js"),
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: false,
      },
    });

    browserWindow.once("ready-to-show", () => {
      browserWindow.show();
      browserWindow.focus();
    });

    if (is.dev && process.env["ELECTRON_RENDERER_URL"]) {
      const desktopUrl = new URL(
        "/desktop/",
        process.env["ELECTRON_RENDERER_URL"]
      );
      browserWindow.loadURL(desktopUrl.toString());
    } else {
      browserWindow.loadFile(join(__dirname, "../renderer/desktop.html"));
    }

    return browserWindow;
  }

  focus(): void {
    if (this.window.isMinimized()) {
      this.window.restore();
    }

    this.window.show();
    this.window.focus();
  }

  onClosed(callback: () => void): void {
    this.window.on("closed", callback);
  }

  get browserWindow(): BrowserWindow {
    return this.window;
  }
}
