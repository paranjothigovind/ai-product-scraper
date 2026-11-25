from collections.abc import Sequence
from typing import Any

from scraper.graph import RunLimits
from scraper.graph.state import GraphState
from scraper.llm.extractor import ExtractedProduct, ExtractionResult
from tests.support import BASE, ScriptedSite, paged_site
from tests.test_graph import LIST, Harness, request, result_of

# Above the evaluator's score for a result that misses products, at the 0.9 ceiling for an
# ungrounded result.
STRICT = 0.9
STRICT_LIMITS = RunLimits(min_quality=STRICT)

PAGE = f"""<html><body>
<a href="{BASE}/p/1">Blue Mug</a> $12.50
<a href="{BASE}/p/2">Red Mug</a> $9.00
<a href="{BASE}/p/3">Green Mug</a> $11.00
</body></html>"""


def poor() -> list[ExtractedProduct]:
    """Only one of the three products on the page: a volume shortfall the evaluator flags."""
    return [
        ExtractedProduct(name="Blue Mug", url=f"{BASE}/p/1", price=11.0, image=f"{BASE}/img/1.jpg")
    ]


def good() -> list[ExtractedProduct]:
    return [
        ExtractedProduct(
            name=f"{c} Mug", url=f"{BASE}/p/{i}", price=10.0 + i, image=f"{BASE}/img/{i}.jpg"
        )
        for i, c in enumerate(["Blue", "Red", "Green"], 1)
    ]


class Scripted:
    """Returns the next scripted answer per call; remembers what it was asked."""

    def __init__(
        self, name: str, answers: Sequence[list[ExtractedProduct]], tokens: int = 10
    ) -> None:
        self.name = name
        self.answers = list(answers)
        self.feedbacks: list[str] = []
        self.tokens = tokens

    async def extract(
        self, text: str, *, page_url: str | None, feedback: str = ""
    ) -> ExtractionResult:
        self.feedbacks.append(feedback)
        products = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return ExtractionResult(products=products, tokens_in=self.tokens, tokens_out=self.tokens)


def trace_of(state: GraphState, node: str) -> list[dict[str, Any]]:
    return [t for t in state["trace"] if t["node"] == node]


async def test_good_first_pass_is_not_retried() -> None:
    ex = Scripted("base", [good()])
    h = Harness(ScriptedSite({LIST: PAGE}), extractor=ex, limits=RunLimits(min_quality=STRICT))
    state = await h.run(request(3))
    assert len(ex.feedbacks) == 1
    assert state["retries"] == 0
    assert trace_of(state, "retry_extract") == []


async def test_poor_result_is_retried_with_feedback_and_improves() -> None:
    ex = Scripted("base", [poor(), good()])
    h = Harness(ScriptedSite({LIST: PAGE}), extractor=ex, limits=STRICT_LIMITS)
    state = await h.run(request(3))
    assert state["retries"] == 1
    assert ex.feedbacks[0] == "" and ex.feedbacks[1] != ""
    assert result_of(state)["evaluation"]["decision"] == "accept"
    prices = {p["name"]: p["price"] for p in result_of(state)["products"]}
    assert prices  # retry products merged, nothing lost
    assert len(result_of(state)["products"]) == 3
    assert trace_of(state, "retry_extract")[0]["meta"]["escalated"] is False


async def test_second_retry_escalates_to_the_stronger_model() -> None:
    base = Scripted("base", [poor()])
    strong = Scripted("strong", [good()])
    h = Harness(
        ScriptedSite({LIST: PAGE}),
        extractor=base,
        escalation_extractor=strong,
        limits=STRICT_LIMITS,
    )
    state = await h.run(request(3))
    assert state["retries"] == 2
    assert len(base.feedbacks) == 2  # first pass + retry 1
    assert len(strong.feedbacks) == 1  # retry 2
    assert [t["meta"]["escalated"] for t in trace_of(state, "retry_extract")] == [False, True]
    assert result_of(state)["evaluation"]["decision"] == "accept"


async def test_retries_stop_at_max_retries() -> None:
    ex = Scripted("base", [poor()])
    h = Harness(
        ScriptedSite({LIST: PAGE}),
        extractor=ex,
        limits=RunLimits(max_retries=1, min_quality=STRICT),
    )
    state = await h.run(request(3))
    assert state["retries"] == 1
    assert len(ex.feedbacks) == 2
    assert result_of(state)["evaluation"]["decision"] == "low_confidence"
    assert len(result_of(state)["products"]) == 1  # still returned, flagged low confidence


async def test_zero_retries_configured_means_no_retry() -> None:
    ex = Scripted("base", [poor()])
    h = Harness(
        ScriptedSite({LIST: PAGE}),
        extractor=ex,
        limits=RunLimits(max_retries=0, min_quality=STRICT),
    )
    state = await h.run(request(3))
    assert len(ex.feedbacks) == 1 and state["retries"] == 0


async def test_empty_first_pass_gets_a_retry() -> None:
    ex = Scripted("base", [[], good()])
    h = Harness(ScriptedSite({LIST: PAGE}), extractor=ex, limits=STRICT_LIMITS)
    state = await h.run(request(3))
    assert state["retries"] == 1
    assert len(result_of(state)["products"]) == 3


async def test_structured_data_pages_are_never_retried() -> None:
    ex = Scripted("base", [poor()])
    h = Harness(paged_site([[1, 2, 3]]), extractor=ex)
    state = await h.run(request(3))
    assert ex.feedbacks == [] and state["retries"] == 0


async def test_no_extractor_means_no_retry() -> None:
    h = Harness(ScriptedSite({LIST: PAGE}))
    state = await h.run(request(3))
    assert state["retries"] == 0 and trace_of(state, "retry_extract") == []


async def test_token_budget_blocks_a_retry() -> None:
    ex = Scripted("base", [poor()], tokens=300)
    h = Harness(
        ScriptedSite({LIST: PAGE}),
        extractor=ex,
        limits=RunLimits(max_tokens_per_run=500, min_quality=STRICT),
    )
    state = await h.run(request(3))
    assert len(ex.feedbacks) == 1  # 600 tokens spent on the first pass; no budget left
    assert state["retries"] == 0
