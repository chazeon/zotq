# zotq Design

## 1. Goal
Build a Python CLI tool (`zotq`) that provides one stable query interface over Zotero content, including:

1. Metadata/item retrieval from Zotero-compatible sources.
2. Local indexing pipeline for full-text, fuzzy, and semantic search.
3. Deterministic CLI behavior across local and remote modes.

Tech constraints:
- CLI framework: `click`
- Packaging/runtime: `pyproject.toml` + `uv`
- Models/config validation: `pydantic`
- Config format: TOML

## 2. Design Principles
- One CLI, many adapters: source differences hidden behind interfaces.
- Pipeline-first architecture: ingestion/indexing/query are explicit stages.
- Safe defaults: never read live `zotero.sqlite` directly.
- Structured output first: JSON output is stable and machine-oriented.
- Explicit capability checks: unsupported features fail clearly or fallback explicitly.
- Incremental by default: sync/index operations should be resumable and cheap.
- Agentic-first operability: non-interactive execution, deterministic errors, and predictable capability gating.

## 3. Scope
### In scope (v1)
- Read/query operations and index lifecycle commands.
- Search modes:
  - `keyword`
  - `fuzzy`
  - `semantic`
  - `hybrid`
- Commands:
  - `system health`
  - `search run`
  - `item get`
  - `item citekey`
  - `collection list`
  - `tag list`
- `index status`
- `index inspect`
- `index sync`
- `index rebuild`
- `index enrich`
- Metadata-first indexing and chunking (attachment extraction remains extensible roadmap work).
- Local index storage for lexical + vector retrieval.
- Config precedence: CLI > env vars > TOML > defaults.

### Out of scope (v1)
- Write/update/delete Zotero library items.
- Organize/insert operations (move items, assign/remove collection membership, create items).
- Sync engine replacement for Zotero itself.
- Distributed serving, multi-node indexing, or HA.
- Direct querying of live Zotero SQLite DB.
- MCP server/client integration (reserved for future phase).

## 4. End-to-End Architecture

```text
Click CLI
  -> ConfigLoader (TOML + env + CLI overrides)
    -> AppConfig (Pydantic)
      -> ZotQueryClient
        -> SourceAdapter (metadata + attachments)
        -> ContentPipeline (extract -> normalize -> chunk)
        -> EmbeddingProvider (local hash model in v1)
        -> IndexService (lexical + vector)
        -> QueryEngine (keyword/fuzzy/semantic/hybrid + fallback)
```

### 4.1 Core Objects
- `ConfigLoader`
  - Resolves precedence and returns validated `AppConfig`.
- `ZotQueryClient`
  - Main object instantiated by CLI handlers.
  - Exposes high-level operations: `health`, `search`, `index_status`, `index_sync`, `index_rebuild`, resource listing/get.
- `SourceAdapter` (Protocol/ABC)
  - Reads items/collections/tags and attachment references from source.
- `ContentPipeline`
  - Uses metadata-first text extraction in v1; attachment extractors remain pluggable roadmap work.
  - Produces normalized chunks with metadata.
- `IndexService`
  - Writes/updates lexical and vector indexes.
  - Provides index status and lifecycle operations.
- `EmbeddingProvider`
  - Deterministic text-to-vector abstraction.
  - Providers: `local`, `openai`, `ollama`, `gemini`.
- `QueryEngine`
  - Executes requested search mode using index capabilities.
  - Applies fallback policy and score fusion.

### 4.2 Source Adapters
- `LocalApiSourceAdapter`
  - Uses Zotero local HTTP API.
- `RemoteApiSourceAdapter`
  - Uses remote/self-hosted HTTP API.
- Optional `SnapshotSourceAdapter` (future)
  - Reads from exported snapshots or safe copies.
  - First practical target is collaborator-provided `.bib`/BibTeX ingestion for offline access.
  - JSON snapshot support remains preferred for full-fidelity metadata where available.
  - Must not touch live `zotero.sqlite`.

### 4.3 Object Lifecycle Per CLI Invocation
1. Parse CLI options.
2. Resolve config into `AppConfig`.
3. Construct `ZotQueryClient(config, profile=...)`.
4. Client builds source adapter + index/query services.
5. Execute one command.
6. Close HTTP/index resources before exit.

## 5. Search and Index Design

### 5.1 Current v1 Behavior
- Local lexical index: SQLite + FTS5 with field-aware projection (`lexical_docs`, `lexical_fts`) plus chunk tables (`chunks`, `chunks_fts`).
- Structured metadata is stored in normalized lookup tables:
  - Field/identifier lookups (`item_fields`, `identifiers`) with indexed SQL filtering.
  - Registry-driven fields currently include `doi`, `citation_key`, `journal`, `journal_abbreviation`, `issn`, `volume`, `pages`, `language`.
  - Creator rows are stored in `item_creators` for normalized author metadata.
