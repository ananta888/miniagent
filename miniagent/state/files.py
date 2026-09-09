"""Small durable file primitives. Runs have a single writer under a file lock."""

import json
import os
import tempfile
from collections import deque
from pathlib import Path


def atomic_write(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def append_json(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def recent_json(path: Path, count: int) -> list[dict]:
    """Read only the tail, including on runs with millions of observations."""
    if count <= 0:
        return []
    with path.open("rb") as stream:
        position = stream.seek(0, os.SEEK_END)
        data = b""
        while position and data.count(b"\n") <= count:
            size = min(8192, position)
            position -= size
            stream.seek(position)
            data = stream.read(size) + data
    return [json.loads(line) for line in deque(data.splitlines(), maxlen=count)]


def repair_tail(path: Path) -> None:
    """Only an unfinished last JSONL record may be removed after a crash."""
    with path.open("r+b") as stream:
        end = stream.seek(0, os.SEEK_END)
        if not end:
            return
        stream.seek(end - 1)
        if stream.read(1) == b"\n":
            return
        position = end
        while position:
            size = min(8192, position)
            position -= size
            stream.seek(position)
            block = stream.read(size)
            boundary = block.rfind(b"\n")
            if boundary >= 0:
                stream.truncate(position + boundary + 1)
                break
        else:
            stream.truncate(0)
        stream.flush()
        os.fsync(stream.fileno())
