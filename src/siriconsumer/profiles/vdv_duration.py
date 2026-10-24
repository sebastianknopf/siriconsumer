"""VDV interval conversion helpers for generic SIRI subscription durations."""

from decimal import Decimal, InvalidOperation
import re

_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def _seconds(value: str) -> Decimal:
    match = _DURATION.fullmatch(value)
    if match is None or not any(part is not None for part in match.groupdict().values()):
        raise ValueError(f"Invalid ISO-8601 duration: {value!r}")
    try:
        parts = {name: Decimal(text or "0") for name, text in match.groupdict().items()}
    except InvalidOperation as exc:
        raise ValueError(f"Invalid ISO-8601 duration: {value!r}") from exc
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def _whole_units(value: str, unit_seconds: int, label: str) -> str:
    units = _seconds(value) / unit_seconds
    if units != units.to_integral_value():
        raise ValueError(f"{label} must be a whole number of {unit_seconds}-second units: {value!r}")
    return str(int(units))


def vdv_hysteresis_seconds(value: str) -> str:
    """Map SIRI ChangeBeforeUpdates to VDV Hysterese (seconds)."""
    return _whole_units(value, 1, "change_before_updates")


def vdv_preview_minutes(value: str) -> str:
    """Map SIRI PreviewInterval to VDV Vorschauzeit (minutes)."""
    return _whole_units(value, 60, "preview_interval")
