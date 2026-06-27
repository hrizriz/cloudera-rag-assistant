# Cloudera LLM

RAG assistant for Cloudera documentation, powered by local vector search + [gemini-web2api](https://github.com/Sophomoresty/gemini-web2api).

## Architecture

```text
Cloudera docs -> scraper -> chunks -> ChromaDB
                                         |
User question --------------------> retrieve top-k
                                         |
                              gemini-web2api (OpenAI-compatible)
                                         |
                                    answer + sources
```

## Prerequisites

- Python 3.10+
- [gemini-web2api](https://github.com/Sophomoresty/gemini-web2api) running at `http://localhost:8081/v1`
- Network access to `docs.cloudera.com` for ingestion

## Quick Start

### 1. Setup project

```powershell
cd d:\personal_project\cloudera_llm
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env
```

### 2. Start gemini-web2api (separate terminal)

```powershell
git clone https://github.com/Sophomoresty/gemini-web2api.git
cd gemini-web2api
pip install httpx
python gemini_web2api.py
```

Server should listen on `http://localhost:8081/v1`.

If Gemini is blocked in your network, configure proxy in gemini-web2api `config.json`.

### 3. Ingest knowledge base

**Local SOP/MOP files** (your files in `data/` — docx, pdf, xlsx, zip):

```powershell
cloudera-ingest --source local
```

**Official Cloudera docs** (support matrix prioritized, version/service auto-detected):

```powershell
# Build catalog first (products, versions, services, matrix URLs)
.\.venv\Scripts\python.exe -m cloudera_llm.cli.catalog

# Scrape 50 pages — support matrix & compatibility pages fetched first
.\.venv\Scripts\python.exe -m cloudera_llm.cli.ingest --source web --max-pages 50
```

Or combine catalog + ingest:

```powershell
.\.venv\Scripts\python.exe -m cloudera_llm.cli.ingest --catalog --source web --max-pages 50
```

Catalog output: `data/catalog.json` — lists all 41 Cloudera products, detected versions, services (Impala, Hive, NiFi, etc.), and 44+ support matrix URLs.

**Both local + web** (recommended):

```powershell
cloudera-ingest --source all
```

Scraping is **resumable** — if interrupted, run the same command again; already-fetched URLs are skipped (`data/raw/crawl_state.json`).

Test run with a page limit first:

```powershell
cloudera-ingest --source web --max-pages 50
```

Full scrape (~50k+ pages) takes hours/days with polite delays. Use `resume: true` and run in batches.

To rebuild vectors from scratch:

```powershell
cloudera-ingest --source all --reset
```

### 4. Chat from CLI

```powershell
cloudera-chat "Apa perbedaan Impala dan Hive di Cloudera?"
```

### 5. Run API server

```powershell
cloudera-serve
```

Example request:

```powershell
curl.exe --% http://127.0.0.1:8000/chat -H "Content-Type: application/json" -d "{\"question\":\"How do I configure Ranger for Hive?\"}"
```

Health check:

```powershell
curl http://127.0.0.1:8000/health
```

### 6. Telegram Bot

1. Buat bot via [@BotFather](https://t.me/BotFather), salin token
2. Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHI...
TELEGRAM_ALLOWED_CHAT_IDS=-5457931851
```

3. Pastikan gemini-web2api & ingest sudah jalan, lalu start bot:

```powershell
.\.venv\Scripts\cloudera-telegram.exe
```

4. Di Telegram (grup/chat dengan ID `-5457931851`), kirim:
   - `/start`
   - `/health`
   - `Bagaimana cara restart Impala?` atau `/ask ...`

Bot hanya merespons chat ID yang ada di `TELEGRAM_ALLOWED_CHAT_IDS`.

## Configuration

Edit `config.yaml` or `.env`:

| Setting | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:8081/v1` | gemini-web2api endpoint |
| `LLM_MODEL` | `gemini-3.5-flash` | Model name |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local embedding model |
| `ingestion.mode` | `sitemap` | `sitemap`, `crawl`, or `both` |
| `ingestion.max_pages` | `0` | `0` = unlimited (use `--max-pages` to cap) |
| `ingestion.delay_seconds` | `2.5` | Base delay between requests |
| `ingestion.sitemap_include` | `[]` | Filter products, e.g. `runtime`, `data-warehouse` |
| `vectorstore.top_k` | `5` | Retrieved chunks per question |

### Anti-bot scraping strategy

The web scraper uses techniques that reduce bot-detection without aggressive evasion:

- Official **sitemap.xml** discovery (same source search engines use)
- **Browser-like headers** + User-Agent rotation
- **Random jitter delays** between requests (not fixed intervals)
- **Session warmup** (homepage visit for cookies)
- **Retry + backoff** on 429/503, long cooldown on rate-limit
- **Resume/checkpoint** — skip URLs already saved in `data/raw/`
- Optional **HTTP proxy** via `ingestion.proxy` in `config.yaml`

Example: scrape only Runtime + CDP Public Cloud docs:

```yaml
ingestion:
  sitemap_include:
    - "runtime/7.3.2"
    - "cdp-public-cloud"
  max_pages: 500
```

## Project Layout

```text
cloudera_llm/
├── config.yaml
├── src/cloudera_llm/
│   ├── ingestion/     # scrape + chunk Cloudera docs
│   ├── embeddings/    # sentence-transformers
│   ├── vectorstore/   # ChromaDB
│   ├── rag/           # retrieve + prompt
│   ├── llm/           # OpenAI client -> gemini-web2api
│   ├── api/           # FastAPI /chat endpoint
│   └── cli/           # ingest + chat commands
└── data/
    ├── *.docx / *.pdf / *.xlsx   # your internal SOP/MOP files
    ├── raw/                      # scraped pages + crawl state
    └── chroma/                   # vector database
```

## Notes

- First ingest downloads the embedding model (~90MB) and may take several minutes.
- gemini-web2api is unofficial and best for prototyping; use Google AI API for production.
- Answers are grounded in retrieved docs — quality depends on ingested pages.

## Troubleshooting

| Issue | Fix |
|---|---|
| `Vector store is empty` | Run `cloudera-ingest` |
| `gemini-web2api is not reachable` | Start gemini-web2api on port 8081 |
| Empty LLM response | Check proxy/network to `gemini.google.com` |
| Low answer quality | Add `sitemap_include` filters, ingest local SOPs, raise `top_k` |
| HTTP 429 / blocked | Increase `delay_seconds`, set `proxy`, run smaller batches with `--max-pages` |
| Legacy `.doc` files | Convert to `.docx` before ingest |
