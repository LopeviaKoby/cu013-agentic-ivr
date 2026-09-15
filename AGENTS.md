# CU013 v0.2.0 — Agent Instructions

CU013 builds the Help Desk telephone conversational backend for XCALLY Motion and Cally Square.

## Authority

Apply this precedence:

1. the owner's current explicit instructions;
2. corporate IOPs supplied in `docs/iop/` for authoritative business procedures;
3. the current [system specification](docs/specs/system.md) and [account-actions specification](docs/specs/account-actions.md) for CU013 behavior and invariants;
4. decisions with `Status: Accepted`;
5. code and configuration for implemented behavior;
6. tests and traces for validated behavior;
7. this file;
8. skills.

IOPs define business procedure. XCALLY/Cally Square and Orchestrator/TIVIT define the currently authorized execution mechanism. The CU013 specs combine both without rewriting the IOPs. The PDFs under `docs/iop/` are owner-supplied, local, read-only for agents and Git-ignored; their `README.md` manifest is versioned.

Context7, technical documentation and analysis tools are not sources of CU013 business requirements.

## Repository tools

Use CodeGraph by default for structure, relationships, symbols, dependencies and impact:

1. run `codegraph status`;
2. run `codegraph init` only when no configuration exists;
3. run `codegraph index` to create or update the index;
4. use `codegraph files` and `codegraph context` when they help narrow inspection;
5. always verify details against the actual files;
6. reindex after relevant structural changes.

A missing index does not justify skipping CodeGraph when a task requires codebase relationships. If cleanup leaves zero symbols, or CodeGraph cannot represent relevant content, record that fact and use filesystem inspection.

CodeGraph versus literal search applies both to its CLI and to the `codegraph_*` MCP tools exposed through `opencode.json`:

| Question | Command |
|---|---|
| Where is X defined? / Symbol named X | `codegraph query <name>` |
| What calls Y? | `codegraph callers <symbol>` |
| What does Y call? | `codegraph callees <symbol>` |
| What would changing Z affect? | `codegraph impact <symbol>` |
| Signature/source/docstring of Y | `codegraph node <symbol>` |
| Focused context for a task | `codegraph context <task>` |
| Explore an unfamiliar module | `codegraph explore <topic>` |
| Which files are under a path? | `codegraph files` |
| Is the index healthy? | `codegraph status` |

Rules:

- CodeGraph answers structural questions: definitions, calls, impact and signatures. Use filesystem search/read for literal text such as strings, comments and logs, or when the exact file is already known.
- Prefer one focused `context` or `explore` call over a chain of `query` and `node` calls.
- `explore` can return substantial source. Keep broad exploration bounded so it does not overwhelm the working context.
- The watcher may take about 500 ms to observe writes. Run `codegraph sync` before querying newly edited structure in the same turn.
- CodeGraph results originate from AST parsing. They are a starting point; the actual files remain authoritative.

`.codegraph/` is local to each machine and is never committed; `codegraph init` recreates it. The `codegraph` MCP server (`codegraph serve --mcp`) is configured through the repository's `opencode.json`. Do not introduce Claude-specific artifacts such as `.claude/` or `.claude.json`; this repository uses OpenCode.

Use Context7 for current syntax, versions and capabilities of libraries, SDKs, APIs and CLIs. Resolve the library ID first and query it with the full question. If it does not resolve the uncertainty, use only current or version-matched official documentation.

Use the filesystem for exact Markdown, YAML, JSON, TOML, XML, script and configuration content.

## Engineering authority

- [`pyproject.toml`](pyproject.toml) governs executable Ruff, MyPy and pytest configuration.
- [Python standards](docs/engineering/python.md), [reliability standards](docs/engineering/reliability.md) and [testing standards](docs/engineering/testing.md) govern conventions that tooling cannot express.
- The current specs and Accepted ADRs always prevail over engineering standards.

Active implementation gaps live in [`docs/gaps.md`](docs/gaps.md) and must be reconciled at every iteration close. Move a resolved outcome to the applicable spec, ADR, experiment, runbook or `CONTEXT.md`, then remove the gap. Never use `docs/gaps.md` as a second spec or general backlog.

## Invariants

- Do not replace XCALLY Motion or Cally Square.
- The LLM owns language and conversation; runtime owns legality, truth, authorization, state and side effects.
- Firestore is the only durable store and LangGraph is the orchestration framework.
- Do not use keyword/regex semantic routing, a large FSM, multi-agent orchestration, RAG/vector databases or a custom orchestrator.
- Tools represent external capabilities, not internal state mutation.
- A normal turn targets one model call; more than two sequential model calls requires STOP & REPORT.
- Do not add infrastructure, dependencies or abstractions without an evidenced problem and approval.
- GitHub Actions is the CI/CD platform.

## Account actions and security

The first slice is `RESET_PASSWORD` plus `UNLOCK_ACCOUNT`, with no mandatory priority. Initial identity validation uses DTMF for document ID and date of birth.

Raw DTMF values must not enter the LLM, logs or durable state beyond the strict validation need. A validated identity does not mean that an account operation succeeded.

