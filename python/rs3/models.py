"""Shared public data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic


@dataclass(frozen=True)
class Pose:
    """Angular pose in degrees."""

    tilt_deg: float
    roll_deg: float
    pan_deg: float


@dataclass(frozen=True)
class VelocityCommand:
    """Semantic velocity request in normalized axis units."""

    tilt: float = 0.0
    roll: float = 0.0
    pan: float = 0.0


@dataclass(frozen=True)
class Waypoint:
    """Absolute target pose in degrees."""

    tilt_deg: float
    pan_deg: float
    roll_deg: float = 0.0
    dwell_s: float | None = None


@dataclass(frozen=True)
class TelemetrySnapshot:
    """Latest decoded telemetry."""

    pose: Pose | None = None
    pose_timestamp: float | None = None
    battery_or_status: float | None = None
    raw_0d02: tuple[int, int, int, int] | None = None
    raw_0466: dict[int, int] = field(default_factory=dict)
    timestamp: float = field(default_factory=monotonic)
