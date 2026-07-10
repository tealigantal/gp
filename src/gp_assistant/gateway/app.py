from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ..core.errors import APIError
from ..core.logging import setup_logging
from .routes import router

setup_logging()

app = FastAPI(title='gp_assistant', version='2.0.0')
app.include_router(router)


@app.exception_handler(APIError)
async def api_error_handler(_, exc: APIError):  # noqa: ANN001
    return JSONResponse(status_code=exc.status_code, content=exc.to_json())


@app.exception_handler(Exception)
async def generic_error_handler(_, exc):  # noqa: ANN001
    return JSONResponse(status_code=500, content={"error": {"message": str(exc)}})
