import type { Tab } from "./Tab";
import {
  showBrowserCompanion,
  type BrowserCompanionTarget,
} from "./BrowserCompanionOverlay";
import type { Window } from "./Window";

export interface GoogleSearchAndCollectArgs {
  query: string;
  purpose: string;
  visited_websites?: Record<string, string>;
}

interface SearchResultLink {
  title: string;
  url: string;
  domain: string;
}

interface SourceCapture {
  title: string;
  url: string;
  domain: string;
  meta_description: string;
  headings: string[];
  text_content: string;
  text_truncated: boolean;
}

interface PageMetadataCapture {
  title: string;
  meta_description: string;
  headings: string[];
}

interface DuckDuckGoSearchResultPayload {
  title?: unknown;
  url?: unknown;
}

interface CookieAcceptanceResult {
  clicked: boolean;
  clicked_text: string;
  clicked_selector: string;
}

export interface BrowserToolResult {
  content: string;
  filesystem_changed?: boolean;
  changed_paths?: string[];
  should_open_desktop_view?: boolean;
  metadata?: Record<string, unknown>;
  visited_website?: {
    url: string;
    title: string;
  };
}

type BrowserCursorTarget = BrowserCompanionTarget;
type SearchProvider = "duckduckgo_dom_scrape";

const DUCKDUCKGO_HOME_URL = "https://duckduckgo.com/";
const MAX_SOURCE_CONTENT_CHARS = 50000;
const MAX_DUCKDUCKGO_RESULTS = 20;
const NAVIGATION_TIMEOUT_MS = 18_000;
const SEARCH_RESULTS_EXTRACTION_TIMEOUT_MS = 8_000;
const SOURCE_CAPTURE_TIMEOUT_MS = 12_000;
const COOKIE_ACCEPT_SELECTORS = [
  "#onetrust-accept-btn-handler",
  "button#onetrust-accept-btn-handler",
  "button[data-testid*='accept']",
  "button[data-test*='accept']",
  "button[aria-label*='Accept']",
  "button[aria-label*='accept']",
  "button[title*='Accept']",
  "button[title*='accept']",
  "button[class*='accept']",
  "button[id*='accept']",
  "button[class*='consent']",
  "button[id*='consent']",
  "button[class*='cookie']",
  "button[id*='cookie']",
  "[role='button'][class*='accept']",
  "[role='button'][id*='accept']",
  "a[class*='accept']",
  "a[id*='accept']",
  "input[type='button'][value*='Accept']",
  "input[type='submit'][value*='Accept']",
];
const COOKIE_ACCEPT_KEYWORDS = [
  "accept",
  "accept all",
  "allow all",
  "allow cookies",
  "agree",
  "i agree",
  "consent",
  "got it",
  "ok",
  "okay",
  "continue",
  "accetta",
  "accetta tutti",
  "accetto",
  "consenti",
  "consenti tutti",
  "acconsento",
  "akzeptieren",
  "accepter",
  "aceptar",
];
const COOKIE_REJECT_KEYWORDS = [
  "reject",
  "decline",
  "deny",
  "necessary",
  "manage",
  "preferences",
  "settings",
  "customize",
  "reject all",
  "only essential",
  "solo essenziali",
  "rifiuta",
  "impostazioni",
  "gestisci",
];
const COOKIE_CONTEXT_KEYWORDS = [
  "cookie",
  "consent",
  "gdpr",
  "privacy",
  "onetrust",
  "didomi",
  "cookiebot",
  "trustarc",
];
const BLOCKED_NON_HTML_EXTENSIONS = new Set([
  ".pdf",
  ".doc",
  ".docx",
  ".ppt",
  ".pptx",
  ".xls",
  ".xlsx",
  ".csv",
  ".zip",
  ".rar",
  ".7z",
  ".tar",
  ".gz",
  ".bz2",
  ".mp3",
  ".mp4",
  ".avi",
  ".mov",
  ".mkv",
  ".jpg",
  ".jpeg",
  ".png",
  ".gif",
  ".webp",
  ".svg",
  ".exe",
  ".dmg",
  ".apk",
  ".iso",
]);
const INACCESSIBLE_URL_PREFIXES = [
  "chrome-error://",
  "edge-error://",
  "about:blank",
  "data:text/html,chromewebdata",
];
const INACCESSIBLE_TITLE_PATTERNS = [
  /access denied/i,
  /forbidden/i,
  /not authorized/i,
  /request blocked/i,
  /attention required/i,
  /verify you are human/i,
  /just a moment/i,
  /security check/i,
  /captcha/i,
];
const INACCESSIBLE_TEXT_PATTERNS = [
  /access denied/i,
  /you do not have permission/i,
  /you don't have permission/i,
  /request blocked/i,
  /verify you are human/i,
  /are you human/i,
  /checking your browser/i,
  /please enable cookies/i,
  /security challenge/i,
  /cloudflare ray id/i,
  /ddos protection by/i,
  /captcha/i,
  /403 forbidden/i,
];

