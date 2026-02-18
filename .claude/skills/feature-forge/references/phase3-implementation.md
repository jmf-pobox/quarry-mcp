# Phase 3: Implementation & Verification

## Engineering Hive-Mind Setup

### Initialize Implementation Hive

Use hierarchical topology for implementation (queen coordinates, workers implement):

```
mcp__claude-flow__hive-mind_init(queenId: "forge-impl-queen", topology: "hierarchical")
```

Spawn workers based on scope:
- Small feature (1-3 beads): 1-2 workers
- Medium feature (4-8 beads): 2-3 workers
- Large feature (9+ beads): 3-5 workers

```
mcp__claude-flow__hive-mind_spawn(count: <N>, agentType: "worker", prefix: "forge-impl", role: "worker")
```

### Worker Assignment

The queen (orchestrator) assigns beads to workers based on:
1. Dependency order (`bd ready` shows unblocked work)
2. File proximity (related files go to same worker)
3. Skill alignment (frontend vs backend vs data)

## Implementation Loop

For each bead, follow this cycle:

### 1. Claim the Bead
```bash
bd update <id> --status in_progress
```

### 2. Read Requirements
Retrieve the bead's description to understand:
- What to implement
- Success criteria
- Files to modify

### 3. Implement

Write code following these principles:
- Minimal changes to achieve the goal
- Follow existing code patterns and style
- Add tests alongside implementation
- Handle error cases identified in SPARC plan

### 4. Test

Run the project's test suite:
```bash
PYTHONPATH=src pytest <relevant test files> -v
```

If tests exist for the affected area, run them first. Then run the full suite:
```bash
PYTHONPATH=src pytest
```

Also run any linters or type checkers:
```bash
PYTHONPATH=src python -m mypy src/<path> --ignore-missing-imports
```

### 5. Verify Success Criteria

Check each success criterion from the bead description. Mark as done only when all criteria are met.

### 6. Close the Bead
```bash
bd close <id>
```

### 7. Check for Newly Unblocked Work
```bash
bd ready
```

## Chrome MCP Acceptance Testing

When the feature involves web UI changes, use Chrome DevTools MCP for verification.

### Checking Availability

```
ToolSearch(query: "chrome-devtools")
```

If Chrome MCP tools are available, use them for acceptance testing.

### Testing Pattern

1. **Navigate to the page**:
```
mcp__chrome-devtools__navigate_page(url: "http://127.0.0.1:8765/<path>")
```

2. **Take a snapshot to understand current state**:
```
mcp__chrome-devtools__take_snapshot()
```

3. **Interact with UI elements**:
```
mcp__chrome-devtools__click(selector: "<css selector>")
mcp__chrome-devtools__fill(selector: "<css selector>", value: "<text>")
```

4. **Verify results**:
```
mcp__chrome-devtools__take_screenshot()
```

5. **Check for errors**:
```
mcp__chrome-devtools__list_console_messages()
```

### Web Server Setup

Ensure the web server is running before UI testing:
```bash
PYTHONPATH=src uvicorn lattice_web.server:get_app --factory --host 127.0.0.1 --port 8765 &
```

Wait for startup, then proceed with tests. Remember to stop the server when done.

## Ralph-Loop Integration

### When to Use Ralph-Loop

Ralph-loop is ideal for beads where:
- Success criteria are clearly testable (tests pass, linter clean)
- The implementation may need several attempts
- The completion state is unambiguous

### Ralph-Loop Pattern

```
/ralph-loop "<implementation prompt>" --completion-promise "<promise>" --max-iterations <N>
```

### Crafting the Prompt

Include in the ralph-loop prompt:
1. The bead's full description and context
2. Specific files to modify
3. Success criteria that can be verified programmatically
4. Test commands to run

Example:
```
/ralph-loop "Implement input sanitization for entity names in src/lattice/extract.py.
Strip leading/trailing quotes (single, double, smart quotes), normalize whitespace,
and trim leading/trailing whitespace. Add tests in tests/test_extract.py.
Success: PYTHONPATH=src pytest tests/test_extract.py -v passes with all new tests green."
--completion-promise "ALL TESTS PASS" --max-iterations 10
```

### Crafting the Completion Promise

The promise should be:
- Verifiable by running a command
- Unambiguous (either true or false)
- Tied to the actual success criteria

Good promises:
- "ALL TESTS PASS"
- "LINTER CLEAN AND TESTS PASS"
- "FEATURE COMPLETE AND ALL ACCEPTANCE CRITERIA MET"

Bad promises:
- "DONE" (too vague)
- "LOOKS GOOD" (subjective)
- "MOSTLY WORKING" (not unambiguous)

### Max Iterations

Set based on complexity:
- Simple bug fix: 3-5 iterations
- New function with tests: 5-10 iterations
- Complex feature with UI: 10-15 iterations
- Multi-file refactor: 10-20 iterations

## Final Verification

After all beads are implemented:

### 1. Full Test Suite
```bash
PYTHONPATH=src pytest -v
```

### 2. Open Bead Check
```bash
bd list --status=open
```
All feature-related beads should be closed.

### 3. Code Quality
```bash
PYTHONPATH=src python -m mypy src/ --ignore-missing-imports
```

### 4. Feature Walkthrough

If the feature has UI components, do a complete walkthrough:
- Navigate through all new/modified pages
- Test happy path
- Test error paths
- Test edge cases from SPARC refinement section
- Verify keyboard shortcuts if applicable
- Check accessibility if applicable

### 5. Git Hygiene

Review all changes before committing:
```bash
git diff --stat
git diff
```

Ensure:
- No debug code left in
- No commented-out code
- No unintended file changes
- All new files are necessary

## Failure Handling

### Test Failures
If tests fail after implementation:
1. Analyze the failure
2. If it's in the new code: fix it
3. If it's a pre-existing failure: note it and move on
4. If it's a regression: investigate and fix before closing the bead

### Bead Blocked
If a bead can't be implemented as planned:
1. Keep it as `in_progress`
2. Create a new bead describing the blocker
3. Add the blocker as a dependency
4. Move to the next unblocked bead

### Scope Discovery
If implementation reveals more work is needed:
1. Create new beads for discovered work
2. Set appropriate dependencies
3. Inform the user about scope change
4. Continue with unblocked work
