from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class PrequalResult:
    raw_xml: str
    result_code: Optional[str] = None
    result_description: Optional[str] = None
    score: Optional[int] = None
    tier: Optional[str] = None
    score_range: Optional[str] = None
    iframe_url: Optional[str] = None
    token: Optional[str] = None
    transid: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)
