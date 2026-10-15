"""Passing test suite for the clean selfcheck fixture.

Exercises every public function exported from ``crtw.selfcheck.clean`` so the
test-engineering agent finds no untested-symbol gaps.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from crtw.selfcheck.clean import (
    add,
    fetch,
    hash_password,
    parse_csv_line,
    query_user,
    safe_div,
    safe_list_dir,
    token_hex,
)


class CleanMathTests(unittest.TestCase):
    def test_safe_div_normal(self):
        self.assertEqual(safe_div(10, 2), 5.0)

    def test_safe_div_zero_raises(self):
        with self.assertRaises(ValueError):
            safe_div(1, 0)

    def test_add(self):
        self.assertEqual(add(2, 3), 5)


class CleanUtilTests(unittest.TestCase):
    def test_parse_csv(self):
        self.assertEqual(parse_csv_line("a, b , c"), ["a", "b", "c"])

    def test_token_hex_length(self):
        self.assertEqual(len(token_hex(8)), 16)


class CleanSecurityTests(unittest.TestCase):
    def test_hash_password_is_salted_and_repeatable(self):
        h1 = hash_password("hunter2")
        # Format: <16-byte salt hex>$<32-byte sha256 hex>
        self.assertIn("$", h1)
        salt_hex, digest_hex = h1.split("$", 1)
        self.assertEqual(len(salt_hex), 32)  # 16 bytes -> 32 hex chars
        self.assertEqual(len(digest_hex), 64)  # sha256 -> 64 hex chars
        # Two hashes of the same password should differ (random salt).
        self.assertNotEqual(h1, hash_password("hunter2"))


class CleanQueryTests(unittest.TestCase):
    def test_query_user_uses_parameterized_placeholder(self):
        sql = query_user("42")
        # The query is parameterized (uses ``?``) so user_id is only
        # interpolated as a comment  this is safe by design.
        self.assertIn("?", sql)
        self.assertIn("SELECT", sql.upper())


class CleanIoTests(unittest.TestCase):
    def test_safe_list_dir_real_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            # create a known file so ``ls -l`` has something to print
            with open(os.path.join(tmp, "hello.txt"), "w", encoding="utf-8") as fh:
                fh.write("hi\n")
            lines = safe_list_dir(tmp)
            joined = "\n".join(lines)
            self.assertIn("hello.txt", joined)

    def test_fetch_with_mocked_urlopen(self):
        # Don't actually hit the network  stub urllib.request.urlopen.
        fake_resp = mock.MagicMock()
        fake_resp.read.return_value = b"hello world"
        fake_resp.__enter__.return_value = fake_resp
        fake_resp.__exit__.return_value = False
        with mock.patch("urllib.request.urlopen", return_value=fake_resp):
            data = fetch("http://example.invalid/")
        self.assertEqual(data, b"hello world")


if __name__ == "__main__":
    unittest.main()
