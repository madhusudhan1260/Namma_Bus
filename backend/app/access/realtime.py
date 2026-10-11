"""
Realtime trip updates over WebSocket (/api/access/ws).

PostgreSQL stays the single source of truth: every message carries the trip's committed values, and it is
sent only after the transaction that changed them has committed (SQLAlchemy `after_commit`), so a rolled-back
change is never broadcast. Each message has a monotonically increasing `seq` (the trip's updated_at in
microseconds) so a client can drop an older message that arrives late. A client that (re)subscribes always
gets a fresh snapshot read from the database first.

Topics: trip:<trip_id> · route:<route> · bus:<bus_id> (its conductor / admin) · admin (Super Admin) ·
user:<user_id> (that user's own notifications only).

Authentication: the client's first message is {"action": "auth", "token": "<access token>"}. The token is never
put in the URL, so it can't end up in server access logs or proxies.

The hub is in-process: with several API worker processes, replace `Hub.publish` with Redis pub/sub.
"""

import asyncio
import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import event
from sqlalchemy.orm import Session

MAX_TOPICS_PER_CONNECTION = 20
QUEUE_LIMIT = 200


class Connection:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.queue: "asyncio.Queue[dict]" = asyncio.Queue(maxsize=QUEUE_LIMIT)
        self.topics: Set[str] = set()

    def _put(self, message: dict) -> None:
        if self.queue.full():
            # A stalled client: drop the oldest message; the newest committed state matters most
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait(message)

    def push(self, message: dict) -> None:
        """Thread-safe: called from request worker threads as well as the event loop."""
        try:
            self.loop.call_soon_threadsafe(self._put, message)
        except RuntimeError:
            pass  # the connection's loop has closed


class Hub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: Dict[str, Set[Connection]] = defaultdict(set)

    def subscribe(self, conn: Connection, topic: str) -> None:
        with self._lock:
            self._subs[topic].add(conn)
            conn.topics.add(topic)

    def unsubscribe(self, conn: Connection, topic: str) -> None:
        with self._lock:
            self._subs.get(topic, set()).discard(conn)
            conn.topics.discard(topic)

    def drop(self, conn: Connection) -> None:
        with self._lock:
            for topic in list(conn.topics):
                self._subs.get(topic, set()).discard(conn)
            conn.topics.clear()

    def publish(self, topics: List[str], message: dict) -> None:
        with self._lock:
            targets: Set[Connection] = set()
            for topic in topics:
                targets |= self._subs.get(topic, set())
        for conn in targets:
            conn.push(message)

    def subscriber_count(self, topic: str) -> int:
        with self._lock:
            return len(self._subs.get(topic, set()))


hub = Hub()


# ---------------------------------------------------------------------------
# Publish after commit
# ---------------------------------------------------------------------------
_PENDING = "realtime_pending"


def publish_after_commit(db: Session, key: str, build: Callable[[], Optional[tuple]]) -> None:
    """Queue a message for when this session's transaction commits. `build` runs at commit time (so it sees the
    final values of the transaction) and returns (topics, message) or None. Later calls with the same key replace
    earlier ones, so a transaction that changes one trip twice publishes it once."""
    db.info.setdefault(_PENDING, {})[key] = build


@event.listens_for(Session, "after_commit")
def _flush_pending(session: Session) -> None:
    pending = session.info.pop(_PENDING, None)
    for build in (pending or {}).values():
        try:
            out = build()
        except Exception:
            continue
        if out:
            hub.publish(*out)


@event.listens_for(Session, "after_rollback")
def _discard_pending(session: Session) -> None:
    session.info.pop(_PENDING, None)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------
router = APIRouter(tags=["Access: Realtime"])


def _authenticate(token: str) -> Optional[dict]:
    from .db import get_db
    from .models import Conductor, User
    from .security import decode_access_token

    try:
        payload = decode_access_token(token)
    except Exception:
        return None
    gen = get_db()
    db = next(gen)
    try:
        user = db.get(User, payload.get("sub"))
        if not user or not user.is_active:
            return None
        c = db.get(Conductor, user.id)
        return {"id": user.id, "role": user.role.value, "bus_id": c.bus_id if c else None}
    finally:
        gen.close()


def _authorize(user: dict, topic: str) -> Optional[str]:
    kind, _, value = topic.partition(":")
    if kind in ("trip", "route") and value:
        return None
    if kind == "user":
        return None if value == user["id"] else "You can only follow your own notifications."
    if kind == "bus" and value:
        if user["role"] == "SUPER_ADMIN" or (user["role"] == "CONDUCTOR" and user["bus_id"] == value):
            return None
        return "You can only follow your own bus."
    if topic == "admin":
        return None if user["role"] == "SUPER_ADMIN" else "Admin only."
    return "Unknown topic."


def _snapshot(topic: str) -> dict:
    if topic.startswith("user:"):
        return {"type": "SNAPSHOT", "topic": topic, "trips": []}
    from .db import get_db
    from .trips import snapshot_for_topic

    gen = get_db()
    db = next(gen)
    try:
        return snapshot_for_topic(db, topic)
    finally:
        gen.close()


AUTH_TIMEOUT_SECONDS = 10


@router.websocket("/ws")
async def realtime_ws(websocket: WebSocket) -> None:
    """Client → first {"action": "auth", "token": "..."}, then {"action": "subscribe" | "unsubscribe", "topics": [...]}
    or {"action": "ping"}. Server → AUTH_OK, SNAPSHOT (on subscribe), PASSENGER_COUNT_UPDATED, TRIP_STATE,
    NOTIFICATION, ERROR, PONG."""
    await websocket.accept()
    user = None
    try:
        first = await asyncio.wait_for(websocket.receive_json(), AUTH_TIMEOUT_SECONDS)
        if isinstance(first, dict) and first.get("action") == "auth" and isinstance(first.get("token"), str):
            user = await asyncio.to_thread(_authenticate, first["token"][:4096])
    except Exception:
        user = None
    if not user:
        await websocket.send_json({"type": "ERROR", "code": "UNAUTHORIZED", "detail": "Sign in again."})
        await websocket.close(code=4401)
        return
    await websocket.send_json({"type": "AUTH_OK", "user_id": user["id"], "role": user["role"]})
    conn = Connection(asyncio.get_running_loop())

    async def sender() -> None:
        while True:
            message = await conn.queue.get()
            await websocket.send_json(message)

    send_task = asyncio.create_task(sender())
    try:
        while True:
            msg: Any = await websocket.receive_json()
            if not isinstance(msg, dict):
                continue
            action = msg.get("action")
            if action == "ping":
                conn.push({"type": "PONG"})
                continue
            topics = [str(t)[:80] for t in (msg.get("topics") or []) if isinstance(t, str)]
            for topic in topics:
                if action == "unsubscribe":
                    hub.unsubscribe(conn, topic)
                    continue
                if action != "subscribe":
                    continue
                problem = _authorize(user, topic)
                if not problem and topic not in conn.topics and len(conn.topics) >= MAX_TOPICS_PER_CONNECTION:
                    problem = "Too many subscriptions."
                if problem:
                    conn.push({"type": "ERROR", "topic": topic, "code": "FORBIDDEN", "detail": problem})
                    continue
                # Subscribe first, then read the snapshot: an update committed in between is delivered too,
                # and the client keeps whichever has the higher seq.
                hub.subscribe(conn, topic)
                conn.push(await asyncio.to_thread(_snapshot, topic))
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        pass
    finally:
        hub.drop(conn)
        send_task.cancel()
