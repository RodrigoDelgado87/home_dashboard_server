import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .docker_apps import DockerApps
from .metrics import MetricsSampler
from .settings_store import SettingsStore

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
STATIC_DIR = Path(__file__).parent / "static"

store = SettingsStore(DATA_DIR / "settings.json")
sampler = MetricsSampler()
docker_apps = DockerApps(store)


@asynccontextmanager
async def lifespan(_app):
    sampler.start()
    yield
    sampler.stop()


app = FastAPI(title="HomeDash", lifespan=lifespan)


class AppPatch(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    url: Optional[str] = Field(None, max_length=500)
    icon: Optional[str] = Field(None, max_length=500)
    hidden: Optional[bool] = None


class CustomLink(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., min_length=1, max_length=500)
    icon: Optional[str] = Field(None, max_length=500)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/system")
def system():
    return sampler.snapshot()


@app.get("/api/apps")
def list_apps():
    return docker_apps.list()


@app.patch("/api/apps/{key}")
def patch_app(key: str, body: AppPatch):
    changes = body.model_dump(exclude_unset=True)
    if key.startswith("custom:"):
        if not store.update_custom(key[len("custom:"):], changes):
            raise HTTPException(404, "Link não encontrado")
    else:
        store.update_app(key, changes)
    return {"ok": True}


@app.delete("/api/apps/{key}")
def delete_app(key: str):
    """Links manuais são excluídos; containers voltam à configuração automática."""
    if key.startswith("custom:"):
        if not store.delete_custom(key[len("custom:"):]):
            raise HTTPException(404, "Link não encontrado")
    else:
        store.reset_app(key)
    return {"ok": True}


@app.post("/api/custom", status_code=201)
def add_custom(body: CustomLink):
    return store.add_custom(body.name, body.url, body.icon)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
