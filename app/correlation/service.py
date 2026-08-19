from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.contracts import IntegrationSource
from app.correlation.matcher import match_observations
from app.correlation.models import (
    CorrelationDecision,
    CorrelationMatch,
    DeviceObservation,
)
from app.correlation.normalize import normalized_identifiers
from app.db.models import Device, DeviceSourceLink


MAX_CORRELATION_OBSERVATIONS = 5000
MAX_CORRELATION_LINKS = 20000


class CorrelationCapacityError(RuntimeError):
    """Raised when a correlation batch exceeds the bounded in-process limits."""


class ManualMappingNotFound(ValueError):
    """Raised when a manual mapping references a missing canonical device."""


@dataclass(slots=True)
class _CorrelationState:
    links_by_key: dict[tuple[str, str], DeviceSourceLink]
    links_by_device: dict[int, list[DeviceSourceLink]]
    devices_by_id: dict[int, Device]
    indexes: dict[str, dict[str, set[int]]]


class DeviceCorrelationService:
    """Persist deterministic, read-only-source device correlation decisions."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def correlate(
        self,
        observations: Sequence[DeviceObservation],
        *,
        manual_mappings: Mapping[tuple[IntegrationSource, str], int] | None = None,
    ) -> list[CorrelationDecision]:
        if len(observations) > MAX_CORRELATION_OBSERVATIONS:
            raise CorrelationCapacityError(
                f"correlation batch exceeds {MAX_CORRELATION_OBSERVATIONS} observations"
            )

        mappings = manual_mappings or {}
        try:
            state = self._load_state()
            decisions: list[CorrelationDecision] = []
            for observation in observations:
                decision = self._correlate_one(observation, mappings, state)
                decisions.append(decision)
            self._db.commit()
            return decisions
        except Exception:
            self._db.rollback()
            raise

    def _load_state(self) -> _CorrelationState:
        links = list(
            self._db.scalars(
                select(DeviceSourceLink)
                .options(joinedload(DeviceSourceLink.device))
                .order_by(DeviceSourceLink.id)
                .limit(MAX_CORRELATION_LINKS + 1)
            )
        )
        if len(links) > MAX_CORRELATION_LINKS:
            raise CorrelationCapacityError(
                f"correlation store exceeds {MAX_CORRELATION_LINKS} source links"
            )

        links_by_key: dict[tuple[str, str], DeviceSourceLink] = {}
        links_by_device: dict[int, list[DeviceSourceLink]] = defaultdict(list)
        devices_by_id: dict[int, Device] = {}
        indexes = _empty_indexes()

        for link in links:
            links_by_key[(link.source, link.source_record_id)] = link
            links_by_device[link.device_id].append(link)
            devices_by_id[link.device_id] = link.device
            _index_link(indexes, link)

        return _CorrelationState(
            links_by_key=links_by_key,
            links_by_device=dict(links_by_device),
            devices_by_id=devices_by_id,
            indexes=indexes,
        )

    def _correlate_one(
        self,
        observation: DeviceObservation,
        manual_mappings: Mapping[tuple[IntegrationSource, str], int],
        state: _CorrelationState,
    ) -> CorrelationDecision:
        key = (observation.source, observation.source_record_id)
        identifiers = normalized_identifiers(observation)
        existing = state.links_by_key.get(key)
        manual_device_id = manual_mappings.get(key)

        if manual_device_id is not None:
            device = self._resolve_manual_device(manual_device_id, state)
            if existing is not None:
                self._apply_manual_existing_link(
                    existing,
                    device,
                    observation,
                    identifiers,
                    state,
                )
                return CorrelationDecision(
                    source=observation.source,
                    source_record_id=observation.source_record_id,
                    device_id=device.id,
                    method="manual",
                    confidence=100,
                    manual_override=True,
                )
            method = "manual"
            confidence = 100
            manual_override = True
            created_device = False
        elif existing is not None:
            _remove_link_from_indexes(
                state.indexes,
                existing,
                state.links_by_device.get(existing.device_id, []),
            )
            existing.identifiers = identifiers
            existing.last_seen_at = observation.observed_at
            _merge_device_fields(existing.device, observation, identifiers)
            _index_link(state.indexes, existing)
            return CorrelationDecision(
                source=observation.source,
                source_record_id=observation.source_record_id,
                device_id=existing.device_id,
                method="existing_link",
                confidence=existing.confidence,
                manual_override=existing.manual_override,
            )
        else:
            candidate = _best_candidate(observation, identifiers, state)
            if candidate is None:
                device = _new_device(observation, identifiers)
                self._db.add(device)
                self._db.flush()
                state.devices_by_id[device.id] = device
                state.links_by_device.setdefault(device.id, [])
                method = "new_device"
                confidence = 0
                manual_override = False
                created_device = True
            else:
                device, match = candidate
                method = match.method
                confidence = match.confidence
                manual_override = False
                created_device = False

        _merge_device_fields(device, observation, identifiers)
        device.correlation_confidence = max(device.correlation_confidence, confidence)
        link = DeviceSourceLink(
            device_id=device.id,
            source=observation.source,
            source_record_id=observation.source_record_id,
            identifiers=identifiers,
            match_method=method,
            confidence=confidence,
            manual_override=manual_override,
            last_seen_at=observation.observed_at,
        )
        self._db.add(link)
        self._db.flush()

        state.links_by_key[key] = link
        state.links_by_device.setdefault(device.id, []).append(link)
        _index_link(state.indexes, link)

        return CorrelationDecision(
            source=observation.source,
            source_record_id=observation.source_record_id,
            device_id=device.id,
            method=method,
            confidence=confidence,
            created_device=created_device,
            manual_override=manual_override,
        )

    def _resolve_manual_device(
        self,
        device_id: int,
        state: _CorrelationState,
    ) -> Device:
        device = state.devices_by_id.get(device_id) or self._db.get(Device, device_id)
        if device is None:
            raise ManualMappingNotFound(
                f"manual mapping references missing device {device_id}"
            )
        state.devices_by_id[device.id] = device
        state.links_by_device.setdefault(device.id, [])
        return device

    def _apply_manual_existing_link(
        self,
        link: DeviceSourceLink,
        target: Device,
        observation: DeviceObservation,
        identifiers: dict[str, str],
        state: _CorrelationState,
    ) -> None:
        old_device = link.device
        old_device_id = link.device_id
        old_links = state.links_by_device.get(old_device_id, [])
        _remove_link_from_indexes(state.indexes, link, old_links)

        if old_device_id != target.id:
            state.links_by_device[old_device_id] = [
                existing for existing in old_links if existing.id != link.id
            ]
            link.device = target
            link.device_id = target.id
            state.links_by_device.setdefault(target.id, []).append(link)
            _refresh_device_confidence(
                old_device,
                state.links_by_device.get(old_device_id, []),
            )

        link.identifiers = identifiers
        link.match_method = "manual"
        link.confidence = 100
        link.manual_override = True
        link.last_seen_at = observation.observed_at
        _merge_device_fields(target, observation, identifiers)
        target.correlation_confidence = 100
        _index_link(state.indexes, link)


def _best_candidate(
    observation: DeviceObservation,
    identifiers: dict[str, str],
    state: _CorrelationState,
) -> tuple[Device, CorrelationMatch] | None:
    candidate_ids: set[int] = set()
    for key in ("serial", "asset_tag", "hostname", "stable_ip", "name"):
        value = identifiers.get(key)
        if value is not None:
            candidate_ids.update(state.indexes[key].get(value, set()))

    matches: list[tuple[Device, CorrelationMatch]] = []
    for device_id in candidate_ids:
        links = state.links_by_device.get(device_id, [])
        if any(link.source == observation.source for link in links):
            continue
        if _has_strong_identifier_conflict(identifiers, links):
            continue
        best_match: CorrelationMatch | None = None
        for link in links:
            match = match_observations(observation, _observation_from_link(link))
            if match is not None and (
                best_match is None or match.confidence > best_match.confidence
            ):
                best_match = match
        if best_match is not None:
            matches.append((state.devices_by_id[device_id], best_match))

    if not matches:
        return None

    top_confidence = max(match.confidence for _, match in matches)
    top = [item for item in matches if item[1].confidence == top_confidence]
    if len(top) != 1:
        return None
    return top[0]


def _observation_from_link(link: DeviceSourceLink) -> DeviceObservation:
    identifiers = link.identifiers or {}
    return DeviceObservation(
        source=link.source,
        source_record_id=link.source_record_id,
        observed_at=link.last_seen_at,
        name=identifiers.get("name"),
        hostname=identifiers.get("hostname"),
        stable_ip=identifiers.get("stable_ip"),
        serial=identifiers.get("serial"),
        asset_tag=identifiers.get("asset_tag"),
        os=identifiers.get("os"),
        device_type=identifiers.get("device_type"),
        location=identifiers.get("location"),
    )


def _new_device(
    observation: DeviceObservation,
    identifiers: dict[str, str],
) -> Device:
    canonical_name = (
        _clean_display(observation.name)
        or identifiers.get("hostname")
        or _clean_display(observation.serial)
        or _clean_display(observation.asset_tag)
        or f"{observation.source}:{observation.source_record_id}"
    )
    return Device(
        canonical_name=canonical_name,
        hostname=identifiers.get("hostname"),
        ip=identifiers.get("stable_ip"),
        serial=identifiers.get("serial"),
        asset_tag=identifiers.get("asset_tag"),
        os=_clean_display(observation.os),
        device_type=_clean_display(observation.device_type),
        location=_clean_display(observation.location),
        correlation_confidence=0,
    )


def _merge_device_fields(
    device: Device,
    observation: DeviceObservation,
    identifiers: dict[str, str],
) -> None:
    if device.hostname is None:
        device.hostname = identifiers.get("hostname")
    if device.ip is None:
        device.ip = identifiers.get("stable_ip")
    if device.serial is None:
        device.serial = identifiers.get("serial")
    if device.asset_tag is None:
        device.asset_tag = identifiers.get("asset_tag")
    if device.os is None:
        device.os = _clean_display(observation.os)
    if device.device_type is None:
        device.device_type = _clean_display(observation.device_type)
    if device.location is None:
        device.location = _clean_display(observation.location)


def _clean_display(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _has_strong_identifier_conflict(
    identifiers: dict[str, str],
    links: list[DeviceSourceLink],
) -> bool:
    for key in ("serial", "asset_tag"):
        incoming = identifiers.get(key)
        if incoming is None:
            continue
        existing_values = {
            value
            for link in links
            if (value := (link.identifiers or {}).get(key)) is not None
        }
        if any(value != incoming for value in existing_values):
            return True
    return False


def _refresh_device_confidence(
    device: Device,
    links: list[DeviceSourceLink],
) -> None:
    device.correlation_confidence = max(
        (link.confidence for link in links),
        default=0,
    )


def _empty_indexes() -> dict[str, dict[str, set[int]]]:
    return {
        key: defaultdict(set)
        for key in ("serial", "asset_tag", "hostname", "stable_ip", "name")
    }


def _remove_link_from_indexes(
    indexes: dict[str, dict[str, set[int]]],
    link: DeviceSourceLink,
    device_links: list[DeviceSourceLink],
) -> None:
    identifiers = link.identifiers or {}
    for key in indexes:
        value = identifiers.get(key)
        if value is None:
            continue
        if any(
            other.id != link.id
            and (other.identifiers or {}).get(key) == value
            for other in device_links
        ):
            continue
        device_ids = indexes[key].get(value)
        if device_ids is None:
            continue
        device_ids.discard(link.device_id)
        if not device_ids:
            indexes[key].pop(value, None)


def _index_link(
    indexes: dict[str, dict[str, set[int]]],
    link: DeviceSourceLink,
) -> None:
    for key in indexes:
        value = (link.identifiers or {}).get(key)
        if value is not None:
            indexes[key][value].add(link.device_id)
