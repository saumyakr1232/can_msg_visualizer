"""
Background worker thread for CAN file parsing.

Handles asynchronous parsing and decoding with progress updates
using Qt signal-slot mechanism for thread-safe UI communication.
"""

import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker

from ..core.parser import CANParser
from ..core.decoder import DBCDecoder
from ..core.cache import CacheManager
from ..core.models import DecodedSignal, ParseProgress, ParseState
from ..utils.logging_config import get_logger

logger = get_logger("worker")


class ParseWorker(QThread):
    """
    Worker thread for parsing CAN trace files.
    
    Emits signals for:
    - Progress updates (batched for UI performance)
    - Decoded signal data (batched for plot updates)
    - Completion and error states
    
    Design decisions:
    - Batched signal emission (every 1000 signals or 100ms)
    - Cancellation support via mutex-protected flag
    - Automatic caching on completion
    - Memory-efficient streaming (never loads full file)
    """
    
    # Signal types for thread-safe communication
    progress_updated = Signal(ParseProgress)
    signals_decoded = Signal(list)  # List[DecodedSignal]
    parsing_started = Signal()
    parsing_completed = Signal(str)  # cache_key
    parsing_cancelled = Signal()
    parsing_error = Signal(str)  # error message
    
    # Batching parameters
    SIGNAL_BATCH_SIZE = 1000
    PROGRESS_UPDATE_INTERVAL = 0.1  # seconds
    
    def __init__(
        self,
        trace_path: Path,
        dbc_path: Path,
        cache_manager: CacheManager,
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
        self._cache_manager = cache_manager
        
        self._cancel_mutex = QMutex()
        self._cancelled = False
        
        self._progress = ParseProgress()
        self._cache_key: Optional[str] = None
    
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
        """Internal parsing implementation."""
        # Initialize parser and decoder
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
        
        # Start fresh parse
        self.parsing_started.emit()
        
        self._progress.state = ParseState.PARSING
        self._progress.total_messages = parser.estimate_message_count()
        self.progress_updated.emit(self._progress)
        
        # Accumulators for batching
        signal_batch: list[DecodedSignal] = []
        all_signals: list[DecodedSignal] = []  # For caching
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
            
            # Emit signal batch
            if len(signal_batch) >= self.SIGNAL_BATCH_SIZE:
                self.signals_decoded.emit(signal_batch.copy())
                signal_batch.clear()
            
            # Emit progress update
            current_time = time.time()
            if current_time - last_progress_time >= self.PROGRESS_UPDATE_INTERVAL:
                self._progress.elapsed_seconds = current_time - start_time
                self.progress_updated.emit(self._progress)
                last_progress_time = current_time
        
        # Emit remaining signals
        if signal_batch:
            self.signals_decoded.emit(signal_batch)
        
        # Final progress update
        self._progress.elapsed_seconds = time.time() - start_time
        self._progress.state = ParseState.COMPLETED
        self.progress_updated.emit(self._progress)
        
        # Cache results
        self._cache_results(all_signals)
        
        logger.info(
            f"Parsing completed: {self._progress.decoded_messages} messages "
            f"in {self._progress.elapsed_seconds:.2f}s "
            f"({self._progress.decode_rate:.0f} msg/s)"
        )
        
        self.parsing_completed.emit(self._cache_key)
    
    def _load_from_cache(self, start_time: float) -> None:
        """Load and stream data from cache."""
        self.parsing_started.emit()
        
        self._progress.state = ParseState.PARSING
        total = self._cache_manager.get_signal_count(self._cache_key)
        self._progress.total_messages = total
        self.progress_updated.emit(self._progress)
        
        signal_batch: list[DecodedSignal] = []
        last_progress_time = time.time()
        
        for signal in self._cache_manager.load_signals(self._cache_key):
            if self._is_cancelled():
                self._handle_cancellation()
                return
            
            signal_batch.append(signal)
            self._progress.processed_messages += 1
            self._progress.decoded_messages += 1
            
            # Emit batch
            if len(signal_batch) >= self.SIGNAL_BATCH_SIZE:
                self.signals_decoded.emit(signal_batch.copy())
                signal_batch.clear()
            
            # Progress update
            current_time = time.time()
            if current_time - last_progress_time >= self.PROGRESS_UPDATE_INTERVAL:
                self._progress.elapsed_seconds = current_time - start_time
                self.progress_updated.emit(self._progress)
                last_progress_time = current_time
        
        # Remaining signals
        if signal_batch:
            self.signals_decoded.emit(signal_batch)
        
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
        self._progress.state = ParseState.CANCELLED
        self.progress_updated.emit(self._progress)
        self.parsing_cancelled.emit()
        logger.info("Parsing cancelled by user")

