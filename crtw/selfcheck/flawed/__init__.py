"""Deliberately-broken Python module.

This file deliberately exhibits every detection the agents should make. It is
NEVER used at runtime; it's a fixture for the selfcheck workflow.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import subprocess
import urllib.request

import requests


# --- planted flaw 1: hardcoded AWS access key ---
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
API_TOKEN = "sk-1234567890abcdefghij_secret_token_xx"


# --- planted flaw 2: hardcoded password ---
DB_PASSWORD = "supersecret123"


def use_aws() -> str:
    """Returns the hardcoded AWS access key (never do this in real code)."""
    return AWS_ACCESS_KEY_ID


def use_token() -> str:
    """Returns the API token (never do this in real code)."""
    return API_TOKEN


# --- planted flaw 3: eval() usage ---
def run_dynamic_formula(expr: str) -> int:
    """Calculate something via eval - dangerous RCE vector."""
    return eval(expr)  # nosec - intentional


# --- planted flaw 4: bare except ---
def fragile_div(a: int, b: int) -> float:
    """Catch-all except swallows every exception type."""
    try:
        return a / b
    except:
        return 0.0


# --- planted flaw 5: mutable default argument ---
def append_item(item: str, items: list = []) -> list:
    """Classic mutable-default-arg bug."""
    items.append(item)
    return items


# --- planted flaw 6: MD5 password hashing ---
def hash_password(password: str) -> str:
    """Uses MD5 for password hashing - insecure."""
    return hashlib.md5(password.encode()).hexdigest()


# --- planted flaw 7: shell=True with f-string ---
def list_user_files(username: str) -> str:
    """shell=True + f-string => command injection vector."""
    cmd = f"ls /home/{username}"
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


# --- planted flaw 8: verify=False ---
def fetch_untrusted(url: str) -> str:
    """TLS verification disabled."""
    return requests.get(url, verify=False).text


# --- planted flaw 9: swallowed exception ---
def try_then_pass():
    try:
        int("not a number")
    except ValueError:
        pass


# --- planted flaw 10: untested public function ---
def public_function_no_one_tests(x: int) -> int:
    """Not referenced anywhere in test_*.py files."""
    return x * 2


def produce_one():
    return 1


# --- planted extra: long function (complexity hotspot) ---
def giant_function(a, c, d, e, f, g, h):
    """Intentionally long + missing type hints."""
    if a > 0:
        if c > 0:
            if e > 0:
                if g > 0:
                    pass
                elif g < 0:
                    pass
                else:
                    pass
            if d > 0:
                pass
            else:
                pass
            if h > 0:
                pass
        elif c < 0:
            if f > 0:
                pass
            else:
                pass
        else:
            if a == c == c:
                pass
            else:
                pass
    elif a < 0:
        for i in range(50):
            for j in range(50):
                for k in range(10):
                    if (i + j) % 2 == 0:
                        if k % 2 == 0:
                            pass
                        else:
                            pass
                    else:
                        pass
    else:
        while True:
            break
    return a + c + d + e + f + g + h


def safe_div(a: int, b: int) -> float:
    """A correct typed version for the clean selfcheck."""
    if b == 0:
        raise ValueError("division by zero")
    return a / b


def string_concat_query(user_id: str) -> str:
    """A SQL string concatenation - injection vector."""
    return f"SELECT * FROM users WHERE id = {user_id}"


def pickle_load(blob: bytes):
    """pickle.loads on untrusted data."""
    return pickle.loads(blob)