import logging
import logging.handlers
import os
import sys
from pathlib import Path


def _resolve_log_dir() -> Path:
    env_dir = os.getenv("MCP_LOG_DIR")
    if env_dir:
        return Path(env_dir)
    try:
        return Path.home() / ".cache" / "codereview-mcp" / "logs"
    except RuntimeError:
        return Path("/tmp") / "codereview-mcp" / "logs"


LOG_DIR = _resolve_log_dir()
LOG_FILE = LOG_DIR / "server.log"


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the 'codereview' namespace that writes to stderr.

    MCP uses stdout for protocol communication, so all diagnostic output
    must go to stderr.
    """
    logger = logging.getLogger(f"codereview.{name}")
    return logger


def setup_logging(level: str = "INFO") -> None:
    """Configure the root 'codereview' logger once at startup."""
    root = logging.getLogger("codereview")
    if root.handlers:
        return  # already configured

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)
    root.addHandler(stderr_handler)

    try:
        LOG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3,
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        print("Warning: could not create log directory, file logging disabled", file=sys.stderr)

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