- Local vector index: SQLite table of chunk embeddings.
- Search modes:
  - `keyword`: FTS5/BM25-derived score.
  - `fuzzy`: `SequenceMatcher` over title + indexed text.
  - `semantic`: vector similarity.
  - `hybrid`: normalized lexical/vector fusion with `alpha`.
- Query routing:
  - `--backend auto`: prefer local index when that executed mode is available.
  - `--backend source`: force source API search path.
  - `--backend index`: force local index search path.
- Incremental sync default:
  - `index sync` updates changed items with split hash checks:
    - lexical hash for metadata/FTS updates.
    - vector hash for semantic embedding refresh.
    - lexical/vector profile versions can force targeted reprocessing when mappings/chunk policy changes.
  - `index sync --profiles-only` reprocesses only items with lexical/vector profile-version mismatches.
  - Source collection checkpoints (`scope`, `full`, `paging_mode`, paging token, `collected_keys`) enable resume before ingest.
  - Offset paging remains the baseline; adapters can opt into watermark/cursor checkpoint paging (`next_cursor`) for higher-fidelity resume.
  - Per-item ingest checkpoints (`mode`, `done`, `total`, `remaining_keys`) enable interruption-safe resume on next `index sync`.
  - `index sync --full` and `index rebuild` force full reprocessing.
- Text extraction in v1 is metadata-first (title/abstract/creators/tags/date/type); attachment extraction remains pluggable roadmap work.
- DOI filtering is normalized (`doi:`, `http(s)://doi.org/`, case/whitespace).
- Citation-key filtering is case-insensitive and also uses `extra` fallback parsing (`Citation Key: ...`) when `citationKey` is absent.
- Search result attachment visibility can be controlled with `--attachments/--no-attachments` (attachments included by default; `--no-attachments` excludes `item_type=attachment` unless explicitly requested via `--item-type attachment`).
- Sync-time citation key enrichment is best-effort: batch Better BibTeX RPC lookup first, then batch BibTeX parse fallback.

### 5.2 v2 Goals
- Add fields over time (for example DOI, journal, publisher) without expensive full rebuilds.
- Support exact identifier lookup (DOI first) separate from lexical/semantic scoring.
- Keep lexical updates cheap and frequent.
- Re-embed vectors only when semantic source text changes.
- Maintain resumable indexing behavior after interruption.

### 5.2.1 Migration Status (Current)
- Migration cutover is complete; runtime is `items`-only.
- Completed in code:
  - Field-aware lexical projection (`lexical_docs`, `lexical_fts`).
  - Normalized metadata/identifier/creator tables (`item_fields`, `identifiers`, `item_creators`).
  - `items` canonical table for ingest/read/hash/profile paths.
  - Safe query-path cutover to `items` for index search/filter execution (`keyword`, `fuzzy`, filter-only, structured prefilter key lookup).
  - Legacy `documents` runtime dual-write/fallback paths removed; legacy `documents` tables are dropped on open when detected.
  - Split lexical/vector hash incremental sync with resumable source + ingest checkpoints.
  - Optional watermark/cursor collect checkpoint flow (`paging_mode=watermark`) for adapters that provide paging tokens.
  - `index inspect` profile-version mismatch reporting against configured lexical/vector targets.
  - Explicit profile migration workflow via `index sync --profiles-only`.
  - `collection export` command path (source-backed pagination + batched BibTeX export).
- Compatibility note:
  - Legacy document-schema importer has been retired.
  - Pre-cutover index files that only contain legacy `documents` rows must be rebuilt (`zotq index rebuild`).

### 5.3 Layered Index Architecture (v2)
Separate metadata, lexical, and vector concerns:

1. `MetadataStore` (SQLite)
   - Canonical item row.
   - Flexible per-field rows.
   - Creator rows.
   - Identifier lookup rows.
2. `LexicalStore` (SQLite FTS5)
   - Field-aware columns (`title`, `abstract`, `journal`, `creators`, `tags`, `body`) instead of one `full_text` blob.
3. `VectorStore` (SQLite)
   - Chunk rows + embeddings.
4. `CheckpointStore`
   - Sync watermark and resumable progress.

