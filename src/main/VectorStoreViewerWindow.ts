import { app, BrowserWindow } from "electron";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import type {
  ChromaChunkDumpEntry,
  ChromaCollectionDump,
  ChromaStoreDumpResult,
} from "./DesktopAgent";

let vectorStoreViewerWindow: BrowserWindow | null = null;

const escapeHtml = (value: string): string =>
  value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

const stringifyValue = (value: unknown): string => {
  if (value === null || value === undefined) {
    return "null";
  }

  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

const getChunkIndexBadge = (chunk: ChromaChunkDumpEntry): string => {
  const rawChunkIndex = chunk.metadata?.chunk_index;
  if (typeof rawChunkIndex !== "number") {
    return "";
  }

  return `<span class="chip chip-accent">chunk_index ${rawChunkIndex}</span>`;
};

const buildMetadataRows = (chunk: ChromaChunkDumpEntry): string => {
  const metadataEntries = Object.entries(chunk.metadata ?? {});
  if (metadataEntries.length === 0) {
    return '<div class="meta-empty">No metadata</div>';
  }

  return metadataEntries
    .map(
      ([key, value]) => `
        <div class="meta-row">
          <div class="meta-key">${escapeHtml(key)}</div>
          <div class="meta-value">${escapeHtml(stringifyValue(value))}</div>
        </div>
      `
    )
    .join("");
};

const buildChunkCard = (
  collection: ChromaCollectionDump,
  chunk: ChromaChunkDumpEntry,
  visualIndex: number
): string => `
  <article class="chunk-card">
    <header class="chunk-header">
      <div>
        <div class="chunk-label">Chunk Box ${visualIndex}</div>
        <div class="chunk-id">${escapeHtml(chunk.id)}</div>
      </div>
      <div class="chip-row">
        <span class="chip">${escapeHtml(collection.name)}</span>
        ${getChunkIndexBadge(chunk)}
        <span class="chip">dims ${chunk.embedding_dimensions}</span>
      </div>
    </header>

    <section class="chunk-section">
      <h3>Document</h3>
      <pre class="chunk-document">${escapeHtml(
        chunk.document || "(empty chunk document)"
      )}</pre>
    </section>

    <section class="chunk-section">
      <h3>Metadata</h3>
      <div class="meta-grid">
        ${buildMetadataRows(chunk)}
      </div>
    </section>
  </article>
`;

const buildCollectionSection = (collection: ChromaCollectionDump): string => `
  <section class="collection-section">
    <div class="collection-header">
      <div class="collection-title">${escapeHtml(collection.name)}</div>
      <div class="collection-count">${collection.chunk_count} chunks</div>
    </div>
    <div class="chunk-grid">
      ${collection.chunks
        .map((chunk, index) => buildChunkCard(collection, chunk, index + 1))
        .join("")}
    </div>
  </section>
`;

const buildWindowHtml = (dump: ChromaStoreDumpResult): string => {
  const collectionHtml =
    dump.collections.length > 0
      ? dump.collections.map((collection) => buildCollectionSection(collection)).join("")
      : '<div class="empty-state">Vector store is empty. Index some web content first.</div>';

  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Vector Store Chunk Viewer</title>
    <style>
      :root {
        color-scheme: light;
      }
      * {
        box-sizing: border-box;
      }
      body {
        margin: 0;
        font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
        background: radial-gradient(circle at top right, #f0f9ff 0%, #f8fafc 32%, #ffffff 100%);
        color: #0f172a;
      }
      .container {
        width: min(1200px, 96vw);
        margin: 24px auto 40px;
      }
      .hero {
        border: 1px solid #dbeafe;
        border-radius: 20px;
        padding: 18px 20px;
        background: linear-gradient(120deg, #ecfeff, #eff6ff 60%, #f8fafc);
        box-shadow: 0 12px 35px rgba(15, 23, 42, 0.08);
      }
      .hero h1 {
        margin: 0;
        font-size: 20px;
      }
      .hero p {
        margin: 6px 0 0;
        color: #475569;
        font-size: 13px;
      }
      .stats {
        margin-top: 14px;
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        gap: 10px;
      }
      .stat {
        border: 1px solid #dbeafe;
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.95);
        padding: 10px 12px;
      }
      .stat-label {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #64748b;
      }
      .stat-value {
        margin-top: 5px;
        font-weight: 600;
        font-size: 14px;
        color: #0f172a;
      }
      .collection-section {
        margin-top: 18px;
      }
      .collection-header {
        margin-bottom: 10px;
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }
      .collection-title {
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #475569;
      }
      .collection-count {
        border: 1px solid #cbd5e1;
        border-radius: 999px;
        padding: 4px 9px;
        font-size: 11px;
        color: #334155;
        background: #fff;
      }
      .chunk-grid {
        display: grid;
        gap: 12px;
      }
      .chunk-card {
        border: 1px solid #dbeafe;
        border-radius: 16px;
        padding: 14px;
        background: linear-gradient(180deg, #ffffff, #f8fafc);
        box-shadow: 0 10px 25px rgba(15, 23, 42, 0.06);
      }
      .chunk-header {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
      }
      .chunk-label {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.14em;
        color: #64748b;
      }
      .chunk-id {
        margin-top: 3px;
        font-size: 13px;
        font-weight: 700;
        color: #0f172a;
      }
      .chip-row {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }
      .chip {
        border: 1px solid #d1d5db;
        border-radius: 999px;
        padding: 3px 8px;
        font-size: 11px;
        color: #475569;
        background: #ffffff;
      }
      .chip-accent {
        border-color: #67e8f9;
        background: #ecfeff;
        color: #155e75;
      }
      .chunk-section {
        margin-top: 12px;
      }
      .chunk-section h3 {
        margin: 0 0 6px;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: #64748b;
      }
      .chunk-document {
        margin: 0;
        border: 1px solid #dbeafe;
        border-radius: 12px;
        background: #f8fafc;
        padding: 10px;
        white-space: pre-wrap;
        word-break: break-word;
        font-size: 12px;
        line-height: 1.45;
        color: #0f172a;
        max-height: 240px;
        overflow: auto;
      }
      .meta-grid {
        display: grid;
        gap: 7px;
      }
      .meta-row {
        border: 1px solid #dbeafe;
        border-radius: 10px;
        background: #ffffff;
        padding: 8px 10px;
      }
      .meta-key {
        font-size: 11px;
        font-weight: 700;
        color: #0f172a;
      }
      .meta-value {
        margin-top: 2px;
        font-size: 12px;
        color: #334155;
        word-break: break-word;
        white-space: pre-wrap;
      }
      .meta-empty, .empty-state {
        border: 1px dashed #cbd5e1;
        border-radius: 12px;
        padding: 14px;
        background: #f8fafc;
        color: #64748b;
        font-size: 13px;
      }
      .empty-state {
        margin-top: 16px;
      }
    </style>
  </head>
  <body>
    <main class="container">
      <section class="hero">
        <h1>Vector Store Chunk Viewer</h1>
        <p>Separate window with one box per chunk. Embedding graphs removed.</p>
        <div class="stats">
          <div class="stat">
            <div class="stat-label">Collections</div>
            <div class="stat-value">${dump.collection_count}</div>
          </div>
          <div class="stat">
            <div class="stat-label">Total Chunks</div>
            <div class="stat-value">${dump.total_chunks}</div>
          </div>
          <div class="stat">
            <div class="stat-label">Default Collection</div>
            <div class="stat-value">${escapeHtml(dump.default_collection)}</div>
          </div>
          <div class="stat">
            <div class="stat-label">Store Path</div>
            <div class="stat-value">${escapeHtml(dump.path)}</div>
          </div>
        </div>
      </section>
      ${collectionHtml}
    </main>
  </body>
</html>`;
};

export const openVectorStoreViewerWindow = (dump: ChromaStoreDumpResult): void => {
  if (vectorStoreViewerWindow && !vectorStoreViewerWindow.isDestroyed()) {
    if (vectorStoreViewerWindow.isMinimized()) {
      vectorStoreViewerWindow.restore();
    }
    vectorStoreViewerWindow.show();
    vectorStoreViewerWindow.focus();
  } else {
    vectorStoreViewerWindow = new BrowserWindow({
      width: 1220,
      height: 860,
      minWidth: 900,
      minHeight: 640,
      show: false,
      autoHideMenuBar: true,
      title: "Vector Store Chunks",
      backgroundColor: "#f8fafc",
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true,
      },
    });

    vectorStoreViewerWindow.once("ready-to-show", () => {
      vectorStoreViewerWindow?.show();
      vectorStoreViewerWindow?.focus();
    });

    vectorStoreViewerWindow.on("closed", () => {
      vectorStoreViewerWindow = null;
    });
  }

  const html = buildWindowHtml(dump);
  const htmlPath = join(app.getPath("temp"), "blueberry-vector-store-viewer.html");
  writeFileSync(htmlPath, html, "utf-8");
  void vectorStoreViewerWindow.loadFile(htmlPath);
};

