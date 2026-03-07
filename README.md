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

Core runtime now includes:
- `sqlite-vec` Python bindings (vector backend cutover path).
- `bibtexparser` (parser-backed BibTeX parse/stringify path).

## Backends
- `local-api`: talks to the Zotero Desktop local API.
- `remote`: talks to a self-hosted or cloud API service.
- `snapshot`: reads from a local BibTeX snapshot file for offline source queries.

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
lexical_profile_version = 1
vector_profile_version = 1
vector_backend = "python" # or "sqlite-vec"
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

[profiles.default.snapshot]
bib_path = "~/exports/zotero-library.bib"
```

Environment variable overrides are supported with the same precedence rule:

`CLI flags > env vars > TOML > defaults`

Useful vars:
- `ZOTQ_MODE`
- `ZOTQ_OUTPUT`
- `ZOTQ_INDEX_DIR`
- `ZOTQ_LEXICAL_PROFILE_VERSION`
- `ZOTQ_VECTOR_PROFILE_VERSION`
- `ZOTQ_VECTOR_BACKEND`
- `ZOTQ_EMBEDDING_PROVIDER`
- `ZOTQ_EMBEDDING_MODEL`
- `ZOTQ_EMBEDDING_BASE_URL`
- `ZOTQ_EMBEDDING_API_KEY`
- `ZOTQ_EMBEDDING_TIMEOUT_SECONDS`
- `ZOTQ_EMBEDDING_MAX_RETRIES`
- `ZOTQ_LOCAL_API_BASE_URL`
- `ZOTQ_REMOTE_BASE_URL`
- `ZOTQ_REMOTE_BEARER_TOKEN`
- `ZOTQ_SNAPSHOT_BIB_PATH`

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
Search hit tables include `Journal` and `DOI` columns when available.
`--output bib` renders formatted CSL bibliography output from Zotero (`format=bib`, typically HTML-like snippets) and supports `--style`, `--locale`, and `--linkwrap`.
`--output bibtex` renders BibTeX entries (`format=bibtex`).
`--non-interactive` disables interactive recovery/fallback prompts for automation.
`--require-offline-ready` fails semantic/hybrid queries early when preflight is not offline-ready.

## Search Modes
- `keyword`: SQLite FTS5 lexical ranking over a field-aware projection (`title`, `abstract`, `journal`, `creators`, `tags`, `body`).
- `fuzzy`: typo-tolerant lexical matching.
- `semantic`: local vector similarity search over indexed chunks.
- `hybrid`: weighted lexical + vector fusion (`--alpha`) using per-query score normalization.

`semantic` and `hybrid` require a ready local index (`index sync` or `index rebuild`).
When the active embedding provider is remote-dependent (for example `openai`), index semantic/hybrid capability is guarded off for offline-safe runs; enable `--allow-fallback` to downgrade to keyword mode.

## Indexing Workflow
Build or refresh index from the active backend:

```bash
uv run zotq --mode local-api index sync
uv run zotq --mode local-api index sync --full
uv run zotq --mode local-api index sync --profiles-only
uv run zotq --mode local-api index rebuild
uv run zotq --mode local-api index enrich
uv run zotq --mode local-api index enrich --field all
uv run zotq --mode local-api index inspect --sample-limit 5
```

In `--output table` mode, `index sync`/`index rebuild` now show rich progress with elapsed/remaining estimates when totals are available.
Use `--no-progress` to disable it.

`index sync` (without `--full`) is incremental with split hashes:
- lexical hash controls document/FTS refresh.
- vector hash controls chunk re-embedding.
- metadata-only changes (for example DOI/journal/citation key) update lexical metadata without forcing vector re-embedding.
`index sync --profiles-only` is an explicit migration/remediation pass that fetches and reprocesses only items whose stored lexical/vector profile versions mismatch current config targets.
It cannot be combined with `--full`.
Interrupted syncs now persist per-item ingest checkpoints and resume on the next run (including `--full`) without restarting from item zero.
Source collection progress is checkpointed with paging mode + token (`next_offset` for offset mode, `next_cursor` for watermark mode) plus collected item keys, so retries can resume collection before ingest.
When an adapter exposes watermark/cursor paging, `zotq` uses that checkpoint path automatically.
`index sync --full` clears and rebuilds lexical/vector indexes from scratch.
`index enrich` updates metadata in place without rebuilding vectors.
- `--field citation-key` (default): BBT RPC/BibTeX fallback enrichment.
- `--field doi|journal`: patch missing values from source metadata pages.
- `--field all`: run all enrichers in one pass.
`index inspect` reports structured-field coverage from the registry-backed store (including DOI, citation key, journal, ISSN, volume, pages, language, and journal abbreviation) with sample item keys.
It also reports lexical/vector profile-version mismatch counts and sample mismatched item keys against the configured `lexical_profile_version` and `vector_profile_version` targets.
For vector backend cutovers, `index inspect` includes `vector_backend` and `vector_migration` summary fields (legacy rows detected/migrated).
`index status` includes a `preflight` block for agentic runs with `offline_ready`, `requires_network_for_query`, `embedding_provider_local`, `vector_backend`, and `degraded_capabilities`.
`index status` also includes an `agentic` block with `non_interactive` and `require_offline_ready` runtime flags.
For `--output json`/`--output jsonl`, CLI failures use a deterministic envelope:

```json
{
  "ok": false,
  "error": {
    "code": "mode_not_supported",
    "message": "...",
    "details": {}
  }
}
```

### Migration Status
- Current status: migration cutover complete; runtime is `items`-only.
- Already cut over:
  - Field-aware lexical projection (`lexical_docs`, `lexical_fts`).
  - Structured metadata tables (`item_fields`, `identifiers`, `item_creators`).
  - Canonical `items` table used for ingest, item reads, and sync/profile hash state.
  - Safe query-path cutover to `items` for index search/filter execution (`keyword`, `fuzzy`, filter-only, structured prefilter lookup).
  - Legacy `documents` runtime dual-write/fallback paths removed; legacy `documents` tables are dropped on open when present.
  - Split hash incremental sync and resume checkpoints.
  - `index inspect` profile-version mismatch reporting.
  - Explicit profile mismatch remediation via `index sync --profiles-only`.
  - `collection export` command surface and source-backed pagination/batching flow.
- Compatibility note:
  - Legacy document-schema importer is retired.
  - Pre-cutover index files that only contain legacy `documents` rows must be rebuilt (`zotq index rebuild`).

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

Field-aware filters:

```bash
uv run zotq --mode local-api --output json search run \
  --doi "doi:10.1016/j.pepi.2018.10.006" \
  --journal "Physics of the Earth and Planetary Interiors" \
  --citation-key "staceyThermodynamicsGruneisenParameter2019"
