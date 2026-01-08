"""
Parallel CAN message decoding using ProcessPoolExecutor.

Provides efficient CPU-bound decoding by distributing work across
multiple processes. Uses a pool of workers initialized with the DBC
database to decode message batches in parallel.
"""

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Iterator, Optional
from dataclasses import dataclass

from ..utils.logging_config import get_logger

logger = get_logger("decode_pool")

# Global decoder instance for worker processes (initialized once per worker)
_worker_decoder = None
_worker_dbc_path = None


@dataclass
class DecodeTask:
    """A batch of messages to decode."""
    batch_id: int
    messages: list  # List of (timestamp, arbitration_id, data_bytes, is_extended_id, channel)


@dataclass  
class DecodeResult:
    """Result from decoding a batch."""
    batch_id: int
    signals: list  # List of decoded signal tuples
    error_count: int


def _init_worker(dbc_path: str) -> None:
    """
    Initialize decoder in worker process.
    
    Called once when worker starts to load DBC file.
    """
    global _worker_decoder, _worker_dbc_path
    
    if _worker_dbc_path == dbc_path and _worker_decoder is not None:
        return
    
    # Import here to avoid import in main process
    import cantools
    
    _worker_dbc_path = dbc_path
    _worker_decoder = cantools.database.load_file(dbc_path)
    

def _decode_batch(task_data: tuple) -> DecodeResult:
    """
    Decode a batch of CAN messages in a worker process.
    
    Args:
        task_data: Tuple of (batch_id, messages, dbc_path)
        
    Returns:
        DecodeResult with decoded signals
    """
    global _worker_decoder
    
    batch_id, messages, dbc_path = task_data
    
    # Initialize decoder if needed
    _init_worker(dbc_path)
    
    decoded_signals = []
    error_count = 0
    
    # Build message lookup from DBC
    msg_by_id = {msg.frame_id: msg for msg in _worker_decoder.messages}
    
    for msg_tuple in messages:
        timestamp, arb_id, data_bytes, is_extended, channel = msg_tuple
        
        dbc_msg = msg_by_id.get(arb_id)
        if dbc_msg is None:
            error_count += 1
            continue
        
        try:
            # Decode message using cantools
            decoded = dbc_msg.decode(data_bytes, decode_choices=False)
            
            for signal_name, physical_value in decoded.items():
                # Find signal for metadata
                sig = next((s for s in dbc_msg.signals if s.name == signal_name), None)
                if sig is None:
                    continue
                
                # Calculate raw value
                if sig.scale != 0:
                    raw_value = int((physical_value - sig.offset) / sig.scale)
                else:
                    raw_value = int(physical_value)
                
                # Return as tuple for efficient serialization
                decoded_signals.append((
                    timestamp,
                    dbc_msg.name,
                    arb_id,
                    signal_name,
                    raw_value,
                    float(physical_value),
                    sig.unit or ""
                ))
                
        except Exception:
            error_count += 1
    
    return DecodeResult(
        batch_id=batch_id,
        signals=decoded_signals,
        error_count=error_count
    )


class DecodePool:
    """
    Manages a pool of worker processes for parallel CAN message decoding.
    
    Usage:
        pool = DecodePool(dbc_path, max_workers=4)
        for result in pool.decode_batches(message_batches):
            process(result.signals)
        pool.shutdown()
    """
    
    # Default batch size for optimal throughput
    DEFAULT_BATCH_SIZE = 2000
    
    def __init__(
        self,
        dbc_path: Path,
        max_workers: Optional[int] = None,
        batch_size: int = DEFAULT_BATCH_SIZE
    ):
        """
        Initialize decode pool.
        
        Args:
            dbc_path: Path to DBC database file
            max_workers: Number of worker processes (default: CPU count - 1)
            batch_size: Messages per batch (default: 2000)
        """
        self._dbc_path = str(dbc_path)
        self._batch_size = batch_size
        
        # Use CPU count - 1 to leave one core for UI
        if max_workers is None:
            cpu_count = os.cpu_count() or 4
            max_workers = max(1, cpu_count - 1)
        
        self._max_workers = max_workers
        self._executor: Optional[ProcessPoolExecutor] = None
        self._batch_counter = 0
        
        logger.info(f"DecodePool initialized with {max_workers} workers, batch_size={batch_size}")
    
    def _ensure_executor(self) -> ProcessPoolExecutor:
        """Create executor on first use (lazy initialization)."""
        if self._executor is None:
            self._executor = ProcessPoolExecutor(max_workers=self._max_workers)
        return self._executor
    
    def decode_messages(
        self,
        messages: Iterator[tuple],
        progress_callback: Optional[callable] = None
    ) -> Iterator[list]:
        """
        Decode messages in parallel batches.
        
        Args:
            messages: Iterator of (timestamp, arb_id, data, is_extended, channel) tuples
            progress_callback: Optional callback(processed_count) for progress updates
            
        Yields:
            Lists of decoded signal tuples
        """
        executor = self._ensure_executor()
        
        # Collect messages into batches and submit
        batch = []
        futures = []
        total_submitted = 0
        
        for msg in messages:
            batch.append(msg)
            
            if len(batch) >= self._batch_size:
                # Submit batch for processing
                self._batch_counter += 1
                task_data = (self._batch_counter, batch, self._dbc_path)
                future = executor.submit(_decode_batch, task_data)
                futures.append(future)
                total_submitted += len(batch)
                batch = []
                
                # Process completed futures to avoid memory buildup
                completed = [f for f in futures if f.done()]
                for f in completed:
                    futures.remove(f)
                    result = f.result()
                    if result.signals:
                        yield result.signals
                    if progress_callback:
                        progress_callback(len(result.signals))
        
        # Submit final partial batch
        if batch:
            self._batch_counter += 1
            task_data = (self._batch_counter, batch, self._dbc_path)
            future = executor.submit(_decode_batch, task_data)
            futures.append(future)
        
        # Wait for remaining futures
        for future in as_completed(futures):
            result = future.result()
            if result.signals:
                yield result.signals
            if progress_callback:
                progress_callback(len(result.signals))
    
    def decode_batch_sync(self, messages: list) -> list:
        """
        Decode a single batch synchronously (for small datasets).
        
        Args:
            messages: List of message tuples
            
        Returns:
            List of decoded signal tuples
        """
        task_data = (0, messages, self._dbc_path)
        result = _decode_batch(task_data)
        return result.signals
    
    def shutdown(self, wait: bool = True) -> None:
        """
        Shutdown the worker pool.
        
        Args:
            wait: Whether to wait for pending tasks to complete
        """
        if self._executor is not None:
            self._executor.shutdown(wait=wait)
            self._executor = None
            logger.info("DecodePool shutdown complete")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return False

