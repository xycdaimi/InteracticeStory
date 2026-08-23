from __future__ import annotations

import pytest

from backend.app.ai.errors import QuotaExhaustedError, is_quota_error, raise_if_quota_error


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (402, "anything", True),
        (429, "insufficient balance", True),
        (429, "rate limit exceeded", False),
        (403, "账户余额不足", True),
        (500, "internal error", False),
    ],
)
def test_is_quota_error(status: int, body: str, expected: bool) -> None:
    assert is_quota_error(status, body) is expected


def test_raise_if_quota_error_raises() -> None:
    with pytest.raises(QuotaExhaustedError) as exc:
        raise_if_quota_error(
            provider="geekai",
            model="gpt-image-2",
            status=402,
            body="payment required",
        )
    assert exc.value.provider == "geekai"
    assert exc.value.http_status == 402


def test_raise_if_quota_error_ok() -> None:
    raise_if_quota_error(provider="geekai", model="m", status=500, body="server error")
