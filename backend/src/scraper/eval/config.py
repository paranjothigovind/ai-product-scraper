from pydantic import BaseModel, Field


class EvalConfig(BaseModel):
    """All evaluation knobs in one place."""

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "schema_validity": 0.25,
            "field_coverage": 0.25,
            "plausibility": 0.20,
            "volume": 0.20,
            "groundedness": 0.10,
        }
    )
    key_fields: tuple[str, ...] = ("name", "price", "url", "image")
    # TODO(next): replace with the per-site observed page size once discovery exists.
    page_size_heuristic: int = 20
    name_length: tuple[int, int] = (3, 200)
    # Without a groundedness check the score cannot claim more than this.
    ungrounded_ceiling: float = 0.9
    high_confidence_score: float = 0.85
