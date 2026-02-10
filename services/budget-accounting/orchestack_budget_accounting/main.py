"""Budget Accounting service - tracks model usage costs."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

import nats
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from orchestack_budget_accounting.config import Settings

logger = logging.getLogger(__name__)
settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    nc = await nats.connect(settings.nats_url)
    js = nc.jetstream()

    # Subscribe to router.metrics for cost recording
    sub = await js.subscribe(
        "router.metrics",
        stream="STREAM_EVENTS",
        durable="budget-accounting",
        manual_ack=True,
    )

    budget_service = BudgetService(settings=settings)
    app.state.budget_service = budget_service

    async def consume_metrics():
        async for msg in sub.messages:
            try:
                data = json.loads(msg.data)
                await budget_service.record_spend(data)
                await msg.ack()
            except Exception as e:
                logger.error("Failed to process metric: %s", e)
                await msg.nak()

    task = asyncio.create_task(consume_metrics())
    yield {"nc": nc, "js": js, "budget_service": budget_service}
    task.cancel()
    await nc.close()


app = FastAPI(title="Orchestack Budget Accounting", version="0.1.0", lifespan=lifespan)


class BudgetResponse(BaseModel):
    id: str
    tenant_id: str
    scope: str
    scope_id: str
    daily_limit_usd: float | None = None
    monthly_limit_usd: float | None = None
    spend_today_usd: float
    spend_month_usd: float
    soft_threshold: float
    hard_threshold: float


class BudgetCheckResponse(BaseModel):
    budget_id: str
    remaining_daily_usd: float | None = None
    remaining_monthly_usd: float | None = None
    status: str  # "ok", "soft_limit", "hard_limit"


class RecordSpendRequest(BaseModel):
    task_id: str | None = None
    step_id: str | None = None
    model_name: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@app.get("/v1/budgets")
async def list_budgets(scope: str | None = None, tenant_id: str = "tenant-default"):
    svc = app.state.budget_service
    return await svc.list_budgets(tenant_id, scope)


@app.get("/v1/budgets/{budget_id}")
async def get_budget(budget_id: str):
    svc = app.state.budget_service
    budget = await svc.get_budget(budget_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    return budget


@app.get("/v1/budgets/{budget_id}/check")
async def check_budget(budget_id: str):
    svc = app.state.budget_service
    return await svc.check_budget(budget_id)


@app.get("/v1/budgets/{budget_id}/breakdown")
async def budget_breakdown(budget_id: str):
    svc = app.state.budget_service
    return await svc.get_breakdown(budget_id)


@app.post("/v1/budgets/{budget_id}/record")
async def record_spend(budget_id: str, request: RecordSpendRequest):
    svc = app.state.budget_service
    return await svc.record_transaction(budget_id, request)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    return {"status": "ok"}


class BudgetService:
    """Budget tracking and enforcement."""

    def __init__(self, settings: Settings):
        self.settings = settings
        # In production, this would use asyncpg connection pool
        self._budgets: dict[str, dict] = {
            "budget-default": {
                "id": "budget-default",
                "tenant_id": "tenant-default",
                "scope": "tenant",
                "scope_id": "tenant-default",
                "daily_limit_usd": 50.0,
                "monthly_limit_usd": 1000.0,
                "spend_today_usd": 0.0,
                "spend_month_usd": 0.0,
                "soft_threshold": 0.8,
                "hard_threshold": 1.0,
            }
        }
        self._transactions: list[dict] = []

    async def list_budgets(self, tenant_id: str, scope: str | None = None) -> list[dict]:
        results = [b for b in self._budgets.values() if b["tenant_id"] == tenant_id]
        if scope:
            results = [b for b in results if b["scope"] == scope]
        return results

    async def get_budget(self, budget_id: str) -> dict | None:
        return self._budgets.get(budget_id)

    async def check_budget(self, budget_id: str) -> dict:
        budget = self._budgets.get(budget_id)
        if not budget:
            return {"budget_id": budget_id, "status": "not_found"}

        status = "ok"
        remaining_daily = None
        remaining_monthly = None

        if budget["daily_limit_usd"]:
            remaining_daily = budget["daily_limit_usd"] - budget["spend_today_usd"]
            ratio = budget["spend_today_usd"] / budget["daily_limit_usd"]
            if ratio >= budget["hard_threshold"]:
                status = "hard_limit"
            elif ratio >= budget["soft_threshold"]:
                status = "soft_limit"

        if budget["monthly_limit_usd"]:
            remaining_monthly = budget["monthly_limit_usd"] - budget["spend_month_usd"]
            ratio = budget["spend_month_usd"] / budget["monthly_limit_usd"]
            if ratio >= budget["hard_threshold"]:
                status = "hard_limit"
            elif ratio >= budget["soft_threshold"] and status == "ok":
                status = "soft_limit"

        return {
            "budget_id": budget_id,
            "remaining_daily_usd": remaining_daily,
            "remaining_monthly_usd": remaining_monthly,
            "status": status,
        }

    async def get_breakdown(self, budget_id: str) -> dict:
        txns = [t for t in self._transactions if t.get("budget_id") == budget_id]

        by_model: dict[str, dict] = {}
        by_provider: dict[str, dict] = {}

        for t in txns:
            model = t["model_name"]
            provider = t["provider"]

            if model not in by_model:
                by_model[model] = {"model": model, "total_tokens": 0, "cost_usd": 0.0}
            by_model[model]["total_tokens"] += t["input_tokens"] + t["output_tokens"]
            by_model[model]["cost_usd"] += t["cost_usd"]

            if provider not in by_provider:
                by_provider[provider] = {"provider": provider, "total_tokens": 0, "cost_usd": 0.0}
            by_provider[provider]["total_tokens"] += t["input_tokens"] + t["output_tokens"]
            by_provider[provider]["cost_usd"] += t["cost_usd"]

        return {
            "budget_id": budget_id,
            "by_model": list(by_model.values()),
            "by_provider": list(by_provider.values()),
        }

    async def record_spend(self, data: dict):
        """Record spend from router.metrics NATS event."""
        budget_id = data.get("budget_id", "budget-default")
        cost = data.get("cost_usd", 0.0)

        if budget_id in self._budgets:
            self._budgets[budget_id]["spend_today_usd"] += cost
            self._budgets[budget_id]["spend_month_usd"] += cost

        self._transactions.append(
            {
                "budget_id": budget_id,
                "model_name": data.get("model", "unknown"),
                "provider": data.get("provider", "unknown"),
                "input_tokens": data.get("input_tokens", 0),
                "output_tokens": data.get("output_tokens", 0),
                "cost_usd": cost,
            }
        )

    async def record_transaction(self, budget_id: str, request: RecordSpendRequest) -> dict:
        """Record a spend transaction via REST API."""
        if budget_id not in self._budgets:
            return {"error": "budget not found"}

        self._budgets[budget_id]["spend_today_usd"] += request.cost_usd
        self._budgets[budget_id]["spend_month_usd"] += request.cost_usd

        txn = {
            "budget_id": budget_id,
            "task_id": request.task_id,
            "step_id": request.step_id,
            "model_name": request.model_name,
            "provider": request.provider,
            "input_tokens": request.input_tokens,
            "output_tokens": request.output_tokens,
            "cost_usd": request.cost_usd,
        }
        self._transactions.append(txn)

        return {"status": "recorded", "transaction": txn}
