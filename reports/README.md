Run artifacts (JSONL run logs, manifests, gate verdicts, evidence packs) are written
here at runtime and are gitignored. Each run creates `runs/<run_id>.jsonl` plus a
`manifests/<run_id>.json` artifact snapshot (AST-1).