### 5.4 Logical Schema (v2)
```sql
CREATE TABLE items (
  item_key TEXT PRIMARY KEY,
  item_type TEXT,
  title TEXT,
  date TEXT,
  doi_norm TEXT,
  raw_json TEXT NOT NULL,
  lexical_hash TEXT NOT NULL,
  vector_hash TEXT NOT NULL,
  lexical_profile_version INTEGER NOT NULL,
  vector_profile_version INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE item_fields (
  item_key TEXT NOT NULL,
  field_name TEXT NOT NULL,
  ordinal INTEGER NOT NULL DEFAULT 0,
  value_raw TEXT,
  value_norm TEXT,
  value_hash TEXT NOT NULL,
  PRIMARY KEY (item_key, field_name, ordinal)
);

CREATE TABLE item_creators (
  item_key TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  creator_type TEXT,
  family TEXT,
  given TEXT,
  full_norm TEXT,
  key_norm TEXT,
  PRIMARY KEY (item_key, ordinal)
);

CREATE TABLE identifiers (
  id_type TEXT NOT NULL,
  id_norm TEXT NOT NULL,
  item_key TEXT NOT NULL,
  PRIMARY KEY (id_type, id_norm, item_key)
);

CREATE TABLE lexical_docs (
  item_key TEXT PRIMARY KEY,
  title TEXT,
  abstract TEXT,
  journal TEXT,
  creators TEXT,
  tags TEXT,
  body TEXT
);

CREATE VIRTUAL TABLE lexical_fts USING fts5(
  item_key UNINDEXED,
  title, abstract, journal, creators, tags, body,
  tokenize='unicode61 remove_diacritics 2'
);
```

### 5.5 Hash and Version Strategy
- `lexical_hash`
  - Derived from fields used by metadata + FTS projection.
  - Changes trigger only metadata/lexical updates.
- `vector_hash`
  - Derived from semantic text inputs and embedding profile (`provider`, `model`, dimensions).
  - Changes trigger rechunk/re-embed.
- `lexical_profile_version` and `vector_profile_version`
  - Allow explicit rollout of new field mappings or chunking policy.
  - Only rows with hash/version mismatch are reprocessed.

### 5.6 Ingestion and Sync Lifecycle (v2)
1. Fetch candidate items from source.
2. Normalize core metadata, identifiers (DOI), and creators.
3. Compute lexical and vector hashes.
4. If lexical changed: upsert `items`, `item_fields`, `item_creators`, `identifiers`, `lexical_docs`, FTS rows.
5. If vector changed: regenerate chunks and embeddings only for changed items.
6. Commit in bounded batches and checkpoint progress.
7. Resume safely after interruption.

### 5.7 Query Pipeline (v2)
1. Identifier short-circuit:
   - If `--doi` and/or `--citation-key` is provided, run an exact identifier lookup first.
   - Execute that lookup in `keyword` mode on the routed backend (`auto|source|index`).
   - If exact hits exist, return immediately; if none, continue to normal mode pipeline.
2. Structured filtering:
   - Apply `item_type`, date range, creator/tag/field filters from normalized tables.
   - Implemented filters include `title`, `doi`, `journal`, `citation_key`, `creators`, `tags`, `item_type`, and year bounds.
3. Retrieval mode execution:
   - `keyword`: FTS5 BM25 with column-aware weighting.
   - `fuzzy`: typo-tolerant lexical matching.
   - `semantic`: vector similarity over chunk embeddings.
   - `hybrid`: normalized lexical + vector score fusion.
4. Backend routing:
   - `auto` chooses index when the executed mode is available in index capabilities; otherwise source API.
   - `source` and `index` are explicit forced routes.
5. Output includes `requested_mode` and `executed_mode`.

### 5.8 Author Encoding
- Store creators in normalized rows (`family`, `given`, `full_norm`, `key_norm`, `ordinal`).
- Build FTS `creators` text projection using display and normalized variants.
- Ranking may apply small boosts for first-author exact/family matches.

### 5.9 Fallback and Capability Rules
- Backends/index services expose capabilities.
- If mode unsupported:
  - `--no-allow-fallback`: return `mode_not_supported` error.
  - `--allow-fallback`: downgrade to `keyword`.
- With `--backend index`, unsupported index modes fail explicitly (or fallback to `keyword` when allowed).
- With `--backend source`, mode support is evaluated against source capabilities.

## 6. CLI API Design

### 6.1 Global Options
- `-c, --config PATH`
- `--profile NAME`
- `--mode [local-api|remote]`
- `--output [table|json|jsonl|bib|bibtex]`
- `--verbose`
- Planned for agentic workflows:
  - `--non-interactive` (no prompts or interactive fallbacks).
  - `--require-offline-ready` (fail early if command path would require network).

### 6.2 Command Grammar
- Canonical form: `zotq <resource> <verb> [options]`
- Reserved resources: `system`, `search`, `item`, `collection`, `tag`, `index`
- Verb names are stable API surface and must be backward compatible.

