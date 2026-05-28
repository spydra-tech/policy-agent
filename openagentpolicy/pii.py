from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

REDACTED_VALUE = "***REDACTED***"


@dataclass(frozen=True)
class PiiSpan:
    """A detected PII region within a string."""

    start: int
    end: int
    entity_type: str


class PiiDetector(Protocol):
    """Detects PII spans inside a free-text value."""

    def detect(self, text: str) -> list[PiiSpan]:
        ...


def redact_spans(text: str, spans: list[PiiSpan]) -> str:
    """Replace detected spans with the redaction marker (non-overlapping, ordered)."""
    if not spans:
        return text
    ordered = sorted(spans, key=lambda s: (s.start, s.end))
    result: list[str] = []
    cursor = 0
    for span in ordered:
        if span.start < cursor:
            # Overlapping span already covered by a previous redaction.
            continue
        result.append(text[cursor : span.start])
        result.append(REDACTED_VALUE)
        cursor = span.end
    result.append(text[cursor:])
    return "".join(result)


def _luhn_valid(digits: str) -> bool:
    total = 0
    reverse = digits[::-1]
    for index, char in enumerate(reverse):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _verhoeff_valid(number: str) -> bool:
    """Verhoeff checksum used by Aadhaar (12 digits)."""
    d_table = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
        [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
        [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
        [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
        [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
        [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
        [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
        [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
        [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
    ]
    p_table = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
        [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
        [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
        [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
        [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
        [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
        [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
    ]
    check = 0
    for index, char in enumerate(reversed(number)):
        check = d_table[check][p_table[index % 8][int(char)]]
    return check == 0


@dataclass
class _Recognizer:
    entity_type: str
    pattern: re.Pattern[str]
    validator: object | None = None  # Callable[[str], bool] | None

    def find(self, text: str) -> list[PiiSpan]:
        spans: list[PiiSpan] = []
        for match in self.pattern.finditer(text):
            if self.validator is not None:
                digits = re.sub(r"\D", "", match.group(0))
                if not self.validator(digits):  # type: ignore[operator]
                    continue
            spans.append(
                PiiSpan(
                    start=match.start(),
                    end=match.end(),
                    entity_type=self.entity_type,
                )
            )
        return spans


def _default_recognizers() -> dict[str, _Recognizer]:
    return {
        "EMAIL_ADDRESS": _Recognizer(
            "EMAIL_ADDRESS",
            re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        ),
        "CREDIT_CARD": _Recognizer(
            "CREDIT_CARD",
            re.compile(r"\b\d(?:[ -]?\d){12,18}\b"),
            validator=_luhn_valid,
        ),
        "IN_PAN": _Recognizer(
            "IN_PAN",
            re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
        ),
        "IN_AADHAAR": _Recognizer(
            "IN_AADHAAR",
            re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
            validator=_verhoeff_valid,
        ),
        "US_SSN": _Recognizer(
            "US_SSN",
            re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        ),
        "PHONE_NUMBER": _Recognizer(
            "PHONE_NUMBER",
            re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\d{10}|\d{3}[\s-]\d{3}[\s-]\d{4})\b"),
        ),
    }


@dataclass
class RegexPiiDetector:
    """Deterministic, local, dependency-free PII detector.

    Uses regex plus checksum validation (Luhn for cards, Verhoeff for Aadhaar)
    to keep false positives low. Suitable for production runtime where
    determinism and reproducibility matter.
    """

    entities: tuple[str, ...]
    _recognizers: dict[str, _Recognizer] = field(default_factory=dict)

    @classmethod
    def from_entities(cls, entities: list[str]) -> "RegexPiiDetector":
        available = _default_recognizers()
        selected = {
            name: available[name] for name in entities if name in available
        }
        return cls(entities=tuple(selected.keys()), _recognizers=selected)

    def detect(self, text: str) -> list[PiiSpan]:
        spans: list[PiiSpan] = []
        for recognizer in self._recognizers.values():
            spans.extend(recognizer.find(text))
        return spans


@dataclass
class PresidioPiiDetector:
    """Optional Presidio-backed detector (value-level NER + recognizers).

    Requires the optional dependency: ``pip install openagentpolicy[pii]``.
    Lazily imports presidio so the core runtime stays dependency-free.
    """

    entities: tuple[str, ...]
    languages: tuple[str, ...]
    _analyzer: object | None = None

    @classmethod
    def create(
        cls, entities: list[str], languages: list[str]
    ) -> "PresidioPiiDetector":
        try:
            from presidio_analyzer import AnalyzerEngine
        except ImportError as exc:  # pragma: no cover - exercised only without extra
            raise ImportError(
                "Presidio is required for engine='presidio'. "
                "Install it with: pip install openagentpolicy[pii]"
            ) from exc
        analyzer = AnalyzerEngine()
        return cls(
            entities=tuple(entities),
            languages=tuple(languages or ["en"]),
            _analyzer=analyzer,
        )

    def detect(self, text: str) -> list[PiiSpan]:
        if self._analyzer is None:  # pragma: no cover - defensive
            return []
        language = self.languages[0] if self.languages else "en"
        results = self._analyzer.analyze(  # type: ignore[attr-defined]
            text=text,
            language=language,
            entities=list(self.entities) or None,
        )
        return [
            PiiSpan(start=r.start, end=r.end, entity_type=r.entity_type)
            for r in results
        ]


def create_pii_detector(
    *,
    enabled: bool,
    engine: str,
    entities: list[str],
    languages: list[str],
) -> PiiDetector | None:
    """Build a PII detector from config, or None when disabled."""
    if not enabled:
        return None
    if engine == "presidio":
        return PresidioPiiDetector.create(entities=entities, languages=languages)
    if engine == "regex":
        return RegexPiiDetector.from_entities(entities)
    raise ValueError(f"Unknown PII detection engine: {engine}")
