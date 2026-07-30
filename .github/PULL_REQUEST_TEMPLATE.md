## What

<!-- One sentence: what does this change do? -->

## Why

<!-- Why is this change needed? Link to the issue or roadmap item it closes. -->

Closes #

---

## Definition of done

Work through this before marking the PR ready for review. Each item maps directly to a rule in `AGENTS.md` or `CONTRIBUTING.md`. Unchecked items block merge.

### Before opening

- [ ] `uvx pre-commit run --all-files` passes locally
- [ ] `uv run mypy .` passes in every service you touched
- [ ] CI is green on this branch
- [ ] PR is scoped to one service or one concern

### Code

- [ ] No comments that explain what code does; only non-obvious *why* (safety invariant, external bug workaround, invariant a reader could accidentally break)
- [ ] No speculative abstraction; built only for the feature in front of you
- [ ] Error handling only at real input/API/IO boundaries, not between internal functions that already trust each other
- [ ] No partially finished work; stubs with `NotImplementedError` + open issue are fine, half-working features pretending to be done are not

### Tests

- [ ] New behavior has a test that fails without it (skip only for pure scaffolding/config)
- [ ] External services mocked (LLM providers, calendar APIs, OS-level deps); code you own is exercised for real
- [ ] Tests target the service boundary (its API, its public functions), not mocked internals
- [ ] All new functions, parameters, and test fixtures have complete type annotations

### Dependencies

- [ ] New runtime deps are MIT / Apache-2.0 / BSD licensed
- [ ] Eval-only or test-only deps live in the correct dependency group, not in `dependencies`

### Service boundaries

- [ ] No imports across `services/` directories
- [ ] No service opens another service's SQLite file directly; data goes through `services/storage` API
- [ ] Logic shared by more than one service lives in `packages/`, not in a relative cross-service import

### If this PR touches `.github/workflows/`

- [ ] All action references pinned to a commit SHA with an inline version comment
- [ ] No `curl | sh` or remote code execution without checksum verification
- [ ] Every new job has `timeout-minutes`
- [ ] Jobs that only apply to specific paths use `if: needs.changes.outputs.X == 'true'`
- [ ] Shell steps pass `shellcheck` (no unquoted variables, `set -e` or `set -euo pipefail`)

### Docs

- [ ] `docs/` updated if this changes anything described there (a stale architecture doc is worse than no doc)
