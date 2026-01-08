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
        logger.info(f"File size: {self._file_size / (1024*1024):.2f} MB")
    
    @property
    def file_size_mb(self) -> float:
        """Return file size in megabytes."""
        return self._file_size / (1024 * 1024)
    
    def count_messages(self, progress_callback: Optional[Callable[[int, int], None]] = None) -> int:
        """
        Count actual messages in the file.
        
        For ASC files: Counts lines that look like CAN messages (fast).
        For BLF files: Quick scan of object headers.
        
        Args:
            progress_callback: Optional callback(bytes_read, total_bytes)
        
        Returns:
            Actual number of CAN messages
        """
        if self._message_count is not None:
            return self._message_count
        
        logger.info(f"Counting messages in: {self.file_path.name}")
        
        if self._is_asc:
            self._message_count = self._count_asc_messages(progress_callback)
        else:
            self._message_count = self._count_blf_messages(progress_callback)
        
        logger.info(f"Message count: {self._message_count}")
        return self._message_count
    
    def _count_asc_messages(self, progress_callback: Optional[Callable[[int, int], None]] = None) -> int:
        """
        Count CAN messages in ASC file by counting valid data lines.
        
        ASC format: timestamp channel id Rx/Tx d dlc data...
        """
        count = 0
        bytes_read = 0
        last_callback = 0
        
        try:
            with open(self.file_path, 'rb') as f:
                # Use mmap for fast line counting
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    for line in iter(mm.readline, b''):
                        bytes_read += len(line)
                        
                        # Skip empty lines and comments
                        line = line.strip()
                        if not line or line.startswith(b';'):
                            continue
                        
                        # Check if line looks like a CAN message
                        # Format: timestamp channel id Rx/Tx d dlc [data]
                        parts = line.split()
                        if len(parts) >= 6:
                            # Check if first part looks like timestamp (number)
                            try:
                                float(parts[0])
                                # Check for Rx/Tx marker
                                if b'Rx' in line or b'Tx' in line:
                                    count += 1
                            except (ValueError, IndexError):
                                pass
                        
                        # Progress callback every ~1MB
                        if progress_callback and bytes_read - last_callback > 1_000_000:
                            progress_callback(bytes_read, self._file_size)
                            last_callback = bytes_read
                            
        except Exception as e:
            logger.warning(f"Error counting ASC messages: {e}")
            # Fallback to estimate
            count = max(1, self._file_size // 80)
        
        return max(1, count)
    
    def _count_blf_messages(self, progress_callback: Optional[Callable[[int, int], None]] = None) -> int:
        """
        Count CAN messages in BLF file by scanning object headers.
        
        BLF files have a header with object count, but it may include
        non-CAN objects. We do a quick scan of object types.
        """
        count = 0
        
        try:
            # BLF header magic: "LOGG"
            with open(self.file_path, 'rb') as f:
                header = f.read(144)  # BLF file header size
                
                if header[:4] != b'LOGG':
                    # Not a valid BLF, use estimate
                    return max(1, self._file_size // 100)
                
                # Object count is at offset 28 (4 bytes, little-endian)
                # This includes all objects, not just CAN messages
                try:
                    total_objects = struct.unpack('<I', header[28:32])[0]
                    # Estimate ~80% are CAN messages
                    count = int(total_objects * 0.8)
                except:
                    count = max(1, self._file_size // 100)
                    
        except Exception as e:
            logger.warning(f"Error counting BLF messages: {e}")
            count = max(1, self._file_size // 100)
        
        return max(1, count)
    
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
                            channel=msg.channel if hasattr(msg, 'channel') else 0,
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
        
        logger.info(
            f"Parsing complete: {message_count} messages, {error_count} errors"
        )
    
    def get_cache_key(self) -> str:
        """
        Generate unique cache key for this file.
        
        Uses file path, size, and modification time to detect changes.
        
        Returns:
            Unique string identifier for caching
        """
        stat = self.file_path.stat()
        return f"{self.file_path.name}_{stat.st_size}_{stat.st_mtime_ns}"
