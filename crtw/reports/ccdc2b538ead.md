# CRTW Run `ccdc2b538ead`

- **Target**: `/workspace/crtw/selfcheck/flawed`
- **Started**: `2026-10-15T08:39:52+00:00`
- **Finished**: `2026-10-15T08:39:55+00:00`

## ⛔ GATE: BLOCKED

**Summary:** verdict=blocked score=183 counts=BLOCKER=8, CRITICAL=7, MAJOR=21, MINOR=5, INFO=4

| Severity | Count |
|----------|------:|
| BLOCKER | 8 |
| CRITICAL | 7 |
| MAJOR | 21 |
| MINOR | 5 |
| INFO | 4 |
| **Weighted score** | **183** |

Thresholds: block ≥ 10, review ≥ 5

## Stages

| Stage | Status | Findings | Duration |
|-------|--------|----------:|---------:|
| `security` | failed | 10 | 17ms |
| `test` | failed | 20 | 556ms |
| `review` | failed | 14 | 3023ms |
| `debug` | failed | 1 | 0ms |

### Stage `security` — failed

Findings:
  - [BLOCKER] Hardcoded secret (aws_access_key_id) (`/workspace/crtw/selfcheck/flawed/__init__.py:18`)
  - [BLOCKER] Hardcoded secret (aws_secret_access_key) (`/workspace/crtw/selfcheck/flawed/__init__.py:19`)
  - [BLOCKER] Hardcoded secret (generic_api_token) (`/workspace/crtw/selfcheck/flawed/__init__.py:20`)
  - [BLOCKER] Hardcoded secret (hardcoded_password) (`/workspace/crtw/selfcheck/flawed/__init__.py:24`)
  - [BLOCKER] Dangerous use of `eval()` (`/workspace/crtw/selfcheck/flawed/__init__.py:40`)
  - [BLOCKER] Command injection: `shell=True` + format string (`/workspace/crtw/selfcheck/flawed/__init__.py:69`)
  - [BLOCKER] SQL injection risk: f-string SQL query (`/workspace/crtw/selfcheck/flawed/__init__.py:150`)
  - [BLOCKER] `pickle.loads` on untrusted input (`/workspace/crtw/selfcheck/flawed/__init__.py:155`)
  - [CRITICAL] Weak hashing for password: `hashlib.md5` (`/workspace/crtw/selfcheck/flawed/__init__.py:62`)
  - [CRITICAL] TLS verification disabled (`verify=False`) (`/workspace/crtw/selfcheck/flawed/__init__.py:75`)

### Stage `test` — failed

Findings:
  - [CRITICAL] Test failure: test_intentional_failure (`/workspace/crtw/selfcheck/flawed/test_flawed.py:16`)
  - [MAJOR] Untested public symbol: `API_TOKEN` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `AWS_ACCESS_KEY_ID` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `AWS_SECRET_ACCESS_KEY` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `DB_PASSWORD` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `append_item` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `fetch_untrusted` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `fragile_div` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `giant_function` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `hash_password` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `list_user_files` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `pickle_load` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `public_function_no_one_tests` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `run_dynamic_formula` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `safe_div` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `string_concat_query` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `use_aws` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Untested public symbol: `use_token` (`/workspace/crtw/selfcheck/flawed:None`)
  - [MAJOR] Test `test_no_assertions` has no assertions (`/workspace/crtw/selfcheck/flawed/test_flawed.py:19`)
  - [MAJOR] Test `test_swallowed` has no assertions (`/workspace/crtw/selfcheck/flawed/test_flawed.py:24`)

### Stage `review` — failed

