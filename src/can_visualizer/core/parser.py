"""
CAN file parser for BLF and ASC formats.

Uses python-can library to read CAN trace files.
Designed for streaming large files without loading all into memory.
"""

import mmap
import struct
from pathlib import Path
from typing import Iterator, Optional, Callable
import can

from ..utils.logging_config import get_logger
from .models import CANMessage

logger = get_logger("parser")


class CANParser:
    """
    Parser for CAN trace files (BLF, ASC formats).

    Provides streaming iteration over messages for memory efficiency
    with large files. Supports accurate message counting for progress.
    """

    SUPPORTED_EXTENSIONS = {".blf", ".asc"}

    def __init__(self, file_path: Path | str):
        """
        Initialize parser with file path.

        Args:
            file_path: Path to BLF or ASC file

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file extension is not supported
        """
        self.file_path = Path(file_path)

        if not self.file_path.exists():
            raise FileNotFoundError(f"CAN trace file not found: {self.file_path}")

        suffix = self.file_path.suffix.lower()
        if suffix not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file format: {suffix}. "
                f"Supported: {', '.join(self.SUPPORTED_EXTENSIONS)}"
            )

        self._file_size = self.file_path.stat().st_size
        self._message_count: Optional[int] = None
        self._is_asc = suffix == ".asc"

        logger.info(f"Initialized parser for: {self.file_path.name}")
        logger.info(f"File size: {self._file_size / (1024 * 1024):.2f} MB")

    @property
    def file_size_mb(self) -> float:
        """Return file size in megabytes."""
        return self._file_size / (1024 * 1024)

    def count_messages(self) -> int:
        """
        Count actual messages in the file.

        For ASC files: Counts lines that look like CAN messages (fast).
        For BLF files: Quick scan of object headers.

        Returns:
            Actual number of CAN messages
        """
        if self._message_count is not None:
            return self._message_count

        logger.info(f"Counting messages in: {self.file_path.name}")

        self._message_count = 0
        with can.LogReader(str(self.file_path)) as reader:
            for msg in reader:
                # if msg.is_error_frame or msg.is_remote_frame:
                #     continue

                self._message_count += 1

        logger.info(f"Message count: {self._message_count}")
        return self._message_count

    def iterate_messages(self) -> Iterator[CANMessage]:
        """
        Stream CAN messages from file.

        Generator that yields CANMessage objects one at a time.
        Memory efficient for large files.

        Yields:
            CANMessage for each valid message in the file
        """
        logger.info(f"Starting to parse: {self.file_path.name}")

        message_count = 0
        error_count = 0

        try:
            # python-can auto-detects format from extension
            with can.LogReader(str(self.file_path)) as reader:
                for msg in reader:
                    try:
                        # Skip error frames and remote frames
                        if msg.is_error_frame or msg.is_remote_frame:
                            continue

                        can_msg = CANMessage(
                            timestamp=msg.timestamp,
                            arbitration_id=msg.arbitration_id,
                            data=bytes(msg.data),
                            is_extended_id=msg.is_extended_id,
                            channel=msg.channel if hasattr(msg, "channel") else 0,
                        )

                        message_count += 1
                        yield can_msg

                    except Exception as e:
                        error_count += 1
                        if error_count <= 10:  # Limit error logging
                            logger.warning(f"Error reading message: {e}")

        except Exception as e:
            logger.error(f"Fatal error reading file: {e}")
            raise

        # Update actual count
        self._message_count = message_count

        logger.info(f"Parsing complete: {message_count} messages, {error_count} errors")

    def get_cache_key(self) -> str:
        """
        Generate unique cache key for this file.

        Uses file path, size, and modification time to detect changes.

        Returns:
            Unique string identifier for caching
        """
        stat = self.file_path.stat()
        return f"{self.file_path.name}_{stat.st_size}_{stat.st_mtime_ns}"
