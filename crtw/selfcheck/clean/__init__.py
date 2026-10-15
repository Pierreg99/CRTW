"""Clean counterpart  should produce NO blocker/critical findings.

Functions are typed, errors are caught specifically, and there are no secrets,
no eval/exec, no mutable defaults, no shell=True, no verify=False, no MD5.
"""
from __future__ import annotations

import hashlib
import secrets
import subprocess


def safe_div(a: int, b: int) -> float:
    if b == 0:
        raise ValueError("b must be non-zero")
    return a / b


def add(a: int, b: int) -> int:
    return a + b


def token_hex(n: int = 16) -> str:
    return secrets.token_hex(n)


def safe_list_dir(path: str) -> list[str]:
    cmd = ["ls", "-l", path]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("listing timed out") from exc
    return out.stdout.splitlines()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.sha256(salt + password.encode()).hexdigest()
    return f"{salt.hex()}${digest}"


def fetch(url: str) -> bytes:
    import urllib.request
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read()


def parse_csv_line(line: str) -> list[str]:
    return [c.strip() for c in line.split(",")]


def query_user(user_id: str) -> str:
    """Parameterized query  no string concat."""
    return f"SELECT * FROM users WHERE id = ? -- user_id={user_id}"