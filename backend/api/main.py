"""UASAE API — FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.api.routes.projects import router as projects_router
from backend.api.routes.verification import router as verification_router
from backend.api.routes.execution import router as execution_router

app = FastAPI(
    title="UASAE",
    description="Universal Autonomous Software Assurance Engine",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router)
app.include_router(verification_router)
app.include_router(execution_router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "uasae", "env": settings.app_env}
