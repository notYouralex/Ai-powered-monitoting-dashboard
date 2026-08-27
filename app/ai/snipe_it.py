import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.ai.models import AISnipeItAssetEvidence, AISnipeItAssetSetEvidence
from app.db.models import Asset


_SNIPE_IT_TIMEZONE = ZoneInfo("Asia/Manila")
_WARRANTY_EXPIRING_DAYS = 90
_COUNT_TERMS = ("how many", "count", "number of")
_ASSET_TERMS = (
    "asset",
    "assets",
    "device",
    "devices",
    "laptop",
    "laptops",
    "desktop",
    "desktops",
    "monitor",
    "monitors",
    "inventory",
    "warranty",
    "warranties",
)
_SEARCH_STOP_WORDS = {
    "a",
    "about",
    "an",
    "any",
    "are",
    "asset",
    "assets",
    "assigned",
    "at",
    "attention",
    "available",
    "device",
    "devices",
    "expired",
    "expiring",
    "first",
    "have",
    "inventory",
    "is",
    "list",
    "maintenance",
    "missing",
    "need",
    "needs",
    "of",
    "ready",
    "repair",
    "retired",
    "show",
    "soon",
    "status",
    "tag",
    "tags",
    "the",
    "to",
    "unassigned",
    "warranty",
    "warranties",
    "what",
    "which",
    "with",
    "without",
}
_WORD_RE = re.compile(r"[a-z0-9]+")


