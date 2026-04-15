import type { Tab } from "./Tab";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

export type BrowserCompanionTarget =
  | "search-bar"
  | "results-list"
  | "page-content"
  | "viewport-center";

export type BrowserCompanionMood = "speaking" | "thinking" | "success";

export interface BrowserCompanionPayload {
  target?: BrowserCompanionTarget;
  label: string;
  sentence?: string;
  click?: boolean;
  mood?: BrowserCompanionMood;
}

const IDLE_BROWSER_COMPANION_PAYLOAD: BrowserCompanionPayload = {
  label: "Blueberry",
  sentence:
    "I am Blueberry, your browser companion. I can search the web, retrieve vector chunks, and explain each step while I work.",
  mood: "speaking",
};

const OVERLAY_ID = "__blueberry-browser-companion-overlay";
const STYLE_ID = "__blueberry-browser-companion-style";
const POSITION_STORAGE_KEY = "__blueberry-browser-companion-position";

const resolveCompanionAvatarPath = (): string | null => {
  const candidates = [
    resolve(process.cwd(), "resources", "avatar-cutout.png"),
    resolve(process.cwd(), "resources", "avatar.png"),
    resolve(process.resourcesPath, "avatar-cutout.png"),
    resolve(process.resourcesPath, "avatar.png"),
    resolve(process.resourcesPath, "resources", "avatar-cutout.png"),
    resolve(process.resourcesPath, "resources", "avatar.png"),
    resolve(
      process.resourcesPath,
      "app.asar.unpacked",
      "resources",
      "avatar-cutout.png"
    ),
    resolve(
      process.resourcesPath,
      "app.asar.unpacked",
      "resources",
      "avatar.png"
    ),
  ];

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }

  return null;
};

const COMPANION_AVATAR_SRC = (() => {
  const avatarPath = resolveCompanionAvatarPath();
  if (!avatarPath) {
    return "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";
  }

  const lowerPath = avatarPath.toLowerCase();
  const mimeType = lowerPath.endsWith(".webp")
    ? "image/webp"
    : lowerPath.endsWith(".jpg") || lowerPath.endsWith(".jpeg")
      ? "image/jpeg"
      : "image/png";
  const encoded = readFileSync(avatarPath).toString("base64");
  return `data:${mimeType};base64,${encoded}`;
})();

const COMPANION_MARKUP = `
  <div data-blueberry-cursor="true" class="bb-browser-cursor" aria-hidden="true">
    <svg width="30" height="30" viewBox="0 0 30 30" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M5 4L21.4 15.1L13.1 16.9L17.2 27L13.1 28.2L8.9 18L5 24.2V4Z" fill="#FFFFFF" stroke="#081120" stroke-width="1.65" stroke-linejoin="round"/>
    </svg>
  </div>
  <div data-blueberry-companion="true" class="bb-browser-companion" data-mood="speaking" aria-hidden="true">
    <div class="bb-browser-bubble">
      <div class="bb-browser-chip">
        <span class="bb-browser-chip-dot"></span>
        <span data-blueberry-companion-label="true">Working</span>
      </div>
      <p data-blueberry-companion-sentence="true" class="bb-browser-sentence">I am working on your request.</p>
    </div>
    <div class="bb-browser-avatar-shell">
      <div class="bb-browser-avatar-glow"></div>
      <img class="bb-browser-avatar" src="${COMPANION_AVATAR_SRC}" alt="" />
    </div>
  </div>
`;