const delay = async (milliseconds: number): Promise<void> => {
  await new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
};

const normalizeCapturedText = (rawText: string): string =>
  rawText
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

const buildDuckDuckGoSearchUrl = (query: string): string =>
  `https://duckduckgo.com/?q=${encodeURIComponent(query)}&ia=web`;

const waitForSettledTab = async (tab: Tab, timeoutMs = 20000): Promise<void> => {
  const webContents = tab.webContents;

  if (webContents.isLoading()) {
    await new Promise<void>((resolve) => {
      const timeout = setTimeout(() => {
        cleanup();
        resolve();
      }, timeoutMs);

      const cleanup = () => {
        clearTimeout(timeout);
        webContents.removeListener("did-stop-loading", finish);
        webContents.removeListener("did-fail-load", finish);
      };

      const finish = () => {
        cleanup();
        resolve();
      };

      webContents.once("did-stop-loading", finish);
      webContents.once("did-fail-load", finish);
    });
  }

  await delay(380);
};

interface TabNavigationOutcome {
  ok: boolean;
  message?: string;
}

interface MainFrameLoadFailure {
  code: number;
  description: string;
  validatedUrl: string;
}

const runWithTimeout = async <T>(
  operation: Promise<T>,
  timeoutMs: number,
  timeoutMessage: string
): Promise<T> => {
  return await new Promise<T>((resolve, reject) => {
    const timeoutHandle = setTimeout(() => {
      reject(new Error(timeoutMessage));
    }, timeoutMs);

    operation
      .then((value) => {
        clearTimeout(timeoutHandle);
        resolve(value);
      })
      .catch((error: unknown) => {
        clearTimeout(timeoutHandle);
        reject(error);
      });
  });
};

const navigateTabWithTimeout = async (
  tab: Tab,
  url: string,
  timeoutMs: number = NAVIGATION_TIMEOUT_MS
): Promise<TabNavigationOutcome> => {
  const webContents = tab.webContents;
  let mainFrameLoadFailure: MainFrameLoadFailure | null = null;

  const handleDidFailLoad = (
    _event: Electron.Event,
    errorCode: number,
    errorDescription: string,
    validatedUrl: string,
    isMainFrame: boolean
  ): void => {
    if (!isMainFrame) {
      return;
    }
    mainFrameLoadFailure = {
      code: errorCode,
      description: String(errorDescription || "navigation failed").trim(),
      validatedUrl: String(validatedUrl || url).trim(),
    };
  };

  webContents.on("did-fail-load", handleDidFailLoad);

  const loadPromise: Promise<{ kind: "loaded" } | { kind: "rejected"; message: string }> =
    tab
      .loadURL(url)
      .then(() => ({ kind: "loaded" as const }))
      .catch((error: unknown) => ({
        kind: "rejected",
        message:
          error instanceof Error
            ? error.message
            : String(error || "navigation failed"),
      }));
  const timeoutPromise = delay(timeoutMs).then(() => ({ kind: "timeout" as const }));

  const outcome = await Promise.race([loadPromise, timeoutPromise]);

  if (outcome.kind === "timeout") {
    try {
      tab.stop();
    } catch {
      // Ignore stop errors after timeout.
    }
  }

  await waitForSettledTab(tab, Math.min(timeoutMs, 6_000));
  webContents.removeListener("did-fail-load", handleDidFailLoad);

  if (outcome.kind === "loaded" && !mainFrameLoadFailure) {
    return { ok: true };
  }

  const messageParts: string[] = [];
  if (outcome.kind === "timeout") {
    messageParts.push(`Navigation timed out after ${timeoutMs}ms.`);
  } else if (outcome.kind === "rejected") {
    const rejectedMessage = String(outcome.message || "").trim();
    if (rejectedMessage) {
      messageParts.push(rejectedMessage);
    }
  }

  if (mainFrameLoadFailure !== null) {
    const loadFailure = mainFrameLoadFailure as MainFrameLoadFailure;
    const codeSegment = `net_error ${loadFailure.code}`;
    const description = loadFailure.description || "navigation failed";
    messageParts.push(
      `${description} (${codeSegment}) at ${loadFailure.validatedUrl}`
    );
  }

  return {
    ok: false,
    message:
      messageParts.join(" ").trim() || "Navigation failed before content could be read.",
  };
};

const showBrowserCursor = async (
  tab: Tab,
  payload: {
    target: BrowserCursorTarget;
    label: string;
    sentence?: string;
    click?: boolean;
  }
): Promise<void> => {
  try {
    await showBrowserCompanion(tab, {
      target: payload.target,
      label: payload.label,
      sentence: payload.sentence ?? payload.label,
      click: payload.click,
      mood: "speaking",
    });
  } catch (error) {
    console.error("Failed to render browser automation cursor:", error);
  }
};

