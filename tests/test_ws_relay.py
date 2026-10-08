"""proxy_ws_relay: large messages pass, and an upstream close reaches the client."""

from __future__ import annotations

import asyncio
import socket
import threading

import pytest
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mograder.core.edit_sessions import proxy_ws_relay

websockets = pytest.importorskip("websockets")

BIG = "x" * (3 * 1024 * 1024)  # a widget's state can be this large (> 1 MiB default)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def upstream():
    """A real WebSocket server: on 'big' sends a 3 MB message, on 'bye' closes."""
    port = _free_port()
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    state = {}

    async def handler(ws):
        async for msg in ws:
            if msg == "big":
                await ws.send(BIG)
            elif msg == "bye":
                await ws.close()
                return
            else:
                await ws.send(f"echo:{msg}")

    async def serve():
        stop = state["stop"] = loop.create_future()
        async with websockets.serve(handler, "127.0.0.1", port, max_size=None):
            ready.set()
            await stop

    t = threading.Thread(target=lambda: loop.run_until_complete(serve()), daemon=True)
    t.start()
    ready.wait(5)
    yield f"ws://127.0.0.1:{port}/"
    stop = state["stop"]
    loop.call_soon_threadsafe(lambda: stop.done() or stop.set_result(None))
    t.join(5)


def _client(target):
    async def relay(websocket):
        await websocket.accept()
        await proxy_ws_relay(websocket, target)

    return TestClient(Starlette(routes=[WebSocketRoute("/ws", relay)]))


def test_relays_small_and_large_messages(upstream):
    with _client(upstream).websocket_connect("/ws") as ws:
        ws.send_text("hi")
        assert ws.receive_text() == "echo:hi"
        ws.send_text("big")
        assert len(ws.receive_text()) == len(BIG)
        ws.send_text("after")  # the relay is still alive after the big one
        assert ws.receive_text() == "echo:after"


def test_upstream_close_closes_client(upstream):
    with _client(upstream).websocket_connect("/ws") as ws:
        ws.send_text("bye")
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()
