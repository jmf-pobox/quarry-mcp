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
   (register the containing directory + sync; the `ingest` tool only accepts
   URLs — there is no in-process file loader)

Expand `~` to the user's home directory before calling any tool.

## Task

Call the appropriate tool(s):

- **URL**: `mcp__plugin_quarry-dev_quarry__ingest` with `source` set to the argument
- **Local path**: Call `mcp__plugin_quarry-dev_quarry__register_directory` with
  `directory` set to the absolute path (its parent directory, if the argument
  is a single file), then call `mcp__plugin_quarry-dev_quarry__sync_all_registrations`

The result is already formatted by a PostToolUse hook and displayed above. Do not repeat or reformat the data. Do not send any text after the tool call.
