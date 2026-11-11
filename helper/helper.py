"""Entry point launched by the browser via native messaging.

The browser starts this process when the extension connects and closes stdin
when it disconnects; we then cancel running jobs and exit.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from vidgrab.commands import Dispatcher
from vidgrab.environment import LOG_DIR
from vidgrab.protocol import MessageWriter, ProtocolError, read_message


def _setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    handler = RotatingFileHandler(LOG_DIR / "helper.log", maxBytes=1_000_000, backupCount=2,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def main() -> int:
    _setup_logging()
    log = logging.getLogger("vidgrab")
    log.info("Helper started (python %s)", sys.version.split()[0])

    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    # Anything accidentally printed must not corrupt the protocol stream.
    sys.stdout = sys.stderr

    dispatcher = Dispatcher(MessageWriter(stdout))
    try:
        while True:
            message = read_message(stdin)
            if message is None:
                break
            dispatcher.handle(message)
    except ProtocolError:
        log.exception("Protocol error; shutting down")
        return 1
    finally:
        running = dispatcher.cancel_all()
        if running:
            log.warning("Browser disconnected while %d download(s) were running; cancelled", running)
            dispatcher.wait_for_jobs(timeout=5)
        log.info("Helper stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
