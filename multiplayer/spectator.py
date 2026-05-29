"""Asteroids spectator client.

Connects to the server with `{spectator: true}` in the HELLO payload,
receives snapshots from one fixed room, and renders the entire world
into an arbitrary-sized window via `SpectatorCamera`. Never spawns
a ship, never sends INPUT or RESTART_REQUEST.

CLI:
    python -m multiplayer.spectator \
        --host localhost --port 8765 \
        --room 0 --token dev-token-1 \
        --width 1280 --height 720
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from typing import Any

import pygame as pg
import websockets

from client.renderer import Renderer
from client.spectator_camera import SpectatorCamera
from core import config as C
from core.world import World
from multiplayer.hud import draw_match_end_screen, draw_scoreboard
from multiplayer.net import ws_uri
from multiplayer.snapshot import snapshot_to_world
from server.protocol import (
    HELLO,
    REJECT,
    SNAPSHOT,
    WELCOME,
    envelope,
    parse,
)

HANDSHAKE_TIMEOUT = 5.0


class Spectator:
    def __init__(
        self,
        host: str,
        port: int,
        room: int,
        token: str,
        window_width: int,
        window_height: int,
        tls: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.room = room
        self.token = token
        self.window_width = window_width
        self.window_height = window_height
        self.tls = tls
        self.server_tick = 0
        self.running = True

        self.world = World(spawn_default_player=False)

        pg.init()
        self.screen = pg.display.set_mode((window_width, window_height))
        pg.display.set_caption(f"Asteroids — Spectator (ROOM {room:02d})")
        self.font = pg.font.SysFont(C.FONT_NAME, C.FONT_SIZE_SMALL)
        self.big = pg.font.SysFont(C.FONT_NAME, C.FONT_SIZE_LARGE)
        self.camera = SpectatorCamera(window_width, window_height)
        self.renderer = Renderer(
            self.screen,
            self.camera,
            config=C,
            fonts={"font": self.font, "big": self.big},
        )

    async def run(self) -> None:
        uri = ws_uri(self.host, self.port, tls=self.tls)
        try:
            async with websockets.connect(uri) as ws:
                if not await self._handshake(ws):
                    return
                recv_task = asyncio.create_task(self._receive_loop(ws))
                try:
                    await self._draw_loop()
                finally:
                    recv_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await recv_task
        finally:
            pg.quit()

    async def _handshake(self, ws: Any) -> bool:
        hello_data = {
            "name": f"spectator-{self.room}",
            "room_id": self.room,
            "token": self.token,
            "spectator": True,
        }
        await ws.send(envelope(HELLO, 0, 0, hello_data))
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=HANDSHAKE_TIMEOUT)
        except TimeoutError:
            print("handshake timed out", file=sys.stderr)
            return False

        msg = parse(raw)
        if msg is None:
            print("invalid handshake reply", file=sys.stderr)
            return False
        if msg["type"] == REJECT:
            reason = msg["data"].get("reason")
            print(
                f"server rejected connection: {reason}",
                file=sys.stderr,
            )
            return False
        if msg["type"] != WELCOME:
            print(
                f"unexpected first message: {msg['type']}",
                file=sys.stderr,
            )
            return False

        print(f"connected as spectator on room {self.room}")
        return True

    async def _receive_loop(self, ws: Any) -> None:
        try:
            async for raw in ws:
                msg = parse(raw)
                if msg is None:
                    continue
                if msg["type"] == SNAPSHOT:
                    snapshot_to_world(msg["data"], self.world)
                    self.server_tick = msg["tick"]
        except websockets.ConnectionClosed:
            pass
        finally:
            self.running = False

    async def _draw_loop(self) -> None:
        period = 1.0 / C.FPS
        loop = asyncio.get_running_loop()
        while self.running:
            frame_start = loop.time()

            for event in pg.event.get():
                if event.type == pg.QUIT or (
                    event.type == pg.KEYDOWN
                    and event.key in (pg.K_ESCAPE, pg.K_q)
                ):
                    self.running = False

            self._draw()

            elapsed = loop.time() - frame_start
            await asyncio.sleep(max(0.0, period - elapsed))

    def _draw(self) -> None:
        state = self.world.match_state
        self.renderer.clear()
        self.renderer.draw_world(self.world)

        # Header strip identifying the room and spectator role.
        header = self.font.render(
            f"ROOM {self.room:02d} — SPECTATING",
            True,
            C.WHITE,
        )
        x = (self.screen.get_width() - header.get_width()) // 2
        self.screen.blit(header, (x, 10))

        # Scoreboard reuses the player helper with no local pid so no
        # row is marked with `> `.
        draw_scoreboard(
            self.screen,
            self.font,
            self.world,
            local_player_id=None,
            color=C.WHITE,
        )

        if state == "ended":
            draw_match_end_screen(
                self.screen,
                self.font,
                self.big,
                self.world,
                C.WHITE,
            )

        pg.display.flip()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="multiplayer.spectator",
        description="Asteroids read-only spectator client.",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="server host (default: localhost)",
    )
    parser.add_argument(
        "--port",
        default=None,
        type=int,
        help="server port (default: 8765, or 443 with --tls)",
    )
    parser.add_argument(
        "--tls",
        action="store_true",
        help="connect over wss:// (TLS), e.g. via a 443 reverse proxy",
    )
    parser.add_argument(
        "--room",
        required=True,
        type=int,
        help="room id to observe",
    )
    parser.add_argument(
        "--token",
        required=True,
        help="allowlist token issued by the server operator",
    )
    parser.add_argument(
        "--width",
        default=1280,
        type=int,
        help="window width in pixels (default: 1280)",
    )
    parser.add_argument(
        "--height",
        default=720,
        type=int,
        help="window height in pixels (default: 720)",
    )
    args = parser.parse_args()
    port = args.port if args.port is not None else (443 if args.tls else 8765)

    spectator = Spectator(
        args.host,
        port,
        args.room,
        args.token,
        args.width,
        args.height,
        tls=args.tls,
    )
    try:
        asyncio.run(spectator.run())
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
