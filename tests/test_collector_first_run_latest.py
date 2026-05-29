from __future__ import annotations

import pytest

from app.telegram.collector import _collect_tg_messages


class FakeMessage:
    def __init__(self, message_id: int):
        self.id = message_id


class FakeAsyncIterator:
    def __init__(self, values):
        self.values = values

    def __aiter__(self):
        self.index = 0
        return self

    async def __anext__(self):
        if self.index >= len(self.values):
            raise StopAsyncIteration
        value = self.values[self.index]
        self.index += 1
        return value


class FakeClient:
    def __init__(self):
        self.calls = []

    def iter_messages(self, entity, **kwargs):
        self.calls.append(kwargs)
        return FakeAsyncIterator([FakeMessage(105), FakeMessage(103), FakeMessage(104)])


@pytest.mark.asyncio
async def test_first_run_collects_latest_without_reverse_and_returns_ascending_order():
    client = FakeClient()
    messages = await _collect_tg_messages(client, object(), last_message_id=0, limit=100)
    assert client.calls == [{"limit": 100}]
    assert [m.id for m in messages] == [103, 104, 105]


@pytest.mark.asyncio
async def test_incremental_collect_uses_min_id_reverse():
    client = FakeClient()
    await _collect_tg_messages(client, object(), last_message_id=102, limit=100)
    assert client.calls == [{"min_id": 102, "reverse": True, "limit": 100}]

