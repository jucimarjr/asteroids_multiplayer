"""Tests for `server/auth.py` and the handshake's token check."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from server.auth import load_tokens
from server.main import Server
from tests.test_server_room_registry import (
    VALID_TOKEN,
    FakeWebSocket,
    _hello,
    _last_reject_reason,
)


def test_load_tokens_strips_whitespace_and_comments(tmp_path: Path):
    path = tmp_path / "tokens.txt"
    path.write_text(
        "# header comment\n"
        "\n"
        "  alpha  \n"
        "beta\n"
        "# inline comment line\n"
        "gamma\n"
        "\n",
        encoding="utf-8",
    )

    tokens = load_tokens(path)

    assert tokens == {"alpha", "beta", "gamma"}


def test_load_tokens_raises_when_file_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_tokens(tmp_path / "missing.txt")


def test_load_tokens_raises_when_file_empty(tmp_path: Path):
    path = tmp_path / "tokens.txt"
    path.write_text("# only comments\n\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_tokens(path)


def test_load_tokens_dedups_identical_lines(tmp_path: Path):
    path = tmp_path / "tokens.txt"
    path.write_text("alpha\nalpha\nbeta\n", encoding="utf-8")
    assert load_tokens(path) == {"alpha", "beta"}


def test_server_rejects_empty_allowed_tokens():
    with pytest.raises(ValueError):
        Server("127.0.0.1", 0, allowed_tokens=set(), rooms=1)


def test_handshake_accepts_listed_token():
    server = Server(
        "127.0.0.1", 0, allowed_tokens={VALID_TOKEN, "other"}, rooms=1
    )
    ws = FakeWebSocket([_hello(name="alice")])
    result = asyncio.run(server._handshake(ws))
    assert result is not None
    welcome = json.loads(ws.sent[-1])
    assert welcome["type"] == "welcome"


def test_handshake_rejects_unknown_token():
    server = Server("127.0.0.1", 0, allowed_tokens={"known"}, rooms=1)
    ws = FakeWebSocket([_hello(name="alice", token="bad")])
    result = asyncio.run(server._handshake(ws))
    assert result is None
    assert _last_reject_reason(ws) == "unauthorized"
    assert ws.closed is True


def test_handshake_rejects_when_token_field_missing():
    """Legacy F4 clients omit token; server rejects them now."""
    server = Server("127.0.0.1", 0, allowed_tokens={"known"}, rooms=1)
    raw = json.dumps(
        {
            "type": "hello",
            "tick": 0,
            "seq": 0,
            "data": {"name": "legacy"},
        }
    )
    ws = FakeWebSocket([raw])
    result = asyncio.run(server._handshake(ws))
    assert result is None
    assert _last_reject_reason(ws) == "unauthorized"


def test_handshake_rejects_non_string_token():
    server = Server("127.0.0.1", 0, allowed_tokens={"known"}, rooms=1)
    raw = json.dumps(
        {
            "type": "hello",
            "tick": 0,
            "seq": 0,
            "data": {"name": "x", "token": 12345},
        }
    )
    ws = FakeWebSocket([raw])
    result = asyncio.run(server._handshake(ws))
    assert result is None
    assert _last_reject_reason(ws) == "unauthorized"


def test_token_check_runs_before_room_validation():
    """Bad token + bad room → caller sees `unauthorized`, not
    `invalid_room`. Catching the access gate first keeps error
    messages stable when both conditions fail."""
    server = Server("127.0.0.1", 0, allowed_tokens={"known"}, rooms=1)
    ws = FakeWebSocket([_hello(name="x", token="bad", room_id=99)])
    asyncio.run(server._handshake(ws))
    assert _last_reject_reason(ws) == "unauthorized"
