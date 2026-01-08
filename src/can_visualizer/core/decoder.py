"""
DBC-based CAN signal decoder.

Uses cantools library to decode raw CAN data into physical signal values.
"""

from pathlib import Path
from typing import Optional
import cantools
from cantools.database import Message as DBCMessage

from ..utils.logging_config import get_logger
from .models import (
    CANMessage,
    DecodedSignal,
    MessageDefinition,
    SignalDefinition,
)

logger = get_logger("decoder")


class DBCDecoder:
    """
    Decodes CAN messages using a DBC database file.
    
    Provides:
    - Message/signal definitions for UI browsing
    - Real-time decoding of raw CAN data
    - Efficient lookup by CAN ID
    """
    
    def __init__(self, dbc_path: Path | str):
        """
        Load and parse a DBC file.
        
        Args:
            dbc_path: Path to the DBC file
            
        Raises:
            FileNotFoundError: If DBC file doesn't exist
            cantools.database.UnsupportedDatabaseFormatError: If file is invalid
        """
        self.dbc_path = Path(dbc_path)
        
        if not self.dbc_path.exists():
            raise FileNotFoundError(f"DBC file not found: {self.dbc_path}")
        
        logger.info(f"Loading DBC: {self.dbc_path.name}")
        
        self._db = cantools.database.load_file(str(self.dbc_path))
        self._message_by_id: dict[int, DBCMessage] = {}
        self._definitions: dict[int, MessageDefinition] = {}
        
        # Build lookup tables
        self._build_lookups()
        
        logger.info(
            f"Loaded DBC with {len(self._message_by_id)} messages, "
            f"{sum(len(m.signals) for m in self._definitions.values())} signals"
        )
    
    def _build_lookups(self) -> None:
        """Build efficient lookup tables from DBC database."""
        for msg in self._db.messages:
            # Handle frame ID (mask off extended ID bit if present)
            frame_id = msg.frame_id
            self._message_by_id[frame_id] = msg
            
            # Build signal definitions for UI
            signals = []
            for sig in msg.signals:
                sig_def = SignalDefinition(
                    name=sig.name,
                    message_name=msg.name,
                    message_id=frame_id,
                    start_bit=sig.start,
                    length=sig.length,
                    byte_order='big_endian' if sig.byte_order == 'big_endian' else 'little_endian',
                    is_signed=sig.is_signed,
                    factor=sig.scale,
                    offset=sig.offset,
                    minimum=sig.minimum,
                    maximum=sig.maximum,
                    unit=sig.unit or "",
                    choices=sig.choices,
                    comment=sig.comment or "",
                )
                signals.append(sig_def)
            
            msg_def = MessageDefinition(
                name=msg.name,
                message_id=frame_id,
                length=msg.length,
                signals=signals,
                comment=msg.comment or "",
            )
            self._definitions[frame_id] = msg_def
    
    @property
    def message_definitions(self) -> dict[int, MessageDefinition]:
        """Get all message definitions indexed by CAN ID."""
        return self._definitions
    
    @property
    def message_count(self) -> int:
        """Get number of messages in DBC."""
        return len(self._definitions)
    
    def get_all_messages(self) -> list[MessageDefinition]:
        """Get list of all message definitions."""
        return list(self._definitions.values())
    
    def get_message(self, can_id: int) -> Optional[MessageDefinition]:
        """Get message definition by CAN ID."""
        return self._definitions.get(can_id)
    
    def decode_message(self, msg: CANMessage) -> list[DecodedSignal]:
        """
        Decode a CAN message into individual signal values.
        
        Args:
            msg: Raw CAN message to decode
            
        Returns:
            List of decoded signals. Empty if message ID not in DBC.
        """
        dbc_msg = self._message_by_id.get(msg.arbitration_id)
        
        if dbc_msg is None:
            return []
        
        decoded_signals = []
        
        try:
            # cantools decode returns dict of signal_name -> value
            decoded = dbc_msg.decode(msg.data, decode_choices=False)
            
            for signal_name, physical_value in decoded.items():
                # Find signal definition for metadata
                sig = next(
                    (s for s in dbc_msg.signals if s.name == signal_name),
                    None
                )
                
                if sig is None:
                    continue
                
                # Calculate raw value from physical
                # physical = raw * factor + offset
                # raw = (physical - offset) / factor
                if sig.scale != 0:
                    raw_value = int((physical_value - sig.offset) / sig.scale)
                else:
                    raw_value = int(physical_value)
                
                decoded_signal = DecodedSignal(
                    timestamp=msg.timestamp,
                    message_name=dbc_msg.name,
                    message_id=msg.arbitration_id,
                    signal_name=signal_name,
                    raw_value=raw_value,
                    physical_value=float(physical_value),
                    unit=sig.unit or "",
                )
                decoded_signals.append(decoded_signal)
                
        except Exception as e:
            logger.debug(
                f"Decode error for 0x{msg.arbitration_id:03X}: {e}"
            )
        
        return decoded_signals
    
    def get_cache_key(self) -> str:
        """
        Generate unique cache key for this DBC file.
        
        Returns:
            Unique string identifier for caching
        """
        stat = self.dbc_path.stat()
        return f"{self.dbc_path.name}_{stat.st_size}_{stat.st_mtime_ns}"