### 6.3 v1 Commands
- `zotq system health`
- `zotq search run [QUERY] [options]`
- `zotq item get KEY`
- `zotq item get --key K1 --key K2 ...`
- `zotq item citekey KEY [--prefer auto|json|extra|rpc|bibtex]`
- `zotq item citekey --key K1 --key K2 ... [--prefer auto|json|extra|rpc|bibtex]`
- `zotq collection list`
- `zotq collection export KEY --format bibtex [--include-children] [--batch-size N]`
- `zotq tag list`
- `zotq index status`
- `zotq index inspect`
- `zotq index sync [--full] [--profiles-only]`
- `zotq index rebuild`
- `zotq index enrich [--field citation-key|doi|journal|all]`

### 6.4 Search Options (`search run`)
- `QUERY` positional argument (preferred)
- `--text`
- `--backend [auto|source|index]`
- `--doi`
- `--journal`
- `--citation-key`
- `--citekey` / `--bibkey` (aliases of `--citation-key`)
- `--search-mode [keyword|fuzzy|semantic|hybrid]`
- `--allow-fallback/--no-allow-fallback`
- `--title`
- `--creator` (repeatable)
- `--tag` (repeatable)
- `--collection`
- `--item-type`
- `--attachments/--no-attachments`
- `--year-from`
- `--year-to`
- `--alpha` (hybrid fusion weight)
- `--lexical-k`
- `--vector-k`
- `--style` (when `--output bib`)
- `--locale` (when `--output bib`)
- `--linkwrap/--no-linkwrap` (when `--output bib`)
- `--debug/--no-debug`
- `--limit`
- `--offset`

### 6.5 Index Command Semantics
- `index status`
  - Reports index readiness, counts, last sync timestamp, embedding model.
- `index inspect`
  - Reports structured field coverage/missingness and sample item keys for gaps.
  - Reports lexical/vector profile-version mismatch counts and sample mismatched item keys against configured targets.
- `index sync`
  - Incremental update from source checkpoints (lexical + vector).
- `index sync --profiles-only`
  - Reprocesses only items with lexical/vector profile-version mismatches.
  - Cannot be combined with `--full`.
- `index sync --full`
  - Full rescan + reindex.
- `index rebuild`
  - Drops and rebuilds local indexes from source.
- `index enrich`
  - Metadata-only enrichment pass without full lexical/vector rebuild.
  - Supports targeted fields (`citation-key`, `doi`, `journal`) or `all`.

### 6.6 Reserved Verb Space (Post-v1)
Keep these verbs reserved now so future write features fit without CLI breakage:
- `zotq item create`
- `zotq item update`
- `zotq item move`
- `zotq item delete`
- `zotq collection create`
- `zotq collection add-item`
- `zotq collection remove-item`
- `zotq collection move-item`
- `zotq collection delete`
- `zotq tag add`
- `zotq tag remove`

### 6.7 Bibliography Output
- `--output bib`
  - Uses Zotero API `format=bib` (CSL formatted bibliography output; often HTML-like snippets).
  - Supports `--style`, `--locale`, and `--linkwrap`.
- `--output bibtex`
  - Uses Zotero API `format=bibtex` for LaTeX/BibTeX entries.
  - Does not accept CSL-only flags (`style`, `locale`, `linkwrap`).
  - List/offline aggregation paths use deterministic BibTeX stringify policy.

### 6.8 Citation Key Resolution (`item citekey`)
- `--prefer auto` (default)
  - Resolution order: `citationKey` field -> `extra` parse (`Citation Key: ...`) -> Better BibTeX JSON-RPC -> BibTeX parse.
- `--prefer json|extra|rpc|bibtex`
  - Restricts lookup to one source only (no fallback chain).
- BibTeX parse implementation policy:
  - Replace regex-based BibTeX key extraction with parser-backed extraction from the selected BibTeX library.
  - Single-entry and batched-entry citation-key extraction must share the same parser path.
  - Current status: parser-first implementation with compatibility fallback for malformed/minimal entries.
- Better BibTeX RPC endpoint (optional):
  - `POST /better-bibtex/json-rpc`
  - method: `item.citationkey`
- For search result sets, bibliography and bibtex retrieval are batched via `itemKey=K1,K2,...` where supported.
- Authentication model:
  - `local-api`: typically no API key required when local API access is enabled in Zotero Desktop.
  - `remote`: API key or bearer token required for non-public libraries.
- `zotq` should treat "zotbib-like" output as Zotero API bibliography formatting support (not dependency on a separate ZoteroBib backend service).

### 6.9 Collection BibTeX Export
- Command shape:
  - `zotq collection export KEY [options]`
