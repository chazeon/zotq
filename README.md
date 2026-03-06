# zotq

`zotq` is a Python CLI for querying Zotero through HTTP backends with one consistent interface.

## Install Dependencies
Core install:

```bash
uv sync
```

Install development dependencies (both forms are supported):

```bash
uv sync --group dev
uv sync --extra dev
```

## Backends
- `local-api`: talks to the Zotero Desktop local API.
- `remote`: talks to a self-hosted or cloud API service.

## Configuration (TOML)
`zotq` uses a TOML config file.

Default path:

`~/.config/zotq/config.toml`

CLI flag:

`-c, --config PATH`

Example:

```bash
uv run zotq -c ~/.config/zotq/config.toml --mode local-api system health
```

Example:

```toml
active_profile = "default"

[profiles.default]
mode = "local-api"
output = "table"

[profiles.default.search]
default_mode = "keyword"
allow_fallback = false
alpha = 0.35
lexical_k = 100
vector_k = 100

[profiles.default.index]
enabled = true
index_dir = "~/.local/share/zotq/index"
embedding_provider = "local"
embedding_model = "local-hash-v1"
embedding_base_url = ""
embedding_api_key = ""
embedding_timeout_seconds = 30
embedding_max_retries = 2

[profiles.default.local_api]
base_url = "http://127.0.0.1:23119"
api_key = ""
timeout_seconds = 10

[profiles.default.remote]
base_url = "https://zotero.example.com/api"
bearer_token = ""
timeout_seconds = 15
verify_tls = true
```

Environment variable overrides are supported with the same precedence rule:

`CLI flags > env vars > TOML > defaults`

Useful vars:
- `ZOTQ_MODE`
- `ZOTQ_OUTPUT`
- `ZOTQ_INDEX_DIR`
- `ZOTQ_EMBEDDING_PROVIDER`
- `ZOTQ_EMBEDDING_MODEL`
- `ZOTQ_EMBEDDING_BASE_URL`
- `ZOTQ_EMBEDDING_API_KEY`
- `ZOTQ_EMBEDDING_TIMEOUT_SECONDS`
- `ZOTQ_EMBEDDING_MAX_RETRIES`
- `ZOTQ_LOCAL_API_BASE_URL`
- `ZOTQ_REMOTE_BASE_URL`
- `ZOTQ_REMOTE_BEARER_TOKEN`

## Enable Zotero Local API
To allow `zotq` to use Zotero's local API:

1. Open Zotero.
2. Go to `Settings -> Advanced`.
3. Check `Allow other applications on this computer to communicate with Zotero`.

This enables local HTTP access to Zotero from tools running on your computer.

## Quick Verification
Verify the Zotero local endpoint:

```bash
curl -sS "http://127.0.0.1:23119/api/users/0/items?limit=1"
```

If local API access is enabled and Zotero is running, this returns JSON.

Verify with `zotq`:

```bash
uv run zotq --mode local-api system health
```

Expected result: a successful health check with no connection/auth errors.

## CLI Command Grammar
`zotq` uses resource-verb commands:

```bash
zotq <resource> <verb> [options]
```

Examples:

```bash
uv run zotq search run "mantle hydration" --search-mode keyword --limit 5
uv run zotq index status
uv run zotq item get ABCD1234
```

`--output table` now renders rich terminal tables (search summary/hits and debug sections).

## Search Modes
- `keyword`: SQLite FTS5 lexical ranking.
- `fuzzy`: typo-tolerant lexical matching.
- `semantic`: local vector similarity search over indexed chunks.
- `hybrid`: weighted lexical + vector fusion (`--alpha`) using per-query score normalization.

`semantic` and `hybrid` require a ready local index (`index sync` or `index rebuild`).

## Indexing Workflow
Build or refresh index from the active backend:

```bash
uv run zotq --mode local-api index sync
uv run zotq --mode local-api index sync --full
uv run zotq --mode local-api index rebuild
```

In `--output table` mode, `index sync`/`index rebuild` now show rich progress with elapsed/remaining estimates when totals are available.
Use `--no-progress` to disable it.

`index sync` (without `--full`) is incremental and skips unchanged items to avoid unnecessary re-embedding.
`index sync --full` clears and rebuilds lexical/vector indexes from scratch.

Run semantic search:

```bash
uv run zotq --mode local-api --output json search run "mantle hydration" --search-mode semantic --limit 5
```

Run hybrid search:

```bash
uv run zotq --mode local-api --output json search run "mantle hydration" --search-mode hybrid --alpha 0.5 --limit 5
```

Hybrid responses include normalized and raw components in each hit:
- `hybrid`, `lexical`, `vector` (normalized fusion components)
- `lexical_raw`, `vector_raw` (pre-normalization signal values)

Add `--debug` to include a debug section with candidate limits, per-hit penalties, and score components:

```bash
uv run zotq --mode local-api --output json search run "mantle hydration" --search-mode hybrid --debug
```

## Embeddings
- `local`: deterministic hashing model, no extra dependencies.
- `openai`: REST-based embedding requests (`embedding_api_key` required).
- `ollama`: local Ollama API (`/api/embed`, with legacy `/api/embeddings` fallback).
- `gemini` (or `google`): Google Gemini embedding API (`embedding_api_key` required).

### Profile Examples
Example OpenAI profile:

```toml
[profiles.openai]
mode = "local-api"
output = "table"

[profiles.openai.index]
embedding_provider = "openai"
embedding_model = "text-embedding-3-small"
embedding_api_key = "sk-..."
embedding_base_url = "https://api.openai.com/v1"
embedding_timeout_seconds = 30
embedding_max_retries = 2
```

Example Ollama profile:

```toml
[profiles.ollama]
mode = "local-api"
output = "table"

[profiles.ollama.index]
embedding_provider = "ollama"
embedding_model = "nomic-embed-text"
embedding_base_url = "http://127.0.0.1:11434"
embedding_timeout_seconds = 30
embedding_max_retries = 2
```

Example Gemini profile:

```toml
[profiles.gemini]
mode = "local-api"
output = "table"

[profiles.gemini.index]
embedding_provider = "gemini"
embedding_model = "gemini-embedding-001"
embedding_api_key = "..."
embedding_base_url = "https://generativelanguage.googleapis.com/v1beta"
embedding_timeout_seconds = 30
embedding_max_retries = 2
```

### Apply And Use
After changing embedding provider/model, rebuild vectors:

```bash
uv run zotq -c ~/.config/zotq/config.toml --profile ollama index sync --full
```

Then query:

```bash
uv run zotq -c ~/.config/zotq/config.toml --profile ollama search run "global sesmology" --search-mode hybrid --debug
```

Ollama setup:

```bash
ollama serve
ollama pull nomic-embed-text
```

## Common Issues
- Zotero is not running.
- Local API checkbox is not enabled.
- `base_url` is not set to `http://127.0.0.1:23119`.
