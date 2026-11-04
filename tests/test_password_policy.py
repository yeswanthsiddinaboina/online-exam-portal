import unittest
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.utils.security import validate_password, COMMON_WEAK_PASSWORDS
from backend.models.user import User

class TestPasswordPolicy(unittest.TestCase):
    def test_minimum_length_requirement(self):
        """1. Passwords shorter than 8 characters must be rejected."""
        valid, err = validate_password("Short1!") # 7 chars
        self.assertFalse(valid)
        self.assertIn("at least 8 characters", err)

        valid, err = validate_password("Abc!123") # 7 chars
        self.assertFalse(valid)
        self.assertIn("at least 8 characters", err)

    def test_missing_character_categories(self):
        """2. Passwords missing each required character category must be rejected."""
        # Missing uppercase
        valid, err = validate_password("lowercase1234!")
        self.assertFalse(valid)
        self.assertIn("uppercase letter", err)

        # Missing lowercase
        valid, err = validate_password("UPPERCASE1234!")
        self.assertFalse(valid)
        self.assertIn("lowercase letter", err)

        # Missing number
        valid, err = validate_password("UppercaseOnly!@#")
        self.assertFalse(valid)
        self.assertIn("digit", err)

        # Missing special character
        valid, err = validate_password("Uppercase1234567")
        self.assertFalse(valid)
        self.assertIn("special character", err)

    def test_compliant_password_accepted(self):
        """3. Compliant passwords of 8-64 characters must be accepted."""
        # Exactly 8 characters
        valid, err = validate_password("Str0ng!1")
        self.assertTrue(valid)
        self.assertIsNone(err)

        valid, err = validate_password("K9#mQ2$v")
        self.assertTrue(valid)
        self.assertIsNone(err)

        valid, err = validate_password("Str0ng#Exam2026")
        self.assertTrue(valid)
        self.assertIsNone(err)

        valid, err = validate_password("AlphaBeta123$!Gamma")
        self.assertTrue(valid)
        self.assertIsNone(err)

    def test_known_weak_passwords_rejected(self):
        """4. Known weak passwords must be rejected."""
        weak_list = [
            "Password123!", "password123!", "PASSWORD123!", "Admin123456!",
            "Welcome1234!", "Qwerty12345!", "Pass@123", "Admin@123", "Welcome@1"
        ]
        for weak in weak_list:
            valid, err = validate_password(weak)
            self.assertFalse(valid, f"Expected weak password '{weak}' to be rejected.")
            self.assertIn("too common or easily guessed", err)

    def test_whitespace_handling(self):
        """5. Whitespace: Leading and trailing spaces must be rejected without silent mutation."""
        valid, err = validate_password(" Str0ng#Exam2026")
        self.assertFalse(valid)
        self.assertIn("leading or trailing spaces", err)

        valid, err = validate_password("Str0ng#Exam2026 ")
        self.assertFalse(valid)
        self.assertIn("leading or trailing spaces", err)

        valid, err = validate_password(" Str0ng#Exam2026 ")
        self.assertFalse(valid)
        self.assertIn("leading or trailing spaces", err)

        # Internal spaces in passphrase are valid
        valid, err = validate_password("Str0ng Pass#Phrase 2026")
        self.assertTrue(valid)
        self.assertIsNone(err)

    def test_maximum_length_and_unicode_handling(self):
        """6. Maximum length and Unicode character handling."""
        # 64 chars compliant -> accepted
        valid_64 = "Aa1!" + "a" * 60
        valid, err = validate_password(valid_64)
        self.assertTrue(valid)

        # 65 chars -> rejected
        invalid_65 = "Aa1!" + "a" * 61
        valid, err = validate_password(invalid_65)
        self.assertFalse(valid)
        self.assertIn("cannot exceed 64 characters", err)

        # Unicode character compliant
        valid, err = validate_password("Ströng#Exam2026")
        self.assertTrue(valid)

    def test_non_string_input(self):
        """Non-string inputs must be rejected safely."""
        valid, err = validate_password(None)
        self.assertFalse(valid)
        valid, err = validate_password(123456789012)
        self.assertFalse(valid)

    def test_bcrypt_hashing_and_verification(self):
        """7. Verify existing bcrypt password hashing and verification."""
        user = User(email="test_pwd_policy@example.com", first_name="Test", last_name="Student")
        plain_password = "Str0ng#Exam2026"
        user.set_password(plain_password)

        # Password hash is bcrypt hash (starts with $2b$ or $2a$)
        self.assertTrue(user.password_hash.startswith("$2"))
        # Plaintext password is never stored
        self.assertNotEqual(user.password_hash, plain_password)

        # Verification succeeds with correct password
        self.assertTrue(user.check_password(plain_password))
        # Verification fails with incorrect password
        self.assertFalse(user.check_password("WrongPassword1!"))

if __name__ == "__main__":
    unittest.main()
