from ipaddress import ip_address

from app.correlation.models import DeviceObservation


def normalize_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    return normalized or None


def normalize_hostname(value: str | None) -> str | None:
    normalized = normalize_identifier(value)
    if normalized is None:
        return None
    normalized = normalized.rstrip(".")
    return normalized or None


def normalize_stable_ip(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = ip_address(value.strip())
    except ValueError:
        return None
    if parsed.is_unspecified or parsed.is_loopback or parsed.is_multicast or parsed.is_link_local:
        return None
    return parsed.compressed


def normalized_identifiers(observation: DeviceObservation) -> dict[str, str]:
    values = {
        "name": normalize_identifier(observation.name),
        "hostname": normalize_hostname(observation.hostname),
        "stable_ip": normalize_stable_ip(observation.stable_ip),
        "serial": normalize_identifier(observation.serial),
        "asset_tag": normalize_identifier(observation.asset_tag),
        "os": normalize_identifier(observation.os),
        "device_type": normalize_identifier(observation.device_type),
        "location": normalize_identifier(observation.location),
    }
    return {key: value for key, value in values.items() if value is not None}