- Initial option contract:
  - `--format bibtex` (required in first release of this command; future formats can be added later)
  - `--include-children/--no-include-children` (default `--no-include-children`)
  - `--batch-size` (default `200`, max `500`) for batched `itemKey=...` bibliography fetches
- Output contract:
  - `--output bibtex`: writes concatenated BibTeX entries to stdout.
  - `--style/--locale/--linkwrap` are invalid for this command (same rule as `--output bibtex` elsewhere).
- Deterministic routing rule:
  - Export should execute against source API pagination, not index ranking, to guarantee complete collection membership export.
- Collection identity rule:
  - `KEY` is a collection key (stable identifier), not a display name.
- Implementation status:
  - Implemented in current v1 surface and covered by tests/docs.

### 6.10 Batched Multi-Key Requests
- Goal:
  - Reduce round trips and latency for repeated read operations while keeping command grammar stable.
  - Reduce network access-elevation churn in agentic workflows by avoiding chatty per-item call patterns.
- Compatibility constraints:
  - Keep existing single-key forms unchanged:
    - `zotq item get KEY`
    - `zotq item citekey KEY [--prefer auto|json|extra|rpc|bibtex]`
  - Additive multi-key form should be option-based (repeatable `--key`) rather than a new command resource/verb.
- Proposed command shape:
  - `zotq item get --key K1 --key K2 ...`
  - `zotq item citekey --key K1 --key K2 ... [--prefer ...]`
- Output contract:
  - `--output json`: envelope object (`ItemGetMultiKeyResponse` or `ItemCiteKeyMultiKeyResponse`) with `results` in input order.
  - `--output jsonl`: one per-key result object per line.
  - `--output table`: multi-row table with `key`, `found/status`, and core fields.
  - Partial failures must be explicit per key (do not fail whole response when only some keys fail).
  - `status` enum: `ok|not_found|error`.
  - Transport telemetry fields: `batch_used`, `fallback_loop`.
  - Contract model targets:
    - `item get` -> `ItemGetMultiKeyResponse` (`results: ItemGetPerKeyResult[]`)
    - `item citekey` -> `ItemCiteKeyMultiKeyResponse` (`results: ItemCiteKeyPerKeyResult[]`)
- Transport strategy:
  - Prefer source batch endpoints (`itemKey=K1,K2,...`) where available.
  - Fallback to per-key adapter calls when batch endpoints are unavailable.
  - In agentic mode, expose whether a batched transport path was used.
- Implementation status:
  - Repeatable `--key` forms are implemented for `item get` and `item citekey`.
  - Multi-key item reads are batch-first via source `itemKey=...` transport with explicit telemetry (`batch_used`, `fallback_loop`).
- Testing requirements (test-first):
  - Backward compatibility for single-key forms.
  - Deterministic output order matching input key order.
  - Partial-failure behavior and timeout/error propagation.
  - Batch-path vs fallback-path coverage for both `local-api` and `remote`.

## 7. Object and Data Models (Pydantic)

### 7.1 Config Models
- `AppConfig`
- `ProfileConfig`
- `LocalApiConfig`
- `RemoteConfig`
- `SearchDefaultsConfig`
- `IndexConfig`

### 7.2 Runtime/Domain Models
- `QuerySpec`
- `Item`, `Creator`, `Collection`, `Tag`
- `BackendCapabilities`
- `IndexStatus`
- `ChunkRecord`
- `SearchHit`, `SearchResult`
- Multi-key output contracts:
  - `MultiKeyResultStatus`, `MultiKeyTransportTelemetry`
  - `ItemGetPerKeyResult`, `ItemGetMultiKeyResponse`
  - `ItemCiteKeyPerKeyResult`, `ItemCiteKeyMultiKeyResponse`

### 7.3 QuerySpec (normalized)
```python
QuerySpec(
  text: str | None,
  backend: Literal["auto", "source", "index"],
  search_mode: Literal["keyword", "fuzzy", "semantic", "hybrid"],
  allow_fallback: bool,
  title: str | None,
  doi: str | None,
  journal: str | None,
  citation_key: str | None,
  creators: list[str],
  year_from: int | None,
  year_to: int | None,
  tags: list[str],
  collection: str | None,
  item_type: str | None,
  include_attachments: bool,
  alpha: float | None,
  lexical_k: int | None,
  vector_k: int | None,
  debug: bool,
  limit: int,
  offset: int,
)
```

## 8. Configuration Model (TOML)
Configuration precedence (highest to lowest):
1. CLI flags
2. Environment variables
3. Config file (`~/.config/zotq/config.toml`)
4. Built-in defaults