const acceptCookiesIfPresent = async (tab: Tab): Promise<CookieAcceptanceResult> => {
  try {
    const rawResult = (await tab.runJs(`
      (() => {
        const cookieContextKeywords = ${JSON.stringify(COOKIE_CONTEXT_KEYWORDS)};
        const acceptKeywords = ${JSON.stringify(COOKIE_ACCEPT_KEYWORDS)};
        const rejectKeywords = ${JSON.stringify(COOKIE_REJECT_KEYWORDS)};
        const selectors = ${JSON.stringify(COOKIE_ACCEPT_SELECTORS)};

        const normalize = (value) =>
          String(value || "")
            .replace(/\\s+/g, " ")
            .trim()
            .toLowerCase();

        const isVisible = (element) => {
          if (!(element instanceof HTMLElement)) {
            return false;
          }
          const style = window.getComputedStyle(element);
          if (!style || style.visibility === "hidden" || style.display === "none") {
            return false;
          }
          const rect = element.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        };

        const readElementText = (element) =>
          normalize(
            element?.textContent ||
              element?.getAttribute?.("aria-label") ||
              element?.getAttribute?.("title") ||
              element?.getAttribute?.("value") ||
              ""
          );

        const hasCookieContext = (element) => {
          let current = element;
          let depth = 0;
          while (current && depth < 6) {
            const attrs = normalize(
              [
                current.id || "",
                current.className || "",
                current.getAttribute?.("aria-label") || "",
                current.getAttribute?.("data-testid") || "",
                current.getAttribute?.("role") || "",
              ].join(" ")
            );

            if (cookieContextKeywords.some((keyword) => attrs.includes(keyword))) {
              return true;
            }

            current = current.parentElement;
            depth += 1;
          }
          return false;
        };

        const scoreCandidate = (candidate) => {
          const text = candidate.text;
          let score = 0;

          if (candidate.selector.includes("accept")) {
            score += 60;
          }
          if (candidate.selector.includes("consent") || candidate.selector.includes("cookie")) {
            score += 20;
          }
          if (candidate.hasContext) {
            score += 25;
          }

          for (const keyword of acceptKeywords) {
            if (text === keyword) {
              score += 90;
            } else if (text.includes(keyword)) {
              score += 45;
            }
          }

          for (const keyword of rejectKeywords) {
            if (text === keyword) {
              score -= 120;
            } else if (text.includes(keyword)) {
              score -= 70;
            }
          }

          return score;
        };

        const candidates = [];
        const seen = new Set();
        const addCandidate = (element, selector, requireContext) => {
          if (!(element instanceof HTMLElement || element instanceof HTMLInputElement)) {
            return;
          }
          if (!isVisible(element)) {
            return;
          }

          const text = readElementText(element);
          if (!text) {
            return;
          }

          const hasContext = hasCookieContext(element);
          if (requireContext && !hasContext) {
            return;
          }

          const key = selector + "::" + text + "::" + element.tagName;
          if (seen.has(key)) {
            return;
          }
          seen.add(key);

          candidates.push({ element, selector, text, hasContext });
        };

        for (const selector of selectors) {
          const nodes = document.querySelectorAll(selector);
          for (const node of nodes) {
            addCandidate(node, selector.toLowerCase(), false);
          }
        }

        const genericNodes = document.querySelectorAll(
          "button, [role='button'], a, input[type='button'], input[type='submit']"
        );
        for (const node of genericNodes) {
          addCandidate(node, "generic", true);
        }

        if (!candidates.length) {
          return {
            clicked: false,
            clicked_text: "",
            clicked_selector: "",
          };
        }

        candidates.sort((a, b) => scoreCandidate(b) - scoreCandidate(a));
        const best = candidates[0];
        if (!best || scoreCandidate(best) <= 0) {
          return {
            clicked: false,
            clicked_text: "",
            clicked_selector: "",
          };
        }

        try {
          best.element.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
        } catch {}

        best.element.dispatchEvent(new MouseEvent("mouseover", { bubbles: true, cancelable: true }));
        best.element.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
        best.element.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true }));
        best.element.click();

        return {
          clicked: true,
          clicked_text: best.text.slice(0, 120),
          clicked_selector: best.selector.slice(0, 140),
        };
      })()
    `)) as unknown;

    if (!rawResult || typeof rawResult !== "object") {
      return { clicked: false, clicked_text: "", clicked_selector: "" };
    }

    const payload = rawResult as Partial<CookieAcceptanceResult>;
    return {
      clicked: payload.clicked === true,
      clicked_text:
        typeof payload.clicked_text === "string" ? payload.clicked_text : "",
      clicked_selector:
        typeof payload.clicked_selector === "string"
          ? payload.clicked_selector
          : "",
    };
  } catch (error) {
    console.error("Failed to auto-accept cookie banner:", error);
    return { clicked: false, clicked_text: "", clicked_selector: "" };
  }
};

