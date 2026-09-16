"""Deterministic policy contract tests for the versioned system prompt.

The prompt is a textual contract expressed as code, so these tests lock the
structural properties the runtime depends on: every closed route and every
decision field is documented, and the prior-request policy precedes identity
collection. No model, network or credentials are involved.
"""

from app.conversation.prompts import PRIOR_REQUEST_RULE, SYSTEM_INSTRUCTIONS
from app.session.turns import ModelTurnDecision, Route


def test_prompt_documents_every_closed_route() -> None:
    for route in Route:
        assert route.value in SYSTEM_INSTRUCTIONS


def test_prompt_documents_every_decision_field() -> None:
    for field in ModelTurnDecision.model_fields:
        assert field in SYSTEM_INSTRUCTIONS


def test_prior_request_policy_precedes_identity_collection() -> None:
    assert "CONTINUE" in PRIOR_REQUEST_RULE
    assert "COLLECT_IDENTITY" in PRIOR_REQUEST_RULE
    policy_index = SYSTEM_INSTRUCTIONS.index(PRIOR_REQUEST_RULE)
    collection_index = SYSTEM_INSTRUCTIONS.index("Usa COLLECT_IDENTITY")
    assert policy_index < collection_index
