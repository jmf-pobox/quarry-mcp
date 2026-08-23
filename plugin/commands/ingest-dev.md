---
description: Ingest a URL, directory, or file into your knowledge base
argument-hint: "<url, directory, or file path>"
---
<!-- markdownlint-disable MD041 -->

## Input

Arguments: $ARGUMENTS

Determine the ingestion method:

1. If it starts with `http://` or `https://`: **URL** (auto-discovers sitemaps)
2. Otherwise it's a local path — a directory or a single file: **Local path**
   (indexed via directory registration + sync; the `ingest` tool itself only
   accepts URLs, so a local file is reached by registering the directory that
   contains it — this indexes the whole directory, not just the one file)

Expand `~` to the user's home directory before calling any tool.

## Task

Call the appropriate tool(s):

- **URL**: `mcp__plugin_quarry-dev_quarry__ingest` with `source` set to the argument
- **Local path**: Call `mcp__plugin_quarry-dev_quarry__register_directory` with
  `directory` set to the absolute path. If it errors because the path is a
  file, retry with the path's parent directory instead. Then call
  `mcp__plugin_quarry-dev_quarry__sync_all_registrations`

The result is already formatted by a PostToolUse hook and displayed above. Do not repeat or reformat the data. Do not send any text after the tool call.
