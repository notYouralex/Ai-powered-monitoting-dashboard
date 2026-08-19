from app.correlation.models import CorrelationMatch, DeviceObservation
from app.correlation.normalize import normalized_identifiers


def match_observations(
    left: DeviceObservation,
    right: DeviceObservation,
) -> CorrelationMatch | None:
    """Return the strongest safe automatic match between two different sources."""

    if left.source == right.source:
        return None

    left_ids = normalized_identifiers(left)
    right_ids = normalized_identifiers(right)

    if _conflicts(left_ids, right_ids, "serial") or _conflicts(
        left_ids, right_ids, "asset_tag"
    ):
        return None

    if _matches(left_ids, right_ids, "serial"):
        return CorrelationMatch(method="serial", confidence=100)
    if _matches(left_ids, right_ids, "asset_tag"):
        return CorrelationMatch(method="asset_tag", confidence=100)

    hostname_conflict = _conflicts(left_ids, right_ids, "hostname")
    if _matches(left_ids, right_ids, "hostname"):
        return CorrelationMatch(method="hostname", confidence=90)

    if not hostname_conflict and _matches(left_ids, right_ids, "stable_ip"):
        return CorrelationMatch(method="stable_ip", confidence=80)

    if hostname_conflict or not _matches(left_ids, right_ids, "name"):
        return None

    secondary_matches = sum(
        _matches(left_ids, right_ids, key)
        for key in ("os", "device_type", "location")
    )
    if secondary_matches < 1:
        return None

    return CorrelationMatch(
        method="combined",
        confidence=min(75, 50 + (secondary_matches * 10)),
    )


def _matches(left: dict[str, str], right: dict[str, str], key: str) -> bool:
    left_value = left.get(key)
    right_value = right.get(key)
    return left_value is not None and left_value == right_value


def _conflicts(left: dict[str, str], right: dict[str, str], key: str) -> bool:
    left_value = left.get(key)
    right_value = right.get(key)
    return left_value is not None and right_value is not None and left_value != right_value
