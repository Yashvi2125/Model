"""In-process WebSocket rooms (one room per trip). Single backend worker; see README for scaling notes."""
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from server import runtime

log = logging.getLogger("tripmate.realtime")


class RoomManager:
    def __init__(self) -> None:
        self.rooms: dict[int, dict[WebSocket, int]] = defaultdict(dict)

    def online_user_ids(self, trip_id: int) -> list[int]:
        return sorted(set(self.rooms.get(trip_id, {}).values()))

    async def connect(self, trip_id: int, ws: WebSocket, user_id: int) -> None:
        self.rooms[trip_id][ws] = user_id
        await self.broadcast(trip_id, {"type": "presence", "online": self.online_user_ids(trip_id)})

    async def disconnect(self, trip_id: int, ws: WebSocket) -> None:
        self.rooms.get(trip_id, {}).pop(ws, None)
        if not self.rooms.get(trip_id):
            self.rooms.pop(trip_id, None)
        else:
            await self.broadcast(trip_id, {"type": "presence", "online": self.online_user_ids(trip_id)})

    async def broadcast(self, trip_id: int, payload: dict[str, Any]) -> None:
        for ws in list(self.rooms.get(trip_id, {})):
            try:
                await ws.send_json(payload)
            except Exception:
                self.rooms.get(trip_id, {}).pop(ws, None)


manager = RoomManager()


def publish(trip_id: int, payload: dict[str, Any]) -> None:
    """Thread-safe broadcast to everyone connected to a trip room."""
    runtime.spawn(manager.broadcast(trip_id, payload))
