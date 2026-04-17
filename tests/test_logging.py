import logging
import logging.handlers

from codereview_openrouter_mcp.logging import get_logger, setup_logging


def test_get_logger_returns_namespaced_logger():
    logger = get_logger("test")
    assert logger.name == "codereview.test"
    assert isinstance(logger, logging.Logger)


def test_setup_logging_adds_stderr_and_file_handler():
    # Reset to test fresh setup
    root = logging.getLogger("codereview")
    root.handlers.clear()

    setup_logging("DEBUG")
    assert len(root.handlers) == 2
    assert isinstance(root.handlers[0], logging.StreamHandler)
    assert isinstance(root.handlers[1], logging.handlers.RotatingFileHandler)
    assert root.level == logging.DEBUG


def test_setup_logging_idempotent():
    root = logging.getLogger("codereview")
    root.handlers.clear()

    setup_logging("INFO")
    setup_logging("INFO")
    assert len(root.handlers) == 2


def test_setup_logging_respects_level():
    root = logging.getLogger("codereview")
    root.handlers.clear()

    setup_logging("WARNING")
    assert root.level == logging.WARNING
    root.handlers.clear()


def test_config_log_level_setting():
    from codereview_openrouter_mcp.config import settings
    assert hasattr(settings, "log_level")
    assert settings.log_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