### 8.1 Example `config.toml`
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
vector_backend = "python" # or "sqlite-vec"
embedding_provider = "local"
embedding_model = "local-hash-v1"
embedding_base_url = ""
embedding_api_key = ""
embedding_timeout_seconds = 30
embedding_max_retries = 2

# planned v2 knobs
lexical_profile_version = 2
vector_profile_version = 2

[profiles.default.index.lexical_fields]
title = { weight = 6 }
abstract = { weight = 3 }
journal = { weight = 2, aliases = ["publicationTitle"] }
creators = { weight = 4 }
tags = { weight = 2 }
body = { weight = 1 }

[profiles.default.index.vector_fields]
fields = ["title", "abstract", "body"]

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

### 8.2 Environment Variables (examples)
- `ZOTQ_MODE`
- `ZOTQ_OUTPUT`
- `ZOTQ_SEARCH_MODE`
- `ZOTQ_ALLOW_FALLBACK`
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

## 9. Package Layout

```text
src/zotq/
  __init__.py
  cli.py
  config.py
  client.py
  models.py
  errors.py
  output.py
  query_engine.py
  index_service.py
  pipeline/
    __init__.py
    extractors.py
    chunking.py
    normalize.py
  sources/
    __init__.py
    base.py
    local_api.py
    remote_api.py
  embeddings/
    __init__.py
    base.py
    local_provider.py
    external_providers.py
  storage/
    __init__.py
    lexical_index.py
    vector_index.py
    checkpoints.py
```

## 10. Dependency Baseline
- Required:
  - `click`
  - `httpx`
  - `pydantic`
  - `rich` (table output)
- Optional:
  - BibTeX parser/serializer library for snapshot mode (`parse` + canonical `stringify`).
  - PDF/text extraction libraries
  - external embedding provider-specific dependencies (if using non-REST SDKs)

## 11. Error Handling
- Typed exceptions:
  - `ConfigError`
  - `BackendConnectionError`
  - `QueryValidationError`
  - `ModeNotSupportedError`
  - `IndexNotReadyError`
  - `ExtractionError`
- Non-zero exit codes for command failure.
- `--verbose` includes stack/debug context.
- Agentic behavior requirements (planned):
  - Stable machine-readable error codes in JSON/JSONL outputs.
  - Deterministic failure classes for precondition, capability, network, and data-shape errors.
  - No interactive recovery prompts when `--non-interactive` is enabled.

## 12. Testing Strategy

### 12.1 Unit tests
- Config resolution and validation.
- Query normalization and mode routing.
- Fallback behavior.
- Chunking and metadata normalization.
- Embedding provider abstraction behavior.

### 12.2 Integration tests
- Local/remote source adapters with mocked HTTP.
- Index lifecycle (`status`, `sync`, `rebuild`).
- End-to-end search mode behavior on fixture corpus.

### 12.3 Contract tests
- Shared adapter contract (`health/search/get/list/index`) across modes.
- Snapshot contract parity tests (planned):
  - `.bib`-backed read/search behavior with explicit degraded capabilities.
  - Citation-key and DOI normalization parity with other modes.
  - Deterministic behavior with missing/partial BibTeX fields.

## 13. Implementation Phases
1. Scaffold project and CLI skeleton.
2. Implement Pydantic config models + `ConfigLoader`.
3. Implement `ZotQueryClient`, source adapters, and basic `health/item/list` flows.
4. Implement content pipeline (extract/normalize/chunk) and checkpoints.
5. Implement lexical index and `keyword`/`fuzzy` search.
6. Implement embedding provider interface + vector index + `semantic` search.
7. Implement hybrid fusion, mode capability checks, and fallback policy.
8. Implement index commands (`status`, `sync`, `rebuild`) end-to-end.
9. Add output shaping, tests, and CI.

## 14. Risks and Mitigations
- Source API differences (local vs remote): normalize in adapters.
- Extraction quality variance across PDFs: keep extractor pluggable and preserve traceable metadata.
- Index drift/staleness: incremental checkpoints + explicit rebuild command.
- Semantic search quality/cost: provider abstraction + required portable local embedding baseline for offline query paths.
- Capability mismatch across modes: explicit capability probing and deterministic fallback rules.

## 15. Future Considerations (Post-v1)
- MCP integration for tool-based interoperability with external clients/agents.
- Expose search/index operations through MCP resources and tools once CLI/API contracts are stable.
- Keep core interfaces (`ZotQueryClient`, `SourceAdapter`, `IndexService`) transport-agnostic to minimize MCP adoption cost.
- Add controlled write features using the reserved verb space (`item/collection/tag`).

### 15.1 Write Roadmap (v2+)
1. Introduce low-risk mutation commands first:
   - `collection add-item`
   - `collection remove-item`
   - `tag add`
   - `tag remove`
