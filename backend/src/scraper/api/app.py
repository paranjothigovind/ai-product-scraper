import logging
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine

from scraper.api.schemas import TERMINAL, Accepted, RunOut
from scraper.core.config import load_settings
from scraper.db.repo import SessionFactory, get_run, list_categories, list_products
from scraper.db.session import create_session_factory
from scraper.queue import enqueue, request_cancel
from scraper.schemas.request import ScrapeRequest

log = logging.getLogger("scraper.api")

# Single tenant until real authentication exists: every run belongs to this user.
LOCAL_USER = "local"
MAX_IDEMPOTENCY_KEY = 200


def create_app(
    sessions: SessionFactory,
    *,
    api_token: str | None = None,
    plan_cap: int = 500,
    cors_origins: Sequence[str] = (),
    dispose: Callable[[], Awaitable[None]] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if dispose:
            await dispose()

    app = FastAPI(title="AI Product Scraper", version="0.1.0", lifespan=lifespan)
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )

    def current_user(authorization: Annotated[str | None, Header()] = None) -> str:
        if api_token is not None:
            scheme, _, token = (authorization or "").partition(" ")
            if scheme.lower() != "bearer" or not secrets.compare_digest(
                token.encode(), api_token.encode()
            ):
                raise HTTPException(401, "invalid or missing token", {"WWW-Authenticate": "Bearer"})
        return LOCAL_USER

    user_dep = Depends(current_user)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/scrapes", status_code=202, response_model=Accepted)
    async def create_scrape(
        response: Response,
        body: Annotated[dict[str, Any], Body()],
        user: Annotated[str, user_dep],
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> Accepted:
        if idempotency_key is not None and not 0 < len(idempotency_key) <= MAX_IDEMPOTENCY_KEY:
            raise HTTPException(422, f"Idempotency-Key must be 1-{MAX_IDEMPOTENCY_KEY} characters")
        try:
            request = ScrapeRequest.model_validate(body, context={"plan_cap": plan_cap})
        except ValidationError as exc:
            # Never echo the input back: it can hold up to 1 MB of the caller's HTML.
            raise HTTPException(
                422, exc.errors(include_input=False, include_url=False, include_context=False)
            ) from None
        if not request.url and not request.html:
            raise HTTPException(422, "provide either url or html")
        run_id, created = await enqueue(
            sessions, user_id=user, request=request, idempotency_key=idempotency_key
        )
        response.headers["Location"] = f"/v1/scrapes/{run_id}"
        if not created:
            response.status_code = 200
        return Accepted(id=run_id, status="queued" if created else "existing", created=created)

    async def load_run(run_id: uuid.UUID, user: str) -> RunOut:
        async with sessions() as session:
            run = await get_run(session, user_id=user, run_id=run_id)
            if run is None:
                raise HTTPException(404, "run not found")
            if run.status not in TERMINAL:
                return RunOut.from_row(run)
            products = await list_products(session, user_id=user, run_id=run_id)
            categories = await list_categories(session, user_id=user, run_id=run_id)
            return RunOut.from_row(run, products, categories)

    @app.get("/v1/scrapes/{run_id}", response_model=RunOut)
    async def read_scrape(run_id: uuid.UUID, user: Annotated[str, user_dep]) -> RunOut:
        return await load_run(run_id, user)

    @app.post("/v1/scrapes/{run_id}/cancel", response_model=RunOut)
    async def cancel_scrape(run_id: uuid.UUID, user: Annotated[str, user_dep]) -> RunOut:
        if await request_cancel(sessions, user_id=user, run_id=run_id) is None:
            raise HTTPException(404, "run not found")
        return await load_run(run_id, user)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Details go to the server log, not to the caller.
        log.error("unhandled error", exc_info=exc)
        return JSONResponse({"detail": "internal error"}, status_code=500)

    return app


def create_app_from_env() -> FastAPI:
    """Entry point for uvicorn: `uvicorn scraper.api.app:create_app_from_env --factory`."""
    settings = load_settings()
    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    return create_app(
        create_session_factory(engine),
        api_token=settings.api_token.get_secret_value() if settings.api_token else None,
        plan_cap=settings.plan_cap_products,
        cors_origins=settings.cors_origins,
        dispose=engine.dispose,
    )