const COMPANION_STYLE = `
  #${OVERLAY_ID} {
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 2147483647;
    font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
  }
  #${OVERLAY_ID} .bb-browser-cursor {
    position: fixed;
    left: 0;
    top: 0;
    width: 30px;
    height: 30px;
    opacity: 0;
    transform: translate(-50%, -50%) scale(1);
    transition:
      left 420ms cubic-bezier(0.22, 1, 0.36, 1),
      top 420ms cubic-bezier(0.22, 1, 0.36, 1),
      transform 160ms ease,
      opacity 160ms ease;
    filter: drop-shadow(0 16px 30px rgba(8, 17, 32, 0.28));
  }
  #${OVERLAY_ID} .bb-browser-companion {
    position: fixed;
    right: 18px;
    bottom: 18px;
    display: flex;
    align-items: flex-end;
    gap: 14px;
    max-width: min(420px, calc(100vw - 32px));
    pointer-events: auto;
    cursor: grab;
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
  }
  #${OVERLAY_ID} .bb-browser-companion.bb-dragging {
    cursor: grabbing;
  }
  #${OVERLAY_ID} .bb-browser-bubble {
    min-width: 210px;
    max-width: 280px;
    padding: 14px 15px 14px 16px;
    border-radius: 22px;
    border: 1px solid rgba(129, 146, 247, 0.28);
    background:
      linear-gradient(180deg, rgba(12, 19, 47, 0.94), rgba(18, 29, 68, 0.9));
    box-shadow:
      0 24px 50px rgba(9, 14, 36, 0.28),
      inset 0 1px 0 rgba(255, 255, 255, 0.06);
    backdrop-filter: blur(18px);
    color: #f8fafc;
    transform-origin: bottom right;
    animation: bbBubbleBreathe 2200ms ease-in-out infinite;
  }
  #${OVERLAY_ID} .bb-browser-chip {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 5px 10px;
    border-radius: 999px;
    background: rgba(115, 133, 255, 0.18);
    color: #dbeafe;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }
  #${OVERLAY_ID} .bb-browser-chip-dot {
    width: 7px;
    height: 7px;
    border-radius: 999px;
    background: #75f0ff;
    box-shadow: 0 0 0 0 rgba(117, 240, 255, 0.55);
    animation: bbStatusPulse 1700ms ease-out infinite;
  }
  #${OVERLAY_ID} .bb-browser-sentence {
    margin: 10px 0 0;
    font-size: 13px;
    line-height: 1.45;
    color: #eff6ff;
  }
  #${OVERLAY_ID} .bb-browser-avatar-shell {
    position: relative;
    width: 128px;
    flex: 0 0 128px;
  }
  #${OVERLAY_ID} .bb-browser-avatar-glow {
    position: absolute;
    inset: 22px 12px 0;
    border-radius: 999px;
    background: radial-gradient(circle, rgba(95, 124, 255, 0.36) 0%, rgba(95, 124, 255, 0) 72%);
    filter: blur(12px);
    animation: bbGlowPulse 2200ms ease-in-out infinite;
  }
  #${OVERLAY_ID} .bb-browser-avatar {
    display: block;
    width: 100%;
    height: auto;
    filter: drop-shadow(0 22px 34px rgba(22, 32, 79, 0.24));
    transform-origin: 52% 70%;
    animation: bbAvatarFloat 2600ms ease-in-out infinite;
  }
  #${OVERLAY_ID} [data-mood="thinking"] .bb-browser-chip {
    background: rgba(124, 58, 237, 0.18);
  }
  #${OVERLAY_ID} [data-mood="thinking"] .bb-browser-chip-dot {
    background: #c4b5fd;
    box-shadow: 0 0 0 0 rgba(196, 181, 253, 0.48);
  }
  #${OVERLAY_ID} [data-mood="thinking"] .bb-browser-bubble {
    border-color: rgba(196, 181, 253, 0.28);
    background:
      linear-gradient(180deg, rgba(18, 17, 48, 0.94), rgba(33, 22, 73, 0.9));
  }
  #${OVERLAY_ID} [data-mood="success"] .bb-browser-chip {
    background: rgba(16, 185, 129, 0.2);
  }
  #${OVERLAY_ID} [data-mood="success"] .bb-browser-chip-dot {
    background: #6ee7b7;
    box-shadow: 0 0 0 0 rgba(110, 231, 183, 0.42);
  }
  #${OVERLAY_ID} [data-mood="success"] .bb-browser-bubble {
    border-color: rgba(110, 231, 183, 0.28);
    background:
      linear-gradient(180deg, rgba(8, 38, 34, 0.94), rgba(10, 59, 51, 0.9));
  }
  @keyframes bbAvatarFloat {
    0%, 100% { transform: translateY(0px); }
    50% { transform: translateY(-6px); }
  }
  @keyframes bbGlowPulse {
    0%, 100% { opacity: 0.85; transform: scale(0.96); }
    50% { opacity: 1; transform: scale(1.04); }
  }
  @keyframes bbBubbleBreathe {
    0%, 100% { transform: translateY(0px); }
    50% { transform: translateY(-2px); }
  }
  @keyframes bbStatusPulse {
    0% { box-shadow: 0 0 0 0 rgba(117, 240, 255, 0.55); }
    70% { box-shadow: 0 0 0 10px rgba(117, 240, 255, 0); }
    100% { box-shadow: 0 0 0 0 rgba(117, 240, 255, 0); }
  }
  @media (max-width: 760px) {
    #${OVERLAY_ID} .bb-browser-companion {
      right: 10px;
      bottom: 10px;
      gap: 10px;
      max-width: calc(100vw - 16px);
    }
    #${OVERLAY_ID} .bb-browser-avatar-shell {
      width: 104px;
      flex-basis: 104px;
    }
    #${OVERLAY_ID} .bb-browser-bubble {
      min-width: 180px;
      max-width: min(230px, calc(100vw - 140px));
      padding: 12px 13px 12px 14px;
    }
    #${OVERLAY_ID} .bb-browser-sentence {
      font-size: 12px;
    }
  }
`;

