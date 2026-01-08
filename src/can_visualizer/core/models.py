"""
Data models for CAN message visualization.

These dataclasses provide type-safe, immutable representations of:
- Raw CAN messages
- Decoded signal values
- Parsing progress state
"""

from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum


class ParseState(Enum):
    """Parsing state enumeration."""

    IDLE = "idle"
    PARSING = "parsing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class CANMessage:
    """
    Represents a single raw CAN message from BLF/ASC file.

    Frozen for immutability and slots for memory efficiency
    when handling millions of messages.
    """

    timestamp: float  # Seconds since start
    arbitration_id: int  # CAN ID (11-bit or 29-bit)
    data: bytes  # Raw payload (0-8 bytes for classic CAN)
    is_extended_id: bool = False
    channel: int = 0

    @property
    def hex_id(self) -> str:
        """Return CAN ID as hex string."""
        return f"0x{self.arbitration_id:03X}"

    @property
    def hex_data(self) -> str:
        """Return data as hex string."""
        return " ".join(f"{b:02X}" for b in self.data)


@dataclass(frozen=True, slots=True)
class DecodedSignal:
    """
    Represents a decoded CAN signal with both raw and physical values.

    Physical values are computed using DBC scaling:
    physical = raw * factor + offset
    """

    timestamp: float
    message_name: str
    message_id: int
    signal_name: str
    raw_value: int
    physical_value: float
    unit: str = ""

    @property
    def full_name(self) -> str:
        """Return fully qualified signal name."""
        return f"{self.message_name}.{self.signal_name}"


@dataclass(slots=True)
class ParseProgress:
    """
    Mutable progress state for streaming updates.

    Used to communicate parsing status to the UI without
    blocking the main thread.
    """

    state: ParseState = ParseState.IDLE
    total_messages: int = 0
    processed_messages: int = 0
    decoded_messages: int = 0
    decode_errors: int = 0
    elapsed_seconds: float = 0.0
    error_message: str = ""

    @property
    def progress_percent(self) -> float:
        """Return progress as percentage (0-100)."""
        if self.total_messages == 0:
            return 0.0
        return (self.processed_messages / self.total_messages) * 100

    @property
    def decode_rate(self) -> float:
        """Return messages per second."""
        if self.elapsed_seconds == 0:
            return 0.0
        return self.decoded_messages / self.elapsed_seconds

    def reset(self) -> None:
        """Reset all progress counters."""
        self.state = ParseState.IDLE
        self.total_messages = 0
        self.processed_messages = 0
        self.decoded_messages = 0
        self.decode_errors = 0
        self.elapsed_seconds = 0.0
        self.error_message = ""


@dataclass
class SignalDefinition:
    """
    DBC signal definition for UI display.

    Contains metadata about a signal from the DBC file,
    used by the signal browser tree.
    """

    name: str
    message_name: str
    message_id: int
    start_bit: int
    length: int
    byte_order: str  # 'little_endian' or 'big_endian'
    is_signed: bool
    factor: float
    offset: float
    minimum: Optional[float]
    maximum: Optional[float]
    unit: str
    choices: Optional[dict[int, str]] = None  # For enum signals
    comment: str = ""

    @property
    def is_enum(self) -> bool:
        """Check if this signal has discrete enum values."""
        return self.choices is not None and len(self.choices) > 0

    @property
    def full_name(self) -> str:
        """Return fully qualified signal name."""
        return f"{self.message_name}.{self.name}"


@dataclass
class MessageDefinition:
    """
    DBC message definition containing all its signals.
    """

    name: str
    message_id: int
    length: int  # DLC
    signals: list[SignalDefinition] = field(default_factory=list)
    comment: str = ""

    @property
    def hex_id(self) -> str:
        """Return message ID as hex string."""
        return f"0x{self.message_id:03X}"
