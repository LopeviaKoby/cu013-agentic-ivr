"""Conversational dependency errors translated by the HTTP boundary."""


class ModelTimeoutError(RuntimeError):
    """The model call exceeded its deadline."""


class ModelUnavailableError(RuntimeError):
    """The model dependency failed or could not be reached."""


class InvalidModelOutputError(RuntimeError):
    """The model output violated the typed decision contract."""
