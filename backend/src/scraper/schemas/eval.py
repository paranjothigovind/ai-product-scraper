from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Score = Field(ge=0, le=1)
Decision = Literal["accept", "retry", "low_confidence"]


class EvalMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_validity: float = Score
    field_coverage: float = Score
    plausibility: float = Score
    volume: float = Score
    # None when the judge was skipped (budget exhausted or nothing to sample).
    groundedness: float | None = Field(default=None, ge=0, le=1)


class EvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float = Score
    metrics: EvalMetrics
    issues: list[str] = Field(default_factory=list)
    decision: Decision
    feedback: str = ""
