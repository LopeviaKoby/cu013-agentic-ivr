---
name: cu013-langgraph
description: Operates and maintains the minimal LangGraph orchestration workflow and typed state.
---

# cu013-langgraph

## Responsibility
Construct and manage the StateGraph workflow, typed conversation state, and graph node transitions.

## Allowed Changes
- Adding minimal graph nodes when concrete conversational steps warrant them.
- Updating `ConversationState` with strictly necessary fields.
- Optimizing node invocation and state passage.

## Forbidden Changes
- Introducing multi-agent orchestration frameworks or continuation stacks.
- Building complex subgraphs or human-in-the-loop loops without demonstrated need.
- Constructing large conversational FSM routing inside Python conditionals.

## Inputs / Contracts
- `ConversationState` dictionary containing turn context and caller transcript.

## Outputs / Contracts
- Mutated state dictionary with `route`, `response_text`, and updated turn count.

## Trusted References
- [app/graph.py](../../app/graph.py)
- [AGENTS.md](../../AGENTS.md)

## Quality Checks
- `pytest tests/test_graph.py`
- Graph compiles without recursion or disconnected node errors.

## STOP Conditions
- Graph topology complexity exceeds single-turn decision scope.
- >2 sequential model calls triggered in a single graph execution.