const buildCompanionOverlayScript = (payload: BrowserCompanionPayload): string => `
(() => {
  const payload = ${JSON.stringify(payload)};
  const overlayId = ${JSON.stringify(OVERLAY_ID)};
  const styleId = ${JSON.stringify(STYLE_ID)};
  const companionMarkup = ${JSON.stringify(COMPANION_MARKUP)};
  const companionStyle = ${JSON.stringify(COMPANION_STYLE)};
  const positionStorageKey = ${JSON.stringify(POSITION_STORAGE_KEY)};
  const doc = document;
  const body = doc.body || doc.documentElement;
  if (!body) {
    return false;
  }

  let styleNode = doc.getElementById(styleId);
  if (!styleNode) {
    styleNode = doc.createElement("style");
    styleNode.id = styleId;
    styleNode.textContent = companionStyle;
    (doc.head || body).appendChild(styleNode);
  }

  let overlay = doc.getElementById(overlayId);
  if (!overlay) {
    overlay = doc.createElement("div");
    overlay.id = overlayId;
    overlay.innerHTML = companionMarkup;
    body.appendChild(overlay);
  }

  const cursor = overlay.querySelector('[data-blueberry-cursor="true"]');
  const companion = overlay.querySelector('[data-blueberry-companion="true"]');
  const labelNode = overlay.querySelector('[data-blueberry-companion-label="true"]');
  const sentenceNode = overlay.querySelector('[data-blueberry-companion-sentence="true"]');

  if (!companion || !labelNode || !sentenceNode || !cursor) {
    return false;
  }

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const saveCompanionPosition = (left, top) => {
    try {
      window.localStorage.setItem(
        positionStorageKey,
        JSON.stringify({ left, top })
      );
    } catch (_error) {
      // Ignore storage failures (private browsing / blocked storage).
    }
  };
  const readCompanionPosition = () => {
    try {
      const raw = window.localStorage.getItem(positionStorageKey);
      if (!raw) {
        return null;
      }
      const parsed = JSON.parse(raw);
      if (
        !parsed ||
        typeof parsed.left !== "number" ||
        typeof parsed.top !== "number"
      ) {
        return null;
      }
      return parsed;
    } catch (_error) {
      return null;
    }
  };
  const applyCompanionPosition = (left, top) => {
    const margin = 8;
    const rect = companion.getBoundingClientRect();
    const maxLeft = Math.max(margin, window.innerWidth - rect.width - margin);
    const maxTop = Math.max(margin, window.innerHeight - rect.height - margin);
    const nextLeft = clamp(left, margin, maxLeft);
    const nextTop = clamp(top, margin, maxTop);
    companion.style.left = nextLeft + "px";
    companion.style.top = nextTop + "px";
    companion.style.right = "auto";
    companion.style.bottom = "auto";
    return { left: nextLeft, top: nextTop };
  };

  const savedPosition = readCompanionPosition();
  if (savedPosition) {
    const clamped = applyCompanionPosition(savedPosition.left, savedPosition.top);
    saveCompanionPosition(clamped.left, clamped.top);
  }

  if (companion.getAttribute("data-draggable-ready") !== "true") {
    companion.setAttribute("data-draggable-ready", "true");

    let isDragging = false;
    let activePointerId = null;
    let pointerOffsetX = 0;
    let pointerOffsetY = 0;

    const stopDrag = () => {
      if (!isDragging) {
        return;
      }
      isDragging = false;
      companion.classList.remove("bb-dragging");
      const left = Number.parseFloat(companion.style.left);
      const top = Number.parseFloat(companion.style.top);
      if (Number.isFinite(left) && Number.isFinite(top)) {
        saveCompanionPosition(left, top);
      }
      if (
        activePointerId !== null &&
        typeof companion.releasePointerCapture === "function"
      ) {
        try {
          companion.releasePointerCapture(activePointerId);
        } catch (_error) {
          // Pointer may already be released.
        }
      }
      activePointerId = null;
    };

    companion.addEventListener(
      "pointerdown",
      (event) => {
        if (event.pointerType === "mouse" && event.button !== 0) {
          return;
        }
        const rect = companion.getBoundingClientRect();
        isDragging = true;
        activePointerId = event.pointerId;
        pointerOffsetX = event.clientX - rect.left;
        pointerOffsetY = event.clientY - rect.top;
        companion.classList.add("bb-dragging");
        if (typeof companion.setPointerCapture === "function") {
          try {
            companion.setPointerCapture(event.pointerId);
          } catch (_error) {
            // Ignore capture failures.
          }
        }
        event.preventDefault();
      },
      { passive: false }
    );

    companion.addEventListener("pointermove", (event) => {
      if (!isDragging) {
        return;
      }
      if (activePointerId !== null && event.pointerId !== activePointerId) {
        return;
      }
      const clamped = applyCompanionPosition(
        event.clientX - pointerOffsetX,
        event.clientY - pointerOffsetY
      );
      saveCompanionPosition(clamped.left, clamped.top);
    });

    const endDragIfActive = (event) => {
      if (!isDragging) {
        return;
      }
      if (activePointerId !== null && event.pointerId !== activePointerId) {
        return;
      }
      stopDrag();
    };

    companion.addEventListener("pointerup", endDragIfActive);
    companion.addEventListener("pointercancel", endDragIfActive);
    companion.addEventListener("lostpointercapture", stopDrag);
    window.addEventListener(
      "resize",
      () => {
        const currentPosition = readCompanionPosition();
        if (!currentPosition) {
          return;
        }
        const clamped = applyCompanionPosition(
          currentPosition.left,
          currentPosition.top
        );
        saveCompanionPosition(clamped.left, clamped.top);
      },
      { passive: true }
    );
  }

  const label = String(payload.label || "Working").trim() || "Working";
  const sentence = String(payload.sentence || label).trim() || label;
  const mood = String(payload.mood || "speaking").trim() || "speaking";

  companion.setAttribute("data-mood", mood);
  labelNode.textContent = label;
  sentenceNode.textContent = sentence;

  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const targetMap = {
    "search-bar": { x: viewportWidth * 0.5, y: Math.max(110, viewportHeight * 0.2) },
    "results-list": { x: viewportWidth * 0.28, y: viewportHeight * 0.38 },
    "page-content": { x: viewportWidth * 0.44, y: viewportHeight * 0.34 },
    "viewport-center": { x: viewportWidth * 0.5, y: viewportHeight * 0.5 }
  };

  if (payload.target && targetMap[payload.target]) {
    const point = targetMap[payload.target];
    cursor.style.opacity = "1";
    cursor.style.left = point.x + "px";
    cursor.style.top = point.y + "px";
  } else {
    cursor.style.opacity = "0";
  }

  cursor.style.transform = "translate(-50%, -50%) scale(1)";
  if (payload.click === true) {
    cursor.style.transform = "translate(-50%, -50%) scale(0.92)";
    window.setTimeout(() => {
      const currentOverlay = document.getElementById(overlayId);
      const currentCursor = currentOverlay?.querySelector('[data-blueberry-cursor="true"]');
      if (currentCursor instanceof HTMLElement) {
        currentCursor.style.transform = "translate(-50%, -50%) scale(1)";
      }
    }, 160);
  }

  return true;
})()
`;

export const showBrowserCompanion = async (
  tab: Tab,
  payload: BrowserCompanionPayload
): Promise<void> => {
  try {
    await tab.runJs(buildCompanionOverlayScript(payload));
  } catch (error) {
    console.error("Failed to render browser companion overlay:", error);
  }
};

export const showIdleBrowserCompanion = async (tab: Tab): Promise<void> => {
  await showBrowserCompanion(tab, IDLE_BROWSER_COMPANION_PAYLOAD);
};

export const clearBrowserCompanion = async (tab: Tab): Promise<void> => {
  await showIdleBrowserCompanion(tab);
};
