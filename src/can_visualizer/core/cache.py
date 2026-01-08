"""
SQLite-based cache for decoded CAN data.

Provides instant reload of previously parsed files by caching
decoded signal values to disk.
"""

import sqlite3
import hashlib
import pickle
from pathlib import Path
from typing import Optional, Iterator
from contextlib import contextmanager

from ..utils.logging_config import get_logger
from .models import DecodedSignal

logger = get_logger("cache")


class CacheManager:
    """
    SQLite cache for decoded CAN signal data.

    Design decisions:
    - SQLite for reliability and query flexibility
    - Batch inserts for performance
    - Content-based cache keys for change detection
    - Separate tables per parse session for isolation
    """

    BATCH_SIZE = 10000  # Signals per batch insert

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize cache manager.

        Args:
            cache_dir: Directory for cache database.
                      Defaults to ~/.can_visualizer/cache
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".can_visualizer" / "cache"

        cache_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = cache_dir / "signal_cache.db"

        self._init_database()
        logger.info(f"Cache initialized at: {self._db_path}")

    def _init_database(self) -> None:
        """Create database schema if not exists."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache_metadata (
                    cache_key TEXT PRIMARY KEY,
                    trace_file TEXT,
                    dbc_file TEXT,
                    signal_count INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS cached_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cache_key TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    message_name TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    signal_name TEXT NOT NULL,
                    raw_value TEXT NOT NULL,
                    physical_value REAL NOT NULL,
                    unit TEXT,
                    FOREIGN KEY (cache_key) REFERENCES cache_metadata(cache_key)
                )
            """)

            # Index for fast lookups
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cache_key 
                ON cached_signals(cache_key)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_name 
                ON cached_signals(cache_key, signal_name)
            """)

            conn.commit()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def generate_cache_key(
        self,
        trace_key: str,
        dbc_key: str,
    ) -> str:
        """
        Generate composite cache key from file keys.

        Args:
            trace_key: Key from CANParser.get_cache_key()
            dbc_key: Key from DBCDecoder.get_cache_key()

        Returns:
            SHA256 hash of combined keys
        """
        combined = f"{trace_key}|{dbc_key}"
        return hashlib.sha256(combined.encode()).hexdigest()[:32]

    def has_cache(self, cache_key: str) -> bool:
        """Check if valid cache exists for this key."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM cache_metadata WHERE cache_key = ?", (cache_key,)
            )
            exists = cursor.fetchone() is not None

        if exists:
            logger.info(f"Cache HIT for key: {cache_key[:16]}...")
        else:
            logger.info(f"Cache MISS for key: {cache_key[:16]}...")

        return exists

    def store_signals(
        self,
        cache_key: str,
        signals: Iterator[DecodedSignal],
        trace_file: str,
        dbc_file: str,
    ) -> int:
        """
        Store decoded signals to cache.

        Uses batch inserts for performance with large datasets.

        Args:
            cache_key: Unique cache identifier
            signals: Iterator of decoded signals
            trace_file: Name of trace file for metadata
            dbc_file: Name of DBC file for metadata

        Returns:
            Total number of signals cached
        """
        logger.info(f"Caching signals for key: {cache_key[:16]}...")

        # Clear any existing data for this key
        self.invalidate_cache(cache_key)

        total_count = 0
        batch = []

        with self._get_connection() as conn:
            for signal in signals:
                # Validate timestamp is a reasonable float
                ts = signal.timestamp
                if not isinstance(ts, (int, float)) or ts < 0 or ts > 1e15:
                    logger.warning(f"Suspicious timestamp {ts}, clamping")
                    ts = max(0.0, min(float(ts), 1e15))

                batch.append(
                    (
                        cache_key,
                        ts,
                        signal.message_name,
                        signal.message_id,
                        signal.signal_name,
                        str(signal.raw_value),  # Store as TEXT for large integers
                        signal.physical_value,
                        signal.unit,
                    )
                )

                if len(batch) >= self.BATCH_SIZE:
                    self._insert_batch(conn, batch)
                    total_count += len(batch)
                    batch.clear()

            # Insert remaining batch
            if batch:
                self._insert_batch(conn, batch)
                total_count += len(batch)

            # Store metadata
            conn.execute(
                """INSERT INTO cache_metadata 
                   (cache_key, trace_file, dbc_file, signal_count)
                   VALUES (?, ?, ?, ?)""",
                (cache_key, trace_file, dbc_file, total_count),
            )

            conn.commit()

        logger.info(f"Cached {total_count} signals")
        return total_count

    def _insert_batch(self, conn: sqlite3.Connection, batch: list) -> None:
        """Insert a batch of signals efficiently."""
        conn.executemany(
            """INSERT INTO cached_signals 
               (cache_key, timestamp, message_name, message_id, 
                signal_name, raw_value, physical_value, unit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            batch,
        )

    def load_signals(self, cache_key: str) -> Iterator[DecodedSignal]:
        """
        Load all cached signals for a key.

        Yields signals in timestamp order for streaming replay.

        Args:
            cache_key: Cache identifier

        Yields:
            DecodedSignal objects from cache
        """
        logger.info(f"Loading cached signals for: {cache_key[:16]}...")

        with self._get_connection() as conn:
            cursor = conn.execute(
                """SELECT timestamp, message_name, message_id, 
                          signal_name, raw_value, physical_value, unit
                   FROM cached_signals 
                   WHERE cache_key = ?
                   ORDER BY timestamp""",
                (cache_key,),
            )

            count = 0
            for row in cursor:
                yield DecodedSignal(
                    timestamp=row["timestamp"],
                    message_name=row["message_name"],
                    message_id=row["message_id"],
                    signal_name=row["signal_name"],
                    raw_value=int(row["raw_value"]),  # Convert TEXT back to int
                    physical_value=row["physical_value"],
                    unit=row["unit"] or "",
                )
                count += 1

            logger.info(f"Loaded {count} signals from cache")

    def load_signal_data(
        self,
        cache_key: str,
        signal_names: list[str],
    ) -> dict[str, tuple[list[float], list[float]]]:
        """
        Load specific signals as numpy-ready arrays.

        Optimized for plotting - returns timestamps and values
        as separate lists for direct numpy conversion.

        Args:
            cache_key: Cache identifier
            signal_names: List of signal names to load

        Returns:
            Dict mapping signal_name to (timestamps, values) tuples
        """
        result: dict[str, tuple[list[float], list[float]]] = {
            name: ([], []) for name in signal_names
        }

        if not signal_names:
            return result

        placeholders = ",".join("?" * len(signal_names))

        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""SELECT signal_name, timestamp, physical_value
                    FROM cached_signals 
                    WHERE cache_key = ? AND signal_name IN ({placeholders})
                    ORDER BY timestamp""",
                (cache_key, *signal_names),
            )

            for row in cursor:
                name = row["signal_name"]
                if name in result:
                    result[name][0].append(row["timestamp"])
                    result[name][1].append(row["physical_value"])

        return result

    def get_signal_count(self, cache_key: str) -> int:
        """Get total cached signal count for a key."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT signal_count FROM cache_metadata WHERE cache_key = ?",
                (cache_key,),
            )
            row = cursor.fetchone()
            return row["signal_count"] if row else 0

    def invalidate_cache(self, cache_key: str) -> None:
        """Remove cached data for a specific key."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM cached_signals WHERE cache_key = ?", (cache_key,))
            conn.execute("DELETE FROM cache_metadata WHERE cache_key = ?", (cache_key,))
            conn.commit()
        logger.debug(f"Invalidated cache: {cache_key[:16]}...")

    def clear_all(self) -> None:
        """Clear entire cache database."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM cached_signals")
            conn.execute("DELETE FROM cache_metadata")
            conn.commit()
        logger.info("Cleared all cached data")

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) as count, SUM(signal_count) as total "
                "FROM cache_metadata"
            )
            row = cursor.fetchone()

            return {
                "cached_files": row["count"] or 0,
                "total_signals": row["total"] or 0,
                "database_size_mb": self._db_path.stat().st_size / (1024 * 1024),
            }
