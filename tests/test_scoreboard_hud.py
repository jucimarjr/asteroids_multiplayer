"""Tests for multiplayer.hud — local HUD and 1-room scoreboard.

These exercise the pure `*_lines` helpers so the drawing primitives can
be verified without touching pygame.
"""

from core.utils import Countdown
from core.world import World
from multiplayer.hud import local_hud_lines, scoreboard_lines


def test_local_hud_lines_uses_world_state():
    w = World(spawn_default_player=False)
    w.scores[7] = 250
    w.deaths[7] = 1
    w.wave = 2
    assert local_hud_lines(w, 7) == ["SCORE 000250", "DEATHS 01", "WAVE 02"]


def test_local_hud_lines_falls_back_to_zeros_for_unknown_player():
    w = World(spawn_default_player=False)
    assert local_hud_lines(w, 99) == ["SCORE 000000", "DEATHS 00", "WAVE 00"]
    assert local_hud_lines(w, None) == ["SCORE 000000", "DEATHS 00", "WAVE 00"]


def test_scoreboard_sorts_by_score_desc_then_pid_asc():
    w = World(spawn_default_player=False)
    w.scores = {1: 200, 2: 500, 3: 200}
    lines = scoreboard_lines(w, local_player_id=None)
    assert "500" in lines[0]
    assert "P2" in lines[0]
    assert "P1" in lines[1]
    assert "P3" in lines[2]


def test_scoreboard_marks_local_player_with_leading_arrow():
    w = World(spawn_default_player=False)
    w.scores = {1: 100, 2: 100}
    lines = scoreboard_lines(w, local_player_id=2)
    pid2 = next(line for line in lines if "P2" in line)
    pid1 = next(line for line in lines if "P1" in line)
    assert pid2.startswith("> ")
    assert pid1.startswith("  ")


def test_scoreboard_uses_name_when_present():
    w = World(spawn_default_player=False)
    w.scores = {1: 100}
    w.names[1] = "Alice"
    assert "Alice" in scoreboard_lines(w, local_player_id=None)[0]


def test_scoreboard_falls_back_to_pid_when_name_missing():
    w = World(spawn_default_player=False)
    w.scores = {1: 100}
    assert "P1" in scoreboard_lines(w, local_player_id=None)[0]


def test_scoreboard_shows_respawn_status_when_player_in_respawning():
    w = World(spawn_default_player=False)
    w.scores = {1: 100}
    w.respawning[1] = Countdown(2.5)
    line = scoreboard_lines(w, local_player_id=None)[0]
    assert "RESPAWN" in line
    assert "2.5" in line


def test_scoreboard_displays_deaths_counter():
    w = World(spawn_default_player=False)
    w.scores = {1: 100}
    w.deaths[1] = 4
    assert "D04" in scoreboard_lines(w, local_player_id=None)[0]


def test_scoreboard_empty_world_returns_empty_list():
    assert scoreboard_lines(World(spawn_default_player=False), None) == []
