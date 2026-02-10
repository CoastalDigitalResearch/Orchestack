"""Core DLP scanning engine.

Provides regex-based detection of PII, secrets, and other sensitive data
patterns.  Designed to be called synchronously -- all work is pure CPU
regex matching so there is no benefit to ``async`` here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .models import Finding, ScanResult

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pattern:
    """A single detection pattern."""

    name: str
    category: str
    regex: re.Pattern[str]
    confidence: float


# Built-in patterns shipped with the scanner.
_BUILTIN_PATTERNS: list[Pattern] = [
    # -- PII ------------------------------------------------------------------
    Pattern(
        name="email",
        category="email",
        regex=re.compile(
            r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
        ),
        confidence=0.95,
    ),
    Pattern(
        name="phone_us",
        category="phone",
        regex=re.compile(
            r"(?<!\d)"  # not preceded by digit
            r"(?:\+?1[-.\s]?)?"  # optional country code
            r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
            r"(?!\d)",  # not followed by digit
        ),
        confidence=0.85,
    ),
    Pattern(
        name="ssn",
        category="ssn",
        regex=re.compile(
            r"(?<!\d)"
            r"\d{3}-\d{2}-\d{4}"
            r"(?!\d)",
        ),
        confidence=0.95,
    ),
    Pattern(
        name="credit_card",
        category="credit_card",
        regex=re.compile(
            r"(?<!\d)"
            r"(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6(?:011|5\d{2}))"
            r"[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{1,4}"
            r"(?!\d)",
        ),
        confidence=0.80,  # raised to 0.95 after Luhn check
    ),
    Pattern(
        name="ip_address",
        category="ip_address",
        regex=re.compile(
            r"(?<!\d)"
            r"(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
            r"(?!\d)",
        ),
        confidence=0.70,
    ),
    # -- Credentials / secrets ------------------------------------------------
    Pattern(
        name="openai_api_key",
        category="api_key",
        regex=re.compile(r"sk-[A-Za-z0-9]{20,}"),
        confidence=0.95,
    ),
    Pattern(
        name="aws_access_key",
        category="api_key",
        regex=re.compile(r"AKIA[0-9A-Z]{16}"),
        confidence=0.95,
    ),
    Pattern(
        name="github_pat",
        category="api_key",
        regex=re.compile(r"ghp_[A-Za-z0-9]{36,}"),
        confidence=0.95,
    ),
    Pattern(
        name="github_fine_grained_pat",
        category="api_key",
        regex=re.compile(r"github_pat_[A-Za-z0-9_]{36,}"),
        confidence=0.95,
    ),
    Pattern(
        name="generic_secret_assignment",
        category="secret",
        regex=re.compile(
            r"""(?i)(?:password|passwd|secret|token|api_key|apikey|access_key)"""
            r"""[\s]*[=:][\s]*["']?[^\s"']{8,}["']?""",
        ),
        confidence=0.75,
    ),
    Pattern(
        name="aws_secret_key",
        category="credential",
        regex=re.compile(
            r"""(?i)aws_secret_access_key[\s]*[=:][\s]*["']?[A-Za-z0-9/+=]{40}["']?""",
        ),
        confidence=0.95,
    ),
    Pattern(
        name="jwt_token",
        category="jwt",
        regex=re.compile(
            r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
        ),
        confidence=0.90,
    ),
]


# ---------------------------------------------------------------------------
# Luhn check for credit card validation
# ---------------------------------------------------------------------------


