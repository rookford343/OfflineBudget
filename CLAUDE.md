## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Security gates

The global "Security gates for AI coding" rules apply here. Project specifics:

- Lint: `.venv/bin/ruff check .` (config `ruff.toml`: Bandit `S` + Pyflakes `F`). Tools pinned in
  `backend/requirements-dev.txt`.
- `.githooks/pre-commit` blocks bank data, private keys, merge markers, files over 1 MB, and ruff
  findings on staged Python. `.githooks/pre-push` re-runs ruff on the whole tree, imports the app,
  and runs the tests with the coverage floor in `backend/.coveragerc` (never lower it).
- Every security fix gets a test in `backend/tests/test_security_regressions.py` that feeds the
  bad input and asserts it is refused.
- After any "remove unused imports" fix, confirm `python -c "import backend.main, cli.budget"`:
  something may have imported a name through that module.
