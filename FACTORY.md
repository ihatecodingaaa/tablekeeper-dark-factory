# The factory

Four Claude Code seats in one Band room build the service one stage at a time. One human
dispatch starts the run, and there is no human input until the final report.

## Seats

| Seat | Owns |
|---|---|
| `architect-x7qk` (Architect / Coordinator) | Reads the requirements and splits each stage into work items with clear file ownership. Integrates seat branches into `main`, runs the coordinator gate and hands exact revisions to the verifier |
| `developer-x7qk` (Developer) | Core logic and data correctness: domain rules, persistence, concurrency, idempotency, state round-trips |
| `product-engineer-x7qk` (Product Engineer) | The delivered interface: HTTP boundary, browser product, packaging (`Dockerfile`, `RUN.md`) and user-facing polish |
| `independent-verifier-x7qk` (Independent Verifier) | Writes its own black-box tests from the requirements in a separate workspace. Gives a binding ACCEPT or REJECT on one exact revision |

The mandates in `mandates/` are generic, so the same seats could build a different product.

## Flow per stage

1. The Architect reads the stage requirements. It pastes the complete requirement text and a
   scoped task into the room for each seat. Long handoffs are split into numbered messages.
2. The Developer and Product Engineer work test-first on their own branches and post each
   committed revision in the room.
3. The Architect merges with `--no-ff` and runs the full gate: unit, HTTP, browser, the
   container build and the supplied stage checks in isolated mode. It also confirms that
   earlier, accepted stage folders are byte-identical.
4. The Verifier builds the exact revision from a clean clone. It runs its own
   requirement-derived suite, regressions for earlier stages and the isolated checks.
5. A REJECT goes back through the room as concrete defects, which are fixed and
   re-verified. On ACCEPT the stage folder is frozen and the next stage starts as a copy
   of it.

Run log, costs and lessons are recorded below as the run proceeds.