Findings:
  - [CRITICAL] Bare `except:` swallows all exceptions (`/workspace/crtw/selfcheck/flawed/__init__.py:48`)
  - [CRITICAL] Mutable default argument in `append_item` (`/workspace/crtw/selfcheck/flawed/__init__.py:53`)
  - [CRITICAL] Long function: giant_function (167 AST nodes) (`/workspace/crtw/selfcheck/flawed/__init__.py:97`)
  - [MAJOR] Unguarded risky call: `requests.get()` (`/workspace/crtw/selfcheck/flawed/__init__.py:75`)
  - [MAJOR] Swallowed exception (`except: pass`) (`/workspace/crtw/selfcheck/flawed/__init__.py:82`)
  - [MINOR] Unused import: `os` (`/workspace/crtw/selfcheck/flawed/__init__.py:9`)
  - [MINOR] ast-fallback:F401: imported but unused: 'os' (`/workspace/crtw/selfcheck/flawed/__init__.py:9`)
  - [MINOR] Unused import: `urllib` (`/workspace/crtw/selfcheck/flawed/__init__.py:12`)
  - [MINOR] ast-fallback:F401: imported but unused: 'urllib' (`/workspace/crtw/selfcheck/flawed/__init__.py:12`)
  - [MINOR] Missing type hints on public function `giant_function` (`/workspace/crtw/selfcheck/flawed/__init__.py:97`)
  - [INFO] Missing return annotation on `try_then_pass` (`/workspace/crtw/selfcheck/flawed/__init__.py:79`)
  - [INFO] Missing return annotation on `produce_one` (`/workspace/crtw/selfcheck/flawed/__init__.py:92`)
  - [INFO] Missing return annotation on `giant_function` (`/workspace/crtw/selfcheck/flawed/__init__.py:97`)
  - [INFO] Missing return annotation on `pickle_load` (`/workspace/crtw/selfcheck/flawed/__init__.py:153`)

### Stage `debug` — failed

Findings:
  - [CRITICAL] Root cause (product bug): Test failure: test_intentional_failure (`/workspace/crtw/selfcheck/flawed/test_flawed.py:16`)

## Findings by File

### `/workspace/crtw/selfcheck/flawed`

| Sev | Line | Title | Stage | Confidence |
|-----|-----:|-------|-------|-----------:|
| 🟡 MAJOR | - | Untested public symbol: `API_TOKEN` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `AWS_ACCESS_KEY_ID` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `AWS_SECRET_ACCESS_KEY` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `DB_PASSWORD` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `append_item` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `fetch_untrusted` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `fragile_div` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `giant_function` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `hash_password` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `list_user_files` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `pickle_load` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `public_function_no_one_tests` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `run_dynamic_formula` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `safe_div` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `string_concat_query` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `use_aws` | `test` | 0.60 |
| 🟡 MAJOR | - | Untested public symbol: `use_token` | `test` | 0.60 |

<details><summary><strong>MAJOR</strong> — Untested public symbol: `API_TOKEN`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `API_TOKEN` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `AWS_ACCESS_KEY_ID`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `AWS_ACCESS_KEY_ID` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `AWS_SECRET_ACCESS_KEY`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `AWS_SECRET_ACCESS_KEY` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `DB_PASSWORD`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `DB_PASSWORD` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `append_item`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `append_item` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `fetch_untrusted`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `fetch_untrusted` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `fragile_div`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `fragile_div` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `giant_function`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `giant_function` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `hash_password`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `hash_password` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `list_user_files`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `list_user_files` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `pickle_load`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `pickle_load` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `public_function_no_one_tests`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `public_function_no_one_tests` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `run_dynamic_formula`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `run_dynamic_formula` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `safe_div`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `safe_div` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `string_concat_query`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `string_concat_query` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `use_aws`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `use_aws` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

