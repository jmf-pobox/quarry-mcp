# Design: Passive Knowledge Capture

**Bead**: quarry-ppv (P2 feature)
**Status**: Draft
**Date**: 2026-03-25

---

## Problem

Knowledge flows through every Claude Code session and evaporates — web research, document reads, debugging discoveries, architectural decisions. Quarry's three shipped hooks capture some of this, but incompletely:

- **PreCompact** extracts only user/assistant message text, discards tool results, and does not preserve the raw transcript file.
- **PostToolUse/WebFetch** auto-ingests URLs but uses a vague collection name (`web-captures`).
- **No recall signal.** The agent doesn't know to check quarry before doing fresh web research on a topic quarry already has indexed.

## Three capabilities

### 1. Full conversation capture before compaction

Every conversation is stored before compaction. Both a raw archive and a search-optimized version.

**Raw archive**: Copy the JSONL transcript to `{quarry_root}/../sessions/{repo}-{session_id[:8]}-{timestamp}.jsonl`. This follows the quarry config system — resolves to `~/.quarry/sessions/` today, `~/.punt-labs/quarry/sessions/` after migration. The raw file is the complete record, never modified.

**Searchable version**: Ingest curated text into the `quarry-conversations` collection. The extraction filter keeps:

- User text blocks (existing behavior)
- Assistant text blocks (existing behavior)
- Short tool results (<500 chars) — these carry signal ("3 tests failed", "file written successfully")

It excludes:

- Long tool results (pytest stdout, file contents, JSON blobs) — these pollute embeddings with noise that outranks the reasoning around them
- Tool-use input blocks (the command invoked is less useful for retrieval than the outcome)
- System messages

**Truncation**: The 500k char cap truncates from the front (oldest content), not the back. The tail of a session is the most recent and most relevant.

**Dedup**: Document name includes compaction number: `session-{session_id[:8]}-compact-{N}`. Multiple compactions in one session produce numbered documents rather than duplicates.

**Retention**: Raw JSONL files in `sessions/` are subject to a max age (90 days) enforced lazily on write — when copying a new transcript, delete files older than the threshold. At ~500KB per session, 5 sessions/day, this caps at ~7GB before cleanup kicks in.

**Fallback**: If `cwd` is not registered (hooks fire before session-start completes), fall back to `quarry-conversations` as a global collection. The design prefers per-project but does not fail on missing registration.

### 1b. Session artifact linkage

Conversations produce git artifacts — commits, PRs, merges, branch operations, bead state changes. The design captures this relationship bidirectionally so `quarry find "PR #113"` returns the conversation that produced it, and the conversation document lists what it produced.

**Layer 1 — Transcript extraction (lightweight).** The enhanced `_extract_transcript_text` already captures short tool results. Git commit output (`[branch abc1234] type: message`), MCP PR creation results (`{"url": "...pull/113"}`), and merge results are all under 500 chars and will be included in the searchable text. This provides basic searchability with no additional work.

**Layer 2 — Structured artifacts header.** At PreCompact time, scan the extracted transcript text for git artifacts using reliable patterns:

| Artifact | Pattern | Source |
|----------|---------|--------|
| Commit SHAs | `[a-f0-9]{7,12}` following `commit` or in `[branch sha]` format | git commit output |
| PR numbers | `#\d+` in context of PR/pull/merge | MCP results, assistant text |
| Branch names | Token after `checkout -b` or `push.*origin` | git output |
| Beads | `quarry-[a-z0-9]{3}` pattern | bd commands |

Prepend a structured header to the ingested document:

```markdown
## Session Artifacts
Branch: fix/remove-sequence-rules
Commits: 5619a29, fe8feb8, 1e9c4f1, bc16aac
PRs created: #112
PRs merged: #112, #113
Beads: quarry-5l9, quarry-fon
```

This header becomes part of the embedding — queries for any artifact return the conversation that produced it.

**Layer 3 — Authoritative git state (follow-up).** At PreCompact time, query git directly for ground-truth artifacts:

```
git log --oneline --since={first_transcript_timestamp} --format="%h %s"
```

This catches commits the transcript extraction might miss (e.g., commits made by hooks or background processes) and provides canonical short SHAs. Also query for PRs via:

```
git log --oneline --merges --since={first_transcript_timestamp}
```

The authoritative layer adds ~1s latency (subprocess calls) and requires `git` in PATH. It runs after transcript extraction and merges results into the artifacts header — git-sourced artifacts override transcript-parsed ones when both are present.

