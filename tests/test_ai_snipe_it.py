from datetime import date, datetime, timezone

from app.ai.snipe_it import AISnipeItRepository
from app.db.models import Asset


NOW = datetime(2026, 8, 27, 1, 0, tzinfo=timezone.utc)


def asset(
    asset_id: int,
    *,
    asset_tag: str | None,
    name: str,
    category: str,
    status_label: str,
    assigned_to_id: int | None,
    location: str,
    warranty_expires: date | None,
    serial: str = "SENSITIVE-SERIAL",
    model: str = "ThinkPad T14",
    manufacturer: str = "Lenovo",
) -> Asset:
    return Asset(
        source_asset_id=asset_id,
        asset_tag=asset_tag,
        name=name,
        serial=serial,
        model=model,
        category=category,
        manufacturer=manufacturer,
        status_label=status_label,
        assigned_to_id=assigned_to_id,
        location=location,
        purchase_date=date(2024, 1, 15),
        warranty_months=36,
        warranty_expires=warranty_expires,
        synced_at=NOW,
    )


def seed_assets(auth_env) -> None:
    with auth_env.session_factory() as db:
        db.add_all(
            [
                asset(
                    1,
                    asset_tag="LT-001",
                    name="Finance Laptop",
                    category="Laptop",
                    status_label="Deployed",
                    assigned_to_id=101,
                    location="Main Office",
                    warranty_expires=date(2026, 8, 20),
                ),
                asset(
                    2,
                    asset_tag=None,
                    name="Spare Laptop",
                    category="Laptop",
                    status_label="Ready to Deploy",
                    assigned_to_id=None,
                    location="Main Office",
                    warranty_expires=date(2026, 9, 10),
                ),
                asset(
                    3,
                    asset_tag="MON-003",
                    name="Reception Monitor",
                    category="Monitor",
                    status_label="In repair",
                    assigned_to_id=None,
                    location="Branch Office",
                    warranty_expires=date(2027, 6, 1),
                    model="P2422H",
                    manufacturer="Dell",
                ),
                asset(
                    4,
                    asset_tag="PC-004",
                    name="Old Desktop",
                    category="Desktop",
                    status_label="Retired",
                    assigned_to_id=None,
                    location="Warehouse",
                    warranty_expires=None,
                    model="ProDesk",
                    manufacturer="HP",
                ),
            ]
        )
        db.commit()


def test_snipe_it_ai_repository_filters_expired_warranty_without_sensitive_fields(auth_env) -> None:
    seed_assets(auth_env)

    with auth_env.session_factory() as db:
        result = AISnipeItRepository(db).asset_details_for_question(
            "Which assets have expired warranties?",
            end=NOW,
        )

    assert result is not None
    assert result.matching_count == 1
    assert result.truncated is False
    assert [row.asset_tag for row in result.assets] == ["LT-001"]
    row = result.assets[0]
    assert row.name == "Finance Laptop"
    assert row.category == "Laptop"
    assert row.status_label == "Deployed"
    assert row.location == "Main Office"
    assert row.is_assigned is True
    assert row.warranty_state == "expired"
    serialized = result.model_dump_json()
    assert "SENSITIVE-SERIAL" not in serialized
    assert "serial" not in serialized
    assert "assigned_to_id" not in serialized
    assert "source_asset_id" not in serialized


def test_snipe_it_ai_repository_supports_asset_tag_assignment_and_location_filters(auth_env) -> None:
    seed_assets(auth_env)

    with auth_env.session_factory() as db:
        repository = AISnipeItRepository(db)
        missing_tag = repository.asset_details_for_question(
            "Which laptops are missing asset tags?",
            end=NOW,
        )
        unassigned_office = repository.asset_details_for_question(
            "What unassigned assets are at Main Office?",
            end=NOW,
        )
        expiring = repository.asset_details_for_question(
            "Which assets have warranties expiring soon?",
            end=NOW,
        )

    assert missing_tag is not None
    assert missing_tag.matching_count == 1
    assert missing_tag.assets[0].name == "Spare Laptop"
    assert missing_tag.assets[0].missing_asset_tag is True
    assert unassigned_office is not None
    assert unassigned_office.matching_count == 1
    assert unassigned_office.assets[0].name == "Spare Laptop"
    assert unassigned_office.assets[0].is_assigned is False
    assert expiring is not None
    assert expiring.matching_count == 1
    assert expiring.assets[0].name == "Spare Laptop"
    assert expiring.assets[0].warranty_state == "expiring_soon"


def test_snipe_it_ai_repository_prioritizes_bounded_assets_needing_attention(auth_env) -> None:
    seed_assets(auth_env)

    with auth_env.session_factory() as db:
        result = AISnipeItRepository(db).asset_details_for_question(
            "Which assets need attention first?",
            end=NOW,
            limit=2,
        )

    assert result is not None
    assert result.matching_count == 3
    assert len(result.assets) == 2
    assert result.truncated is True
    assert result.assets[0].name == "Finance Laptop"
    assert result.assets[0].warranty_state == "expired"


def test_snipe_it_ai_repository_does_not_load_details_for_count_only_question(auth_env) -> None:
    seed_assets(auth_env)

    with auth_env.session_factory() as db:
        result = AISnipeItRepository(db).asset_details_for_question(
            "How many assets are unassigned?",
            end=NOW,
        )

    assert result is None
