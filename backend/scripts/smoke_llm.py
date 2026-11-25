"""Live check of the LLM extraction path against the configured provider.

Runs the real graph on a saved page that has no JSON-LD, so the LLM is the only source of
products. Makes one or a few real API calls (a small cost).

    uv run python scripts/smoke_llm.py [path/to/page.html] [max_products]
"""

import asyncio
import sys
import uuid
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # for the test doubles in tests/support.py

from tests.support import MemoryStore, ScriptedSite  # noqa: E402

from scraper.core.config import load_settings  # noqa: E402
from scraper.graph import GraphDeps, RunLimits, build_graph, run_graph  # noqa: E402
from scraper.html.decode import decode_html  # noqa: E402
from scraper.llm import build_extractor  # noqa: E402
from scraper.schemas.request import ScrapeRequest  # noqa: E402


async def main() -> None:
    page = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests/fixtures/books_page.html"
    max_products = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    settings = load_settings()
    print(f"provider={settings.llm_provider} model={settings.model_extract}")

    # Serve the page at a real-looking URL so links resolve and the model can see them.
    html = decode_html(page.read_bytes())
    site = ScriptedSite({"https://books.test/list": html})
    deps = GraphDeps(
        fetch=site.fetch,
        store=MemoryStore(),
        limits=RunLimits.from_settings(settings),
        extractor=build_extractor(settings),
    )
    graph = build_graph(deps, MemorySaver())
    request = ScrapeRequest.model_validate(
        {"url": "https://books.test/list", "max_products": max_products}
    )
    state = await run_graph(graph, str(uuid.uuid4()), request, deps.limits)

    result = state["result"]
    budget = state["budget"]
    print(
        f"confidence={result['confidence']} incomplete={result['incomplete']} "
        f"reason={result['incomplete_reason']} stop_reason={state.get('stop_reason')}"
    )
    print(f"tokens in/out: {budget['tokens_in']}/{budget['tokens_out']}")
    print(f"validation: {state['validation']}")
    print(f"errors: {state.get('errors')}")
    llm = [t for t in state["trace"] if t["node"] == "extract"]
    print(f"extract meta: {[t['meta'] for t in llm]}")
    ev = state["evaluation"]
    print(f"quality score={ev['score']:.2f} decision={ev['decision']} issues={ev['issues']}")
    for p in result["products"]:
        print(f"  #{p['rank']} {p['name'][:50]!r} price={p['price']} url={p['url']}")


if __name__ == "__main__":
    asyncio.run(main())
