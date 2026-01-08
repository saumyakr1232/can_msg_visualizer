"""
Background worker thread for CAN file parsing.

Handles asynchronous parsing and decoding with progress updates
using Qt signal-slot mechanism for thread-safe UI communication.

Key design decisions for UI responsiveness:
- Small signal batches (100 signals max) to prevent UI blocking
- Frequent progress updates with accurate percentage
- Queued connections for signal delivery
- Pre-counting messages for accurate progress
"""

import time
from pathlib import Path
from typing import Optional
from collections import deque

from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker

from ..core.parser import CANParser
from ..core.decoder import DBCDecoder
from ..core import DataStore
from ..core.models import DecodedSignal, ParseProgress, ParseState
from ..utils.logging_config import get_logger

logger = get_logger("worker")


class ParseWorker(QThread):
    """
    Worker thread for parsing CAN trace files.

    Emits signals for:
    - Progress updates (frequent, small overhead)
    - Decoded signal data (small batches for responsive UI)
    - Completion and error states

    Threading strategy:
    - All heavy work (parsing, decoding) in worker thread
    - Small batches emitted frequently for smooth UI
    - Pre-count messages for accurate progress
    """

    # Signal types - use Qt.QueuedConnection for thread safety
    progress_updated = Signal(ParseProgress)
    signals_decoded = Signal()
    parsing_started = Signal()
    parsing_completed = Signal(str)  # cache_key
    parsing_cancelled = Signal()
    parsing_error = Signal(str)  # error message
    counting_started = Signal()  # Emitted when counting messages

    # Smaller batches for responsive UI
    SIGNAL_BATCH_SIZE = 1000  # Reduced from 1000
    PROGRESS_UPDATE_INTERVAL = 0.2  # 200ms for smooth progress bar

    def __init__(
        self,
        trace_path: Path,
        dbc_path: Path,
        data_store: DataStore,
        parent=None,
    ):
        """
        Initialize parse worker.

        Args:
            trace_path: Path to BLF/ASC file
            dbc_path: Path to DBC file
            cache_manager: Shared cache manager instance
            parent: Qt parent object
        """
        super().__init__(parent)

        self._trace_path = trace_path
        self._dbc_path = dbc_path
        self._data_store = data_store

        self._cancel_mutex = QMutex()
        self._cancelled = False

        self._progress = ParseProgress()
        self._cache_key: Optional[str] = None

        # Set lower priority to keep UI responsive
        self.setPriority(QThread.Priority.LowPriority)

    def cancel(self) -> None:
        """Request cancellation of parsing operation."""
        with QMutexLocker(self._cancel_mutex):
            self._cancelled = True
        logger.info("Parse cancellation requested")

    def _is_cancelled(self) -> bool:
        """Check if cancellation was requested (thread-safe)."""
        with QMutexLocker(self._cancel_mutex):
            return self._cancelled

    def run(self) -> None:
        """
        Main worker thread entry point.

        Executes parsing in background, emitting signals for UI updates.
        """
        logger.info(f"Parse worker starting: {self._trace_path.name}")
        start_time = time.time()

        try:
            self._run_parsing(start_time)
        except Exception as e:
            logger.exception("Fatal error in parse worker")
            self._progress.state = ParseState.ERROR
            self._progress.error_message = str(e)
            self.progress_updated.emit(self._progress)
            self.parsing_error.emit(str(e))

    def _run_parsing(self, start_time: float) -> None:
        """Internal parsing implementation with optimized batching."""
        # Initialize parser and decoder
        parser = CANParser(self._trace_path)
        decoder = DBCDecoder(self._dbc_path)

        # Count messages first for accurate progress
        self.counting_started.emit()
        self._progress.state = ParseState.PARSING
        self._progress.total_messages = 0
        self.progress_updated.emit(self._progress)

        # Count with progress callback
        def count_progress(bytes_read: int, total_bytes: int):
            if self._is_cancelled():
                return

        total_messages = parser.count_messages(count_progress)

        if self._is_cancelled():
            self._handle_cancellation()
            return

        # Start actual parsing
        self.parsing_started.emit()

        self._progress.state = ParseState.PARSING
        self._progress.total_messages = total_messages
        self.progress_updated.emit(self._progress)

        # Accumulators for batching
        signal_batch: list[DecodedSignal] = []
        all_signals: deque[DecodedSignal] = deque()  # Use deque for efficient appends
        last_progress_time = time.time()

        # Stream through messages
        for msg in parser.iterate_messages():
            if self._is_cancelled():
                self._handle_cancellation()
                return

            self._progress.processed_messages += 1

            # Decode message
            decoded_signals = decoder.decode_message(msg)

            if decoded_signals:
                self._progress.decoded_messages += 1
                signal_batch.extend(decoded_signals)
                all_signals.extend(decoded_signals)
            else:
                self._progress.decode_errors += 1

            current_time = time.time()

            if len(signal_batch) >= self.SIGNAL_BATCH_SIZE:
                self._data_store.add_data(list(signal_batch))
                self.signals_decoded.emit()
                signal_batch.clear()
                # Small sleep to let UI process
                self.msleep(1)

            # Emit progress update frequently
            if current_time - last_progress_time >= self.PROGRESS_UPDATE_INTERVAL:
                self._progress.elapsed_seconds = current_time - start_time
                self.progress_updated.emit(self._progress)
                last_progress_time = current_time

        # Emit remaining signals
        if signal_batch:
            self._data_store.add_data(list(signal_batch))
            self.signals_decoded.emit()

        # Final progress update
        self._progress.elapsed_seconds = time.time() - start_time
        self._progress.total_messages = (
            self._progress.processed_messages
        )  # Fix final count
        self._progress.state = ParseState.COMPLETED
        self.progress_updated.emit(self._progress)

        logger.info(
            f"Parsing completed: {self._progress.decoded_messages} messages "
            f"in {self._progress.elapsed_seconds:.2f}s "
            f"({self._progress.decode_rate:.0f} msg/s)"
        )

    def _handle_cancellation(self) -> None:
        """Handle graceful cancellation."""
        self._progress.state = ParseState.CANCELLED
        self.progress_updated.emit(self._progress)
        self.parsing_cancelled.emit()
        logger.info("Parsing cancelled by user")
