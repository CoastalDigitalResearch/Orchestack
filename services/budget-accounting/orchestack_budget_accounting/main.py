"""Budget Accounting service entry point."""

from fastapi import FastAPI

app = FastAPI(title="Orchestack Budget Accounting", version="0.1.0")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    return {"status": "ok"}