const typeSearchQuery = async (tab: Tab, query: string): Promise<boolean> => {
  try {
    const didType = await tab.runJs(`
      new Promise((resolve) => {
        const input =
          document.querySelector('input[name="q"]') ||
          document.querySelector('textarea[name="q"]') ||
          document.querySelector('input[type="search"]');

        if (!(input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement)) {
          resolve(false);
          return;
        }

        const text = ${JSON.stringify(query)};
        input.focus();
        input.value = "";

        let index = 0;
        const interval = Math.max(18, Math.min(55, Math.floor(820 / Math.max(text.length, 1))));

        const tick = () => {
          if (index >= text.length) {
            input.dispatchEvent(new Event("change", { bubbles: true }));
            resolve(true);
            return;
          }

          input.value += text[index];
          index += 1;
          input.dispatchEvent(new Event("input", { bubbles: true }));
          window.setTimeout(tick, interval);
        };

        tick();
      })
    `);

    return didType === true;
  } catch (error) {
    console.error("Failed to type search query:", error);
    return false;
  }
};

const normalizeUrl = (rawUrl: string): string => {
  try {
    return new URL(rawUrl).toString();
  } catch {
    return rawUrl.trim();
  }
};

const decodeURIComponentSafe = (value: string): string => {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
};

const resolveDuckDuckGoResultUrl = (rawUrl: string): string => {
  const normalizedRawUrl = normalizeUrl(rawUrl);

  try {
    const parsedUrl = new URL(normalizedRawUrl);
    const normalizedHost = parsedUrl.hostname.trim().toLowerCase().replace(/\.+$/, "");

    if (normalizedHost === "duckduckgo.com" || normalizedHost.endsWith(".duckduckgo.com")) {
      const redirectCandidates = [
        parsedUrl.searchParams.get("uddg"),
        parsedUrl.searchParams.get("rut"),
        parsedUrl.searchParams.get("u"),
      ];

      for (const candidate of redirectCandidates) {
        if (!candidate || !candidate.trim()) {
          continue;
        }

        const decodedCandidate = decodeURIComponentSafe(candidate.trim());
        const resolvedCandidate = normalizeUrl(decodedCandidate);
        if (resolvedCandidate.startsWith("http")) {
          return resolvedCandidate;
        }
      }
    }

    return parsedUrl.toString();
  } catch {
    return normalizedRawUrl;
  }
};

const isLikelyNonHtmlResult = (url: string): boolean => {
  try {
    const parsedUrl = new URL(url);
    const pathname = parsedUrl.pathname.toLowerCase();

    for (const extension of BLOCKED_NON_HTML_EXTENSIONS) {
      if (pathname.endsWith(extension)) {
        return true;
      }
    }

    return false;
  } catch {
    return false;
  }
};

const detectInaccessiblePageReason = (
  pageUrl: string,
  pageTitle: string,
  pageTextContent: string
): string | null => {
  const normalizedUrl = normalizeUrl(pageUrl).toLowerCase();
  const inaccessibleUrlPrefix = INACCESSIBLE_URL_PREFIXES.find((prefix) =>
    normalizedUrl.startsWith(prefix)
  );
  if (inaccessibleUrlPrefix) {
    return `page resolved to browser error URL (${inaccessibleUrlPrefix})`;
  }

  for (const pattern of INACCESSIBLE_TITLE_PATTERNS) {
    if (pattern.test(pageTitle)) {
      return `page title matched inaccessible pattern (${pattern.source})`;
    }
  }

  const textSample = pageTextContent.slice(0, 5000);
  const matchedTextPatterns: string[] = [];
  for (const pattern of INACCESSIBLE_TEXT_PATTERNS) {
    if (pattern.test(textSample)) {
      matchedTextPatterns.push(pattern.source);
    }
  }

  if (matchedTextPatterns.length >= 2) {
    return `page text matched inaccessible patterns (${matchedTextPatterns
      .slice(0, 2)
      .join(", ")})`;
  }

  if (matchedTextPatterns.length === 1 && textSample.length <= 1200) {
    return `short page text matched inaccessible pattern (${matchedTextPatterns[0]})`;
  }

  return null;
};

const isBlockedSearchResultHost = (hostname: string): boolean => {
  const normalizedHost = hostname.trim().toLowerCase().replace(/\.+$/, "");
  if (!normalizedHost) {
    return true;
  }

  if (normalizedHost.includes("google.")) {
    return true;
  }

  if (normalizedHost === "duckduckgo.com" || normalizedHost.endsWith(".duckduckgo.com")) {
    return true;
  }

  return (
    normalizedHost === "youtube.com" ||
    normalizedHost.endsWith(".youtube.com") ||
    normalizedHost === "youtu.be" ||
    normalizedHost.endsWith(".youtu.be") ||
    normalizedHost === "youtube-nocookie.com" ||
    normalizedHost.endsWith(".youtube-nocookie.com")
  );
};

