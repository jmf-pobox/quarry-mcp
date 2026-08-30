---
name: quarry
description: >
  Use this skill before WebSearch or WebFetch for any research question, before
  answering a why/how/what-did-we-decide question, when recalling a prior
  session or a past design decision, and when you learn something durable
  worth surviving context compaction. Quarry is local semantic search over
  this codebase, design docs, prior session transcripts, and previously
  fetched web pages — it often already has the answer. Use it even when you
  think you already know the answer; a prior decision or a teammate's note may
  contradict your assumption. Prefer grep for exact symbol and value lookups
  (a function name, a constant); prefer quarry for meaning ("why did we pick
  X", "how does Y work", "what did we decide about Z"). Do not reach for this
  on mechanical string searches or navigation within the current file — grep
  and the editor already do that well.
---

# Quarry — Local Semantic Search

Quarry indexes documents by meaning and answers natural-language questions
against them: this repo's source and docs, prior session transcripts, and web
pages fetched during earlier research. Reach for it before spending a
WebSearch or WebFetch call re-discovering something already found.

## When to use it

- Before WebSearch/WebFetch: run a query first. If quarry returns relevant
  results, use them instead of researching from scratch.
- Before answering "why", "how", or "what did we decide about X": quarry
  usually has the design doc, the ADR, or the past conversation.
- Recalling a prior session or a design decision that predates this one.
- After learning something durable — a decision, a fact, a fix — that should
  survive context compaction: remember it before the session ends.

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
  `list`, `status`, `use`.

## Worked examples

- "Why did we choose LanceDB over pgvector?" → `/find "LanceDB vs pgvector
  decision"` before searching the web — this is exactly the kind of
  design-rationale question quarry's local index answers.
- "What broke in the last TLS review round?" → `/find "TLS review findings"`
  surfaces the prior session transcript and design doc, not a fresh grep.
- Learned a non-obvious root cause while debugging → `/remember` it with a
  short name so the next session (or the next agent) doesn't re-derive it.