XCALLY/Cally Square initially mediates Orchestrator/TIVIT/AD. This route is experimental and may be reevaluated. SendMail integration is deferred; when implemented, Cally Square delivers any temporary password and CU013 receives only delivery status. CU013 never retains the password in the LLM, Firestore, logs, telemetry or fixtures.

Do not store secrets in `config.yaml`. `.env` is local and Git-ignored; Secret Manager will provide cloud secrets when they exist. Never use service-account JSON keys.

## Workflow

- Normally work on `dev`; `main` represents accepted releases.
- Inspect remote, branch, HEAD, status, tags and local changes before acting.
- Preserve unrelated local changes; never discard work silently.
- Define observable properties before concrete contracts.
- Run only gates applicable to artifacts that exist.
- Validate accepted conversational changes with DEV voice calls.
- Update [CONTEXT.md](CONTEXT.md) after an iteration is accepted and before integration.
- Do not commit, push, deploy or run mutating cloud actions without explicit authorization.

When Python code and the applicable targets exist, the canonical gates are:

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy app
```

Do not run or create nonexistent targets merely to make gates pass.

## Commit discipline

- Commit after one completed logical unit or task; do not mix unrelated changes.
- Stage by path or hunk when needed, and never hide unrelated modifications inside a convenient commit.
- Use Conventional Commits 1.0.0: `<type>[optional scope]: <imperative description>`.
- Use imperative wording such as `add`, `fix`, `change` or `remove`.
- Limit the title to 50 characters; do not end it with punctuation or an ellipsis.
- Start an optional body after one blank line and wrap it at 72 characters per line.
- Use the body for context and rationale, not a line-by-line account of implementation.
- Use `feat` for product capability and `fix` for bug fixes. Use `docs`, `chore`, `refactor`, `test`, `build`, `ci` or `perf` when semantically appropriate.
- Add a scope only when it improves precision.
- Never commit secrets, local `.env` files, IOP PDFs, credentials or experimental cloud data.
- Before every commit inspect both `git diff` and `git diff --cached`.
- After every commit verify `git status --short` and `git log -1 --format="%h %s"`.

[Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) is the structural reference. The 50/72 limits and imperative wording are CU013 repository policy, not requirements of that specification.

## Documentation lifecycle

Canonical artifacts are Documentation as Code:

| Artifact | Update when | Lifecycle rule |
|---|---|---|
| Specs | Accepted behavior, contract or invariant changes | Normative current state; replace obsolete requirements and do not preserve historical variants inside the spec. |
| ADRs | An architectural decision is accepted or revoked | Accepted ADRs are historical records; supersede or deprecate instead of silently rewriting decision history. |
| Experiments | A spike is planned, executed or concluded | The same record evolves through `Planned`, `Running`, and `Completed` / `Failed` / `Inconclusive`, and remains as evidence. |
| `CONTEXT.md` | After an iteration is accepted, before commit or integration | Replace the current snapshot and keep only two or three brief previous checkpoints. |
| `CHANGELOG.md` | An accepted change is relevant to the project or version | Update `[Unreleased]`; never duplicate the Git log. |
| `README.md` | Entry points, purpose or navigation materially change | Keep it concise and aligned with current authority. |
| `AGENTS.md` | Agent workflow, tools, gates or repository operating rules change | Keep it operational; do not duplicate specs or ADRs. |
| Skills | A recurrent procedure is added, changed or removed | Update the procedure and remove obsolete skills instead of retaining legacy guidance. |
| Runbooks and scripts | An operational procedure or managed infrastructure changes | Keep the runbook and automation synchronized. |

Before an accepted iteration is committed or integrated:

1. determine which canonical artifacts became stale;
2. update them in the same iteration;
3. validate cross-links and contradictions;
4. update `CONTEXT.md` last, using only accepted and verified state;
5. update `CHANGELOG.md` when the change is version-relevant.

Do not preserve obsolete documentation merely for history. Git, ADRs and experiment records provide history. Current specs, runbooks, `AGENTS.md` and skills must describe the current system and workflow.

## Artifact language

- Write `AGENTS.md`, `CHANGELOG.md` and every future `.agents/skills/**/SKILL.md` in English.
- Write `README.md`, `CONTEXT.md` and `docs/decisions/*.md` in Spanish. Keep the canonical ADR status values in English.
- Preserve the current language of other artifacts unless the owner explicitly defines a different policy.

## STOP & REPORT

Stop when required XCALLY behavior is unknown, a required business rule or external contract is ambiguous, an Accepted decision conflicts with the work, a turn needs more than two sequential model calls, or the task requires another database, framework, provider, RAG, multi-agent architecture, large FSM or unapproved infrastructure.

## Decisions and skills

Decisions live in `docs/decisions/`, use `NNNN-short-kebab-title.md`, and use the status values `Proposed`, `Accepted`, `Deprecated` or `Superseded`.

The only active CU013 skill is `iteration-closeout` (`.agents/skills/iteration-closeout/SKILL.md`), used to close and reconcile an iteration before commit, integration or handoff. A future skill requires an explicit owner instruction and must represent a recurrent procedure, not a technology component, person, isolated bug or copy of a spec, ADR or `AGENTS.md`.
