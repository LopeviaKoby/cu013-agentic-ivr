# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Minimal productive Thin Session Repository core in `app/session`: semantic
  whitelisted `SessionRecord`, durable `pending_operation`, ephemeral
  `GraphState`, a deterministic single-node LangGraph turn without persistent
  checkpointer, an async Firestore repository with a narrow document seam and a
  turn service with exactly one load and one save.
- Deterministic test suite for the session core, including continuity,
  crash-before-save recovery, durable pending operation, PII and whitelist
  exclusion and async repository behavior.
- `requirements.lock` with the exact reproducible production pins, verified in
  a clean environment and reviewed against current OSV advisories.
- GCP DEV/SPIKE baseline in `us-east1`.
- Firestore `(default)` in Native mode, Standard edition.
- Artifact Registry DEV repository.
- Dedicated spike, runtime and deployer service accounts.
- Reproducible GCP bootstrap and verification runbook and PowerShell scripts.
- Versioned non-sensitive `config.yaml`.
- Versioned source manifest for local corporate IOPs.
- Engineering standards for Python, reliability and testing.
- Add the CU013 iteration-closeout agent skill.

### Changed

- Replace the transitional `packages = []` packaging with explicit `app`
  package discovery; editable DEV install verified.
- Raise dev tooling to advisory-free floors: `pytest>=9.0.3` and
  `pytest-asyncio>=1.4.0`.
- Remove the experimental Firestore spike documents (111 documents) under the
  documented `cu013spike_meas_*` prefixes.
- Adopt Thin Firestore Session Repository for durable voice-session state.
- Reject persistent LangGraph checkpointing for the production voice path.
- Raise the LangGraph security floor to `langgraph>=1.0.10` and
  `langgraph-checkpoint>=4.1.1`; defer the exact production lock to the first
  minimal production implementation.

- Documented reproducible `gcloud` bootstrap before Terraform.
- Resolved the infrastructure blocker for the Firestore persistence spike.
- Moved the deadline for evaluating a Gemini alternative to 16-10-2026.
- Clarified business-authority precedence, account-action paths, experiment retention and the documentation lifecycle.
- Clarified the automated account-action and ticketing boundary.
