# TODO Backlog

Status values: `todo`, `in_progress`, `done`.

## Active Staged Plan

- [x] `S0` (`done`) Baseline docs commit (`d88c964`) for DESIGN/TODO runbook.
- [x] `S1` (`done`) Dependency bootstrap (`sqlite-vec` + BibTeX parser) and smoke coverage.
- [x] `S2` (`done`) Execute P0 contracts (`T0.1`, `T0.2`) with tests first.
- [x] `S3` (`done`) Execute P0 benchmark harness (`T0.3`) with tests first.
- [x] `S4` (`done`) Execute P1 retrieval overhead work (`T1.1`/`T1.2`/`T1.3`) with test coverage.
- [x] `S5` (`done`) Execute `T2.2`: parser-backed citation-key extraction and batch parsing in client.
- [x] `S6` (`done`) Execute `T2.3`: deterministic BibTeX stringify policy + output integration tests.
- [x] `S7` (`done`) Execute `T3.1`: vector backend abstraction (`python|sqlite-vec`) + parity tests.
- [x] `S8` (`done`) Execute `T3.2`: migration/backfill path for sqlite-vec cutover.
- [ ] `S9` (`in_progress`) Start `T3.3`: preflight readiness output for vector backend state.

## P0 Contracts and Benchmarks

- [x] `T0.1` (`done`) Add multi-key output contract models and docs.
  - Files: `src/zotq/models.py`, `src/zotq/contracts.py`, `DESIGN.md`.
  - Tests: `tests/test_cli_contract_model.py`.

- [x] `T0.2` (`done`) Add vector backend selector contract (`python|sqlite-vec`).
  - Files: `src/zotq/models.py`, `src/zotq/config.py`, `README.md`, `DESIGN.md`.
  - Tests: `tests/test_config_precedence.py`.

- [x] `T0.3` (`done`) Add retrieval benchmark harness and stage timing.
  - Files: `src/zotq/index_service.py`, `src/zotq/cli.py`.
  - Tests: `tests/test_index_progress.py`.

## P1 Retrieval Overhead First

- [x] `T1.1` (`done`) Implement `item get --key` multi-key CLI form.
  - Files: `src/zotq/cli.py`, `src/zotq/contracts.py`.
  - Tests: `tests/test_cli_commands.py`, `tests/test_cli_contract_model.py`.

- [x] `T1.2` (`done`) Implement `item citekey --key` multi-key CLI form.
  - Files: `src/zotq/cli.py`, `src/zotq/contracts.py`, `src/zotq/client.py`.
  - Tests: `tests/test_cli_commands.py`, `tests/test_item_multi_key.py`.

- [x] `T1.3` (`done`) Batch-first transport for multi-key item reads with fallback telemetry.
  - Files: `src/zotq/client.py`, `src/zotq/sources/base.py`, `src/zotq/sources/http_base.py`.
  - Tests: `tests/test_item_multi_key.py`, `tests/test_bibliography_batching.py`.

## P2 Parser-backed BibTeX Path

- [x] `T2.1` (`done`) Add BibTeX parser/serializer dependency.
  - Files: `pyproject.toml`, `README.md`.
  - Tests: dependency import smoke in `tests/`.

- [x] `T2.2` (`done`) Replace regex citation-key extraction with parser-backed functions.
  - Files: `src/zotq/client.py`, new parser helper module under `src/zotq/`.
  - Tests: `tests/test_citation_key_resolution.py`.

- [x] `T2.3` (`done`) Add deterministic BibTeX stringify policy for offline output.
  - Files: parser helper module, `src/zotq/output.py`.
  - Tests: new round-trip BibTeX tests.

## P3 SQLite-vec Backend

- [x] `T3.1` (`done`) Add vector storage backend abstraction and `sqlite-vec` backend.
  - Files: `src/zotq/storage/vector_index.py`, `src/zotq/models.py`, `src/zotq/config.py`.
  - Tests: backend parity tests in new `tests/test_vector_backend_parity.py`.

- [x] `T3.2` (`done`) Add migration/backfill path from legacy vector rows to `sqlite-vec`.
  - Files: `src/zotq/storage/vector_index.py`, `src/zotq/index_service.py`.
  - Tests: `tests/test_vector_migration.py`.

- [ ] `T3.3` (`in_progress`) Add preflight readiness output for vector backend state.
  - Files: `src/zotq/client.py`, `src/zotq/cli.py`.
  - Tests: `tests/test_agentic_preflight.py`.

## P4 Portable Local Embeddings and Guards

- [ ] `T4.1` (`todo`) Add local portable embedding provider (`fastembed`-class) with explicit fallback.
  - Files: `src/zotq/embeddings/factory.py`, new provider module.
  - Tests: `tests/test_embedding_provider.py`.

- [ ] `T4.2` (`todo`) Add semantic/hybrid remote-dependency query guards.
  - Files: `src/zotq/index_service.py`, `src/zotq/client.py`.
  - Tests: `tests/test_semantic_offline_guards.py`.

- [ ] `T4.3` (`todo`) Add agentic structured error envelope and non-interactive behavior.
  - Files: `src/zotq/cli.py`, `src/zotq/errors.py`, `src/zotq/output.py`.
  - Tests: `tests/test_agentic_non_interactive.py`, `tests/test_agentic_error_envelope.py`.

## P5 Snapshot Mode and Full-text Traceability

- [ ] `T5.1` (`todo`) Add `snapshot` mode and `BibtexSnapshotSourceAdapter`.
  - Files: `src/zotq/models.py`, `src/zotq/config.py`, `src/zotq/factory.py`, `src/zotq/sources/snapshot_bibtex.py`.
  - Tests: `tests/test_snapshot_mode_config.py`, `tests/test_snapshot_bibtex_adapter.py`, `tests/test_snapshot_mode_contract.py`.

- [ ] `T5.2` (`todo`) Add chunk provenance schema fields and persistence.
  - Files: `src/zotq/storage/lexical_index.py`, `src/zotq/pipeline/chunking.py`, `src/zotq/pipeline/extractors.py`.
  - Tests: `tests/test_chunk_provenance.py`.

- [ ] `T5.3` (`todo`) Add extractor increments (text/html/pdf) with safe fallback.
  - Files: `src/zotq/pipeline/extractors.py`.
  - Tests: `tests/test_extractors.py`.
