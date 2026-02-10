"""Core agent execution loop."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

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

    async def handle_dispatch(self, msg):
        """Handle a tasks.dispatch event."""
        data = json.loads(msg.data)
        payload = data.get("payload", {})

        ctx = LoopContext(
            task_id=payload["task_id"],
            session_id=payload["session_id"],
            agent_id=payload["agent_id"],
            tenant_id=data.get("tenant_id", "tenant-default"),
            capability_grant_id=payload.get("capability_grant_id", ""),
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

            # Send response via connector egress
            await self._emit_event(
                "egress.message",
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
        """Load agent configuration from database."""
        # TODO: Query agent_definitions table
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
        """Call the model router to get a completion."""
        request_data = json.dumps(
            {
                "messages": ctx.messages,
                "capability_grant_id": ctx.capability_grant_id,
                "task_id": ctx.task_id,
            }
        ).encode()

        # Publish to router.request and wait for reply
        try:
            await self.js.publish(
                "router.request",
                request_data,
            )
            # In production, this would use request/reply pattern
            # For now, return a mock response
            return {
                "content": "I'll help you with that.",
                "tool_calls": [],
                "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
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