<details><summary><strong>MAJOR</strong> — Untested public symbol: `use_token`</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed:?`
- **Detail:** No test references this public symbol.
- **Evidence:**

```
public symbol `use_token` not referenced in any test_*.py
```
- **Remediation:** Add a unit test that exercises this function.
- **Tags:** `tests, coverage-gap`

</details>

### `/workspace/crtw/selfcheck/flawed/__init__.py`

| Sev | Line | Title | Stage | Confidence |
|-----|-----:|-------|-------|-----------:|
| 🔴 BLOCKER | 18 | Hardcoded secret (aws_access_key_id) | `security` | 0.99 |
| 🔴 BLOCKER | 19 | Hardcoded secret (aws_secret_access_key) | `security` | 0.99 |
| 🔴 BLOCKER | 20 | Hardcoded secret (generic_api_token) | `security` | 0.99 |
| 🔴 BLOCKER | 24 | Hardcoded secret (hardcoded_password) | `security` | 0.99 |
| 🔴 BLOCKER | 40 | Dangerous use of `eval()` | `security` | 0.95 |
| 🔴 BLOCKER | 69 | Command injection: `shell=True` + format string | `security` | 0.95 |
| 🔴 BLOCKER | 150 | SQL injection risk: f-string SQL query | `security` | 0.85 |
| 🔴 BLOCKER | 155 | `pickle.loads` on untrusted input | `security` | 0.90 |
| 🟠 CRITICAL | 48 | Bare `except:` swallows all exceptions | `review` | 0.95 |
| 🟠 CRITICAL | 53 | Mutable default argument in `append_item` | `review` | 0.99 |
| 🟠 CRITICAL | 62 | Weak hashing for password: `hashlib.md5` | `security` | 0.90 |
| 🟠 CRITICAL | 75 | TLS verification disabled (`verify=False`) | `security` | 0.95 |
| 🟠 CRITICAL | 97 | Long function: giant_function (167 AST nodes) | `review` | 0.80 |
| 🟡 MAJOR | 75 | Unguarded risky call: `requests.get()` | `review` | 0.70 |
| 🟡 MAJOR | 82 | Swallowed exception (`except: pass`) | `review` | 0.95 |
| 🔵 MINOR | 9 | Unused import: `os` | `review` | 0.90 |
| 🔵 MINOR | 9 | ast-fallback:F401: imported but unused: 'os' | `review` | 0.80 |
| 🔵 MINOR | 12 | Unused import: `urllib` | `review` | 0.90 |
| 🔵 MINOR | 12 | ast-fallback:F401: imported but unused: 'urllib' | `review` | 0.80 |
| 🔵 MINOR | 97 | Missing type hints on public function `giant_function` | `review` | 0.70 |
| ⚪ INFO | 79 | Missing return annotation on `try_then_pass` | `review` | 0.60 |
| ⚪ INFO | 92 | Missing return annotation on `produce_one` | `review` | 0.60 |
| ⚪ INFO | 97 | Missing return annotation on `giant_function` | `review` | 0.60 |
| ⚪ INFO | 153 | Missing return annotation on `pickle_load` | `review` | 0.60 |

<details><summary><strong>BLOCKER</strong> — Hardcoded secret (aws_access_key_id)</summary>

- **Stage:** `security` (S6-AGI3-037-SECURITYAUDITOR)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:18`
- **Detail:** AWS access key id
- **Evidence:**

```
AKIA...MPLE
```
- **Remediation:** Move the secret to an environment variable, vault, or secrets manager. Rotate the leaked credential.
- **Tags:** `secret, aws_access_key_id`

</details>

<details><summary><strong>BLOCKER</strong> — Hardcoded secret (aws_secret_access_key)</summary>

- **Stage:** `security` (S6-AGI3-037-SECURITYAUDITOR)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:19`
- **Detail:** AWS secret access key
- **Evidence:**

```
AWS_...KEY"
```
- **Remediation:** Move the secret to an environment variable, vault, or secrets manager. Rotate the leaked credential.
- **Tags:** `secret, aws_secret_access_key`

</details>

<details><summary><strong>BLOCKER</strong> — Hardcoded secret (generic_api_token)</summary>

- **Stage:** `security` (S6-AGI3-037-SECURITYAUDITOR)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:20`
- **Detail:** Generic API/auth token
- **Evidence:**

```
API_..._xx"
```
- **Remediation:** Move the secret to an environment variable, vault, or secrets manager. Rotate the leaked credential.
- **Tags:** `secret, generic_api_token`

</details>

<details><summary><strong>BLOCKER</strong> — Hardcoded secret (hardcoded_password)</summary>

- **Stage:** `security` (S6-AGI3-037-SECURITYAUDITOR)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:24`
- **Detail:** Hardcoded password
- **Evidence:**

```
PASS...123"
```
- **Remediation:** Move the secret to an environment variable, vault, or secrets manager. Rotate the leaked credential.
- **Tags:** `secret, hardcoded_password`

</details>

<details><summary><strong>BLOCKER</strong> — Dangerous use of `eval()`</summary>

- **Stage:** `security` (S6-AGI3-037-SECURITYAUDITOR)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:40`
- **Detail:** `eval()` executes arbitrary code; common RCE vector if input is untrusted.
- **Evidence:**

```
/workspace/crtw/selfcheck/flawed/__init__.py:40: eval
```
- **Remediation:** Avoid `eval`/`exec`. Use `ast.literal_eval` for data, or restructure to avoid dynamic execution.
- **Tags:** `rce, eval`

</details>

<details><summary><strong>BLOCKER</strong> — Command injection: `shell=True` + format string</summary>