const collectDuckDuckGoResults = async (tab: Tab): Promise<SearchResultLink[]> => {
  const rawPayload = (await tab.runJs(`
    (() => {
      const selectors = [
        'a[data-testid="result-title-a"]',
        'a.result__a',
        'article h2 a',
        '.result h2 a',
        'h2 a'
      ];
      const results = [];
      const seen = new Set();

      for (const selector of selectors) {
        const nodes = document.querySelectorAll(selector);
        for (const node of nodes) {
          if (!(node instanceof HTMLAnchorElement)) {
            continue;
          }

          const title = (node.textContent || "").replace(/\\s+/g, " ").trim();
          const url = (node.href || "").trim();
          if (!title || !url) {
            continue;
          }

          const key = \`\${url}::\${title}\`;
          if (seen.has(key)) {
            continue;
          }
          seen.add(key);
          results.push({ title, url });

          if (results.length >= ${MAX_DUCKDUCKGO_RESULTS}) {
            return results;
          }
        }
      }

      return results;
    })()
  `)) as unknown;

  const items = Array.isArray(rawPayload)
    ? (rawPayload as DuckDuckGoSearchResultPayload[])
    : [];

  const results: SearchResultLink[] = [];
  const seenUrls = new Set<string>();

  for (const item of items) {
    const rawItemUrl = typeof item?.url === "string" ? item.url.trim() : "";
    const rawItemTitle = typeof item?.title === "string" ? item.title.trim() : "";
    if (!rawItemUrl || !rawItemTitle) {
      continue;
    }

    const resolvedResultUrl = resolveDuckDuckGoResultUrl(rawItemUrl);
    if (!resolvedResultUrl.startsWith("http")) {
      continue;
    }

    try {
      const parsedUrl = new URL(resolvedResultUrl);
      if (isBlockedSearchResultHost(parsedUrl.hostname)) {
        continue;
      }

      const normalizedResultUrl = parsedUrl.toString();
      if (seenUrls.has(normalizedResultUrl)) {
        continue;
      }

      seenUrls.add(normalizedResultUrl);
      results.push({
        title: rawItemTitle,
        url: normalizedResultUrl,
        domain: parsedUrl.hostname,
      });
    } catch {
      continue;
    }
  }

  return results;
};

const extractTextFromHtml = (rawHtml: string): string => {
  if (!rawHtml.trim()) {
    return "";
  }

  const textWithoutScripts = rawHtml
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<noscript[\s\S]*?<\/noscript>/gi, " ");
  const textWithoutTags = textWithoutScripts.replace(/<[^>]+>/g, " ");
  const decodedEntities = textWithoutTags
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&#39;/g, "'")
    .replace(/&quot;/gi, '"');

  return normalizeCapturedText(decodedEntities);
};

const extractPageMetadata = async (tab: Tab): Promise<PageMetadataCapture> => {
  const payload = (await tab.runJs(`
    (() => {
      const normalize = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const readMeta = (selector) => {
        const node = document.querySelector(selector);
        if (!(node instanceof HTMLMetaElement)) {
          return "";
        }
        return normalize(node.content || node.getAttribute("content") || "");
      };

      const title = normalize(document.title);
      const metaDescription =
        readMeta('meta[name="description"]') ||
        readMeta('meta[property="og:description"]') ||
        readMeta('meta[name="twitter:description"]');

      const headingNodes = Array.from(document.querySelectorAll("h1, h2, h3"));
      const headings = [];
      const seen = new Set();
      for (const node of headingNodes) {
        const text = normalize(node.textContent || "");
        if (!text || seen.has(text)) {
          continue;
        }
        seen.add(text);
        headings.push(text);
        if (headings.length >= 12) {
          break;
        }
      }

      return {
        title,
        meta_description: metaDescription,
        headings
      };
    })()
  `)) as unknown;

  const defaultMetadata: PageMetadataCapture = {
    title: "",
    meta_description: "",
    headings: [],
  };

  if (!payload || typeof payload !== "object") {
    return defaultMetadata;
  }

  const candidate = payload as Partial<PageMetadataCapture>;
  const title = typeof candidate.title === "string" ? candidate.title.trim() : "";
  const metaDescription =
    typeof candidate.meta_description === "string"
      ? candidate.meta_description.trim()
      : "";
  const headings = Array.isArray(candidate.headings)
    ? candidate.headings
        .filter((item): item is string => typeof item === "string")
        .map((item) => item.trim())
        .filter(Boolean)
        .slice(0, 12)
    : [];

  return {
    title,
    meta_description: metaDescription,
    headings,
  };
};

