

## Blueberry Browser
[Tutorial News Research](./resources/Tutorial_News_Research.mp4)


The above video tutorials show two main blueberry use cases:

### (Strawberry) Competitor Analysis 
It shows how bluebarry can autonomously conduct market competitor analysis and create multiple files using the retrieved informaiton. Specifically, it shows transparently end to end the creation of pdf with structured comparison on strongest and weakest points, and a xlsx file comparing the features of the different products

###  News Research 
It shows how blueberry can autonomously plan, reason and research critically the latest web news from different sources. Especially, it shows how it can explore the files in the sandbox folder (blueberry), in this case, it finds an already exisiting relevant file to the request, it converts the .docx file into a .pdf file format and update the file content with the latest news as user requested




   


## 🚀 Project Setup

### Install
```bash
$ pnpm install
```

### Development
```bash
$ pnpm dev
```

### Python Agent + Chroma Setup
Blueberry now includes a project-local Chroma setup for future vector-search work.

Create the local Python environment, install the Python agent dependencies, and bootstrap a persistent Chroma database in `data/chroma`:

```bash
$ npm run setup:chroma
```

Run a smoke test against the local Chroma store:

```bash
$ npm run chroma:smoke-test
```

The Electron app will automatically prefer `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on Unix-like systems when launching the Python agent. You can override that with `BLUEBERRY_AGENT_PYTHON`. Document drafting defaults to the main agent model, but you can optionally override the dedicated writer with `BLUEBERRY_AGENT_WRITER_MODEL`.

**Add a Gemini API key to `.env`** in the root folder.

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
LLM_MODEL=gemini-3.1-pro-preview
BLUEBERRY_AGENT_WRITER_MODEL=
# Web search uses DuckDuckGo page scraping from the in-app browser.
# No external search API key is required.
# Compatibility alias is also accepted: BLUEBERRY_AGENT_DESKTOP_FOLDER
BLUEBARRY_AGENT_DESKTOP_FOLDER=BLUEBARRY
BLUEBERRY_CHROMA_PATH=data/chroma
BLUEBERRY_CHROMA_DEFAULT_COLLECTION=blueberry_default
BLUEBERRY_CHROMA_EMBEDDING_MODEL=gemini-embedding-001
BLUEBERRY_AGENT_PYTHON=
# Optional inactivity timeout. Default is 600000 (10 minutes).
BLUEBERRY_AGENT_RUN_TIMEOUT_MS=
```

Strawberry will reimburse LLM costs, so go crazy! *(Please not more than a few hundred dollars though!)*
