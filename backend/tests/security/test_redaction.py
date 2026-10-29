import pytest

from redfirst.security.redact import REDACTED, redact

SECRETS = [
    "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
    "sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD",
    "AKIAIOSFODNN7EXAMPLE",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz0123456789",
    "xoxb-1234567890-abcdefghijkl",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_known_token_formats_are_removed(secret):
    out = redact(f"loaded config token={secret} ok")
    assert secret not in out and REDACTED in out
    out = redact(f"value {secret} trailing")
    assert secret not in out


def test_private_key_block_is_removed():
    body = "MIIEow\nIBAAKCAQEA"
    text = f"a\n-----BEGIN RSA PRIVATE KEY-----\n{body}\n-----END RSA PRIVATE KEY-----\nb"
    out = redact(text)
    assert "MIIEow" not in out and out.startswith("a\n") and out.endswith("\nb")


@pytest.mark.parametrize("line", [
    "DATABASE_PASSWORD=hunter2",
    "api_key: 'abc123'",
    'SECRET = "s3cr3t value"',
    "export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG",
    "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456",
])
def test_secret_assignments_hide_value_keep_name(line):
    out = redact(line)
    assert REDACTED in out
    for leaked in ("hunter2", "abc123", "s3cr3t", "wJalrXUtnFEMI", "abcdefghijklmnop"):
        assert leaked not in out


def test_assignment_keeps_variable_name_for_debugging():
    assert redact("DB_PASSWORD=hunter2") == f"DB_PASSWORD={REDACTED}"


@pytest.mark.parametrize("text", [
    "KeyError: 'username'",
    "assert discount_rate(100) == 0.1",
    "FAILED test_redfirst.py::test_reproduces_bug - AssertionError",
    "tokenize the input; keyboard shortcuts",
    "/repo/accounts/registration.py:9: in register",
])
def test_ordinary_output_is_untouched(text):
    assert redact(text) == text


def test_redaction_is_idempotent():
    once = redact("password=hunter2 sk-ant-api03-abcdefghijklmnopqrstuvwxyz")
    assert redact(once) == once
