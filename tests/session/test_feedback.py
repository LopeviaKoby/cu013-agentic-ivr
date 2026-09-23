"""Polling feedback composer seam and message-normalization tests.

No model, network, Firestore or credentials are involved: the composer is a
deterministic double and every message is synthetic.
"""

import pytest

from app.session.actions import Action
from app.session.feedback import (
    MAX_FEEDBACK_MESSAGE_CHARS,
    FeedbackObservationKind,
    FeedbackOperationState,
    NullPollingFeedbackComposer,
    PollingFeedbackRequest,
    validate_feedback_message,
)
from app.session.text import normalize_message

REQUEST = PollingFeedbackRequest(
    action=Action.UNLOCK_ACCOUNT,
    goal_revision=2,
    confirmation_obtained=True,
    operation_state=FeedbackOperationState.PENDING,
    observation_kind=FeedbackObservationKind.PENDING,
    poll_sequence=3,
    observations_used=3,
    observation_limit=9,
)


# --- normalization ----------------------------------------------------------


def test_normalize_keeps_null_as_null() -> None:
    assert normalize_message(None) is None


def test_normalize_collapses_cr_lf_tab_and_space_runs() -> None:
    assert normalize_message("Hola\r\nmundo\t\totra   vez") == "Hola mundo otra vez"
    assert normalize_message("  espacios  alrededor  ") == "espacios alrededor"


def test_normalize_preserves_unicode_apostrophes_quotes_and_backslash() -> None:
    original = 'esperá: ¿seguís ahí? d\'accord "quote" áéíóúñ\\ruta'
    assert normalize_message(original) == original


# --- validation -------------------------------------------------------------


def test_validation_accepts_a_short_wait_message() -> None:
    assert validate_feedback_message("Sigo con tu solicitud. Gracias por esperar.") == (
        "Sigo con tu solicitud. Gracias por esperar."
    )


def test_validation_normalizes_before_accepting() -> None:
    assert validate_feedback_message("Sigo\r\ncon tu solicitud.") == "Sigo con tu solicitud."


def test_validation_rejects_empty_or_null() -> None:
    assert validate_feedback_message(None) is None
    assert validate_feedback_message("   ") is None


def test_validation_rejects_percentages_and_etas() -> None:
    for message in (
        "Está al 80%.",
        "Faltan 2 minutos.",
        "En 30 segundos tendrás el resultado.",
        "Dentro de 1 hora.",
    ):
        assert validate_feedback_message(message) is None


def test_validation_rejects_internal_names() -> None:
    for message in (
        "El AD está respondiendo.",
        "RD sigue procesando.",
        "Orchestrator recibió tu solicitud.",
        "Firestore guardó el estado.",
    ):
        assert validate_feedback_message(message) is None


def test_validation_rejects_unbacked_terminal_or_delivery_claims() -> None:
    for message in (
        "El desbloqueo fue confirmado.",
        "La operación fue exitosa.",
        "El proceso terminó.",
        "El correo fue enviado.",
        "Ya casi termina.",
        "Tu solicitud quedó lista.",
    ):
        assert validate_feedback_message(message) is None


def test_validation_rejects_an_overlong_message() -> None:
    assert validate_feedback_message("a" * (MAX_FEEDBACK_MESSAGE_CHARS + 1)) is None


# --- protocol default -------------------------------------------------------


async def test_null_composer_returns_nothing() -> None:
    composer = NullPollingFeedbackComposer()
    assert await composer.compose(REQUEST) is None


def test_request_is_closed_to_unknown_fields() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PollingFeedbackRequest.model_validate(
            {
                "action": "UNLOCK_ACCOUNT",
                "goal_revision": 1,
                "confirmation_obtained": True,
                "operation_state": "PENDING",
                "observation_kind": "PENDING",
                "poll_sequence": 1,
                "observations_used": 1,
                "observation_limit": 9,
                "transcript": "SYNTHETIC-TRANSCRIPT-0000",
            }
        )