- **Stage:** `security` (S6-AGI3-037-SECURITYAUDITOR)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:69`
- **Detail:** `shell=True` with an f-string/.format() first arg enables command injection.
- **Evidence:**

```
/workspace/crtw/selfcheck/flawed/__init__.py:69: subprocess.run
```
- **Remediation:** Use list-form subprocess (no shell) and pass arguments separately; never interpolate user input.
- **Tags:** `command-injection, shell`

</details>

<details><summary><strong>BLOCKER</strong> — SQL injection risk: f-string SQL query</summary>

- **Stage:** `security` (S6-AGI3-037-SECURITYAUDITOR)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:150`
- **Detail:** SQL string built with f-string / .format() — use parameterized queries.
- **Evidence:**

```
/workspace/crtw/selfcheck/flawed/__init__.py:150
```
- **Remediation:** Use parameter substitution: `cursor.execute(sql, (param,))`.
- **Tags:** `sql-injection`

</details>

<details><summary><strong>BLOCKER</strong> — `pickle.loads` on untrusted input</summary>

- **Stage:** `security` (S6-AGI3-037-SECURITYAUDITOR)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:155`
- **Detail:** `pickle.loads` allows arbitrary code execution.
- **Evidence:**

```
/workspace/crtw/selfcheck/flawed/__init__.py:155: pickle.loads
```
- **Remediation:** Use JSON or msgpack for untrusted input; never unpickle attacker-controlled bytes.
- **Tags:** `rce, pickle`

</details>

<details><summary><strong>CRITICAL</strong> — Bare `except:` swallows all exceptions</summary>

- **Stage:** `review` (S3-AGI3-010-REVIEWER)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:48`
- **Detail:** A bare `except:` catches BaseException including KeyboardInterrupt and SystemExit.
- **Evidence:**

```
/workspace/crtw/selfcheck/flawed/__init__.py:48: bare except
```
- **Remediation:** Catch a specific exception class (e.g. `except ValueError:`).
- **Tags:** `error-handling, bare-except`

</details>

<details><summary><strong>CRITICAL</strong> — Mutable default argument in `append_item`</summary>

- **Stage:** `review` (S3-AGI3-010-REVIEWER)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:53`
- **Detail:** Mutable defaults are shared between calls and cause subtle state-leak bugs.
- **Evidence:**

```
def append_item(...)
```
- **Remediation:** Use `None` as the default and create the mutable inside the function.
- **Tags:** `mutable-default`

</details>

<details><summary><strong>CRITICAL</strong> — Weak hashing for password: `hashlib.md5`</summary>

- **Stage:** `security` (S6-AGI3-037-SECURITYAUDITOR)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:62`
- **Detail:** MD5/SHA1 are not suitable for password hashing.
- **Evidence:**

```
/workspace/crtw/selfcheck/flawed/__init__.py:62: hashlib.md5(...)
```
- **Remediation:** Use `hashlib.bcrypt`, `argon2`, or `hashlib.scrypt`.
- **Tags:** `crypto, weak-hash-password`

</details>

<details><summary><strong>CRITICAL</strong> — TLS verification disabled (`verify=False`)</summary>

- **Stage:** `security` (S6-AGI3-037-SECURITYAUDITOR)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:75`
- **Detail:** `verify=False` disables certificate validation. Vulnerable to MITM.
- **Evidence:**

```
/workspace/crtw/selfcheck/flawed/__init__.py:75: requests.get(verify=False)
```
- **Remediation:** Remove `verify=False`; if you must use a self-signed cert pass `verify='/path/to/cert'`.
- **Tags:** `tls, mitm`

</details>

<details><summary><strong>CRITICAL</strong> — Long function: giant_function (167 AST nodes)</summary>

- **Stage:** `review` (S3-AGI3-010-REVIEWER)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:97`
- **Detail:** Function `giant_function` has 167 AST nodes which is a complexity hotspot. Consider splitting it.
- **Evidence:**

```
/workspace/crtw/selfcheck/flawed/__init__.py:97:def giant_function
```
- **Remediation:** Extract helper functions; lower cyclomatic complexity.
- **Tags:** `complexity`

</details>

<details><summary><strong>MAJOR</strong> — Unguarded risky call: `requests.get()`</summary>

- **Stage:** `review` (S3-AGI3-010-REVIEWER)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:75`
- **Detail:** Network or file operation without a try/except or with-context guard.
- **Evidence:**

```
/workspace/crtw/selfcheck/flawed/__init__.py:75: requests.get
```
- **Remediation:** Wrap in try/except (and handle the specific exception class) or use a `with` context.
- **Tags:** `error-handling`

</details>

<details><summary><strong>MAJOR</strong> — Swallowed exception (`except: pass`)</summary>

- **Stage:** `review` (S3-AGI3-010-REVIEWER)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:82`
- **Detail:** Exception caught and silently dropped.
- **Evidence:**

