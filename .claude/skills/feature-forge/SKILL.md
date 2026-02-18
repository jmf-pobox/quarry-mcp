---
name: feature-forge
description: This skill should be used when the user describes an observation, problem, or feature idea and wants end-to-end design and implementation. Triggers include "I notice...", "feature forge", "design and implement this", "hive-mind PRD", "end-to-end feature", or when the user describes a problem and expects a full product development cycle from PRD through implementation. This skill orchestrates a multi-phase workflow using hive-mind consensus, SPARC planning, beads issue tracking, and ralph-loop iteration.
---

# Feature Forge

Orchestrate end-to-end feature development from a user observation through PRD consensus, SPARC planning, and verified implementation using multi-agent hive-minds.

## Autonomy Mode

By default, Feature Forge runs **autonomously** - proceeding through all phases without stopping for user confirmation. The hive-mind consensus process provides the quality gate between phases.

**Always stop** when:
- A genuine ambiguity exists that the hive-mind cannot resolve (e.g., two equally valid approaches with different trade-offs and no clear winner)
- The user's observation is too vague to act on confidently
- Implementation reveals the scope is dramatically larger than the observation implied

**Stop for review** when the user explicitly requests it using phrases like:
- "let me review", "ask me to confirm", "check with me before..."
- "be cautious", "go slow", "I want to approve each phase"
- "review mode", "confirm before implementing"

When the user requests review mode, present artifacts (PRD, SPARC plan, beads) at each phase transition and wait for approval. Otherwise, proceed continuously, writing artifacts to disk and summarizing progress inline as work progresses.

## Workflow Overview

```
User Observation
       |
       v
  Phase 1: Discovery & PRD
  (Hive-Mind: PM, Design, UX, Engineering, Domain Expert)
  - Explore current implementation
  - Ideate on solutions
  - Produce PRD(s)
  - Reach unanimous consensus
       |
       v
  Phase 2: SPARC Planning
  (Engineering + PM experts)
  - Create SPARC plan (S-P-A-R-C)
  - Evaluate: usability, value, feasibility, viability
  - Translate into beads issues with dependencies
       |
       v
  Phase 3: Implementation & Verification
  (Engineering Hive-Mind + Ralph Loop)
  - Implement beads in dependency order
  - Clear success criteria per bead
  - Chrome MCP acceptance testing (if available)
  - Ralph-loop iteration until proven correct
       |
       v
  Session Close Protocol
  (git push, bd sync)
```

## Phase 1: Discovery & PRD

### 1.1 Initialize the Hive-Mind

Use MCP tools to initialize a mesh-topology hive-mind:

```
mcp__claude-flow__hive-mind_init(queenId: "forge-queen", topology: "mesh")
```

### 1.2 Spawn Expert Agents

Spawn five specialist agents. Select the domain expert based on the user's observation:

```
mcp__claude-flow__hive-mind_spawn(count: 1, agentType: "specialist", prefix: "forge-pm", role: "specialist")
mcp__claude-flow__hive-mind_spawn(count: 1, agentType: "specialist", prefix: "forge-design", role: "specialist")
mcp__claude-flow__hive-mind_spawn(count: 1, agentType: "specialist", prefix: "forge-ux", role: "specialist")
mcp__claude-flow__hive-mind_spawn(count: 1, agentType: "specialist", prefix: "forge-eng", role: "specialist")
mcp__claude-flow__hive-mind_spawn(count: 1, agentType: "specialist", prefix: "forge-domain", role: "specialist")
```

### 1.3 Explore Current Implementation

Before ideation, explore the codebase to understand the current state. Use the Explore agent or direct tool calls to:
- Find relevant source files
- Understand existing data flows
- Identify where the problem manifests
- Document current behavior

Store findings in hive-mind shared memory:
```
mcp__claude-flow__hive-mind_memory(action: "set", key: "current-implementation", value: "<findings>")
```

### 1.4 Expert Ideation

Each expert analyzes the observation from their perspective. Broadcast the user's observation and implementation context to all agents. Consult `references/expert-personas.md` for the perspective each expert should take.

### 1.5 PRD Synthesis & Consensus

Synthesize expert perspectives into one or more PRDs. Use the consensus mechanism to reach unanimous agreement:

```
mcp__claude-flow__hive-mind_consensus(action: "propose", type: "prd-approval", value: "<PRD content>")
```

All experts must vote in favor. If any expert dissents, revise the PRD addressing their concerns and re-propose. Continue until unanimous consensus (maximum 5 rounds).

