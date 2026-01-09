"""
Background worker thread for CAN file parsing.

Handles asynchronous parsing and decoding with progress updates
using Qt signal-slot mechanism for thread-safe UI communication.

Key design decisions for UI responsiveness:
- Small signal batches (100 signals max) to prevent UI blocking
- Frequent progress updates with accurate percentage
- Queued connections for signal delivery
- Pre-counting messages for accurate progress
- Parallel decoding using DecodePool for improved performance
"""

import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker

from ..core.parser import CANParser
from ..core import DataStore
from ..core.models import DecodedSignal, ParseProgress, ParseState
from .decode_pool import DecodePool
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
    - Parallel decoding using DecodePool for multi-core utilization
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

    # Batch sizes for responsive UI
    SIGNAL_BATCH_SIZE = 5000  # Larger batches to reduce signal frequency on Windows
    PROGRESS_UPDATE_INTERVAL = 0.5  # 500ms to reduce event queue flooding

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
            data_store: Data store instance for decoded signals
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
        """Internal parsing implementation with parallel decoding."""
        # Initialize parser
        parser = CANParser(self._trace_path)

        # Count messages first for accurate progress
        self.counting_started.emit()
        self._progress.state = ParseState.PARSING
        self._progress.total_messages = 0
        self.progress_updated.emit(self._progress)

        total_messages = parser.count_messages()

        if self._is_cancelled():
            self._handle_cancellation()
            return

        # Start actual parsing
        self.parsing_started.emit()

        self._progress.state = ParseState.PARSING
        self._progress.total_messages = total_messages
        self.progress_updated.emit(self._progress)

        last_progress_time = time.time()
        messages_since_progress = 0

        def message_iterator():
            """Generate message tuples for decode pool."""
            nonlocal last_progress_time, messages_since_progress
            for msg in parser.iterate_messages():
                if self._is_cancelled():
                    return
                self._progress.processed_messages += 1
                messages_since_progress += 1

                # Emit progress update during message iteration
                # Use time-based throttling AND message count to reduce frequency
                current_time = time.time()
                if (
                    current_time - last_progress_time >= self.PROGRESS_UPDATE_INTERVAL
                    and messages_since_progress >= 1000
                ):
                    self._progress.elapsed_seconds = current_time - start_time
                    self.progress_updated.emit(self._progress)
                    last_progress_time = current_time
                    messages_since_progress = 0
                    # Small sleep to let UI thread process the signal
                    self.msleep(5)

                # Convert CANMessage to tuple for decode pool
                yield (
                    msg.timestamp,
                    msg.arbitration_id,
                    msg.data,
                    msg.is_extended_id,
                    msg.channel,
                )

        # Process decoded signals from parallel pool with automatic cleanup
        signal_batch: list[DecodedSignal] = []

        with DecodePool(self._dbc_path) as decode_pool:
            for decoded_tuples in decode_pool.decode_messages(message_iterator()):
                if self._is_cancelled():
                    self._handle_cancellation()
                    return

                # Convert tuples to DecodedSignal objects
                for signal_tuple in decoded_tuples:
                    (
                        timestamp,
                        msg_name,
                        arb_id,
                        signal_name,
                        raw_value,
                        phys_value,
                        unit,
                    ) = signal_tuple
                    signal = DecodedSignal(
                        timestamp=timestamp,
                        message_name=msg_name,
                        message_id=arb_id,
                        signal_name=signal_name,
                        raw_value=raw_value,
                        physical_value=phys_value,
                        unit=unit,
                    )
                    signal_batch.append(signal)
                    self._progress.decoded_messages += 1

                # Emit batch when large enough
                if len(signal_batch) >= self.SIGNAL_BATCH_SIZE:
                    self._data_store.add_data(list(signal_batch))
                    self.signals_decoded.emit()
                    signal_batch.clear()
                    # Sleep to let UI thread process signals_decoded
                    self.msleep(10)

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