```
/workspace/crtw/selfcheck/flawed/__init__.py:82
```
- **Remediation:** Log or re-raise; do not silently ignore exceptions.
- **Tags:** `swallowed`

</details>

<details><summary><strong>MINOR</strong> — Unused import: `os`</summary>

- **Stage:** `review` (S3-AGI3-010-REVIEWER)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:9`
- **Detail:** Imported but never referenced.
- **Evidence:**

```
line 9: import os
```
- **Remediation:** Remove the unused import.
- **Tags:** `unused-import`

</details>

<details><summary><strong>MINOR</strong> — ast-fallback:F401: imported but unused: 'os'</summary>

- **Stage:** `review` (S3-AGI3-010-REVIEWER)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:9`
- **Detail:** imported but unused: 'os'
- **Evidence:**

```
/workspace/crtw/selfcheck/flawed/__init__.py:9
```
- **Remediation:** See linter documentation.
- **Tags:** `linter, ast_fallback`

</details>

<details><summary><strong>MINOR</strong> — Unused import: `urllib`</summary>

- **Stage:** `review` (S3-AGI3-010-REVIEWER)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:12`
- **Detail:** Imported but never referenced.
- **Evidence:**

```
line 12: import urllib
```
- **Remediation:** Remove the unused import.
- **Tags:** `unused-import`

</details>

<details><summary><strong>MINOR</strong> — ast-fallback:F401: imported but unused: 'urllib'</summary>

- **Stage:** `review` (S3-AGI3-010-REVIEWER)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:12`
- **Detail:** imported but unused: 'urllib'
- **Evidence:**

```
/workspace/crtw/selfcheck/flawed/__init__.py:12
```
- **Remediation:** See linter documentation.
- **Tags:** `linter, ast_fallback`

</details>

<details><summary><strong>MINOR</strong> — Missing type hints on public function `giant_function`</summary>

- **Stage:** `review` (S3-AGI3-010-REVIEWER)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:97`
- **Detail:** Missing annotations for: a, c, d, e, f, g, h
- **Evidence:**

```
def giant_function(a, c, d, e, f, g, h)
```
- **Remediation:** Add type annotations to arguments and return.
- **Tags:** `typing`

</details>

<details><summary><strong>INFO</strong> — Missing return annotation on `try_then_pass`</summary>

- **Stage:** `review` (S3-AGI3-010-REVIEWER)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:79`
- **Detail:** Public function has no return type annotation.
- **Evidence:**

```
def try_then_pass(...)
```
- **Remediation:** Add a return annotation.
- **Tags:** `typing`

</details>

<details><summary><strong>INFO</strong> — Missing return annotation on `produce_one`</summary>

- **Stage:** `review` (S3-AGI3-010-REVIEWER)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:92`
- **Detail:** Public function has no return type annotation.
- **Evidence:**

```
def produce_one(...)
```
- **Remediation:** Add a return annotation.
- **Tags:** `typing`

</details>

<details><summary><strong>INFO</strong> — Missing return annotation on `giant_function`</summary>

- **Stage:** `review` (S3-AGI3-010-REVIEWER)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:97`
- **Detail:** Public function has no return type annotation.
- **Evidence:**

```
def giant_function(...)
```
- **Remediation:** Add a return annotation.
- **Tags:** `typing`

</details>

<details><summary><strong>INFO</strong> — Missing return annotation on `pickle_load`</summary>

- **Stage:** `review` (S3-AGI3-010-REVIEWER)
- **Location:** `/workspace/crtw/selfcheck/flawed/__init__.py:153`
- **Detail:** Public function has no return type annotation.
- **Evidence:**

```
def pickle_load(...)
```
- **Remediation:** Add a return annotation.
- **Tags:** `typing`

</details>

### `/workspace/crtw/selfcheck/flawed/test_flawed.py`

| Sev | Line | Title | Stage | Confidence |
|-----|-----:|-------|-------|-----------:|
| 🟠 CRITICAL | 16 | Root cause (product bug): Test failure: test_intentional_failure | `debug` | 0.85 |
| 🟠 CRITICAL | 16 | Test failure: test_intentional_failure | `test` | 0.95 |
| 🟡 MAJOR | 19 | Test `test_no_assertions` has no assertions | `test` | 0.85 |
| 🟡 MAJOR | 24 | Test `test_swallowed` has no assertions | `test` | 0.85 |

