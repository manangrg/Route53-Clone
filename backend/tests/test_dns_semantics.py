import sqlite3
import unittest

from fastapi import HTTPException

from app.main import (
    ensure_cname_compatibility,
    normalize_record_name,
    normalize_zone_name,
    validate_record_data,
)


class DnsSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.zone = {"id": 1, "name": "example.com."}
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "CREATE TABLE dns_records (id INTEGER PRIMARY KEY, zone_id INTEGER, name TEXT, type TEXT)"
        )

    def tearDown(self):
        self.conn.close()

    def test_zone_names_are_normalized_and_validated(self):
        self.assertEqual(normalize_zone_name("Example.COM"), "example.com.")
        with self.assertRaises(HTTPException):
            normalize_zone_name("bad..example")

    def test_relative_and_absolute_record_names_stay_in_zone(self):
        self.assertEqual(normalize_record_name("www", "example.com."), "www.example.com.")
        self.assertEqual(normalize_record_name("www.example.com.", "example.com."), "www.example.com.")
        with self.assertRaises(HTTPException):
            normalize_record_name("outside.net.", "example.com.")

    def test_address_record_values_are_validated(self):
        data = validate_record_data(
            self.zone,
            {"name": "@", "type": "A", "ttl": 60, "value": "192.0.2.9"},
        )
        self.assertEqual(data["value"], "192.0.2.9")
        with self.assertRaises(HTTPException):
            validate_record_data(
                self.zone,
                {"name": "www", "type": "AAAA", "value": "192.0.2.9"},
            )

    def test_cname_is_not_allowed_at_zone_apex_or_alongside_other_data(self):
        with self.assertRaises(HTTPException):
            validate_record_data(
                self.zone,
                {"name": "@", "type": "CNAME", "value": "target.net"},
            )
        self.conn.execute(
            "INSERT INTO dns_records (id, zone_id, name, type) VALUES (1, 1, 'www.example.com.', 'A')"
        )
        cname = validate_record_data(
            self.zone,
            {"name": "www", "type": "CNAME", "value": "target.net"},
        )
        with self.assertRaises(HTTPException):
            ensure_cname_compatibility(self.conn, 1, cname)

    def test_mx_and_srv_require_protocol_fields(self):
        with self.assertRaises(HTTPException):
            validate_record_data(
                self.zone,
                {"name": "mail", "type": "MX", "value": "mail.example.net"},
            )
        srv = validate_record_data(
            self.zone,
            {
                "name": "_sip._tcp",
                "type": "SRV",
                "priority": 10,
                "weight": 5,
                "port": 5060,
                "target": "sip.example.net",
            },
        )
        self.assertEqual(srv["target"], "sip.example.net.")


if __name__ == "__main__":
    unittest.main()
