---
name: cu013-voice-validation
description: Operates live telephony voice testing and audio UX validation over DEV phone lines.
---

# cu013-voice-validation

## Responsibility
Validate conversational naturalness, latency, barge-in robustness, and audio flow through live phone calls on the DEV environment.

## Allowed Changes
- Defining test call scripts and verification checklists.
- Recording telephony timing metrics and transcript accuracy logs.

## Forbidden Changes
- Merging conversational behavior changes without live telephony verification on DEV.
- Simulating live call success purely with synthetic unit tests.

## Inputs / Contracts
- DEV telephony entry point (phone number, SIP trunk, Cally Square application).

## Outputs / Contracts
- Voice call audit reports with latency breakdown (ASR + Backend + TTS) and dialogue flow assessments.

## Trusted References
- [docs/DEVELOPMENT_RULES.md](../../docs/DEVELOPMENT_RULES.md)
- [AGENTS.md](../../AGENTS.md)

## Quality Checks
- Live test call completed without unexpected silence, loops, or unnatural phrasing.

## STOP Conditions
- Total roundtrip latency exceeds 2.5 seconds on live voice calls.
