# TODO Backlog

Status values: `todo`, `in_progress`, `done`.

## P0 Contracts and Benchmarks

- [ ] `T0.1` (`todo`) Add multi-key output contract models and docs.
  - Files: `src/zotq/models.py`, `src/zotq/contracts.py`, `DESIGN.md`.
  - Tests: `tests/test_cli_contract_model.py`.

- [ ] `T0.2` (`todo`) Add vector backend selector contract (`python|sqlite-vec`).
  - Files: `src/zotq/models.py`, `src/zotq/config.py`, `README.md`, `DESIGN.md`.
  - Tests: `tests/test_config_precedence.py`.

- [ ] `T0.3` (`todo`) Add retrieval benchmark harness and stage timing.
  - Files: `src/zotq/index_service.py`, `src/zotq/cli.py`.
  - Tests: `tests/test_index_progress.py`.

## P1 Retrieval Overhead First

- [ ] `T1.1` (`todo`) Implement `item get --key` multi-key CLI form.
  - Files: `src/zotq/cli.py`, `src/zotq/contracts.py`.
  - Tests: `tests/test_cli_commands.py`, `tests/test_cli_contract_model.py`.

- [ ] `T1.2` (`todo`) Implement `item citekey --key` multi-key CLI form.
  - Files: `src/zotq/cli.py`, `src/zotq/contracts.py`, `src/zotq/client.py`.
  - Tests: `tests/test_cli_commands.py`, `tests/test_item_multi_key.py`.

- [ ] `T1.3` (`todo`) Batch-first transport for multi-key item reads with fallback telemetry.
  - Files: `src/zotq/client.py`, `src/zotq/sources/base.py`, `src/zotq/sources/http_base.py`.
  - Tests: `tests/test_item_multi_key.py`, `tests/test_bibliography_batching.py`.

## P2 Parser-backed BibTeX Path

- [ ] `T2.1` (`todo`) Add BibTeX parser/serializer dependency.
  - Files: `pyproject.toml`, `README.md`.
  - Tests: dependency import smoke in `tests/`.

- [ ] `T2.2` (`todo`) Replace regex citation-key extraction with parser-backed functions.
  - Files: `src/zotq/client.py`, new parser helper module under `src/zotq/`.
  - Tests: `tests/test_citation_key_resolution.py`.

- [ ] `T2.3` (`todo`) Add deterministic BibTeX stringify policy for offline output.
  - Files: parser helper module, `src/zotq/output.py`.
  - Tests: new round-trip BibTeX tests.

## P3 SQLite-vec Backend

- [ ] `T3.1` (`todo`) Add vector storage backend abstraction and `sqlite-vec` backend.
  - Files: `src/zotq/storage/vector_index.py`, `src/zotq/models.py`, `src/zotq/config.py`.
  - Tests: backend parity tests in new `tests/test_vector_backend_parity.py`.

- [ ] `T3.2` (`todo`) Add migration/backfill path from legacy vector rows to `sqlite-vec`.
  - Files: `src/zotq/storage/vector_index.py`, `src/zotq/index_service.py`.
  - Tests: `tests/test_vector_migration.py`.

- [ ] `T3.3` (`todo`) Add preflight readiness output for vector backend state.
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

