from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.middleware import access_log
from app.api.routes import chat, feedback, health
from app.api.routes.channels import include_channel_routers
from app.core import observability
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.rate_limit import limiter


@asynccontextmanager
async def lifespan(_: FastAPI):
    observability.init_observability(get_settings())
    yield
    observability.flush()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    settings.check_channels()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.middleware("http")(access_log)

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.include_router(health.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(feedback.router, prefix="/api")
    include_channel_routers(app, settings)
    if settings.eval_enabled:
        # Imported here so the deployed app never loads the evaluator.
        from app.api.routes import evals

        app.include_router(evals.router, prefix="/api")

    # Last: serves frontend/dist with SPA fallback; API routes above take priority.
    app.frontend("/", directory=settings.frontend_dist, check_dir="auto")
    return app


app = create_app()