**Trade-offs:**

| Layer | Cost | Dependency | What it catches |
|-------|------|------------|-----------------|
| 1 (extraction) | Zero — falls out of short tool-result inclusion | Enhanced `_extract_transcript_text` | Artifacts that appear in tool output |
| 2 (text scanning) | ~50 lines, pure functions, no I/O | Layer 1 text available | Structured header with deduplicated artifacts |
| 3 (git query) | ~1s latency, subprocess calls, `git` in PATH | None (reads git directly) | Commits by hooks/background processes, canonical SHAs |

### 2. Web research capture

The PostToolUse/WebFetch hook already auto-ingests fetched URLs. This works. Rename the collection from `web-captures` to `quarry-research` for clarity.

No accumulator needed. The `quarry-research` collection is the accumulator — it persists across sessions and is searchable. The conversation transcript (capability 1) preserves the context around web fetches.

### 3. Knowledge recall hints

The agent should know to check quarry before doing fresh research.

**SessionStart**: Replace the existing `additionalContext` line with a behavioral trigger:

```
Before doing fresh web research on a topic, check quarry first — prior research and conversations are indexed here.
Collection: "{collection_name}" ({directory})
```

This tells the agent _when_ to use quarry (before web research), not just _that_ it exists.

**PreCompact**: After capturing the transcript, return `additionalContext` confirming preservation:

```
Session transcript captured in quarry. Prior conversations are searchable via quarry find.
```

Return dict format: `hookSpecificOutput.hookEventName = "PreCompact"`, `permissionDecision = "allow"`, `additionalContext = <text>`.

---

## Collection naming

Literal names that say what's in them:

| Collection | Contents | Source hook |
|------------|----------|-------------|
| `quarry-code` | Synced project files | SessionStart (auto-register) |
| `quarry-research` | Web pages fetched during sessions | PostToolUse/WebFetch |
| `quarry-conversations` | Session transcripts before compaction | PreCompact |

Rename `web-captures` → `quarry-research` and `session-notes` → `quarry-conversations`. The project's registered collection name stays as-is for code (typically the repo slug, e.g., `quarry`). A follow-up can standardize this to `quarry-code` if warranted.

---

## Implementation

### Modify

- **`src/quarry/hooks.py`** (`handle_pre_compact`):
  - Copy raw JSONL to `{quarry_root}/../sessions/`
  - Enhance `_extract_transcript_text` to include short tool results (<500 chars)
  - Truncate from front instead of back
  - Use `quarry-conversations` collection (rename from `session-notes`)
  - Add compaction-number dedup to document name
  - Lazy cleanup of sessions older than 90 days
  - Extract git artifacts from transcript text (Layer 2) and prepend structured header
  - Return `additionalContext` with recall hint
  - Fall back to `quarry-conversations` when cwd not registered

- **`src/quarry/artifacts.py`** (new):
  - `extract_artifacts(text: str) -> SessionArtifacts` — scan transcript text for commit SHAs, PR numbers, branch names, bead IDs
  - `format_artifacts_header(artifacts: SessionArtifacts) -> str` — render the structured markdown header
  - Pure functions, no I/O, fully testable

- **`src/quarry/hooks.py`** (`handle_post_web_fetch`):
  - Use `quarry-research` collection (rename from `web-captures`)

- **`src/quarry/hooks.py`** (`handle_session_start`):
  - Replace `additionalContext` text with behavioral trigger

- **`src/quarry/hooks.py`** (`_extract_transcript_text`):
  - Add short tool-result extraction (text content <500 chars)
  - Reverse truncation direction (front, not back)

### Migration

Existing documents in `web-captures` and `session-notes` collections are not migrated. New documents go into `quarry-research` and `quarry-conversations`. Old collections remain searchable until explicitly deleted.

---

## Verification

1. Trigger compaction in a session with commits, PRs, and web fetches
2. Verify raw JSONL exists in `{quarry_root}/../sessions/`
3. `quarry find "what did we discuss"` in `quarry-conversations` returns transcript
4. `quarry find "PR #113"` returns the conversation that created/merged it
5. Verify ingested document starts with `## Session Artifacts` header listing commits, PRs, beads
6. `quarry find "some URL topic"` in `quarry-research` returns web content
7. Verify session-start hint says "check quarry first"
8. Verify short tool results appear in ingested transcript, long ones do not
9. Verify second compaction produces `compact-2` document, not a duplicate
10. `make check` — all tests pass
