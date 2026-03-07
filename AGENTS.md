# AGENTS.md

## Purpose
This repository builds `zotq`, a Zotero-focused CLI with:
- Source adapters (`local-api`, `remote`)
- Local indexing pipeline (lexical + vector)
- Search modes (`keyword`, `fuzzy`, `semantic`, `hybrid`)

## Current Stage
Design-first and test-first implementation.

Before implementing behavior-heavy features:
1. Lock the CLI/API contract in models.
2. Write/adjust tests for the contract.
3. Implement code to satisfy tests.

## Non-Negotiable Constraints
- Do not query live `zotero.sqlite` directly.
- v1 is read/query + index lifecycle only.
- Keep write/organize/insert features out of v1 (reserved verb space only).
- Keep command grammar stable: `zotq <resource> <verb> [options]`.
- Config format is TOML with precedence:
  - CLI flags > environment > config file > defaults.

## Canonical CLI Surface (v1)
- `zotq system health`
- `zotq search run [QUERY] [options]`
- `zotq item get KEY`
- `zotq item citekey KEY`
- `zotq collection list`
- `zotq tag list`
- `zotq index status`
- `zotq index sync [--full]`
- `zotq index rebuild`
- `zotq index enrich`

## Search/Output Contract Notes
- `search run` supports `--backend [auto|source|index]`; preserve deterministic routing semantics.
- `search run` supports `--citation-key` with aliases `--citekey` and `--bibkey`.
- `--output bib` means Zotero `format=bib` (CSL formatted output, often HTML-like).
- `--output bibtex` means Zotero `format=bibtex` (LaTeX BibTeX entries).
- `item citekey` supports `--prefer [auto|json|extra|rpc|bibtex]`; keep `auto` fallback order stable.
- DOI matching must stay normalized (`doi:`, `http(s)://doi.org/`, case/whitespace).
- Citation-key search must remain case-insensitive and support `extra` fallback parsing (`Citation Key: ...`).

## Reserved Verb Space (Post-v1)
Keep names reserved now; do not repurpose:
- `item create|update|move|delete`
- `collection create|add-item|remove-item|move-item|delete`
- `tag add|remove`

## Architecture Rules
- `ZotQueryClient` orchestrates adapters, query engine, and index service.
- `SourceAdapter` is the abstraction boundary for Zotero data sources.
- `QuerySpec` and response models are the contract source of truth.
- Capability checks and fallback behavior must be explicit and test-covered.

## Testing Rules
- Write tests first for:
  - config precedence and profile/mode resolution
  - CLI grammar/command contracts
  - mode capability and fallback behavior
  - index command semantics
- Avoid fragile tests that depend on a live Zotero process by default.
- Use fixtures/mocks for adapter HTTP behavior.

## Implementation Guidance
- Prefer explicit, typed models (Pydantic) over ad hoc dicts.
- Keep modules small and composable.
- Add comments only for non-obvious logic.
- Preserve backward compatibility for command names/options once committed.

## Operational Commands
- Install deps: `uv sync`
- Run tests: `uv run pytest -q`
- Run CLI help: `uv run zotq --help`

## Documentation Maintenance
When changing CLI/API contracts, update together:
- `DESIGN.md`
- `README.md`
- Tests that define contract expectations