Write the approved PRD to `docs/prd/<feature-name>.md`.

### 1.6 Phase Transition

**Autonomous mode (default):** Write the PRD to `docs/prd/<feature-name>.md`, summarize key decisions inline, and proceed directly to Phase 2. If any genuine ambiguity remains that the hive-mind could not resolve, stop and ask only about that specific question.

**Review mode:** Present the consensus PRD to the user for review. Ask if they want to proceed, modify, or reject. Only advance to Phase 2 after user approval.

---

## Phase 2: SPARC Planning

### 2.1 Create SPARC Plan

Engineering and PM experts collaborate to produce a complete SPARC plan:

- **S - Specification**: Problem statement, success criteria, user stories (P0/P1/P2)
- **P - Pseudocode**: Key algorithms, data flows, API contracts
- **A - Architecture**: System design, file/module layout, schema changes
- **R - Refinement**: Edge cases, error handling, configuration, testing strategy
- **C - Completion**: Definition of done, task breakdown, acceptance criteria

Evaluate the plan against four dimensions:
- **Usability**: Is the solution intuitive and accessible?
- **Value**: Does it solve the user's actual problem?
- **Feasibility**: Can it be built with current tools and architecture?
- **Viability**: Is it maintainable and consistent with system direction?

Write the SPARC plan to `docs/sparc/<feature-name>-implementation.md`.

### 2.2 Translate to Beads

Convert each SPARC phase/task into beads issues:

```bash
bd create --title="<task title>" --type=task --priority=<0-4>
```

Set up dependencies between beads:
```bash
bd dep add <child-bead> <parent-bead>
```

Use parallel subagents when creating multiple beads for efficiency.

### 2.3 Phase Transition

**Autonomous mode (default):** Write the SPARC plan to disk, create the beads, summarize the plan and bead count inline, and proceed directly to Phase 3.

**Review mode:** Present the SPARC plan and beads breakdown to the user. Ask for approval before implementation.

---

## Phase 3: Implementation & Verification

### 3.1 Launch Engineering Hive-Mind

Initialize a new hive-mind for implementation:

```
mcp__claude-flow__hive-mind_init(queenId: "forge-impl-queen", topology: "hierarchical")
mcp__claude-flow__hive-mind_spawn(count: 3, agentType: "worker", prefix: "forge-impl", role: "worker")
```

### 3.2 Implement Beads

Work through beads in dependency order (`bd ready` to find unblocked work). For each bead:

1. Claim: `bd update <id> --status in_progress`
2. Implement the changes with clear, testable code
3. Run tests: `PYTHONPATH=src pytest` (or project-appropriate test command)
4. Close: `bd close <id>`

### 3.3 Acceptance Testing

Define clear success criteria for each bead. If Chrome MCP tools are available (check with ToolSearch for "chrome-devtools"), use them for web UI verification:
- Navigate to relevant pages
- Verify UI elements render correctly
- Test user interactions
- Capture screenshots for evidence

### 3.4 Ralph-Loop Iteration (When Appropriate)

For beads with complex or hard-to-verify success criteria, use the ralph-loop for iterative refinement:

```
/ralph-loop "Implement <bead description>. Success criteria: <criteria>. Run tests and verify." --completion-promise "ALL TESTS PASS AND ACCEPTANCE CRITERIA MET" --max-iterations 10
```

Ralph-loop is appropriate when:
- The task has clear, testable success criteria
- Multiple iterations may be needed to get it right
- Automated verification (tests, type checks) can confirm completion

Ralph-loop is NOT appropriate when:
- Design judgment is needed
- Requirements are ambiguous
- The task is a one-shot operation

### 3.5 Final Verification

After all beads are complete:
1. Run full test suite
2. Run linters/type checks
3. Verify all beads are closed: `bd list --status=open`
4. Do a final walkthrough of the feature

---

## Session Close

Follow the mandatory session close protocol:

```bash
git status
git add <changed files>
bd sync
git commit -m "<descriptive message>"
bd sync
git push
```

---

## Additional Resources

### Reference Files

Consult these for detailed guidance on each phase:
- **`references/expert-personas.md`** - Expert role definitions and perspectives for Phase 1
- **`references/phase1-discovery.md`** - Detailed hive-mind PRD generation workflow
- **`references/phase2-planning.md`** - SPARC plan creation and beads translation
- **`references/phase3-implementation.md`** - Engineering hive-mind, testing, and ralph-loop patterns
