---
name: cu013-protocols
description: Operates and maintains IT-support domain business protocols (VPN, Password Reset, Account Unlock).
---

# cu013-protocols

## Responsibility
Define and safeguard authoritative business protocols and diagnostic trees for enterprise IT-support domains.

## Allowed Changes
- Adding protocol validation rules as conversational scope expands.
- Updating golden evaluation test cases to reflect revised operational procedures.

## Forbidden Changes
- Hardcoding conversational branching or keyword-based protocol routers in Python.
- Copying monolithic legacy protocol engines or execution policies.
- Implementing non-VPN protocols prematurely in Increment 1.

## Inputs / Contracts
- Authoritative IT-support operational documents (IOPs).

## Outputs / Contracts
- Protocol evaluation criteria and golden evaluation scenarios in `evals/golden/`.

## Trusted References
- [docs/PROTOCOLS.md](../../docs/PROTOCOLS.md)
- [evals/golden/vpn_cases.json](../../evals/golden/vpn_cases.json)

## Quality Checks
- Golden evaluation validation across standard scenarios (simple, multi-fact, clarification, correction).

## STOP Conditions
- Ambiguous or conflicting corporate IT-support procedure definitions.
