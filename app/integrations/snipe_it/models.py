from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class SnipeItAsset(BaseModel):
    """Normalized read-only Snipe-IT asset fields used by synchronization and reporting."""

    model_config = ConfigDict(extra="forbid")

    asset_id: int = Field(gt=0)
    asset_tag: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    serial: str | None = Field(default=None, max_length=255)
    model_id: int | None = Field(default=None, gt=0)
    model: str | None = Field(default=None, max_length=255)
    category_id: int | None = Field(default=None, gt=0)
    category: str | None = Field(default=None, max_length=255)
    manufacturer_id: int | None = Field(default=None, gt=0)
    manufacturer: str | None = Field(default=None, max_length=255)
    company_id: int | None = Field(default=None, gt=0)
    company: str | None = Field(default=None, max_length=255)
    status_label_id: int | None = Field(default=None, gt=0)
    status_label: str | None = Field(default=None, max_length=255)
    status_type: str | None = Field(default=None, max_length=64)
    assigned_to_id: int | None = Field(default=None, gt=0)
    assigned_type: str | None = Field(default=None, max_length=64)
    location_id: int | None = Field(default=None, gt=0)
    location: str | None = Field(default=None, max_length=255)
    purchase_date: date | None = None
    warranty_months: int | None = Field(default=None, ge=0, le=1200)
    warranty_expires: date | None = None


class SnipeItActivity(BaseModel):
    """Normalized read-only Snipe-IT asset activity used by the Grafana activity panel."""

    model_config = ConfigDict(extra="forbid")

    activity_id: int = Field(gt=0)
    action: str = Field(min_length=1, max_length=128)
    asset: str | None = Field(default=None, max_length=512)
    target: str | None = Field(default=None, max_length=512)
    performed_by: str | None = Field(default=None, max_length=256)
    location: str | None = Field(default=None, max_length=255)
    occurred_at: str = Field(min_length=1, max_length=128)
