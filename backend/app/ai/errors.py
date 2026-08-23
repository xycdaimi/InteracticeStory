from __future__ import annotations

import re

_QUOTA_KEYWORDS = re.compile(
    r"insufficient|balance|quota|credit|billing|payment|余额|额度|不足|欠费|充值",
    re.IGNORECASE,
)


class QuotaExhaustedError(Exception):
    """API 余额/配额不足；调用方须暂停任务，禁止自动重试。"""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        http_status: int | None = None,
        raw_message: str = "",
    ) -> None:
        self.provider = provider
        self.model = model
        self.http_status = http_status
        self.raw_message = raw_message
        super().__init__(f"quota exhausted ({provider}/{model}): {raw_message}")


def is_quota_error(status: int, body: str) -> bool:
    if status == 402:
        return True
    if status == 429 and _QUOTA_KEYWORDS.search(body):
        return True
    if status in (400, 403) and _QUOTA_KEYWORDS.search(body):
        return True
    return False


def raise_if_quota_error(
    *,
    provider: str,
    model: str,
    status: int,
    body: str,
) -> None:
    if is_quota_error(status, body):
        raise QuotaExhaustedError(
            provider=provider,
            model=model,
            http_status=status,
            raw_message=body[:500],
        )
