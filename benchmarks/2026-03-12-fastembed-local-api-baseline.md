# Fastembed Local-API Baseline (March 12, 2026)

Config:
- `-c config.fastembed.toml`
- profile: `fastembed_eval`
- provider/model: `portable` + `BAAI/bge-small-en-v1.5`
- backend: `sqlite-vec`

Dataset snapshot (`index inspect --sample-limit 0`):
- documents: `3305`
- lexical chunks: `3970`
- vector rows: `3846`
- missing citation keys: `1864`

## Timing Baseline

### Full rebuild (`index sync --full`)
Command:
```bash
uv run zotq -c config.fastembed.toml --output json index sync --full
```

Observed benchmark:
- total: `147982 ms` (~`2m 28s`)
- collect: `1623 ms`
- index: `95554 ms` (~`1m 35s`)
- enrich: `50698 ms` (~`51s`)

### Follow-up incremental (`index sync`)
Command:
```bash
uv run zotq -c config.fastembed.toml --output json index sync
```

Observed benchmark:
- total: `5573 ms` (~`5.6s`)
- collect: `1827 ms`
- index: `3620 ms`
- enrich: `8 ms`

## Notes
- This baseline reflects metadata/abstract indexing (not attachment full-text extraction).
- The full rebuild includes citation-key enrichment over all missing keys.
- Incremental sync is much faster because unchanged content is skipped and unresolved citation-key misses are cached.
