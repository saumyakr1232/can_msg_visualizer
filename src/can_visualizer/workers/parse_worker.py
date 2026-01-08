"""
Background worker thread for CAN file parsing.

Handles asynchronous parsing and decoding with progress updates
using Qt signal-slot mechanism for thread-safe UI communication.

Key design decisions for UI responsiveness:
- Parallel decoding using ProcessPoolExecutor for CPU-bound work
- Batch processing for efficient throughput
- Lazy UI updates via signal batches
- Frequent progress updates with accurate percentage
- Queued connections for signal delivery
"""

import os
import time
from pathlib import Path
from typing import Optional
from collections import deque

from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker

from ..core.parser import CANParser
from ..core.decoder import DBCDecoder, signal_tuples_to_decoded, message_to_tuple
from ..core.cache import CacheManager
from ..core.models import DecodedSignal, ParseProgress, ParseState
from ..utils.logging_config import get_logger
from .decode_pool import DecodePool

logger = get_logger("worker")


class ParseWorker(QThread):
    """
    Worker thread for parsing CAN trace files.
    
    Emits signals for:
    - Progress updates (frequent, small overhead)
    - Decoded signal data (batches for responsive UI)
    - Completion and error states
    
    Threading strategy:
    - Message parsing in worker thread
    - CPU-bound decoding distributed across ProcessPoolExecutor
    - Batched signal emission for lazy UI updates
    """
    
    # Signal types - use Qt.QueuedConnection for thread safety
    progress_updated = Signal(ParseProgress)
    signals_decoded = Signal(list)  # List[DecodedSignal]
    parsing_started = Signal()
    parsing_completed = Signal(str)  # cache_key
    parsing_cancelled = Signal()
    parsing_error = Signal(str)  # error message
    counting_started = Signal()  # Emitted when counting messages
    
    # Tuned batch sizes for parallel processing
    SIGNAL_BATCH_SIZE = 500  # Larger batches for less UI overhead
    UI_EMIT_INTERVAL = 0.1  # 100ms between UI updates
    PROGRESS_UPDATE_INTERVAL = 0.05  # 50ms for smooth progress bar
    MESSAGE_BATCH_SIZE = 2000  # Messages per decode batch (matches DecodePool)
    
    def __init__(
        self,
        trace_path: Path,
        dbc_path: Path,
        cache_manager: CacheManager,
        parent=None,
        use_parallel: bool = True,
    ):
        """
        Initialize parse worker.
        
        Args:
            trace_path: Path to BLF/ASC file
            dbc_path: Path to DBC file
            cache_manager: Shared cache manager instance
            parent: Qt parent object
            use_parallel: Whether to use parallel decoding (default True)
        """
        super().__init__(parent)
        
        self._trace_path = trace_path
        self._dbc_path = dbc_path
        self._cache_manager = cache_manager
        self._use_parallel = use_parallel
        
        self._cancel_mutex = QMutex()
        self._cancelled = False
        
        self._progress = ParseProgress()
        self._cache_key: Optional[str] = None
        self._decode_pool: Optional[DecodePool] = None
        
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
        finally:
            # Cleanup decode pool
            if self._decode_pool is not None:
                self._decode_pool.shutdown(wait=False)
                self._decode_pool = None
    
    def _run_parsing(self, start_time: float) -> None:
        """Internal parsing implementation with parallel decoding."""
        # Initialize parser and decoder (decoder needed for cache key)
        parser = CANParser(self._trace_path)
        decoder = DBCDecoder(self._dbc_path)
        
        # Generate cache key
        self._cache_key = self._cache_manager.generate_cache_key(
            parser.get_cache_key(),
            decoder.get_cache_key(),
        )
        
        # Check for existing cache
        if self._cache_manager.has_cache(self._cache_key):
            logger.info("Using cached data - skipping parse")
            self._load_from_cache(start_time)
            return
        
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
        
        # Choose parsing strategy based on file size and configuration
        if self._use_parallel and total_messages > 5000:
            self._run_parallel_parsing(parser, decoder, start_time)
        else:
            self._run_sequential_parsing(parser, decoder, start_time)
    
    def _run_parallel_parsing(self, parser: CANParser, decoder: DBCDecoder, start_time: float) -> None:
        """
        Parse and decode using parallel ProcessPoolExecutor.
        
        Batches messages and distributes decoding across CPU cores.
        """
        # Calculate optimal worker count
        cpu_count = os.cpu_count() or 4
        max_workers = max(1, cpu_count - 1)  # Leave one core for UI
        
        logger.info(f"Starting parallel decode with {max_workers} workers")
        
        # Initialize decode pool
        self._decode_pool = DecodePool(
            self._dbc_path,
            max_workers=max_workers,
            batch_size=self.MESSAGE_BATCH_SIZE
        )
        
        # Accumulators
        all_signals: deque[DecodedSignal] = deque()
        signal_batch: list[DecodedSignal] = []
        message_batch: list[tuple] = []
        last_progress_time = time.time()
        last_emit_time = time.time()
        
        def emit_signals_if_needed(force: bool = False) -> None:
            """Emit signal batch to UI if threshold reached."""
            nonlocal signal_batch, last_emit_time
            
            current_time = time.time()
            should_emit = (
                force or
                len(signal_batch) >= self.SIGNAL_BATCH_SIZE or
                (signal_batch and current_time - last_emit_time >= self.UI_EMIT_INTERVAL)
            )
            
            if should_emit and signal_batch:
                self.signals_decoded.emit(list(signal_batch))
                signal_batch.clear()
                last_emit_time = current_time
        
        def process_decoded_batch(signal_tuples: list) -> None:
            """Process a batch of decoded signal tuples."""
            nonlocal signal_batch, all_signals
            
            decoded = signal_tuples_to_decoded(signal_tuples)
            self._progress.decoded_messages += len(decoded)
            signal_batch.extend(decoded)
            all_signals.extend(decoded)
            
            emit_signals_if_needed()
        
        # Stream messages to batches
        for msg in parser.iterate_messages():
            if self._is_cancelled():
                self._handle_cancellation()
                return
            
            self._progress.processed_messages += 1
            
            # Convert to tuple for serialization
            message_batch.append(message_to_tuple(msg))
            
            # When batch is full, decode it
            if len(message_batch) >= self.MESSAGE_BATCH_SIZE:
                # Decode batch synchronously in pool (pool handles parallelism internally)
                for signal_tuples in self._decode_pool.decode_messages(iter(message_batch)):
                    if signal_tuples:
                        process_decoded_batch(signal_tuples)
                        
                        if self._is_cancelled():
                            self._handle_cancellation()
                            return
                
                # Track errors (messages that didn't decode)
                decoded_in_batch = self._progress.decoded_messages
                self._progress.decode_errors += len(message_batch) - (decoded_in_batch - self._progress.decode_errors)
                
                message_batch.clear()
            
            # Progress update
            current_time = time.time()
            if current_time - last_progress_time >= self.PROGRESS_UPDATE_INTERVAL:
                self._progress.elapsed_seconds = current_time - start_time
                self.progress_updated.emit(self._progress)
                last_progress_time = current_time
        
        # Process remaining messages
        if message_batch:
            for signal_tuples in self._decode_pool.decode_messages(iter(message_batch)):
                if signal_tuples:
                    process_decoded_batch(signal_tuples)
        
        # Emit remaining signals
        emit_signals_if_needed(force=True)
        
        # Shutdown pool
        self._decode_pool.shutdown()
        self._decode_pool = None
        
        # Final progress update
        self._progress.elapsed_seconds = time.time() - start_time
        self._progress.total_messages = self._progress.processed_messages
        self._progress.state = ParseState.COMPLETED
        self.progress_updated.emit(self._progress)
        
        # Cache results
        self._cache_results(list(all_signals))
        
        logger.info(
            f"Parallel parsing completed: {self._progress.decoded_messages} signals "
            f"in {self._progress.elapsed_seconds:.2f}s "
            f"({self._progress.decode_rate:.0f} msg/s)"
        )
        
        self.parsing_completed.emit(self._cache_key)
    
    def _run_sequential_parsing(self, parser: CANParser, decoder: DBCDecoder, start_time: float) -> None:
        """
        Parse and decode sequentially (for small files or fallback).
        
        Uses single-threaded decoding for lower overhead on small datasets.
        """
        logger.info("Using sequential decode (small file or parallel disabled)")
        
        # Accumulators for batching
        signal_batch: list[DecodedSignal] = []
        all_signals: deque[DecodedSignal] = deque()
        last_progress_time = time.time()
        last_emit_time = time.time()
        
        # Stream through messages
        for msg in parser.iterate_messages():
            if self._is_cancelled():
                self._handle_cancellation()
                return
            
            self._progress.processed_messages += 1
            
            # Decode message
            decoded_signals = decoder.decode_message(msg)
            
            if decoded_signals:
                self._progress.decoded_messages += len(decoded_signals)
                signal_batch.extend(decoded_signals)
                all_signals.extend(decoded_signals)
            else:
                self._progress.decode_errors += 1
            
            current_time = time.time()
            
            # Emit signal batch - batched for lazy UI updates
            should_emit_signals = (
                len(signal_batch) >= self.SIGNAL_BATCH_SIZE or
                (signal_batch and current_time - last_emit_time >= self.UI_EMIT_INTERVAL)
            )
            
            if should_emit_signals:
                self.signals_decoded.emit(list(signal_batch))
                signal_batch.clear()
                last_emit_time = current_time
            
            # Emit progress update frequently
            if current_time - last_progress_time >= self.PROGRESS_UPDATE_INTERVAL:
                self._progress.elapsed_seconds = current_time - start_time
                self.progress_updated.emit(self._progress)
                last_progress_time = current_time
        
        # Emit remaining signals
        if signal_batch:
            self.signals_decoded.emit(list(signal_batch))
        
        # Final progress update
        self._progress.elapsed_seconds = time.time() - start_time
        self._progress.total_messages = self._progress.processed_messages
        self._progress.state = ParseState.COMPLETED
        self.progress_updated.emit(self._progress)
        
        # Cache results in background
        self._cache_results(list(all_signals))
        
        logger.info(
            f"Sequential parsing completed: {self._progress.decoded_messages} signals "
            f"in {self._progress.elapsed_seconds:.2f}s "
            f"({self._progress.decode_rate:.0f} msg/s)"
        )
        
        self.parsing_completed.emit(self._cache_key)
    
    def _load_from_cache(self, start_time: float) -> None:
        """Load and stream data from cache with responsive updates."""
        self.parsing_started.emit()
        
        self._progress.state = ParseState.PARSING
        total = self._cache_manager.get_signal_count(self._cache_key)
        self._progress.total_messages = total
        self.progress_updated.emit(self._progress)
        
        signal_batch: list[DecodedSignal] = []
        last_progress_time = time.time()
        last_emit_time = time.time()
        
        for signal in self._cache_manager.load_signals(self._cache_key):
            if self._is_cancelled():
                self._handle_cancellation()
                return
            
            signal_batch.append(signal)
            self._progress.processed_messages += 1
            self._progress.decoded_messages += 1
            
            current_time = time.time()
            
            # Emit batch - larger batches for cache loading
            should_emit = (
                len(signal_batch) >= self.SIGNAL_BATCH_SIZE or
                (signal_batch and current_time - last_emit_time >= self.UI_EMIT_INTERVAL)
            )
            
            if should_emit:
                self.signals_decoded.emit(list(signal_batch))
                signal_batch.clear()
                last_emit_time = current_time
            
            # Progress update
            if current_time - last_progress_time >= self.PROGRESS_UPDATE_INTERVAL:
                self._progress.elapsed_seconds = current_time - start_time
                self.progress_updated.emit(self._progress)
                last_progress_time = current_time
        
        # Remaining signals
        if signal_batch:
            self.signals_decoded.emit(list(signal_batch))
        
        self._progress.elapsed_seconds = time.time() - start_time
        self._progress.state = ParseState.COMPLETED
        self.progress_updated.emit(self._progress)
        
        logger.info(f"Loaded {self._progress.decoded_messages} signals from cache")
        self.parsing_completed.emit(self._cache_key)
    
    def _cache_results(self, signals: list[DecodedSignal]) -> None:
        """Store parsed results in cache."""
        if not signals:
            return
        
        try:
            self._cache_manager.store_signals(
                self._cache_key,
                iter(signals),
                self._trace_path.name,
                self._dbc_path.name,
            )
        except Exception as e:
            logger.warning(f"Failed to cache results: {e}")
    
    def _handle_cancellation(self) -> None:
        """Handle graceful cancellation."""
        # Shutdown decode pool if active
        if self._decode_pool is not None:
            self._decode_pool.shutdown(wait=False)
            self._decode_pool = None
        
        self._progress.state = ParseState.CANCELLED
        self.progress_updated.emit(self._progress)
        self.parsing_cancelled.emit()
        logger.info("Parsing cancelled by user")
