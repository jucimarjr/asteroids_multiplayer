"""Token allowlist loading for the multi-room server.

The server keeps a global ``set[str]`` of accepted tokens that the
handshake checks for every incoming connection. The allowlist is read
once at boot from a plain-text file (default: ``tokens.txt``). The
file is gitignored; ``tokens.example.txt`` ships a placeholder so
operators know the format.

Format rules:
- one token per line;
- leading and trailing whitespace is stripped;
- lines that start with ``#`` are comments;
- blank lines are ignored.

The loader is intentionally fail-fast — missing file, empty file, or
all-comment file raise. The CLI translates the exception into a
human-readable stderr message and ``sys.exit(2)``.
"""

from __future__ import annotations

from pathlib import Path


def load_tokens(path: Path) -> set[str]:
    """Read accepted tokens from ``path``.

    Raises:
        FileNotFoundError: ``path`` does not exist.
        ValueError: file exists but contains no non-comment tokens.
    """
    text = path.read_text(encoding="utf-8")
    tokens = {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    if not tokens:
        raise ValueError(f"token file is empty: {path}")
    return tokens
