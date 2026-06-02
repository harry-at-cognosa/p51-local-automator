"""Hermetic unit tests for Email Reaper (type 8) pure helpers.

Covers the safety-critical bits that don't need a DB or live email account:
preview-default gating, single-account resolution, sender-list validation
(clamp / dedupe / cap / drop-invalid), and report CSV shaping.

Run with: pytest backend/tests/test_email_reaper.py -v
"""
import pytest

from backend.services.workflows.email_reaper import (
    WINDOW_DEFAULT,
    WINDOW_MAX,
    WINDOW_MIN,
    _build_csv,
    _is_preview,
    _resolve_single_account,
    _validate_senders,
)


# ── _is_preview: deletion must never arm without an explicit False ──────────


def test_is_preview_defaults_true_when_missing():
    assert _is_preview({}) is True


@pytest.mark.parametrize("value,expected", [
    (False, False),   # the ONLY way to arm live deletion
    (True, True),
    (None, True),
    (0, True),         # falsey-but-not-False still previews (fail safe)
    ("no", True),
])
def test_is_preview_only_explicit_false_arms(value, expected):
    assert _is_preview({"preview_only": value}) is expected


# ── _resolve_single_account ─────────────────────────────────────────────────


def test_resolve_apple_mail_defaults_to_icloud():
    assert _resolve_single_account({"service": "apple_mail"}) == {
        "service": "apple_mail", "account": "iCloud", "mailboxes": ["INBOX"],
    }
    # apple_mail is the default service when unspecified.
    assert _resolve_single_account({})["service"] == "apple_mail"


def test_resolve_apple_mail_mailboxes():
    # Custom mailbox list is honored and whitespace-trimmed.
    acct = _resolve_single_account(
        {"service": "apple_mail", "account": "iCloud", "mailboxes": ["INBOX", " 1-Newsletters ", ""]}
    )
    assert acct["mailboxes"] == ["INBOX", "1-Newsletters"]
    # Empty / non-list falls back to INBOX.
    assert _resolve_single_account(
        {"service": "apple_mail", "mailboxes": []}
    )["mailboxes"] == ["INBOX"]


def test_resolve_gmail_requires_int_account_id():
    assert _resolve_single_account({"service": "gmail", "account_id": 3}) == {
        "service": "gmail", "account_id": 3,
    }
    with pytest.raises(ValueError):
        _resolve_single_account({"service": "gmail"})
    with pytest.raises(ValueError):
        _resolve_single_account({"service": "gmail", "account_id": "3"})


def test_resolve_gmail_imap_requires_email():
    assert _resolve_single_account({"service": "gmail_imap", "email": "x@gmail.com"}) == {
        "service": "gmail_imap", "email": "x@gmail.com",
    }
    with pytest.raises(ValueError):
        _resolve_single_account({"service": "gmail_imap"})


def test_resolve_rejects_unknown_service():
    with pytest.raises(ValueError):
        _resolve_single_account({"service": "outlook"})


# ── _validate_senders ───────────────────────────────────────────────────────


def test_validate_clamps_window_to_bounds():
    cleaned, _ = _validate_senders(
        [
            {"from_address": "a@x.com", "safety_window_days": 1},     # < min
            {"from_address": "b@x.com", "safety_window_days": 9999},  # > max
            {"from_address": "c@x.com", "safety_window_days": 30},    # ok
        ],
        max_senders=150,
    )
    by_addr = {r["from_address"]: r["safety_window_days"] for r in cleaned}
    assert by_addr["a@x.com"] == WINDOW_MIN
    assert by_addr["b@x.com"] == WINDOW_MAX
    assert by_addr["c@x.com"] == 30


def test_validate_defaults_window_when_missing_or_bad():
    cleaned, _ = _validate_senders(
        [
            {"from_address": "a@x.com"},
            {"from_address": "b@x.com", "safety_window_days": "abc"},
        ],
        max_senders=150,
    )
    assert all(r["safety_window_days"] == WINDOW_DEFAULT for r in cleaned)


def test_validate_drops_invalid_addresses():
    cleaned, notes = _validate_senders(
        [
            {"from_address": "good@x.com", "safety_window_days": 10},
            {"from_address": "not-an-email", "safety_window_days": 10},
            {"from_address": "", "safety_window_days": 10},
            "totally wrong shape",
        ],
        max_senders=150,
    )
    assert [r["from_address"] for r in cleaned] == ["good@x.com"]
    assert any("invalid" in n for n in notes)


def test_validate_dedupes_case_insensitive():
    cleaned, notes = _validate_senders(
        [
            {"from_address": "Dup@X.com", "safety_window_days": 10},
            {"from_address": "dup@x.com", "safety_window_days": 20},
        ],
        max_senders=150,
    )
    assert len(cleaned) == 1
    assert cleaned[0]["safety_window_days"] == 10  # first occurrence wins
    assert any("duplicate" in n for n in notes)


def test_validate_caps_at_max_senders():
    rows = [{"from_address": f"u{i}@x.com", "safety_window_days": 10} for i in range(20)]
    cleaned, _ = _validate_senders(rows, max_senders=5)
    assert len(cleaned) == 5


def test_validate_handles_non_list():
    cleaned, _ = _validate_senders(None, max_senders=150)
    assert cleaned == []


# ── _build_csv ──────────────────────────────────────────────────────────────


def test_build_csv_header_and_rows():
    matches = [
        {
            "from_address": "a@x.com", "subject": "Hello", "date": "2026-01-01T00:00:00+00:00",
            "mailbox": "(all mail)", "age_days": 40, "safety_window_days": 14, "action": "trashed",
        },
        {
            "from_address": "b@x.com", "subject": "", "date": "", "mailbox": "",
            "age_days": None, "safety_window_days": 30, "action": "would delete",
        },
    ]
    csv_text = _build_csv(matches)
    lines = csv_text.strip().splitlines()
    assert lines[0] == "from_address,subject,date,mailbox,age_days,safety_window_days,action"
    assert "a@x.com,Hello," in lines[1]
    assert lines[1].endswith("trashed")
    # None age_days renders as an empty field, not the literal "None".
    assert ",,30,would delete" in lines[2]