2. Require safety controls:
   - `--dry-run` for all mutation commands.
   - `--yes` confirmation for bulk/destructive operations.
   - Idempotency checks and duplicate-prevention behavior.
3. Add higher-risk mutations only after stabilization:
   - `item create/update/delete`
   - `collection create/delete`
   - `item move` / `collection move-item`

## 16. MVP Acceptance Criteria
- User can run same command structure in both `local-api` and `remote` modes.
- `keyword` and `fuzzy` search work with indexed content.
- `semantic` and `hybrid` work when vector indexing is enabled.
- Built-in `local` embedding provider works without extra runtime dependencies.
- At least one portable local embedding path supports semantic/hybrid query execution without network access.
- External providers (`openai`/`ollama`/`gemini`) are configurable via `IndexConfig`.
- Unsupported modes fail clearly or fallback only when explicitly enabled.
- `index status/inspect/sync/rebuild/enrich` provide actionable output.
- JSON output schema is stable across modes.
- No live Zotero DB reads are required.

## 17. Next Milestones (Unfinished)
1. Improve migration UX for pre-cutover index files:
   - Detect legacy-only index files early and emit explicit rebuild guidance.
   - Surface actionable status text in `index status`/`index inspect`.
2. Add projection/version migration controls:
   - Apply `lexical_profile_version`/`vector_profile_version` across all relevant stores.
   - Reporting for version mismatch counts is now available via `index inspect`.
   - Explicit migration workflow is available via `index sync --profiles-only`.
3. Improve source checkpointing fidelity:
   - Source watermark/checkpoint support is now available where adapters provide paging tokens.
   - Restart logic now tolerates source-order drift via collected-key dedupe + resume checkpoints.
4. Add batched multi-key read UX for item operations:
   - Introduce repeatable `--key` support for `item get` and `item citekey` while preserving current single-key forms.
   - Use batch transport where available and fallback loops otherwise, with deterministic per-key output/error reporting.
5. Post-v1 feature roadmap:
   - Introduce low-risk mutation commands (`collection add-item/remove-item`, `tag add/remove`) with `--dry-run`/`--yes`.
   - Keep MCP integration as separate phase after CLI contracts stabilize.

## 18. Unified Priority + Findings (Execution-Critical)
This section fuses the execution plan and technical findings into one priority model.
Execution rule:
1. Lock contract/models.
2. Add tests.
3. Implement.

### 18.1 Re-evaluated Priority Order
Priority 0: Retrieval overhead reduction (immediate pain point)
1. Add multi-key reads (`item get --key`, `item citekey --key`) with batch-first transport.
2. Add explicit transport telemetry (`batch_used`, `fallback_loop`) for agentic runs.
3. Keep command grammar stable (`zotq <resource> <verb> [options]`).

Priority 1: Vector retrieval backend cutover
1. Keep current Python cosine path as fallback.
2. Introduce backend abstraction (`python` vs `sqlite-vec`) and benchmark parity.
3. Standardize on `sqlite-vec` as the single extension backend (no dual-extension production matrix).

Priority 2: Portable local semantic/hybrid path
1. Require local embedding provider path for offline-ready profiles.
2. Add query-time guards for remote-only embedding dependency.
3. Preserve deterministic fallback/fail-fast policy.

Priority 3: Snapshot/offline source usability
1. Add `snapshot` mode and `BibtexSnapshotSourceAdapter`.
2. Add parser/serializer-backed BibTeX handling (including replacing regex citation-key extraction path).

Priority 4: Full-text and chunk-scale foundations
1. Add chunk traceability and provenance schema.
2. Add extractor increments and ANN scale path.

### 18.2 Key Technical Findings Driving Order
1. Item fan-out is multiplicative:
   - `chunks_per_item = sum(k_i)` across indexed sources/fields.
   - Vector rows therefore scale with chunk fan-out.
2. Current cosine path is Python full scan (`O(N*d)`), which makes retrieval latency the first bottleneck at scale.
3. SQLite core stores vectors but does not provide ANN acceleration without extensions.
4. Environment findings (March 7, 2026):
   - Extension loading is available.
   - `sqlite-vec` and `sqlite-vss` resolve.
   - `sqlite-vector` does not resolve for this macOS arm64 environment.
5. Role split must remain explicit:
   - embed engine (for example `fastembed`) generates vectors.
   - `sqlite-vec` indexes/searches vectors.

### 18.3 Data Model and Retrieval Constraints
Current support:
1. `item -> fields` one-to-many (`item_fields`, `ordinal`).
2. `item -> chunks` one-to-many (`chunks`).
3. `item -> vectors` chunk-granular one-to-many (`vectors`).

