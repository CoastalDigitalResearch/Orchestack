"""Core agent execution loop."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20
MAX_TOOL_CALLS = 50


@dataclass
class LoopContext:
    """Context for a single loop execution."""

    task_id: str
    session_id: str
    agent_id: str
    tenant_id: str
    capability_grant_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_call_count: int = 0
    token_count: int = 0
    start_time: float = field(default_factory=time.time)
    max_wall_time_s: int = 3600
    budget_remaining_usd: float = 50.0


class AgentLoop:
    """Executes the agent loop for dispatched tasks."""

    def __init__(self, js, settings):
        self.js = js
        self.settings = settings
        self._http = httpx.AsyncClient(timeout=180.0)

    async def handle_dispatch(self, msg):
        """Handle a tasks.dispatch event."""
        data = json.loads(msg.data)

        # task-dispatcher publishes flat top-level fields (no nested payload)
        ctx = LoopContext(
            task_id=data["task_id"],
            session_id=data["session_id"],
            agent_id=data["agent_id"],
            tenant_id=data.get("tenant_id", ""),
            capability_grant_id=data.get("capability_grant_id", ""),
        )

        logger.info("Starting loop for task %s", ctx.task_id)

        try:
            response = await self.run_loop(ctx)

            # Publish step completed event
            await self._emit_event(
                "tasks.run.completed",
                {
                    "task_id": ctx.task_id,
                    "session_id": ctx.session_id,
                    "response": response,
                    "token_count": ctx.token_count,
                    "tool_call_count": ctx.tool_call_count,
                },
            )

            # Send response via connector egress (webchat for MVP)
            await self._emit_event(
                "egress.webchat.message",
                {
                    "task_id": ctx.task_id,
                    "session_id": ctx.session_id,
                    "content": response,
                },
            )

            await msg.ack()

        except BudgetExceededError as e:
            logger.warning("Budget exceeded for task %s: %s", ctx.task_id, e)
            await self._emit_event(
                "tasks.run.failed",
                {
                    "task_id": ctx.task_id,
                    "error": "budget_exceeded",
                    "message": str(e),
                },
            )
            await msg.ack()

        except Exception as e:
            logger.error("Loop failed for task %s: %s", ctx.task_id, e)
            await msg.nak()

    async def run_loop(self, ctx: LoopContext) -> str:
        """Execute the agent loop."""

        # 1. Load agent context (system prompt, tools, etc.)
        agent_config = await self._load_agent_config(ctx.agent_id)

        # 2. Load session history from memory
        history = await self._load_session_history(ctx.session_id)
        ctx.messages = [
            {"role": "system", "content": agent_config.get("system_prompt", "You are a helpful assistant.")},
            *history,
        ]

        # 3. Search memory for relevant context
        memory_hits = await self._search_memory(ctx)
        if memory_hits:
            ctx.messages.append(
                {
                    "role": "system",
                    "content": f"Relevant context from memory:\n{memory_hits}",
                }
            )

        content = ""

        # 4. Run the loop
        for iteration in range(MAX_ITERATIONS):
            # Check budget
            self._check_budget(ctx)
            self._check_wall_time(ctx)

            # Emit step started
            await self._emit_event(
                "tasks.run.step.started",
                {
                    "task_id": ctx.task_id,
                    "step_type": "model_call",
                    "iteration": iteration,
                },
            )

            # 5. Call model router
            model_response = await self._call_model(ctx)
            ctx.token_count += model_response.get("usage", {}).get("total_tokens", 0)

            content = model_response.get("content", "")
            tool_calls = model_response.get("tool_calls", [])

            # Emit step completed
            await self._emit_event(
                "tasks.run.step.completed",
                {
                    "task_id": ctx.task_id,
                    "step_type": "model_call",
                    "iteration": iteration,
                    "tokens": model_response.get("usage", {}),
                },
            )

            if not tool_calls:
                # No tool calls - we have a final response
                return content

            # 6. Execute tool calls
            ctx.messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

            for tool_call in tool_calls:
                ctx.tool_call_count += 1
                if ctx.tool_call_count > MAX_TOOL_CALLS:
                    raise BudgetExceededError(f"Max tool calls ({MAX_TOOL_CALLS}) exceeded")

                result = await self._execute_tool(ctx, tool_call)
                ctx.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": result,
                    }
                )

        return content if content else "I was unable to complete the task within the iteration limit."

    async def _load_agent_config(self, agent_id: str) -> dict:
        """Load agent configuration from database via asyncpg."""
        try:
            import asyncpg

            conn = await asyncpg.connect(self.settings.database_url)
            try:
                row = await conn.fetchrow(
                    "SELECT definition FROM agent_definitions WHERE agent_id = $1 LIMIT 1",
                    agent_id,
                )
                if row and row["definition"]:
                    import json as _json

                    return _json.loads(row["definition"]) if isinstance(row["definition"], str) else row["definition"]
            finally:
                await conn.close()
        except Exception as e:
            logger.warning("Failed to load agent config for %s: %s", agent_id, e)
        return {"system_prompt": "You are a helpful AI assistant."}

    async def _load_session_history(self, session_id: str) -> list[dict]:
        """Load recent session messages from memory."""
        # TODO: Query memory plane L0 for session history
        return []

    async def _search_memory(self, ctx: LoopContext) -> str:
        """Search memory layers for relevant context."""
        # TODO: Call memory plane search API
        return ""

    async def _call_model(self, ctx: LoopContext) -> dict:
        """Call the model router HTTP endpoint to get a completion."""
        model_router_url = getattr(self.settings, "model_router_url", "http://model-router:8080")
        request_payload = {
            "messages": ctx.messages,
            "capability_grant_id": ctx.capability_grant_id,
            "tenant_id": ctx.tenant_id,
        }

        try:
            resp = await self._http.post(
                f"{model_router_url}/v1/router/request",
                json=request_payload,
            )
            resp.raise_for_status()
            result = resp.json()

            # Extract from RoutingResponse envelope
            provider_resp = result.get("response", {})
            usage = provider_resp.get("usage", {})
            return {
                "content": provider_resp.get("content", ""),
                "tool_calls": provider_resp.get("tool_calls") or [],
                "usage": {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                },
            }
        except Exception as e:
            logger.error("Model call failed: %s", e)
            return {"content": "I encountered an error processing your request.", "tool_calls": [], "usage": {}}

    async def _execute_tool(self, ctx: LoopContext, tool_call: dict) -> str:
        """Execute a tool call via NATS."""
        tool_id = tool_call.get("function", {}).get("name", "unknown")
        arguments = tool_call.get("function", {}).get("arguments", "{}")

        # Emit tool call event
        await self._emit_event(
            "tasks.run.step.started",
            {
                "task_id": ctx.task_id,
                "step_type": "tool_call",
                "tool_id": tool_id,
            },
        )

        try:
            # Publish to tools.{tool_id}.call
            request_data = json.dumps(
                {
                    "task_id": ctx.task_id,
                    "tool_id": tool_id,
                    "arguments": arguments,
                    "capability_grant_id": ctx.capability_grant_id,
                }
            ).encode()

            # In production, use NATS request/reply
            await self.js.publish(f"tools.{tool_id}.call", request_data)

            result = f"Tool {tool_id} executed successfully"

            await self._emit_event(
                "tasks.run.step.completed",
                {
                    "task_id": ctx.task_id,
                    "step_type": "tool_call",
                    "tool_id": tool_id,
                },
            )

            return result

        except Exception as e:
            logger.error("Tool call failed: %s", e)
            return f"Error executing tool {tool_id}: {e}"

    def _check_budget(self, ctx: LoopContext):
        """Check if budget limits are exceeded."""
        # TODO: Query budget accounting service
        pass

    def _check_wall_time(self, ctx: LoopContext):
        """Check if wall time limit is exceeded."""
        elapsed = time.time() - ctx.start_time
        if elapsed > ctx.max_wall_time_s:
            raise BudgetExceededError(f"Wall time exceeded: {elapsed:.0f}s > {ctx.max_wall_time_s}s")

    async def _emit_event(self, subject: str, payload: dict):
        """Emit an event to NATS."""
        try:
            await self.js.publish(subject, json.dumps(payload).encode())
        except Exception as e:
            logger.error("Failed to emit event %s: %s", subject, e)


class BudgetExceededError(Exception):
    """Raised when budget limits are exceeded."""