class AISnipeItRepository:
    """Read-only bounded asset evidence from normalized synchronized Snipe-IT records."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def asset_details_for_question(
        self,
        question: str,
        *,
        end: datetime,
        limit: int = 20,
    ) -> AISnipeItAssetSetEvidence | None:
        if limit < 1 or limit > 20:
            raise ValueError("Snipe-IT AI asset detail limit must be between 1 and 20")
        if not _is_asset_detail_question(question):
            return None

        local_today = end.astimezone(_SNIPE_IT_TIMEZONE).date()
        criteria = _asset_filter_criteria(question, local_today=local_today)
        search_terms = _search_terms(question)
        searchable_columns = (
            Asset.asset_tag,
            Asset.name,
            Asset.model,
            Asset.manufacturer,
            Asset.category,
            Asset.status_label,
            Asset.location,
        )
        for term in search_terms:
            criteria.append(
                or_(*[column.ilike(f"%{term}%") for column in searchable_columns])
            )

        matching_count = self._count(*criteria)
        attention_rank = case(
            (and_(Asset.warranty_expires.is_not(None), Asset.warranty_expires < local_today), 0),
            (or_(Asset.asset_tag.is_(None), func.trim(Asset.asset_tag) == ""), 1),
            (Asset.assigned_to_id.is_(None), 2),
            (func.lower(Asset.status_label).like("%repair%"), 3),
            (func.lower(Asset.status_label).like("%maintenance%"), 3),
            else_=4,
        )
        rows = self._db.scalars(
            select(Asset)
            .where(*criteria)
            .order_by(
                attention_rank,
                Asset.warranty_expires.asc().nulls_last(),
                Asset.source_asset_id,
            )
            .limit(limit)
        ).all()

        assets = [
            _asset_evidence(row, local_today=local_today)
            for row in rows
        ]
        return AISnipeItAssetSetEvidence(
            matching_count=matching_count,
            assets=assets,
            truncated=matching_count > len(assets),
        )

    def _count(self, *criteria) -> int:
        statement = select(func.count()).select_from(Asset)
        if criteria:
            statement = statement.where(*criteria)
        return int(self._db.scalar(statement) or 0)


def _is_asset_detail_question(question: str) -> bool:
    if not _contains_any_term(question, _ASSET_TERMS):
        return False
    if _contains_any_term(question, _COUNT_TERMS):
        return False
    return True


def _asset_filter_criteria(question: str, *, local_today: date) -> list:
    criteria = []
    missing_asset_tag = or_(Asset.asset_tag.is_(None), func.trim(Asset.asset_tag) == "")
    warranty_expired = and_(
        Asset.warranty_expires.is_not(None),
        Asset.warranty_expires < local_today,
    )
    warranty_soon = and_(
        Asset.warranty_expires.is_not(None),
        Asset.warranty_expires >= local_today,
        Asset.warranty_expires <= local_today + timedelta(days=_WARRANTY_EXPIRING_DAYS),
    )
    maintenance = or_(
        func.lower(Asset.status_label).like("%maintenance%"),
        func.lower(Asset.status_label).like("%repair%"),
    )

    if _contains_term(question, "expired warranty") or _contains_term(question, "expired warranties"):
        criteria.append(warranty_expired)
    elif (
        _contains_term(question, "expiring warranty")
        or _contains_term(question, "expiring warranties")
        or _contains_term(question, "warranty expiring")
        or _contains_term(question, "warranties expiring")
    ):
        criteria.append(warranty_soon)

    if _contains_term(question, "unassigned"):
        criteria.append(Asset.assigned_to_id.is_(None))
    elif _contains_term(question, "assigned"):
        criteria.append(Asset.assigned_to_id.is_not(None))

    if (
        _contains_term(question, "missing asset tag")
        or _contains_term(question, "missing asset tags")
        or _contains_term(question, "without asset tag")
        or _contains_term(question, "without asset tags")
    ):
        criteria.append(missing_asset_tag)

    if _contains_term(question, "maintenance") or _contains_term(question, "repair"):
        criteria.append(maintenance)
    if _contains_term(question, "retired"):
        criteria.append(func.lower(Asset.status_label).like("%retired%"))
    if _contains_term(question, "available") or _contains_term(question, "ready to deploy"):
        criteria.append(
            or_(
                func.lower(Asset.status_label).like("%available%"),
                func.lower(Asset.status_label).like("%ready to deploy%"),
            )
        )

    if _contains_term(question, "need attention") or _contains_term(question, "needs attention"):
        active_unassigned = and_(
            Asset.assigned_to_id.is_(None),
            or_(
                Asset.status_label.is_(None),
                ~func.lower(Asset.status_label).like("%retired%"),
            ),
        )
        criteria.append(
            or_(
                warranty_expired,
                warranty_soon,
                missing_asset_tag,
                active_unassigned,
                maintenance,
            )
        )
    return criteria


def _search_terms(question: str) -> list[str]:
    terms: list[str] = []
    for raw_token in _WORD_RE.findall(question.casefold()):
        token = _singularize_asset_word(raw_token)
        if len(token) < 3 or token in _SEARCH_STOP_WORDS or token.isdigit():
            continue
        if token not in terms:
            terms.append(token)
        if len(terms) >= 4:
            break
    return terms


def _singularize_asset_word(value: str) -> str:
    return {
        "laptops": "laptop",
        "desktops": "desktop",
        "monitors": "monitor",
    }.get(value, value)


def _asset_evidence(asset: Asset, *, local_today: date) -> AISnipeItAssetEvidence:
    return AISnipeItAssetEvidence(
        asset_tag=_bounded_text(asset.asset_tag, 255),
        name=_bounded_text(asset.name, 255),
        model=_bounded_text(asset.model, 128),
        manufacturer=_bounded_text(asset.manufacturer, 128),
        category=_bounded_text(asset.category, 128),
        status_label=_bounded_text(asset.status_label, 128),
        location=_bounded_text(asset.location, 128),
        purchase_date=asset.purchase_date,
        warranty_expires=asset.warranty_expires,
        is_assigned=asset.assigned_to_id is not None,
        warranty_state=_warranty_state(asset.warranty_expires, local_today=local_today),
        missing_asset_tag=not bool(asset.asset_tag and asset.asset_tag.strip()),
    )


def _warranty_state(value: date | None, *, local_today: date) -> str:
    if value is None:
        return "unknown"
    if value < local_today:
        return "expired"
    if value <= local_today + timedelta(days=_WARRANTY_EXPIRING_DAYS):
        return "expiring_soon"
    return "active"


def _bounded_text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:limit]


def _contains_any_term(question: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_term(question, term) for term in terms)


def _contains_term(question: str, term: str) -> bool:
    normalized_question = " ".join(_WORD_RE.findall(question.casefold()))
    normalized_term = " ".join(_WORD_RE.findall(term.casefold()))
    return f" {normalized_term} " in f" {normalized_question} "