<details><summary><strong>CRITICAL</strong> — Root cause (product bug): Test failure: test_intentional_failure</summary>

- **Stage:** `debug` (S6-AGI3-014-DEBUGGER)
- **Location:** `/workspace/crtw/selfcheck/flawed/test_flawed.py:16`
- **Detail:** Test: Test failure: test_intentional_failure
Assertion/Message: assert produce_one() == 2
Suspected production frame: (unknown)
Classification: product bug.
- **Evidence:**

```
This test always fails — verifies the tester/debugger agents can pick it up.
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/crtw/selfcheck/flawed/test_flawed.py", line 16, in test_intentional_failure
    assert produce_one() == 2
           ^^^^^^^^^^^^^^^^^^
AssertionError

----------------------------------------------------------------------
Ran 4 tests in 0.001s

FAILED (failures=1)
```
- **Remediation:** Inspect the failing frame in production code. If it's a test bug, fix the assertion or test fixture.
- **Tags:** `debug, product`

</details>

<details><summary><strong>CRITICAL</strong> — Test failure: test_intentional_failure</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed/test_flawed.py:16`
- **Detail:** assert produce_one() == 2
- **Evidence:**

```
This test always fails — verifies the tester/debugger agents can pick it up.
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/crtw/selfcheck/flawed/test_flawed.py", line 16, in test_intentional_failure
    assert produce_one() == 2
           ^^^^^^^^^^^^^^^^^^
AssertionError

----------------------------------------------------------------------
Ran 4 tests in 0.001s

FAILED (failures=1)
```
- **Remediation:** Read the traceback, fix the production code or the test expectation.
- **Tags:** `tests, failure`

</details>

<details><summary><strong>MAJOR</strong> — Test `test_no_assertions` has no assertions</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed/test_flawed.py:19`
- **Detail:** Tests with no `assert` always pass — flaky / no-op test.
- **Evidence:**

```
def test_no_assertions(...)
```
- **Remediation:** Add at least one `assert ...` to validate behaviour.
- **Tags:** `tests, no-assertion`

</details>

<details><summary><strong>MAJOR</strong> — Test `test_swallowed` has no assertions</summary>

- **Stage:** `test` (S3-AGI3-009-TESTER)
- **Location:** `/workspace/crtw/selfcheck/flawed/test_flawed.py:24`
- **Detail:** Tests with no `assert` always pass — flaky / no-op test.
- **Evidence:**

```
def test_swallowed(...)
```
- **Remediation:** Add at least one `assert ...` to validate behaviour.
- **Tags:** `tests, no-assertion`

</details>

## Blocking findings

- **[BLOCKER]** Hardcoded secret (aws_access_key_id)  — `/workspace/crtw/selfcheck/flawed/__init__.py:18`
  - AWS access key id
- **[BLOCKER]** Hardcoded secret (aws_secret_access_key)  — `/workspace/crtw/selfcheck/flawed/__init__.py:19`
  - AWS secret access key
- **[BLOCKER]** Hardcoded secret (generic_api_token)  — `/workspace/crtw/selfcheck/flawed/__init__.py:20`
  - Generic API/auth token
- **[BLOCKER]** Hardcoded secret (hardcoded_password)  — `/workspace/crtw/selfcheck/flawed/__init__.py:24`
  - Hardcoded password
- **[BLOCKER]** Dangerous use of `eval()`  — `/workspace/crtw/selfcheck/flawed/__init__.py:40`
  - `eval()` executes arbitrary code; common RCE vector if input is untrusted.
- **[BLOCKER]** SQL injection risk: f-string SQL query  — `/workspace/crtw/selfcheck/flawed/__init__.py:150`
  - SQL string built with f-string / .format() — use parameterized queries.
- **[BLOCKER]** `pickle.loads` on untrusted input  — `/workspace/crtw/selfcheck/flawed/__init__.py:155`
  - `pickle.loads` allows arbitrary code execution.
- **[BLOCKER]** Command injection: `shell=True` + format string  — `/workspace/crtw/selfcheck/flawed/__init__.py:69`
  - `shell=True` with an f-string/.format() first arg enables command injection.

## Artifacts

- JSON: `ccdc2b538ead.json`
- Markdown: `ccdc2b538ead.md`
