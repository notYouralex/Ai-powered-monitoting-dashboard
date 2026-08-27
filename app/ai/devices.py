import re

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.ai.models import AICorrelatedDeviceEvidence
from app.contracts import IntegrationSource
from app.db.models import Device, DeviceSourceLink


_MAX_QUESTION_WORDS = 20
_MAX_PHRASES = 64
_SOURCE_ORDER: tuple[IntegrationSource, ...] = (
    "wazuh",
    "zabbix",
    "snipe_it",
    "freshservice",
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")


class AIDeviceRepository:
    """Read only minimal correlated-device identity for bounded AI question routing."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def find_matches(
        self,
        question: str,
        *,
        limit: int = 3,
    ) -> list[AICorrelatedDeviceEvidence]:
        if limit < 1 or limit > 3:
            raise ValueError("AI device match limit must be between 1 and 3")

        phrases = _candidate_phrases(question)
        if not phrases:
            return []

        statement = (
            select(Device)
            .options(selectinload(Device.source_links))
            .where(
                or_(
                    func.lower(Device.canonical_name).in_(phrases),
                    func.lower(Device.hostname).in_(phrases),
                    func.lower(Device.ip).in_(phrases),
                    func.lower(Device.serial).in_(phrases),
                    func.lower(Device.asset_tag).in_(phrases),
                )
            )
            .order_by(Device.id)
            .limit(limit)
        )
        devices = self._db.scalars(statement).all()
        return [_to_evidence(device) for device in devices]

    def get_source_record_id(
        self,
        device_id: int,
        source: IntegrationSource,
    ) -> str | None:
        """Resolve an internal source record identifier without exposing it to AI evidence."""

        return self._db.scalar(
            select(DeviceSourceLink.source_record_id)
            .where(
                DeviceSourceLink.device_id == device_id,
                DeviceSourceLink.source == source,
            )
            .order_by(DeviceSourceLink.id)
            .limit(1)
        )


def _candidate_phrases(question: str) -> list[str]:
    words = [match.group(0).casefold() for match in _TOKEN_RE.finditer(question)][
        :_MAX_QUESTION_WORDS
    ]
    phrases: list[str] = []
    seen: set[str] = set()
    for size in range(1, 5):
        for index in range(0, len(words) - size + 1):
            phrase = " ".join(words[index : index + size])
            if len(phrase) < 3 or phrase in seen:
                continue
            seen.add(phrase)
            phrases.append(phrase)
            if len(phrases) >= _MAX_PHRASES:
                return phrases
    return phrases


def _to_evidence(device: Device) -> AICorrelatedDeviceEvidence:
    linked = {
        link.source
        for link in device.source_links
        if link.source in _SOURCE_ORDER
    }
    return AICorrelatedDeviceEvidence(
        device_id=device.id,
        canonical_name=device.canonical_name,
        hostname=device.hostname,
        asset_tag=device.asset_tag,
        correlation_confidence=device.correlation_confidence,
        linked_sources=[source for source in _SOURCE_ORDER if source in linked],
    )
