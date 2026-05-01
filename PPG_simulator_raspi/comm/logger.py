"""
logger.py — Debug logging handler for PPG Signal Simulator

Writes DEBUG-level logs to /tmp/ppg_simulator.log.
Logging can be enabled/disabled via the PPG_LOG_ENABLED environment variable.
"""

import logging
import os
import sys

from config import LOG_ENABLED, LOG_FILE, LOG_LEVEL, DEVICE_NAME, FIRMWARE_VERSION


def setup_logger(name: str = "ppg_simulator") -> logging.Logger:
    """
    Create and configure the application logger.

    - Console handler: INFO level (concise)
    - File handler: DEBUG level (verbose), writes to LOG_FILE
    - Controlled by PPG_LOG_ENABLED env var (default: enabled)

    Returns:
        Configured logging.Logger instance.
    """
    logger = logging.getLogger(name)

    # Prevent duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    level = getattr(logging, LOG_LEVEL.upper(), logging.DEBUG)
    logger.setLevel(level)

    # Formatter
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (INFO level — concise output)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # File handler (DEBUG level — verbose)
    if LOG_ENABLED:
        try:
            file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)
            logger.debug(f"Log file opened: {LOG_FILE}")
        except (PermissionError, OSError) as e:
            logger.warning(f"Cannot open log file {LOG_FILE}: {e}")

    logger.info(f"{DEVICE_NAME} v{FIRMWARE_VERSION} — Logger initialized")
    return logger


# Module-level logger instance
log = setup_logger()
