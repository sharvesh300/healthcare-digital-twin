"""In-process publish/subscribe for twin state changes, one topic per patient.

Each subscriber has a bounded queue. A subscriber that falls behind does not slow the
publisher: its queue is cleared and replaced by a single {"type": "resync"} marker, and the
WebSocket handler answers that with a fresh snapshot.

State lives in the API process, so this bus requires a single worker. To scale out, put
Postgres LISTEN/NOTIFY (or Redis) behind the same `publish` / `subscribe` interface.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

RESYNC = {"type": "resync"}


class Subscription:
    def __init__(self, maxsize: int):
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize)

    def offer(self, message: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            self.request_resync()

    def request_resync(self) -> None:
        """Drop everything queued; the consumer gets one resync marker instead."""
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(RESYNC)

    async def get(self) -> dict[str, Any]:
        return await self._queue.get()


class InProcessBus:
    def __init__(self, queue_size: int = 256):
        self._queue_size = queue_size
        self._topics: dict[str, set[Subscription]] = defaultdict(set)

    async def publish(self, topic: str, message: dict[str, Any]) -> None:
        for sub in list(self._topics.get(topic, ())):
            sub.offer(message)

    @asynccontextmanager
    async def subscribe(self, topic: str) -> AsyncIterator[Subscription]:
        sub = Subscription(self._queue_size)
        self._topics[topic].add(sub)
        try:
            yield sub
        finally:
            self._topics[topic].discard(sub)
            if not self._topics[topic]:
                del self._topics[topic]

    def subscribers(self, topic: str) -> int:
        return len(self._topics.get(topic, ()))
