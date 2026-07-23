from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ..store import ContractStore, UnsupportedDatabaseSchema
from .routes import router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ContractStore().initialize()
    yield


app = FastAPI(title="GP Contract Kernel", version="3.0.0", lifespan=lifespan)
app.include_router(router)


@app.exception_handler(UnsupportedDatabaseSchema)
async def unsupported_schema_handler(_, exc: UnsupportedDatabaseSchema):
    return JSONResponse(status_code=503, content={"error": str(exc)})
