"""Model Router service entry point."""

from fastapi import FastAPI

app = FastAPI(title="Orchestack Model Router", version="0.1.0")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    return {"status": "ok"}
