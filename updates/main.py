from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging

from api.v1.middleware.settings import get_settings
from api.v1.routes import router as v1_router
from api.v1.middleware.auth_middleware import AuthMiddleware
from api.v1.middleware.get_connection import get_connection_pool
from api.v1.middleware.get_schema_path import get_schema
from api.v1.middleware.lkp_tables import warm_cache

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()

    # Attempt to initialize connection pool but don't crash if it fails
    try:
        get_connection_pool()
        logger.info("Database connection pool initialized successfully")

        # Build the lookup-table registry once at startup so the first
        # request doesn't pay for it. Swallows its own errors.
        warm_cache(get_schema())
    except ConnectionError as e:
        logger.warning(f"Database connection pool failed to initialize: {e}")
        logger.warning("Service will start but database operations will fail until connection is restored")
    except Exception as e:
        logger.error(f"Unexpected error initializing connection pool: {e}")
        logger.warning("Service will start but database operations may fail")

    yield


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    # Must be registered inside the factory. Previously this ran on the
    # module-level `app` after create_app() returned, which meant anything
    # calling create_app() directly -- a test fixture, typically -- got an
    # app with no auth middleware at all.
    app.add_middleware(AuthMiddleware)

    # Everything in v1_router will appear under /v1/...
    app.include_router(v1_router, prefix="/v1", tags=["v1"])

    return app


app = create_app()
