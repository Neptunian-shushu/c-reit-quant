from dataclasses import dataclass
from typing import Optional


@dataclass
class ReitMaster:
    symbol: str
    name: str
    exchange: str
    asset_type: str
    listing_date: Optional[str] = None
    sponsor: Optional[str] = None
    manager: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None


@dataclass
class OperatingObservation:
    symbol: str
    period_end: str
    metric: str
    value: float
    unit: str
    source_document: str
    publication_date: Optional[str] = None
