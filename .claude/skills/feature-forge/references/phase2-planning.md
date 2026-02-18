# Phase 2: SPARC Planning & Beads Translation

## SPARC Plan Creation

Engineering and PM experts collaborate to produce the SPARC plan. The plan must address all four evaluation dimensions.

### S - Specification

Draw directly from the approved PRD:
- **Problem Statement**: Restate from PRD, refined with technical context
- **Success Criteria**: Testable, automated where possible
- **User Stories**: From PRD, with technical acceptance criteria added
- **Functional Requirements**: Derived from user stories
- **Non-Functional Requirements**: Performance, accessibility, compatibility

### P - Pseudocode

For each major component or user story:
- Write pseudocode for key algorithms
- Define API contracts (endpoints, request/response shapes)
- Specify data transformations
- Define state transitions
- Include error handling pseudocode

Format:
```
function <name>(<params>):
    <step-by-step logic>
    <error handling>
    <return value>
```

### A - Architecture

- **File/Module Layout**: Which files to create/modify
- **Component Interactions**: How new code connects to existing systems
- **Database Schema Changes**: If applicable, with migration plan
- **API Design**: New endpoints or modifications
- **State Management**: How state flows through the system

Include a simple diagram where helpful:
```
[Component A] --> [Component B] --> [Database]
                      |
                      v
              [Component C]
```

### R - Refinement

- **Edge Cases**: Enumerate and plan for each
- **Error Handling**: Strategy for each failure mode
- **Configuration**: Any new settings or flags needed
- **Testing Strategy**: Unit, integration, and acceptance test plan
- **Performance Considerations**: Benchmarks or targets
- **Migration/Backwards Compatibility**: If applicable

### C - Completion

- **Definition of Done**: Clear, verifiable criteria
- **Task Breakdown**: Ordered list of implementation tasks
- **Acceptance Criteria**: Per-task and overall
- **Deliverables Checklist**: All artifacts that must be produced

## Four-Dimensional Evaluation

Before finalizing, evaluate the SPARC plan against:

### Usability
- Is the solution intuitive for the target user?
- Does it follow existing UX patterns?
- Is the learning curve acceptable?
- Are error messages clear and actionable?

### Value
- Does it solve the user's stated problem?
- Is the solution proportional to the problem?
- Does it create lasting value or is it a band-aid?
- Will users notice and appreciate the improvement?

### Feasibility
- Can it be built with current tools and architecture?
- What is the implementation risk?
- Are there unknown unknowns?
- Is the testing strategy adequate?

### Viability
- Is it maintainable long-term?
- Does it align with the system's architectural direction?
- Does it create or reduce technical debt?
- Is the scope sustainable?

## Beads Translation

### Creating Issues

Convert each task from the SPARC Completion section into a bead:

```bash
bd create --title="<task title>" --type=<task|bug|feature> --priority=<0-4>
```

Priority mapping:
- P0 (critical): Core functionality, blocking
- P1 (high): Important for completeness
- P2 (medium): Standard implementation tasks
- P3 (low): Polish and optimization
- P4 (backlog): Nice-to-have enhancements

### Setting Dependencies

Map task ordering from the SPARC plan to bead dependencies:

```bash
bd dep add <child-bead-id> <parent-bead-id>
```

Common dependency patterns:
- API foundation before UI implementation
- Schema changes before data access code
- Core logic before edge case handling
- Unit tests alongside implementation
- Integration tests after component completion

### Efficiency Tips

When creating many beads, use parallel subagents via the Task tool:

```
Task(subagent_type: "Bash", prompt: "bd create --title='...' --type=task --priority=2")
```

Launch multiple in parallel when they don't depend on each other's IDs.

### Adding Context to Beads

Each bead should have enough context for an engineer to implement it independently:

```bash
bd update <id> --description "## Context
<relevant PRD section>

## Implementation
<relevant SPARC pseudocode>

## Success Criteria
- [ ] <testable criterion 1>
- [ ] <testable criterion 2>

## Files to Modify
- <file path 1>
- <file path 2>"
```

## Phase Transition

**Autonomous mode (default):** Write the SPARC plan to disk, create all beads with dependencies, summarize the plan and bead count inline, and proceed directly to Phase 3.

**Review mode (user explicitly requested review/confirmation):** Present to the user:
1. The complete SPARC plan
2. The beads breakdown with dependencies
3. Total estimated scope
4. Recommended implementation order

Ask: "Should I proceed to implementation, or would you like to adjust the plan?"

## Output Artifacts

- `docs/sparc/<feature-name>-implementation.md` - The SPARC plan
- Beads issues in `.beads/issues.jsonl` with dependencies configured
