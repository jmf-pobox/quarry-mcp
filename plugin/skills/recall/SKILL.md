---
name: recall
description: >
  Use find before WebSearch or WebFetch for research, or before answering a
  why/how/what-did-we-decide question. Quarry indexes this codebase, design
  docs, prior session transcripts, and previously fetched web pages — it often
  already has the answer. Prefer grep for symbol and value lookups; prefer find
  for meaning. Use remember when you learn something durable — a decision, a
  gotcha, a non-obvious fact, a procedure — so it survives context compaction.
  Use even when you think you already know the answer; a prior decision or a
  teammate's note may contradict your assumption. Do not reach for find on
  mechanical string searches or navigation within the current file — grep and
  the editor already do that well.
---

# Quarry — Local Semantic Search

Quarry indexes documents by meaning and answers natural-language questions
against them: this repo's source and docs, prior session transcripts, and web
pages fetched during earlier research. Reach for it before spending a
WebSearch or WebFetch call re-discovering something already found.

## When to use it

- Use find before WebSearch or WebFetch for research, or before answering a
  why/how/what-did-we-decide question. Quarry indexes this codebase, design
  docs, prior session transcripts, and previously fetched web pages — it often
  already has the answer.
- Prefer grep for symbol and value lookups; prefer find for meaning.
- Use remember when you learn something durable — a decision, a gotcha, a
  non-obvious fact, a procedure — so it survives context compaction.

## When not to use it

- Exact symbol or value lookups (a function name, a literal string) — grep is
  faster and precise.
- Navigating the file currently open — use the editor, not search.

## Tools

- `/find <query>` — search the knowledge base; natural language beats keywords
  ("What did we decide about retry limits?" beats "retry limits").
- `/remember <name>` — persist inline text as a named memory.
- `/ingest <url, directory, or file>` — index new content.
- `/explain <document or topic>` — search and synthesize an explanation.
- `/source <claim or text>` — find which document a claim came from.
- MCP tools (same operations, callable directly): `find`, `remember`,
  `ingest`, `register_directory`, `sync_all_registrations`, `show`, `delete`,
  `list`, `status`, `use`. Prefer `/quarry:quarry use <db>` as the interactive
  entry for database switching; the `use` MCP tool is also available.

## Worked examples

- "Why did we choose LanceDB over pgvector?" → `/find "LanceDB vs pgvector
  decision"` before searching the web — this is exactly the kind of
  design-rationale question quarry's local index answers.
- "What broke in the last TLS review round?" → `/find "TLS review findings"`
  surfaces the prior session transcript and design doc, not a fresh grep.
- Learned a non-obvious root cause while debugging → `/remember` it with a
  short name so the next session (or the next agent) doesn't re-derive it.
