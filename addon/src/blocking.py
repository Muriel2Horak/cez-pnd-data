"""Offload cancellable application waits without holding up process shutdown.

Cancelling an await does not kill a native thread. These daemon workers must
therefore wrap operations that also provide cooperative stop/deadline handling
(the MQTT transport does). Unlike asyncio's default executor, they do not make
asyncio.run wait indefinitely after the application's shutdown deadline.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable


async def run_blocking(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    loop = asyncio.get_running_loop()
    result = loop.create_future()

    def settle(value: Any, error: BaseException | None) -> None:
        if result.done():
            return
        if error is not None:
            result.set_exception(error)
        else:
            result.set_result(value)

    def worker() -> None:
        try:
            value, error = function(*args, **kwargs), None
        except BaseException as exc:
            value, error = None, exc
        try:
            loop.call_soon_threadsafe(settle, value, error)
        except RuntimeError:
            # The shutdown deadline can expire before an operation returns.
            if not loop.is_closed():
                raise

    threading.Thread(target=worker, daemon=True).start()
    return await result
