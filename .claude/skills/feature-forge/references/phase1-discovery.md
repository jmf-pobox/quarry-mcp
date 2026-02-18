# Phase 1: Discovery & PRD Generation

## Detailed Workflow

### Step 1: Capture the Observation

Record the user's exact words as the starting point. The observation is the ground truth - everything flows from it.

Store in hive-mind shared memory:
```
mcp__claude-flow__hive-mind_memory(action: "set", key: "user-observation", value: "<exact user quote>")
```

### Step 2: Codebase Exploration

Before any ideation, thoroughly explore the current implementation. Use the Task tool with subagent_type=Explore to understand:

1. **Where the problem manifests**: Find the specific code paths where the observed behavior occurs
2. **Data flow**: Trace how data moves through the system relevant to the observation
3. **Existing handling**: Identify any existing code that attempts to address similar concerns
4. **Test coverage**: Check what tests exist for the affected areas
5. **Configuration**: Find any settings or flags related to the observed behavior

Store structured findings:
```
mcp__claude-flow__hive-mind_memory(action: "set", key: "codebase-analysis", value: {
  "affected_files": ["<file paths>"],
  "data_flow": "<description>",
  "existing_handling": "<description>",
  "test_coverage": "<description>",
  "configuration": "<description>"
})
```

### Step 3: Expert Analysis

Each expert analyzes the observation and codebase findings from their perspective. Use broadcast to share the analysis prompt:

```
mcp__claude-flow__hive-mind_broadcast(
  message: "Analyze this observation from your expert perspective: <observation>. Codebase context: <findings>. Provide: (1) root cause analysis, (2) proposed solution approach, (3) risks and concerns, (4) success criteria from your perspective.",
  priority: "high"
)
```

### Step 4: Synthesize PRD

Collect all expert analyses and synthesize into a structured PRD:

```markdown
# PRD: <Feature Name>

**Status:** Draft
**Date:** <date>
**Origin:** User observation: "<exact quote>"

## Problem Statement
<Synthesized from all expert analyses>

## Root Cause Analysis
<From engineering and domain experts>

## Proposed Solution
<Synthesized approach that addresses all expert concerns>

## User Stories

### P0 - Must Have
| ID | Story | Acceptance Criteria |
|----|-------|---------------------|
| US-1 | ... | ... |

### P1 - Important
| ID | Story | Acceptance Criteria |
|----|-------|---------------------|

### P2 - Nice to Have
| ID | Story | Acceptance Criteria |
|----|-------|---------------------|

## Design Considerations
<From design and UX experts>

## Technical Considerations
<From engineering expert>

## Domain Considerations
<From domain expert>

## Success Metrics
<From PM, measurable criteria>

## Risks & Mitigations
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| ... | H/M/L | H/M/L | ... |

## Out of Scope
<Explicitly excluded items>

## Open Questions
<Unresolved items requiring user input>
```

### Step 5: Consensus Voting

Propose the PRD for consensus:

```
mcp__claude-flow__hive-mind_consensus(
  action: "propose",
  type: "prd-approval",
  value: "<PRD content or reference to stored memory key>"
)
```

For each expert, cast their vote:
```
mcp__claude-flow__hive-mind_consensus(
  action: "vote",
  proposalId: "<proposal-id>",
  vote: true/false,
  voterId: "<expert-agent-id>"
)
```

Check status:
```
mcp__claude-flow__hive-mind_consensus(action: "status", proposalId: "<proposal-id>")
```

### Step 6: Iteration on Dissent

If any expert votes against:

1. Record the specific objection
2. Analyze whether the objection is:
   - A missing requirement (add it)
   - A conflicting requirement (facilitate trade-off)
   - A scope concern (adjust scope)
   - A feasibility concern (revisit approach)
3. Revise the PRD
4. Re-propose for consensus

### Step 7: Phase Transition

**Autonomous mode (default):** Write the PRD to disk, summarize key decisions and scope inline, and proceed directly to Phase 2. Only stop if the PRD has genuinely unresolvable open questions that require user input - ambiguities the hive-mind could not resolve despite trying.

**Review mode (user explicitly requested review/confirmation):** Present the consensus PRD to the user with:
- Summary of what was agreed
- Key design decisions made
- Any trade-offs that were resolved
- Estimated scope (story points or T-shirt sizing)

Ask: "Should I proceed to SPARC planning, or would you like to modify this PRD?" Only proceed after explicit user approval.

## Output Artifacts

- `docs/prd/<feature-name>.md` - The approved PRD
- Hive-mind memory with analysis context for Phase 2
