from mediaos.security import REDACTED, redact


def test_redact_removes_nested_secret_values() -> None:
    payload = {
        "channel": "safe",
        "credentials": {
            "api_token": "must-not-survive",
            "password": "must-not-survive-either",
        },
        "items": [{"authorization": "must-not-survive"}],
    }

    redacted = redact(payload)

    assert redacted == {
        "channel": "safe",
        "credentials": {
            "api_token": REDACTED,
            "password": REDACTED,
        },
        "items": [{"authorization": REDACTED}],
    }


def test_redact_keeps_non_secret_values() -> None:
    assert redact({"status": "ok", "cost_cents": 125}) == {
        "status": "ok",
        "cost_cents": 125,
    }
