"""
Modus Light — TokenShield Lite
==============================
Zero-cost, CPU-speed entity shielding and prompt-injection pre-filter.
Guarantees 0 external wire tokens consumed during sanitization.
"""

import re
import unicodedata
from typing import Tuple, Dict


class TokenShield:
    """
    TokenShield Lite Engine:
    Normalizes Unicode, folds homoglyphs, neutralizes Trojan Bidi overrides,
    and replaces sensitive entities (IPs, emails, credentials, payment cards)
    with zero-cost placeholder tokens.
    """

    # Cyrillic & Greek homoglyphs commonly used in evasion attacks
    HOMOGLYPH_MAP = {
        # Cyrillic lowercase
        'а': 'a', 'с': 'c', 'е': 'e', 'о': 'o', 'р': 'p', 'х': 'x', 'у': 'y', 'і': 'i', 'ј': 'j',
        # Cyrillic uppercase
        'А': 'A', 'В': 'B', 'Е': 'E', 'К': 'K', 'М': 'M', 'Н': 'H', 'О': 'O', 'Р': 'P', 'С': 'C', 'Т': 'T', 'Х': 'X',
        # Greek lowercase
        'α': 'a', 'ο': 'o', 'ρ': 'p', 'ν': 'v',
    }

    # Zero-width spaces & invisible characters
    ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200D\uFEFF\u00AD]")

    # Trojan Source Bidi control characters (CVE-2021-42574)
    BIDI_OVERRIDE_RE = re.compile(r"[\u202A-\u202E\u2066-\u2069]")

    # Sensitive Entity Regexes
    IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
    # Credential prefixes. The separator after `sk`/`rk` is `[-_]`, not a literal
    # hyphen: Stripe issues `sk_live_…`, `sk_test_…` and restricted `rk_live_…`,
    # all of which a hyphen-only pattern passed through to the provider verbatim.
    # GitHub's family is likewise more than `ghp_` — `gho_`, `ghs_`, `ghu_` and
    # `ghr_` are all live token prefixes.
    KEY_RE = re.compile(
        r"\b(?:[sr]k[-_][a-zA-Z0-9_-]{16,}"
        r"|gh[posur]_[A-Za-z0-9]{20,}"
        r"|github_pat_[A-Za-z0-9_]{20,}"
        r"|glpat-[A-Za-z0-9_-]{16,}"
        r"|AKIA[0-9A-Z]{16}"
        r"|ASIA[0-9A-Z]{16}"
        r"|xox[baprs]-[A-Za-z0-9-]{10,})\b"
    )
    CARD_CANDIDATE_RE = re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b")

    def __init__(self, fold_homoglyphs: bool = True):
        self.fold_homoglyphs = fold_homoglyphs

    @staticmethod
    def passes_luhn(digits: str) -> bool:
        """
        Luhn checksum validation for a payment card number.
        Non-card 16-digit sequences (IDs, timestamps) are rejected.
        """
        stripped = re.sub(r"[-\s]", "", digits)
        if not stripped.isdigit() or not (13 <= len(stripped) <= 19):
            return False
        total = 0
        # Double every second digit from the right
        for index, char in enumerate(reversed(stripped)):
            digit = int(char)
            if index % 2 == 1:
                digit *= 2
                if digit > 9:
                    digit -= 9
            total += digit
        return total % 10 == 0

    def normalize(self, text: str) -> str:
        """
        Performs Unicode NFKC normalization, removes zero-width characters,
        strips Bidi overrides, and optionally folds homoglyphs.
        """
        if not text:
            return ""

        # 1. NFKC normalization
        normalized = unicodedata.normalize("NFKC", text)

        # 2. Strip zero-width & invisible characters
        normalized = self.ZERO_WIDTH_RE.sub("", normalized)

        # 3. Neutralize Trojan Source Bidi overrides
        normalized = self.BIDI_OVERRIDE_RE.sub("", normalized)

        # 4. Homoglyph folding
        if self.fold_homoglyphs:
            chars = [self.HOMOGLYPH_MAP.get(ch, ch) for ch in normalized]
            normalized = "".join(chars)

        return normalized

    def shield(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Shields text by neutralizing adversarial Unicode and masking sensitive entities.
        Returns:
            Tuple[str, Dict[str, str]]: (masked_text, token_mapping)
        """
        if not text:
            return "", {}

        clean = self.normalize(text)
        token_map: Dict[str, str] = {}

        def _replace_entity(match: re.Match, prefix: str) -> str:
            val = match.group(0)
            token = f"<{prefix}_{len(token_map)}>"
            token_map[token] = val
            return token

        # Mask API Keys & Secrets first
        clean = self.KEY_RE.sub(lambda m: _replace_entity(m, "TOKEN_SECRET"), clean)

        # Mask payment cards only when the Luhn checksum confirms a real card number
        clean = self.CARD_CANDIDATE_RE.sub(
            lambda m: _replace_entity(m, "TOKEN_CARD")
            if self.passes_luhn(m.group(0))
            else m.group(0),
            clean,
        )

        # Mask Emails
        clean = self.EMAIL_RE.sub(lambda m: _replace_entity(m, "TOKEN_EMAIL"), clean)

        # Mask IP Addresses
        clean = self.IP_RE.sub(lambda m: _replace_entity(m, "TOKEN_IP"), clean)

        return clean, token_map

    def unshield(self, text: str, token_map: Dict[str, str]) -> str:
        """
        Restores the masked entities into the text using the private token map.

        Scope note: this reverses the *masking* step, not the normalization step.
        `shield()` returns NFKC-normalized, zero-width-stripped, homoglyph-folded
        text by design — that sanitisation is the security property and is not
        meant to be undone — so the result here is byte-identical to the original
        only when the input was already normalized. The masked entities
        themselves always round-trip exactly.
        """
        if not text or not token_map:
            return text

        result = text
        for token, original in token_map.items():
            result = result.replace(token, original)
        return result
