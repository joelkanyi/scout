"""FastAPI main app — mounts all routers, serves bundled frontend."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from src.api.applications import router as applications_router
from src.api.auth import APITokenMiddleware, get_or_create_token
from src.api.data_management import router as data_management_router
from src.api.jobs import router as jobs_router
from src.api.preferences import router as preferences_router
from src.api.resume import router as resume_router
from src.api.scheduler import router as scheduler_router
from src.api.settings import router as settings_router
from src.database import init_db

app = FastAPI(title="Scout API", version="0.1.0")

# Security: CORS restricted to localhost only
# Combined with bearer token auth, this prevents CSRF attacks since
# browsers won't send custom Authorization headers cross-origin.
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security: require bearer token for all /api/ endpoints
app.add_middleware(APITokenMiddleware)


@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception):
    """Return a clear message on any unhandled error instead of a blank 500."""
    import logging
    import traceback

    logging.getLogger("scout.api").error(
        "Unhandled error on %s %s:\n%s", request.method, request.url.path, traceback.format_exc()
    )
    return JSONResponse(status_code=500, content={"detail": f"Something went wrong: {exc}"})

# --- API routers (must come before SPA catch-all) ---
app.include_router(jobs_router, prefix="/api")
app.include_router(applications_router, prefix="/api")
app.include_router(resume_router, prefix="/api")
app.include_router(preferences_router, prefix="/api")
app.include_router(scheduler_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(data_management_router, prefix="/api")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/auth/token")
def get_token():
    """Return the API token for the local UI to use.

    This endpoint is public (no auth required) because the UI needs
    the token to authenticate subsequent requests. Only accessible
    from localhost via CORS restriction.
    """
    return {"token": get_or_create_token()}


# --- Bundled frontend (only when built) ---
STATIC_DIR = Path(__file__).parent / "static"

if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    # Mount Vite's assets directory (JS/CSS bundles with hashed names)
    if (STATIC_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="static-assets")

    @app.get("/{full_path:path}")
    async def spa_catch_all(full_path: str):
        """Serve static files or fall back to index.html for SPA routing."""
        file_path = STATIC_DIR / full_path
        if full_path and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(STATIC_DIR / "index.html"))
