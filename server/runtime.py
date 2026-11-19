"""Bridges synchronous request threads and the asyncio loop (background AI tasks, WebSocket broadcasts)."""
import asyncio
import logging
from typing import Any, Coroutine, Optional

log = logging.getLogger("tripmate.runtime")
_loop: Optional[asyncio.AbstractEventLoop] = None
_tasks: set = set()


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def spawn(coro: Coroutine[Any, Any, Any]) -> None:
    """Run a coroutine in the background on the server's event loop (works from any thread)."""
    if _loop is None or _loop.is_closed():
        coro.close()
        log.error("Event loop not ready; background task dropped")
        return
    fut = asyncio.run_coroutine_threadsafe(coro, _loop)
    _tasks.add(fut)

    def _done(f):
        _tasks.discard(f)
        if not f.cancelled() and f.exception():
            log.error("Background task failed", exc_info=f.exception())

    fut.add_done_callback(_done)
