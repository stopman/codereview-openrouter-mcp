import getpass
import logging
import logging.handlers
import os
import sys
import tempfile
from pathlib import Path


def _resolve_log_dir() -> Path:
    """Resolve the log directory from env var, home dir, or per-user temp dir."""
    env_dir = os.getenv("MCP_LOG_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    try:
        return Path.home() / ".cache" / "codereview-mcp" / "logs"
    except RuntimeError:
        user = getpass.getuser()
        return Path(tempfile.gettempdir()) / f"codereview-mcp-{user}" / "logs"


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the 'codereview' namespace that writes to stderr.

    MCP uses stdout for protocol communication, so all diagnostic output
    must go to stderr.
    """
    logger = logging.getLogger(f"codereview.{name}")
    return logger


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Configure the root 'codereview' logger once at startup.

    Log directory is resolved at call time (not import time) from:
    1. The explicit ``log_dir`` parameter
    2. The ``MCP_LOG_DIR`` environment variable
    3. ``~/.cache/codereview-mcp/logs``
    4. A per-user temp directory as a last resort
    """
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

    resolved_dir = log_dir or _resolve_log_dir()
    log_file = resolved_dir / "server.log"

    try:
        resolved_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3,
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as e:
        print(f"Warning: could not set up file logging ({e}), file logging disabled", file=sys.stderr)

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
