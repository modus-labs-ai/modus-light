"""
Tests for Modus Light TokenShield
"""

import unittest
from modus_light.token_shield import TokenShield


class TestTokenShield(unittest.TestCase):

    def setUp(self):
        self.shield = TokenShield()

    def test_unicode_normalization_and_zero_width_stripping(self):
        # Text with zero-width space and soft hyphen
        adversarial = "ad\u200Bmin\u00ADuser"
        cleaned = self.shield.normalize(adversarial)
        self.assertEqual(cleaned, "adminuser")

    def test_trojan_source_bidi_neutralization(self):
        # CVE-2021-42574 Trojan Source right-to-left override
        bidi_text = "access_level = 'user' \u202E } \u2066 /* checks admin */"
        cleaned = self.shield.normalize(bidi_text)
        self.assertNotIn("\u202E", cleaned)
        self.assertNotIn("\u2066", cleaned)

    def test_homoglyph_folding(self):
        # Cyrillic 'а' (\u0430) and 'о' (\u043E) masquerading as Latin 'a' and 'o'
        spoofed = "\u0430dm\u043En"
        cleaned = self.shield.normalize(spoofed)
        self.assertEqual(cleaned, "admon")

    def test_entity_masking_and_unshielding(self):
        text = "Contact alice@example.com at 192.0.2.10 with key sk-ant-live-12345678901234567890"
        masked, token_map = self.shield.shield(text)

        # Check masked tokens present
        self.assertIn("<TOKEN_SECRET_0>", masked)
        self.assertIn("<TOKEN_EMAIL_1>", masked)
        self.assertIn("<TOKEN_IP_2>", masked)

        # Check original sensitive strings not in masked text
        self.assertNotIn("alice@example.com", masked)
        self.assertNotIn("192.0.2.10", masked)
        self.assertNotIn("sk-ant-live-12345678901234567890", masked)

        # Reconstruct
        restored = self.shield.unshield(masked, token_map)
        self.assertEqual(restored, text)

    def test_email_pattern_has_no_literal_pipe(self):
        """A '|' inside a character class matches a literal pipe rather than
        acting as alternation, which silently narrows the pattern."""
        self.assertNotIn("|", TokenShield.EMAIL_RE.pattern)

    def test_masks_common_secret_prefixes(self):
        # Assembled at runtime rather than written as literals: a hard-coded
        # key-shaped string trips secret scanners and pre-push gates even when
        # the value is obviously synthetic.
        github_token = "ghp" + "_" + ("0123456789" * 3)[:30]
        aws_key_id = "AKI" + "A" + "0123456789ABCDEF"

        masked, token_map = self.shield.shield(f"{github_token} and {aws_key_id}")

        self.assertEqual(len(token_map), 2)
        self.assertNotIn(github_token, masked)
        self.assertNotIn(aws_key_id, masked)
        self.assertEqual(sorted(token_map.values()), sorted([github_token, aws_key_id]))

    def test_payment_card_requires_luhn_checksum(self):
        masked, token_map = self.shield.shield("card 4111111111111111 ref 1234567890123456")
        self.assertIn("<TOKEN_CARD_0>", masked)
        self.assertNotIn("4111111111111111", masked)
        # A 16-digit identifier that is not a card number must stay untouched
        self.assertIn("1234567890123456", masked)
        self.assertEqual(len(token_map), 1)

    def test_luhn_helper(self):
        self.assertTrue(TokenShield.passes_luhn("4111111111111111"))
        self.assertFalse(TokenShield.passes_luhn("1234567890123456"))
        self.assertFalse(TokenShield.passes_luhn("not-a-number"))


if __name__ == "__main__":
    unittest.main()
