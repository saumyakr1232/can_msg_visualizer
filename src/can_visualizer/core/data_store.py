import sqlite3
from typing import Iterator, Optional, List
from .models import DecodedSignal
from contextlib import contextmanager


class DataStore:
    """
    In-memory SQLite datastore for DecodedSignal objects.
    Provides efficient querying, pagination, and filtering.
    """

    def __init__(self):
        """Initialize in-memory database."""
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_database()

    def _init_database(self) -> None:
        """Create database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    message_name TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    signal_name TEXT NOT NULL,
                    raw_value TEXT NOT NULL,
                    physical_value REAL NOT NULL,
                    unit TEXT
                )
            """)

            # Indices for performance
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON signals(timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_signal_name ON signals(signal_name)"
            )
            conn.commit()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        # Since we use :memory: and share the connection object, we can just yield it.
        # However, for thread safety with check_same_thread=False, we rely on SQLite's serialization.
        # For :memory:, creating new connections would create NEW databases, so we must share self._conn.
        yield self._conn

    def add_data(self, data: List[DecodedSignal]) -> int:
        """
        Add a batch of DecodedSignal objects to the store.

        Args:
            data: List of DecodedSignal objects.

        Returns:
            Number of records added.
        """
        if not data:
            return 0

        batch = [
            (
                d.timestamp,
                d.message_name,
                d.message_id,
                d.signal_name,
                str(d.raw_value),  # Store as string to handle large integers if needed
                d.physical_value,
                d.unit,
            )
            for d in data
        ]

        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO signals 
                (timestamp, message_name, message_id, signal_name, raw_value, physical_value, unit)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                batch,
            )
            conn.commit()

        return len(batch)

    def fetch_data(self, limit: Optional[int] = None) -> Iterator[DecodedSignal]:
        """
        Fetch data from the store.

        Args:
            limit: precise number of records to return.

        Yields:
            DecodedSignal objects.
        """
        query = "SELECT * FROM signals ORDER BY timestamp"
        params = ()

        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            for row in cursor:
                yield self._row_to_signal(row)

    def fetch_paginated_data(
        self, page: int, page_size: int
    ) -> Iterator[DecodedSignal]:
        """
        Fetch a page of data.

        Args:
            page: Page number (1-based).
            page_size: Number of records per page.

        Yields:
            DecodedSignal objects for the requested page.
        """
        if page < 1:
            page = 1

        offset = (page - 1) * page_size

        query = "SELECT * FROM signals ORDER BY timestamp LIMIT ? OFFSET ?"

        with self._get_connection() as conn:
            cursor = conn.execute(query, (page_size, offset))
            for row in cursor:
                yield self._row_to_signal(row)

    def fetch_by_signal(self, signal_name: str) -> Iterator[DecodedSignal]:
        """
        Fetch all occurrences of a specific signal.

        Args:
            signal_name: Name of the signal to filter by.

        Yields:
            DecodedSignal objects.
        """
        query = "SELECT * FROM signals WHERE signal_name = ? ORDER BY timestamp"

        with self._get_connection() as conn:
            cursor = conn.execute(query, (signal_name,))
            for row in cursor:
                yield self._row_to_signal(row)

    def get_total_count(self) -> int:
        """Get total number of records in the store."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) as count FROM signals")
            row = cursor.fetchone()
            return row["count"] if row else 0

    def get_signal_names(self) -> List[str]:
        """Get list of unique signal names in the store."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT DISTINCT signal_name FROM signals ORDER BY signal_name"
            )
            return [row["signal_name"] for row in cursor]

    def _row_to_signal(self, row: sqlite3.Row) -> DecodedSignal:
        """Convert a database row to a DecodedSignal object."""
        return DecodedSignal(
            timestamp=row["timestamp"],
            message_name=row["message_name"],
            message_id=row["message_id"],
            signal_name=row["signal_name"],
            raw_value=int(row["raw_value"]),
            physical_value=row["physical_value"],
            unit=row["unit"],
        )

    def clear(self) -> None:
        """Clear all data from the store."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM signals")
            conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
