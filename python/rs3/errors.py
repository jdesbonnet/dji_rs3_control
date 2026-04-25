"""Domain-specific errors for RS3 control."""


class RS3Error(Exception):
    """Base error for library consumers."""


class ConnectionError(RS3Error):
    """Raised when BLE connection or setup fails."""


class ProtocolError(RS3Error):
    """Raised when protocol encoding or decoding fails."""
