"""Profile World.update over a synthetic deathmatch.

Builds a deterministic deathmatch World with N ships, M asteroids,
and a fixed thrust+shoot command stream, then runs ``world.update``
under cProfile for the requested number of ticks. Top entries by
cumulative time are printed to stdout; the raw stats are saved to
``/tmp/profile.pstats`` for follow-up with ``python -m pstats``.

Stdlib only — no benchmark dependency.

Usage:
    python scripts/profile_tick.py [--ticks N] [--ships N] [--asteroids N]
"""

from __future__ import annotations

import argparse
import cProfile
import pstats
from random import seed, uniform

from core import config as C
from core.commands import PlayerCommand
from core.utils import Vec
from core.world import World


def build_world(ships: int, asteroids: int) -> World:
    """Create a deathmatch world with `ships` players and `asteroids`
    pre-spawned rocks, started in the running state."""
    world = World(spawn_default_player=False, deathmatch=True)
    for pid in range(1, ships + 1):
        world.spawn_player(pid)
    world.match_state = "running"
    world.match_timer.reset(C.MATCH_DURATION)
    for _ in range(asteroids):
        pos = Vec(
            uniform(0, C.WORLD_WIDTH),
            uniform(0, C.WORLD_HEIGHT),
        )
        vel = Vec(uniform(-50, 50), uniform(-50, 50))
        world.spawn_asteroid(pos, vel, "L")
    return world


def build_rooms(
    rooms: int,
    ships_per_room: int,
    asteroids_per_room: int,
) -> dict[int, World]:
    """Mirror Server.worlds — `rooms` independent worlds each loaded
    like `build_world(ships_per_room, asteroids_per_room)`."""
    return {
        room_id: build_world(ships_per_room, asteroids_per_room)
        for room_id in range(rooms)
    }


def run(ticks: int, ships: int, asteroids: int, rooms: int = 1) -> None:
    """Drive `ticks` updates across `rooms` synthetic worlds.

    Total ships and asteroids are split evenly across rooms, so the
    workload is comparable across `--rooms` values when the
    `--ships`/`--asteroids` totals stay constant. Every spawned
    player issues `thrust=True, shoot=True` on every frame.
    """
    seed(42)  # deterministic asteroid placement and velocities
    ships_per_room = max(1, ships // rooms)
    asteroids_per_room = max(0, asteroids // rooms)
    worlds = build_rooms(rooms, ships_per_room, asteroids_per_room)
    cmd = PlayerCommand(thrust=True, shoot=True)
    inputs_per_world = {
        room_id: {pid: cmd for pid in world.ships}
        for room_id, world in worlds.items()
    }
    dt = 1.0 / C.FPS
    for _ in range(ticks):
        for room_id, world in worlds.items():
            world.update(dt, inputs_per_world[room_id])


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="profile_tick",
        description="Profile World.update on a synthetic deathmatch.",
    )
    parser.add_argument("--ticks", type=int, default=600)
    parser.add_argument("--ships", type=int, default=8)
    parser.add_argument("--asteroids", type=int, default=30)
    parser.add_argument(
        "--rooms",
        type=int,
        default=1,
        help=(
            "number of concurrent worlds (Server.worlds) — "
            "ships and asteroids are split evenly across rooms "
            "(default: 1)"
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=30,
        help="number of rows from cumulative profile (default: 30)",
    )
    parser.add_argument(
        "--out",
        default="/tmp/profile.pstats",
        help="path to dump raw pstats (default: /tmp/profile.pstats)",
    )
    args = parser.parse_args()

    profiler = cProfile.Profile()
    profiler.enable()
    run(args.ticks, args.ships, args.asteroids, rooms=args.rooms)
    profiler.disable()

    stats = pstats.Stats(profiler).sort_stats("cumulative")
    stats.print_stats(args.top)
    stats.dump_stats(args.out)
    print(f"\nraw pstats saved to {args.out}")


if __name__ == "__main__":
    main()