def _luhn_check(number_str: str) -> bool:
    """Return True if *number_str* passes the Luhn algorithm."""
    digits = [int(d) for d in number_str if d.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    reverse = digits[::-1]
    for i, d in enumerate(reverse):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


@dataclass
class DLPScanner:
    """Regex-based DLP scanning engine."""

    patterns: list[Pattern] = field(default_factory=lambda: list(_BUILTIN_PATTERNS))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self, content: str, content_type: str = "message") -> ScanResult:
        """Scan *content* and return a :class:`ScanResult`."""
        findings: list[Finding] = []

        for pattern in self.patterns:
            for match in pattern.regex.finditer(content):
                confidence = pattern.confidence

                # Luhn validation for credit-card candidates
                if pattern.category == "credit_card":
                    if _luhn_check(match.group()):
                        confidence = 0.95
                    else:
                        # Failed Luhn -- skip this match entirely.
                        continue

                findings.append(
                    Finding(
                        category=pattern.category,
                        matched_text=match.group(),
                        start=match.start(),
                        end=match.end(),
                        confidence=confidence,
                    )
                )

        # Deduplicate overlapping findings (keep higher confidence).
        findings = self._deduplicate(findings)

        risk_level = self._compute_risk_level(findings)
        tags = self._generate_tags(findings)

        return ScanResult(
            findings=findings,
            risk_level=risk_level,
            tags=tags,
        )

    def redact(
        self,
        content: str,
        findings: list[Finding],
        mode: str = "mask",
    ) -> str:
        """Return *content* with sensitive spans redacted.

        Parameters
        ----------
        mode:
            ``"mask"``   -- replace characters with ``*`` keeping length.
            ``"remove"`` -- replace the span with ``[REDACTED]``.
        """
        if not findings:
            return content

        # Sort by start position descending so replacements don't shift
        # subsequent indices.
        sorted_findings = sorted(findings, key=lambda f: f.start, reverse=True)

        chars = list(content)
        for finding in sorted_findings:
            start, end = finding.start, finding.end
            if mode == "mask":
                for i in range(start, min(end, len(chars))):
                    chars[i] = "*"
            elif mode == "remove":
                chars[start:end] = list("[REDACTED]")

        return "".join(chars)

    def list_patterns(self) -> list[dict]:
        """Return metadata about every active pattern."""
        return [
            {
                "name": p.name,
                "category": p.category,
                "confidence": p.confidence,
            }
            for p in self.patterns
        ]

    def load_custom_patterns(self, path: str) -> None:
        """Load additional patterns from a JSON file.

        Expected format::

            [
                {
                    "name": "my_pattern",
                    "category": "secret",
                    "regex": "REGEX_STRING",
                    "confidence": 0.9
                }
            ]
        """
        raw = json.loads(Path(path).read_text())
        for entry in raw:
            self.patterns.append(
                Pattern(
                    name=entry["name"],
                    category=entry["category"],
                    regex=re.compile(entry["regex"]),
                    confidence=float(entry["confidence"]),
                )
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_risk_level(findings: Sequence[Finding]) -> str:
        """Derive an overall risk level from the list of findings."""
        if not findings:
            return "none"

        categories = {f.category for f in findings}
        max_confidence = max(f.confidence for f in findings)

        critical_categories = {"credential", "api_key", "ssn", "credit_card"}
        high_categories = {"secret", "jwt"}
        medium_categories = {"email", "phone", "ip_address"}

        if categories & critical_categories and max_confidence >= 0.9:
            return "critical"
        if categories & critical_categories:
            return "high"
        if categories & high_categories:
            return "high" if max_confidence >= 0.85 else "medium"
        if categories & medium_categories:
            return "medium" if len(findings) > 2 else "low"

        return "low"

    @staticmethod
    def _generate_tags(findings: Sequence[Finding]) -> set[str]:
        """Generate classification tags from findings."""
        tags: set[str] = set()
        for finding in findings:
            tags.add(finding.category)

            # Add broader grouping tags.
            if finding.category in {"email", "phone", "ssn", "credit_card", "ip_address"}:
                tags.add("pii")
            if finding.category in {"credential", "api_key", "secret", "jwt"}:
                tags.add("secrets")
        return tags

    @staticmethod
    def _deduplicate(findings: list[Finding]) -> list[Finding]:
        """Remove overlapping findings, keeping higher-confidence ones."""
        if not findings:
            return findings

        # Sort by start ascending, then confidence descending.
        findings.sort(key=lambda f: (f.start, -f.confidence))

        deduped: list[Finding] = [findings[0]]
        for finding in findings[1:]:
            prev = deduped[-1]
            # If this finding overlaps with the previous one, keep only the
            # one with higher confidence.
            if finding.start < prev.end:
                if finding.confidence > prev.confidence:
                    deduped[-1] = finding
            else:
                deduped.append(finding)

        return deduped
