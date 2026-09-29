"""Deterministic test oracle for spoken password dictation.

This is evaluation-only tooling: it never runs in the runtime and it never
stores a password. Given a synthetic reference and the model's spoken text it
returns a closed verdict (``full``, ``partial`` or ``none``) plus the number of
characters matched in order. The oracle is intentionally small: it validates
character correspondence, order and case, not prose quality.
"""

from __future__ import annotations

import unicodedata

__all__ = [
    "decode_match",
    "match_count",
    "spoken_variants",
]

_LETTER_NAMES = {
    "a": ("a",),
    "b": ("b", "be", "be larga"),
    "c": ("c", "ce"),
    "d": ("d", "de"),
    "e": ("e",),
    "f": ("f", "efe"),
    "g": ("g", "ge"),
    "h": ("h", "hache"),
    "i": ("i",),
    "j": ("j", "jota"),
    "k": ("k", "ka"),
    "l": ("l", "ele"),
    "m": ("m", "eme"),
    "n": ("n", "ene"),
    "o": ("o",),
    "p": ("p", "pe"),
    "q": ("q", "cu"),
    "r": ("r", "erre"),
    "s": ("s", "ese"),
    "t": ("t", "te"),
    "u": ("u",),
    "v": ("v", "uve", "ve"),
    "w": ("w", "doble u", "doble ve"),
    "x": ("x", "equis"),
    "y": ("y", "ye", "i griega"),
    "z": ("z", "zeta"),
}

_DIGIT_NAMES = {
    "0": ("0", "cero"),
    "1": ("1", "uno", "un"),
    "2": ("2", "dos"),
    "3": ("3", "tres"),
    "4": ("4", "cuatro"),
    "5": ("5", "cinco"),
    "6": ("6", "seis"),
    "7": ("7", "siete"),
    "8": ("8", "ocho"),
    "9": ("9", "nueve"),
}

_SYMBOL_NAMES = {
    "!": ("!", "exclamacion", "admiracion", "signo de exclamacion"),
    "@": ("@", "arroba"),
    "#": ("#", "numeral", "almohadilla", "hash"),
    "$": ("$", "dolar", "peso"),
    "%": ("%", "porcentaje", "por ciento"),
    "?": ("?", "interrogacion", "signo de interrogacion", "pregunta"),
    "-": ("-", "guion", "menos"),
    "_": ("_", "guion bajo", "subrayado"),
    ".": (".", "punto"),
    ",": (",", "coma"),
    "=": ("=", "igual"),
    "+": ("+", "mas"),
    "*": ("*", "asterisco"),
    "/": ("/", "barra"),
}


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def spoken_variants(char: str) -> tuple[str, ...]:
    """Closed spoken/typed variants for one reference character."""
    lowered = char.lower()
    if lowered in _LETTER_NAMES:
        variants = list(_LETTER_NAMES[lowered])
        if char.isupper():
            variants.extend(f"{name} mayuscula" for name in variants[:1])
        else:
            variants.extend(f"{name} minuscula" for name in variants[:1])
        return tuple(variants)
    if lowered in _DIGIT_NAMES:
        return _DIGIT_NAMES[lowered]
    if lowered in _SYMBOL_NAMES:
        return _SYMBOL_NAMES[lowered]
    return (lowered,)


def match_count(reference: str, spoken: str) -> int:
    """Characters of ``reference`` found in order inside ``spoken``."""
    haystack = _normalize(spoken)
    position = 0
    matched = 0
    for char in reference:
        found = -1
        for variant in spoken_variants(char):
            index = haystack.find(variant, position)
            if index >= 0 and (found < 0 or index < found):
                found = index
        if found < 0:
            continue
        position = found + 1
        matched += 1
    return matched


def decode_match(reference: str, spoken: str) -> str:
    """Closed verdict: ``full``, ``partial`` or ``none``."""
    if not reference:
        return "none"
    matched = match_count(reference, spoken)
    if matched >= len(reference):
        return "full"
    if matched > 0:
        return "partial"
    return "none"
