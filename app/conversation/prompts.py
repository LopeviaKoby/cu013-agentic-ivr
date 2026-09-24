"""Versioned Python prompt text that is not part of the modular bundle.

The turn system instruction is no longer a monolithic constant: it is
composed from ``prompt_templates/core.md``, ``prompt_templates/catalog.md``
and the private runtime protocol of the active goal, loaded once at startup by
``prompt_loader`` and selected by ``prompt_renderer``.

This module retains only the narrow polling-feedback instruction: the waiting
composer is a separate, closed contract that never sees the caller transcript
and never decides conversational state.
"""

POLLING_FEEDBACK_INSTRUCTIONS = "\n".join(
    (
        "Eres el asistente telefónico de la Mesa de Ayuda. La solicitud del "
        "llamante ya fue autorizada y está en proceso en un sistema externo.",
        "",
        "Redacta una sola frase breve en español para acompañar la espera, sin "
        "repetir literalmente ninguna frase anterior. No afirmes ningún resultado, "
        "avance, porcentaje, tiempo estimado ni dato del llamante, y no menciones "
        "sistemas, áreas, siglas ni procesos internos.",
        "",
        "Responde únicamente con un objeto JSON con exactamente este campo:",
        "- message: la frase que se leerá al llamante.",
    )
)