const captureSourceFromTab = async (
  tab: Tab,
  fallbackUrl: string,
  fallbackTitle: string,
  fallbackDomain: string
): Promise<SourceCapture | null> => {
  const [rawPageText, pageMetadata] = await Promise.all([
    tab.getTabText().catch(() => ""),
    extractPageMetadata(tab).catch(() => ({
      title: "",
      meta_description: "",
      headings: [],
    })),
  ]);

  let normalizedText = normalizeCapturedText(rawPageText || "");
  if (!normalizedText) {
    const rawHtml = await tab.getTabHtml().catch(() => "");
    normalizedText = extractTextFromHtml(rawHtml || "");
  }

  if (!normalizedText) {
    return null;
  }

  const textContent = normalizedText.slice(0, MAX_SOURCE_CONTENT_CHARS);
  const textTruncated = normalizedText.length > MAX_SOURCE_CONTENT_CHARS;

  const currentUrl = normalizeUrl(tab.url || fallbackUrl);
  let parsedUrl: URL;
  try {
    parsedUrl = new URL(currentUrl);
  } catch {
    return null;
  }

  const sourceTitle =
    pageMetadata.title.trim() || fallbackTitle.trim() || parsedUrl.hostname;
  const sourceDomain = parsedUrl.hostname || fallbackDomain || "unknown";

  return {
    title: sourceTitle,
    url: parsedUrl.toString(),
    domain: sourceDomain,
    meta_description: pageMetadata.meta_description || "",
    headings: pageMetadata.headings || [],
    text_content: textContent,
    text_truncated: textTruncated,
  };
};