```

`--bibkey` and `--citekey` are aliases for `--citation-key`.
Use `--no-attachments` to exclude `item_type=attachment` rows from search results.
Use `--attachments` to keep attachment rows in the result set.

Search backend selection:

```bash
uv run zotq --mode local-api --output json search run "mantle hydration" --backend auto
uv run zotq --mode local-api --output json search run "mantle hydration" --backend source
uv run zotq --mode local-api --output json search run "mantle hydration" --backend index
```

Snapshot mode example:

```bash
uv run zotq --mode snapshot search run "mantle hydration" --search-mode keyword --limit 5
```

Notes:
- If `--doi` or `--citation-key` is provided, `zotq` first runs an exact identifier lookup in `keyword` mode on the selected backend route (`auto|source|index`). If no exact hit is found, it falls back to the requested search mode.
- DOI matching is normalized (`doi:`, `http(s)://doi.org/`, case, surrounding whitespace).
- Citation-key matching is case-insensitive and also supports keys stored in `extra` as `Citation Key: ...`.
- Local index search stores structured DOI/citation-key/journal metadata in normalized SQLite tables (`item_fields`, `identifiers`) with indexed lookups and `items`-first canonical metadata.
- During `index sync`/`index rebuild`, missing citation keys are enriched (batch Better BibTeX RPC first, then batch BibTeX parse fallback when available).

Resolve citation key:

```bash
uv run zotq --mode local-api item citekey XVMVWQZX
uv run zotq --mode local-api item citekey XVMVWQZX --prefer auto
uv run zotq --mode local-api item citekey XVMVWQZX --prefer rpc
uv run zotq --mode local-api item citekey XVMVWQZX --prefer bibtex
```

`--prefer` controls citation-key resolution source:
- `auto`: try `item.citationKey`, then `extra` (`Citation Key: ...`), then Better BibTeX RPC, then BibTeX parse fallback.
- `json|extra|rpc|bibtex`: force a single source with no fallback.
- BibTeX citation-key extraction uses a parser-first path (with compatibility fallback for malformed/minimal BibTeX stubs).

Better BibTeX RPC requires the Better BibTeX plugin in Zotero and uses:
- `POST http://127.0.0.1:23119/better-bibtex/json-rpc`
- method: `item.citationkey`

Multi-key item reads (repeat `--key`):

```bash
uv run zotq --mode local-api --output json item get --key XVMVWQZX --key MI26RYRR
uv run zotq --mode local-api --output json item citekey --key XVMVWQZX --key MI26RYRR --prefer auto
uv run zotq --mode local-api --output jsonl item get --key XVMVWQZX --key MISSING
```

For multi-key commands:
- `--output json` returns an envelope with `command`, `transport`, and ordered `results`.
- `transport.batch_used`/`transport.fallback_loop` report batch vs single-call retrieval path.
- `--output jsonl` emits one per-key result object per line.

Bibliography output:

```bash
uv run zotq --mode local-api --output bib item get XVMVWQZX --style apa --locale en-US --linkwrap
uv run zotq --mode local-api --output bib search run "mantle hydration" --limit 5 --style apa
uv run zotq --mode local-api --output bibtex item get XVMVWQZX
uv run zotq --mode local-api --output bibtex search run "mantle hydration" --limit 5
uv run zotq --mode local-api --output bibtex collection export C1 --format bibtex
uv run zotq --mode local-api --output bibtex collection export C1 --format bibtex --include-children --batch-size 200
```

`collection export` is source-backed (not index-backed) and paginates through collection items before batched BibTeX fetches.
`--output bibtex` is required for this command.
When multiple BibTeX chunks are rendered together (for example multi-key reads), output is canonicalized with deterministic entry ordering/formatting.

## Embeddings
- `local`: deterministic hashing model, no extra dependencies.
- `fastembed` / `portable` / `local-portable`: portable local embedding path with explicit fallback to local hashing when `fastembed` is unavailable.
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
