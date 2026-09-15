---
name: iteration-closeout
description: Close a CU013 repository iteration by reconciling Documentation as Code, running applicable quality gates, updating current-state artifacts, and reporting Git state without committing or pushing unless explicitly authorized.
compatibility: opencode
metadata:
  project: cu013
  workflow: iteration-closeout
---

# Iteration Closeout

Close one implemented/accepted iteration so no artifact, gate, or Git state is left inconsistent.

## When to use

Use at the end of an implemented/accepted iteration, before commit, integration, or handoff. Do not use to design architecture or decide requirements.

## Inputs

Read only what the diff actually touches:

- `AGENTS.md` for workflow, gates, and STOP rules.
- `CONTEXT.md` for the current-state snapshot.
- `CHANGELOG.md` for the `[Unreleased]` section.
- Affected specs, ADRs, experiments, and gaps under `docs/`.
- `pyproject.toml` for the canonical gate configuration.
- Git state and diff (`git status`, `git diff`, `git diff --cached`).
- Test and gate results produced during the iteration.

## Procedure

Follow this order:

1. Inspect `git status`, the diff, and the real scope of the iteration.
2. Identify which canonical artifacts went stale (per the Documentation lifecycle table in `AGENTS.md`).
3. Reconcile `docs/gaps.md`: move each resolved outcome to its spec, ADR, experiment, runbook, or `CONTEXT.md`, then remove the gap. Never use `docs/gaps.md` as a second spec or backlog.
4. Update a spec, ADR, experiment, or runbook only when the iteration really changed its authority, evidence, or procedure. Do not invent new decisions to make the iteration "close".
5. Run only gates applicable to artifacts that exist (see Quality checks).
6. Verify Markdown links, contradictions across spec / Accepted ADR / implementation / evidence, and scan for secrets, credentials, PII, and accidental files.
7. Update `CHANGELOG.md` under `[Unreleased]` when the change is version-relevant.
8. Update `CONTEXT.md` last, using only accepted and verified state.
9. Revalidate the diff and Git state after all edits.
10. Return the closeout evidence (see Outputs).

## Quality checks

Minimum set:

- `git diff --check` clean.
- Markdown links valid.
- Secret/credential scan clean (no `.env`, keys, tokens, passwords, raw DTMF beyond the strict validation need).
- Applicable `pytest` / Ruff / MyPy gates pass; never run nonexistent targets.
- `codegraph sync` + `codegraph status` when structure changed.
- No stale active gaps left behind.
- No contradiction between spec, Accepted ADR, implementation, and evidence.

## Outputs

Return:

- Reconciled files (per file: what changed and why).
- Gates executed and their result.
- Gaps resolved vs. still open.
- `CONTEXT.md` / `CHANGELOG.md` changes.
- Final `git status`.
- Remaining blockers.

## STOP conditions

STOP & REPORT when:

- The implementation contradicts a spec or an Accepted ADR.
- Resolving a gap requires inventing a contract or business rule.
- Required evidence is missing to claim something was validated.
- An applicable mandatory gate fails.
- Accidental secrets or PII appear.
- Closing requires new architecture, infrastructure, or an unapproved dependency.

## Git boundary

By default: NO commit, NO push, NO deploy. Execute those actions only when the current task explicitly authorizes them and `AGENTS.md` also permits them.