export const runGoogleSearchAndCollect = async (
  browserWindow: Window,
  args: GoogleSearchAndCollectArgs
): Promise<BrowserToolResult> => {
  const query = args.query.trim();
  const purpose = args.purpose.trim();
  const visitedWebsites = new Map<string, string>(
    Object.entries(args.visited_websites ?? {})
      .filter(([rawUrl]) => rawUrl.trim().length > 0)
      .map(([rawUrl, rawTitle]) => [normalizeUrl(rawUrl), rawTitle.trim()])
  );

  if (!query) {
    return {
      content: JSON.stringify({
        status: "error",
        message: "google_search_and_collect requires a non-empty query.",
      }),
    };
  }

  const originalTabId = browserWindow.activeTab?.id ?? null;
  const researchTab = browserWindow.createTab(DUCKDUCKGO_HOME_URL);

  try {
    browserWindow.switchActiveTab(researchTab.id);
    await waitForSettledTab(researchTab);

    await showBrowserCursor(researchTab, {
      target: "search-bar",
      label: "Opening DuckDuckGo",
      sentence: "I am opening DuckDuckGo to start the web search.",
    });
    await delay(240);

    await showBrowserCursor(researchTab, {
      target: "search-bar",
      label: "Typing search query",
      sentence: "I am typing the search query into the browser.",
    });
    const didTypeQuery = await typeSearchQuery(researchTab, query);
    await delay(didTypeQuery ? 180 : 60);

    await showBrowserCursor(researchTab, {
      target: "search-bar",
      label: "Searching the web",
      sentence: "I am submitting the query and waiting for the search results.",
      click: true,
    });
    const searchUrl = buildDuckDuckGoSearchUrl(query);
    const searchNavigation = await navigateTabWithTimeout(researchTab, searchUrl);
    if (!searchNavigation.ok) {
      return {
        content: JSON.stringify({
          status: "error",
          tool_name: "google_search_and_collect",
          query,
          purpose,
          search_provider: "duckduckgo_dom_scrape",
          search_url: searchUrl,
          message: `Could not load DuckDuckGo search results: ${searchNavigation.message}`,
        }),
      };
    }

    const searchCookieAcceptance = await acceptCookiesIfPresent(researchTab);
    if (searchCookieAcceptance.clicked) {
      await showBrowserCursor(researchTab, {
        target: "results-list",
        label: "Accepting cookies",
        sentence:
          "I am accepting the cookie banner so I can read the search results cleanly.",
        click: true,
      });
      console.log(
        "[browser-research] cookies_accepted",
        JSON.stringify({
          phase: "search_results",
          query,
          clicked_text: searchCookieAcceptance.clicked_text,
          clicked_selector: searchCookieAcceptance.clicked_selector,
        })
      );
      await delay(260);
    }

    await showBrowserCursor(researchTab, {
      target: "results-list",
      label: "Reading search results",
      sentence:
        "I am reading the result list and skipping blocked, non-HTML, and already visited pages.",
    });

    const searchProvider: SearchProvider = "duckduckgo_dom_scrape";
    const searchResults = await runWithTimeout(
      collectDuckDuckGoResults(researchTab),
      SEARCH_RESULTS_EXTRACTION_TIMEOUT_MS,
      "Timed out while reading the search results list."
    );
    const candidateResults = searchResults.filter((result) => {
      const normalizedResultUrl = normalizeUrl(result.url);
      return (
        !isBlockedSearchResultHost(result.domain) &&
        !visitedWebsites.has(normalizedResultUrl) &&
        !isLikelyNonHtmlResult(normalizedResultUrl)
      );
    });

    if (!candidateResults.length) {
      return {
        content: JSON.stringify({
          status: "exhausted",
          purpose,
          query,
          search_provider: searchProvider,
          searched_with_duckduckgo: true,
          search_url: searchUrl,
          duckduckgo_search_url: searchUrl,
          message:
            "No eligible unvisited search result URL was available for this query in the current agent session.",
          visited_result_count: visitedWebsites.size,
        }),
      };
    }

    const candidatesToTry = candidateResults;
    const attemptedResultUrls: string[] = [];
    const failedCandidateNavigations: Array<{ url: string; reason: string }> = [];
    let lastVisitedWebsiteUrl = "";
    let lastVisitedWebsiteTitle = "";

    for (const selectedResult of candidatesToTry) {
      const selectedResultUrl = normalizeUrl(selectedResult.url);
      const shortDomain = selectedResult.domain.replace(/^www\./, "");

      await showBrowserCursor(researchTab, {
        target: "results-list",
        label: `Opening ${shortDomain}`,
        sentence: `I am opening ${shortDomain} to inspect the page content.`,
        click: true,
      });
      await delay(160);
      const candidateNavigation = await navigateTabWithTimeout(
        researchTab,
        selectedResultUrl
      );
      if (!candidateNavigation.ok) {
        attemptedResultUrls.push(selectedResultUrl);
        failedCandidateNavigations.push({
          url: selectedResultUrl,
          reason: candidateNavigation.message || "navigation failed",
        });
        console.log(
          "[browser-research] candidate_navigation_failed",
          JSON.stringify({
            query,
            url: selectedResultUrl,
            reason: candidateNavigation.message || "navigation failed",
            attempted_candidate_count: attemptedResultUrls.length,
          })
        );
        await showBrowserCursor(researchTab, {
          target: "results-list",
          label: "Trying next result",
          sentence:
            "This result could not be loaded reliably, so I am moving to the next candidate.",
        });
        continue;
      }

      const pageCookieAcceptance = await acceptCookiesIfPresent(researchTab);
      if (pageCookieAcceptance.clicked) {
        await showBrowserCursor(researchTab, {
          target: "page-content",
          label: "Accepting cookies",
          sentence:
            "I am accepting the page cookie banner before extracting the page content.",
          click: true,
        });
        console.log(
          "[browser-research] cookies_accepted",
          JSON.stringify({
            phase: "page_content",
            query,
            url: selectedResultUrl,
            clicked_text: pageCookieAcceptance.clicked_text,
            clicked_selector: pageCookieAcceptance.clicked_selector,
          })
        );
        await delay(280);
      }

      await showBrowserCursor(researchTab, {
        target: "page-content",
        label: `Reading ${shortDomain}`,
        sentence:
          "I am extracting the page text and metadata so the vector store can index this source.",
      });
      await delay(220);

      const sourceCapture = await runWithTimeout(
        captureSourceFromTab(
          researchTab,
          selectedResultUrl,
          selectedResult.title,
          selectedResult.domain
        ),
        SOURCE_CAPTURE_TIMEOUT_MS,
        "Timed out while extracting page text."
      ).catch((error: unknown) => {
        console.log(
          "[browser-research] source_capture_timeout_or_error",
          JSON.stringify({
            query,
            url: selectedResultUrl,
            reason:
              error instanceof Error
                ? error.message
                : String(error || "source capture failed"),
          })
        );
        return null;
      });
      const visitedWebsiteUrl = normalizeUrl(sourceCapture?.url || selectedResultUrl);
      const visitedWebsiteTitle =
        sourceCapture?.title?.trim() || selectedResult.title.trim() || visitedWebsiteUrl;
      const hasIngestableText = !!sourceCapture?.text_content?.trim();
      const sourceTextContent = sourceCapture?.text_content?.trim() || "";
      const normalizedSourceTextContent = sourceTextContent.slice(
        0,
        MAX_SOURCE_CONTENT_CHARS
      );
      const textWasTruncated =
        sourceCapture?.text_truncated === true ||
        sourceTextContent.length > MAX_SOURCE_CONTENT_CHARS;
      const visibleSources = hasIngestableText
        ? [
            {
              title: visitedWebsiteTitle,
              url: visitedWebsiteUrl,
              domain: sourceCapture?.domain || selectedResult.domain,
              meta_description: sourceCapture?.meta_description || "",
              headings: sourceCapture?.headings || [],
              text_content: normalizedSourceTextContent,
              text_truncated: textWasTruncated,
            },
          ]
        : [];

      attemptedResultUrls.push(selectedResultUrl);
      lastVisitedWebsiteUrl = visitedWebsiteUrl;
      lastVisitedWebsiteTitle = visitedWebsiteTitle;

      const inaccessiblePageReason = detectInaccessiblePageReason(
        visitedWebsiteUrl,
        visitedWebsiteTitle,
        sourceTextContent
      );
      if (inaccessiblePageReason) {
        failedCandidateNavigations.push({
          url: selectedResultUrl,
          reason: inaccessiblePageReason,
        });
        await showBrowserCursor(researchTab, {
          target: "results-list",
          label: "Trying next result",
          sentence:
            "This page appears inaccessible from the current session, so I am moving to the next candidate result.",
        });
        console.log(
          "[browser-research] candidate_inaccessible_page",
          JSON.stringify({
            query,
            url: selectedResultUrl,
            reason: inaccessiblePageReason,
            attempted_candidate_count: attemptedResultUrls.length,
          })
        );
        continue;
      }

      console.log(
        "[browser-research] capture_source_final",
        JSON.stringify({
          query,
          search_provider: searchProvider,
          selected_result_url: selectedResultUrl,
          visited_website_url: visitedWebsiteUrl,
          has_source_capture: !!sourceCapture,
          ingestable_text_length: sourceTextContent.length,
          normalized_ingestable_text_length: normalizedSourceTextContent.length,
          source_count: visibleSources.length,
        })
      );

      if (!hasIngestableText) {
        await showBrowserCursor(researchTab, {
          target: "results-list",
          label: "Trying next result",
          sentence:
            "This page did not expose usable text, so I am moving to the next candidate result.",
        });
        console.log(
          "[browser-research] candidate_without_ingestable_text",
          JSON.stringify({
            query,
            url: selectedResultUrl,
            attempted_candidate_count: attemptedResultUrls.length,
          })
        );
        continue;
      }

      console.log(
        "[browser-research] page_content_retrieved",
        JSON.stringify({
          query,
          search_provider: searchProvider,
          url: visitedWebsiteUrl,
          title: visitedWebsiteTitle,
          text_length: normalizedSourceTextContent.length,
          text_truncated: textWasTruncated,
        })
      );

      await showBrowserCursor(researchTab, {
        target: "page-content",
        label: "Source collected",
        sentence:
          "I have the page text and metadata. I am passing this source back for indexing in the vector store.",
      });

      const indexedSource = {
        title: visitedWebsiteTitle,
        url: visitedWebsiteUrl,
        domain: sourceCapture?.domain || selectedResult.domain,
        meta_description: sourceCapture?.meta_description || "",
        headings: sourceCapture?.headings || [],
        text_content: normalizedSourceTextContent,
        text_truncated: textWasTruncated,
        query,
        purpose,
      };

      return {
        content: JSON.stringify({
          status: "ok",
          purpose,
          query,
          search_provider: searchProvider,
          searched_with_duckduckgo: true,
          search_url: searchUrl,
          duckduckgo_search_url: searchUrl,
          source_count: visibleSources.length,
          selected_result_url: selectedResultUrl,
          selected_result_title: selectedResult.title,
          visited_website_url: visitedWebsiteUrl,
          visited_website_title: visitedWebsiteTitle,
          sources: visibleSources,
        }),
        metadata: { indexed_sources: [indexedSource] },
        visited_website: {
          url: visitedWebsiteUrl,
          title: visitedWebsiteTitle,
        },
      };
    }

    return {
      content: JSON.stringify({
        status: "no_ingestable_content",
        purpose,
        query,
        search_provider: searchProvider,
        searched_with_duckduckgo: true,
        search_url: searchUrl,
        duckduckgo_search_url: searchUrl,
        message:
          "Result pages were opened but TypeScript page scraping did not return ingestable page content.",
        attempted_result_count: attemptedResultUrls.length,
        attempted_result_urls: attemptedResultUrls,
        failed_candidate_navigations: failedCandidateNavigations,
        visited_website_url: lastVisitedWebsiteUrl,
        visited_website_title: lastVisitedWebsiteTitle,
        sources: [],
      }),
      visited_website: lastVisitedWebsiteUrl
        ? {
            url: lastVisitedWebsiteUrl,
            title: lastVisitedWebsiteTitle || lastVisitedWebsiteUrl,
          }
        : undefined,
    };
  } catch (error) {
    return {
      content: JSON.stringify({
        status: "error",
        query,
        purpose,
        message:
          error instanceof Error ? error.message : "DuckDuckGo research workflow failed.",
      }),
    };
  } finally {
    if (originalTabId) {
      browserWindow.switchActiveTab(originalTabId);
    }

    if (browserWindow.getTab(researchTab.id)) {
      browserWindow.closeTab(researchTab.id);
    }
  }
};
