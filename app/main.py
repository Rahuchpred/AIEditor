from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.reel_routes import router as reel_router
from app.api.routes import router
from app.errors import ServiceError


def create_app(container=None) -> FastAPI:
    app = FastAPI(title="AIEdit Feature 4 API")
    app.state.container = container
    app.include_router(router)
    app.include_router(reel_router)

    @app.exception_handler(ServiceError)
    async def handle_service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": {"code": exc.code, "message": exc.message}},
        )

    return app


app = create_app()
