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
- Local lexical index: SQLite + FTS5 (`documents`, `chunks`, `chunks_fts`).
- Structured filter columns in `documents` (`doi_norm`, `citation_key_norm`, `journal_norm`) with SQLite indexes.
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
  - `index sync` updates changed items only (content-hash based).
  - `index sync --full` and `index rebuild` force full reprocessing.
- Text extraction in v1 is metadata-first (title/abstract/creators/tags/date/type); attachment extraction remains pluggable roadmap work.
- DOI filtering is normalized (`doi:`, `http(s)://doi.org/`, case/whitespace).
- Citation-key filtering is case-insensitive and also uses `extra` fallback parsing (`Citation Key: ...`) when `citationKey` is absent.
- Sync-time citation key enrichment is best-effort: batch Better BibTeX RPC lookup first, then batch BibTeX parse fallback.

### 5.2 v2 Goals
- Add fields over time (for example DOI, journal, publisher) without expensive full rebuilds.
- Support exact identifier lookup (DOI first) separate from lexical/semantic scoring.
- Keep lexical updates cheap and frequent.
- Re-embed vectors only when semantic source text changes.
- Maintain resumable indexing behavior after interruption.

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

### 6.2 Command Grammar
- Canonical form: `zotq <resource> <verb> [options]`
- Reserved resources: `system`, `search`, `item`, `collection`, `tag`, `index`
- Verb names are stable API surface and must be backward compatible.

### 6.3 v1 Commands
- `zotq system health`
- `zotq search run [QUERY] [options]`
- `zotq item get KEY`
- `zotq item citekey KEY [--prefer auto|json|extra|rpc|bibtex]`
- `zotq collection list`
- `zotq tag list`
- `zotq index status`
- `zotq index inspect`
- `zotq index sync [--full]`
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
- `index sync`
  - Incremental update from source checkpoints (lexical + vector).
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

### 6.8 Citation Key Resolution (`item citekey`)
- `--prefer auto` (default)
  - Resolution order: `citationKey` field -> `extra` parse (`Citation Key: ...`) -> Better BibTeX JSON-RPC -> BibTeX parse.
- `--prefer json|extra|rpc|bibtex`
  - Restricts lookup to one source only (no fallback chain).
- Better BibTeX RPC endpoint (optional):
  - `POST /better-bibtex/json-rpc`
  - method: `item.citationkey`
- For search result sets, bibliography and bibtex retrieval are batched via `itemKey=K1,K2,...` where supported.
- Authentication model:
  - `local-api`: typically no API key required when local API access is enabled in Zotero Desktop.
  - `remote`: API key or bearer token required for non-public libraries.
- `zotq` should treat "zotbib-like" output as Zotero API bibliography formatting support (not dependency on a separate ZoteroBib backend service).

### 6.9 Proposed Extension: Collection BibTeX Export
This is a read-only candidate command for the next contract revision (not part of the locked v1 command list yet).

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

Gaps to close before implementation:
- CLI/API contract gap: no `collection export` verb is modeled in contract definitions/tests today.
- Pagination gap: existing `search run --collection ... --output bibtex` is query-limit based (`QuerySpec.limit`, max 500), so it cannot represent unbounded full export.
- Traversal gap: no explicit policy for child/subcollection inclusion.
- Verification gap: no tests currently assert complete collection export semantics across page boundaries and batch BibTeX fetch behavior.

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
- Semantic search quality/cost: provider abstraction + optional local embeddings.
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
- External providers (`openai`/`ollama`/`gemini`) are configurable via `IndexConfig`.
- Unsupported modes fail clearly or fallback only when explicitly enabled.
- `index status/inspect/sync/rebuild/enrich` provide actionable output.
- JSON output schema is stable across modes.
- No live Zotero DB reads are required.
