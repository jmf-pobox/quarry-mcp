---
description: Ingest a URL, sitemap, or file into your knowledge base
argument-hint: "<url or path>"
---
<!-- markdownlint-disable MD041 -->

## Input

Arguments: $ARGUMENTS

Parse the argument to determine the ingestion method:

- If it starts with `http://` or `https://`: use `ingest_auto` (auto-discovers sitemaps)
- Otherwise: use `ingest_file`

## Task

Call the appropriate tool:

- **URL**: `mcp__plugin_quarry_quarry__ingest_auto` with `url` set to the argument
- **File**: `mcp__plugin_quarry_quarry__ingest_file` with `file_path` set to the argument

The result is already formatted by a PostToolUse hook and displayed above. Do not repeat or reformat the data. Do not send any text after the tool call.
