"""Chrome native-messaging wire protocol.

Each message is a 4-byte little-endian length prefix followed by UTF-8 JSON.
stdout is reserved exclusively for this protocol, so nothing else in the
helper may print to it (use the logging module instead).
"""

from __future__ import annotations

import json
import struct
import threading
from typing import Any, BinaryIO

# Chrome refuses messages from the host larger than 1 MB.
MAX_OUTGOING_BYTES = 1024 * 1024
# Messages from the browser are capped at 64 MB by Chrome; ours are tiny.
MAX_INCOMING_BYTES = 16 * 1024 * 1024


class ProtocolError(Exception):
    pass


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    """Read one message. Returns None when the browser closes the pipe."""
    header = stream.read(4)
    if len(header) == 0:
        return None
    if len(header) != 4:
        raise ProtocolError("Truncated message header")
    (length,) = struct.unpack("<I", header)
    if length > MAX_INCOMING_BYTES:
        raise ProtocolError(f"Message too large: {length} bytes")
    body = stream.read(length)
    if len(body) != length:
        raise ProtocolError("Truncated message body")
    message = json.loads(body.decode("utf-8"))
    if not isinstance(message, dict):
        raise ProtocolError("Message must be a JSON object")
    return message


class MessageWriter:
    """Thread-safe writer: jobs run on worker threads and all share stdout."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def send(self, message: dict[str, Any]) -> None:
        body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_OUTGOING_BYTES:
            raise ProtocolError(f"Outgoing message too large: {len(body)} bytes")
        with self._lock:
            try:
                self._stream.write(struct.pack("<I", len(body)))
                self._stream.write(body)
                self._stream.flush()
            except (BrokenPipeError, ValueError):
                # The browser already disconnected (ValueError: pipe closed);
                # nobody is listening, so there's nothing useful to do.
                pass
