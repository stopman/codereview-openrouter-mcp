import logging
import sys


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

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
