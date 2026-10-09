import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database
from app.database import hash_password, verify_password
from app.main import ensure_user


class PasswordHashTests(unittest.TestCase):
    def test_password_hash_is_salted_and_verifiable(self):
        first_hash = hash_password("admin123")
        second_hash = hash_password("admin123")

        self.assertNotEqual(first_hash, second_hash)
        self.assertTrue(verify_password("admin123", first_hash))
        self.assertFalse(verify_password("wrong-password", first_hash))

    def test_login_uses_hash_verification(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT, name TEXT)"
        )
        conn.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
            (1, "admin", hash_password(" admin123 "), "admin", "Demo Admin"),
        )

        self.assertIsNotNone(ensure_user(conn, "admin", " admin123 "))
        self.assertIsNone(ensure_user(conn, "admin", "admin123"))
        conn.close()

    def test_database_initialization_upgrades_legacy_plaintext_passwords(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "route53.db"
            with patch.object(database, "DB_PATH", db_path):
                database.init_db()
                conn = sqlite3.connect(db_path)
                conn.execute("UPDATE users SET password = ? WHERE username = 'admin'", ("admin123",))
                conn.commit()
                conn.close()

                database.init_db()

                conn = sqlite3.connect(db_path)
                stored_password = conn.execute(
                    "SELECT password FROM users WHERE username = 'admin'"
                ).fetchone()[0]
                conn.close()

            self.assertNotEqual(stored_password, "admin123")
            self.assertTrue(verify_password("admin123", stored_password))


if __name__ == "__main__":
    unittest.main()
