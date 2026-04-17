import logging
import logging.handlers
from unittest.mock import patch

from codereview_openrouter_mcp.logging import get_logger, setup_logging


def test_get_logger_returns_namespaced_logger():
    logger = get_logger("test")
    assert logger.name == "codereview.test"
    assert isinstance(logger, logging.Logger)


def test_setup_logging_adds_stderr_and_file_handler(tmp_path):
    root = logging.getLogger("codereview")
    root.handlers.clear()

    setup_logging("DEBUG", log_dir=tmp_path)
    assert len(root.handlers) == 2
    assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
    assert any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers)
    assert root.level == logging.DEBUG
    assert (tmp_path / "server.log").exists()


def test_setup_logging_idempotent(tmp_path):
    root = logging.getLogger("codereview")
    root.handlers.clear()

    setup_logging("INFO", log_dir=tmp_path)
    setup_logging("INFO", log_dir=tmp_path)
    assert len(root.handlers) == 2


def test_setup_logging_respects_level(tmp_path):
    root = logging.getLogger("codereview")
    root.handlers.clear()

    setup_logging("WARNING", log_dir=tmp_path)
    assert root.level == logging.WARNING
    root.handlers.clear()


def test_setup_logging_degrades_gracefully_on_oserror():
    root = logging.getLogger("codereview")
    root.handlers.clear()

    with patch("codereview_openrouter_mcp.logging._resolve_log_dir") as mock_resolve:
        mock_resolve.return_value = __import__("pathlib").Path("/nonexistent/readonly/path")
        setup_logging("INFO")

    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0], logging.StreamHandler)


def test_config_log_level_setting():
    from codereview_openrouter_mcp.config import settings
    assert hasattr(settings, "log_level")
    assert settings.log_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
