"""
CAN Message Visualizer - Entry Point

Professional CAN bus analysis tool for parsing, decoding,
and visualizing CAN logs from BLF and ASC files using DBC databases.
"""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from .utils.logging_config import setup_logging
from .app import MainWindow


def main() -> int:
    """
    Application entry point.

    Returns:
        Exit code (0 for success)
    """
    # Setup logging first
    logger = setup_logging()
    logger.info("Starting CAN Message Visualizer")

    # Enable High DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Create application
    app = QApplication(sys.argv)
    app.setApplicationName("CAN Message Visualizer")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("CAN Tools")

    # Set default font
    font = QFont("Segoe UI", 10)
    if not font.exactMatch():
        font = QFont("SF Pro Display", 10)
    if not font.exactMatch():
        font = QFont()
        font.setPointSize(10)
    app.setFont(font)

    # Create and show main window
    window = MainWindow()
    window.show()

    logger.info("Application window shown")

    # Run event loop
    exit_code = app.exec()

    logger.info(f"Application exiting with code {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
