# UASAE Architecture

## The three-layer separation

```
INTELLIGENCE  → "What should we do?"       → AI/LLM agentic layer
VERIFICATION  → "Execute this precisely."  → Deterministic execution engines
EVIDENCE      → "What actually happened?"  → Observed outputs
```

The AI dominates the first. Deterministic software dominates the second. Observed evidence dominates the third. This separation is what makes the architecture credible.

## Canonical workflow

```
Ingest → Understand → Establish Current Truth → Model → Assess Risk →
Plan → Compile → Execute → Observe → Evaluate → Investigate → Learn → Reverify → Assure
```

## Canonical evidence chain

```
Intent → Requirement → Behavior → Implementation → Verification Case →
Scenario → Execution → Evidence → Verdict → Defect → Regression
```

## Build phases

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Constitution & SSOT | ✅ Done |
| 1 | Repository Understanding | 🔄 Active |
| 2 | Verification Case Engine | Planned |
| 3 | Deterministic Execution (API/Browser/DB) | Planned |
| 4 | Evidence & Verdict | Planned |
| 5 | Risk & Intelligent Planning | Planned |
| 6 | Autonomous Investigation | Planned |
| 7 | Temporal Intelligence | Planned |
| 8 | Advanced Verification | Planned |
| 9 | Agent Layer | Planned |
| 10 | MCP | Planned |
| 11 | Continuous Assurance | Planned |
| 12 | Self-Verifying Assurance | Planned |
| 13 | Universal Adapter Ecosystem | Planned |

## Key design decisions

- **Backend: FastAPI/Python** — AI orchestration, AST analysis, and evidence pipelines are better suited to Python than Next.js routes.
- **Adapters are non-negotiable** — every execution backend (browser, API, DB, events) implements `ExecutionAdapter`. The core never imports a specific browser or HTTP framework directly.
- **Artifact content is untrusted** — treated as data input, never as agent instructions (prompt injection boundary).
- **Production defaults to READ ONLY** — destructive operations require explicit policy authorization.
