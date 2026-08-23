from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.ai.ephone_video import EphoneVideoClient
from backend.app.config import Settings


@pytest.mark.asyncio
async def test_ephone_submit_requires_duration_and_768p(tmp_path: Path) -> None:
    frame = tmp_path / "first.png"
    frame.write_bytes(b"png")

    captured: dict = {}

    async def fake_post(url: str, *, json: dict, headers: dict) -> MagicMock:
        captured["json"] = json
        resp = MagicMock()
        resp.status_code = 200
        resp.text = '{"id":"task-abc"}'
        resp.json.return_value = {"id": "task-abc"}
        resp.raise_for_status = MagicMock()
        return resp

    client_mock = MagicMock()
    client_mock.post = AsyncMock(side_effect=fake_post)
    settings = Settings(ephone_api_key="test-key", video_resolution="768P")
    client = EphoneVideoClient(settings=settings, client=client_mock)

    task_id = await client.submit(
        model="MiniMax-H3",
        prompt="镜头推进",
        first_frame=frame,
        duration=9,
    )

    assert task_id == "task-abc"
    inp = captured["json"]["input"]
    assert inp["duration"] == 9
    assert inp["resolution"] == "768P"


@pytest.mark.asyncio
async def test_ephone_submit_missing_duration_raises(tmp_path: Path) -> None:
    frame = tmp_path / "first.png"
    frame.write_bytes(b"png")
    client = EphoneVideoClient(settings=Settings(ephone_api_key="test-key"))
    with pytest.raises(ValueError, match="duration is required"):
        await client.submit(
            model="MiniMax-H3",
            prompt="test",
            first_frame=frame,
        )
