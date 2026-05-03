"""Pulse entry point — invoked by launchd via ``python -m pulse``."""

from __future__ import annotations

import sys

from .config import PulseConfig
from .daemon import PulseDaemon, _setup_logging


def main(argv: list[str] | None = None) -> int:
    cfg = PulseConfig.from_env()
    cfg.ensure_dirs()
    _setup_logging(cfg.log_path)
    daemon = PulseDaemon(cfg)
    return daemon.run()


if __name__ == "__main__":
    sys.exit(main())