Current gaps:
1. Missing chunk source/provenance metadata (`source_type`, `source_id`, offsets, extractor version/hash).
2. Missing explicit multi-profile vector identity in rows (`profile_id`-class field).
3. No ANN index path in current runtime.

Mandatory retrieval-profile alignment:
1. Lock profile by `model/provider`, dimension/truncation, dtype (`float`/`int8`/`bit`), normalization/quantization rules, and profile version.
2. Query-time transform must match index-time transform exactly.
3. Cross-profile retrieval mismatch must fail fast (or explicit fallback when configured).

### 18.4 Agentic Requirements (Mandatory)
1. Non-interactive execution.
2. Preflight capability/status output:
   - `offline_ready`
   - `requires_network_for_query`
   - `embedding_provider_local`
   - `degraded_capabilities`
3. Deterministic JSON/JSONL error envelope.
4. `--require-offline-ready` guard for automation.

### 18.5 Migration and Cutover Policy
1. Lexical schema does not need movement for vector-backend cutover.
2. Vector rows require one-time extension-compatible backfill/migration.
3. Re-embedding is not mandatory when model/dimension/profile remains compatible.
4. Keep Python fallback until ANN parity tests pass.
5. Do not run `sqlite-vec` and `sqlite-vss` together in production profiles.

## 19. Step-by-Step Execution Plan
This section is an implementation runbook derived from section 18 priorities.
Execution tracking for this runbook is maintained in `TODO.md` (ticket IDs `T0.x`-`T5.x`).

### 19.1 Step 0: Contracts and Benchmarks
1. Add config contracts for:
   - multi-key read output envelope
   - vector backend selector (`python|sqlite-vec`)
   - profile alignment/version fields
2. Add retrieval benchmark harness and stage timing.

### 19.2 Step 1: Retrieval Overhead First
1. Implement `item get --key` and `item citekey --key`.
2. Use batch transport where available; explicit fallback loop otherwise.
3. Add deterministic per-key partial-failure contract.

Tests:
1. `tests/test_item_multi_key.py`
2. `tests/test_cli_contract_model.py` updates
3. `tests/test_bibliography_batching.py`/`tests/test_citation_key_resolution.py` extensions

### 19.3 Step 2: Parser-backed BibTeX Path
1. Add BibTeX parser/serializer dependency.
2. Replace regex citation-key extraction helpers with parser-backed extraction.
3. Add stable stringify policy for offline output.

Tests:
1. `tests/test_citation_key_resolution.py` parser-backed single/batch cases
2. BibTeX parse/stringify round-trip tests

### 19.4 Step 3: SQLite-vec Backend Introduction
1. Add vector-backend abstraction in storage layer.
2. Implement `sqlite-vec` backend path with fallback to current Python scan.
3. Add migration/backfill command path and compatibility checks.

Tests:
1. Backend parity tests on sampled queries.
2. Migration tests from legacy vector table to extension-backed index path.

### 19.5 Step 4: Portable Local Embeddings + Offline Guards
1. Add required local embedding profile path (`fastembed`-class + local-hash fallback).
2. Add remote-dependency guardrails for semantic/hybrid query path.
3. Surface preflight readiness fields for agents.

Tests:
1. `tests/test_semantic_offline_guards.py`
2. `tests/test_agentic_preflight.py`
3. `tests/test_agentic_non_interactive.py`
4. `tests/test_agentic_error_envelope.py`

### 19.6 Step 5: Snapshot Mode
1. Add `snapshot` mode/config and `BibtexSnapshotSourceAdapter`.
2. Preserve degraded capability semantics explicitly.
3. Keep deterministic source/index routing behavior.

Tests:
1. `tests/test_snapshot_mode_config.py`
2. `tests/test_snapshot_bibtex_adapter.py`
3. `tests/test_snapshot_mode_contract.py`

### 19.7 Step 6: Full-text Traceability Foundations
1. Add chunk provenance fields:
   - `source_type`, `source_id`
   - `extractor`, `extractor_version`
   - `source_content_hash`
   - `char_start`, `char_end`
2. Add extractor increments behind safe fallbacks.

Tests:
1. `tests/test_chunk_provenance.py`
2. `tests/test_extractors.py`

### 19.8 Final Acceptance Gates
1. Retrieval overhead is reduced via multi-key batching and explicit fallback telemetry.
2. Offline-ready profiles execute semantic/hybrid without network.
3. `sqlite-vec` backend passes parity and migration checks with Python fallback retained until stable.
4. Snapshot `.bib` workflows are deterministic and parser-backed.
5. Chunked full-text rows are source-traceable and migration-safe.
