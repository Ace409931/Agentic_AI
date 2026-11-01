"""
FastAPI application — Travel Budget Planner backend.

Endpoints:
  POST /api/analyze   — runs the LangGraph agent and returns a structured response.
  GET  /api/health    — checks Ollama reachability and model availability.
"""

from __future__ import annotations

import json
import logging
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from .config import CORS_ORIGINS, OLLAMA_HOST, OLLAMA_MODEL
from .models import (
    AnalyzeRequest,
    AnalyzeResponse,
    ErrorResponse,
    HealthResponse,
    TraceEvent,
    TripPlanRequest,
    TripPlanResponse,
    TripPreferences,
)
from .tracing import build_trace, extract_structured_data
from .persistence import TripStore
from .rag import DestinationCostGuide

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Travel Budget Planner API",
    description="Autonomous AI agent that answers travel-budget questions via two-tool reasoning.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=5),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
async def _check_ollama() -> tuple[bool, bool]:
    """Returns (ollama_reachable, model_available) with retry on network errors."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(f"{OLLAMA_HOST}/api/tags")
        if r.status_code != 200:
            return False, False
        data = r.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        model_available = OLLAMA_MODEL in models
        return True, model_available


async def _ollama_status() -> tuple[bool, bool]:
    try:
        return await _check_ollama()
    except (httpx.HTTPError, ValueError):
        logger.warning("Unable to check Ollama health at %s", OLLAMA_HOST, exc_info=True)
        return False, False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/api/health", response_model=HealthResponse)
async def health():
    """Check whether Ollama is running and the required model is pulled."""
    reachable, available = await _ollama_status()

    if not reachable:
        msg = (
            "Unable to connect to Ollama. Make sure Ollama is running "
            f"at {OLLAMA_HOST} (run: ollama serve)."
        )
    elif not available:
        msg = (
            f"Ollama is running but model '{OLLAMA_MODEL}' is not pulled. "
            f"Run: ollama pull {OLLAMA_MODEL}"
        )
    else:
        msg = f"Ollama is running and model '{OLLAMA_MODEL}' is available."

    return HealthResponse(
        ollama_reachable=reachable,
        model_available=available,
        model=OLLAMA_MODEL,
        message=msg,
    )


@app.get("/api/destinations", response_model=list[str])
async def list_destinations():
    return DestinationCostGuide().destinations()


@app.put("/api/trips/{trip_id}/preferences", response_model=TripPreferences)
@app.post("/api/trips/{trip_id}/preferences", response_model=TripPreferences)
async def save_trip_preferences(trip_id: str, preferences: TripPreferences):
    if not trip_id.strip() or len(trip_id) > 100:
        raise HTTPException(status_code=422, detail="trip_id must contain 1 to 100 characters.")
    TripStore().save_preferences(trip_id, preferences)
    return preferences


@app.get("/api/trips/{trip_id}/preferences", response_model=TripPreferences)
async def get_trip_preferences(trip_id: str):
    preferences = TripStore().get_preferences(trip_id)
    if preferences is None:
        raise HTTPException(status_code=404, detail="No saved preferences for this trip.")
    return preferences


@app.get("/api/trips/{trip_id}/conversation", response_model=list[dict[str, str]])
async def get_trip_conversation(trip_id: str):
    return TripStore().get_conversation(trip_id)


@app.get("/api/trips/{trip_id}/plan", response_model=TripPlanResponse)
async def get_trip_plan(trip_id: str):
    if TripStore().get_preferences(trip_id) is None:
        raise HTTPException(status_code=404, detail="No saved preferences for this trip.")
    from .supervisor import get_saved_plan

    result = await run_in_threadpool(get_saved_plan, trip_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No plan has been generated for this trip.")
    result.conversation = TripStore().get_conversation(trip_id)
    return result


@app.post("/api/trips/{trip_id}/plan", response_model=TripPlanResponse)
async def plan_trip(trip_id: str, request: TripPlanRequest):
    if not trip_id.strip() or len(trip_id) > 100:
        raise HTTPException(status_code=422, detail="trip_id must contain 1 to 100 characters.")
    store = TripStore()
    preferences = store.get_preferences(trip_id)
    if preferences is None:
        raise HTTPException(
            status_code=404,
            detail="Save trip preferences before requesting a plan.",
        )
    try:
        from .supervisor import run_planning_thread

        result = await run_in_threadpool(
            run_planning_thread, trip_id, request.query, preferences
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Persistent trip planner failed for trip %s", trip_id)
        raise HTTPException(
            status_code=500,
            detail="Trip planning failed; no result was saved.",
        ) from exc
    store.save_preferences(trip_id, result.preferences)
    store.append_conversation(trip_id, request.query, result.answer)
    result.conversation = store.get_conversation(trip_id)
    return result


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    """
    Run the autonomous LangGraph agent on the user's travel-budget query.

    The agent decides which tools to call and in what order.
    Returns a structured response with the final answer, feasibility data,
    and the full execution trace derived from real LangGraph messages.
    """
    # Pre-flight Ollama check
    reachable, available = await _ollama_status()
    if not reachable:
        raise HTTPException(
            status_code=503,
            detail=(
                "Unable to connect to Ollama. Make sure Ollama is running "
                f"at {OLLAMA_HOST} (run: ollama serve)."
            ),
        )
    if not available:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Model '{OLLAMA_MODEL}' is not available in Ollama. "
                f"Run: ollama pull {OLLAMA_MODEL}"
            ),
        )

    # Run agent (import here to avoid build-time Ollama requirement)
    try:
        from .agent import run_agent
        messages = await run_in_threadpool(run_agent, request.query)
    except httpx.HTTPError as exc:
        logger.exception("Unable to communicate with Ollama")
        raise HTTPException(
            status_code=502,
            detail="Unable to communicate with Ollama while processing the request.",
        ) from exc
    except Exception as exc:
        logger.exception("Travel budget agent failed")
        raise HTTPException(
            status_code=500,
            detail="The travel budget agent failed while processing the request.",
        ) from exc

    # Build trace from real messages
    trace = build_trace(messages)

    # Extract structured data from tool results
    structured = extract_structured_data(trace)

    # Collect the final answer text
    final_answer = ""
    from langchain_core.messages import AIMessage
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", []):
            final_answer = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    if not final_answer:
        raise HTTPException(
            status_code=502,
            detail="The agent did not produce a final text response.",
        )

    return AnalyzeResponse(
        answer=final_answer,
        feasible=structured["feasible"],
        total_cost=structured["total_cost"],
        budget=structured["budget"],
        remaining=structured["remaining"],
        overage=structured["overage"],
        currency=structured["currency"],
        trace=trace,
    )


@app.post("/api/analyze/stream")
async def analyze_stream(request: AnalyzeRequest):
    """
    Streaming version of /api/analyze using Server-Sent Events.
    Pushes trace events progressively as the agent processes them.
    """
    reachable, available = await _ollama_status()
    if not reachable or not available:
        message = (
            f"Ollama is unavailable at {OLLAMA_HOST}."
            if not reachable
            else f"Model '{OLLAMA_MODEL}' is not available. Run: ollama pull {OLLAMA_MODEL}"
        )
        raise HTTPException(status_code=503, detail=message)

    async def event_stream():
        try:
            from langchain_core.messages import HumanMessage
            from .agent import agent as _agent

            completed = False
            async for event in _agent.astream_events(
                {"messages": [HumanMessage(content=request.query)]},
                version="v2",
            ):
                kind = event.get("event", "")
                data = event.get("data", {})

                if kind == "on_tool_start":
                    payload = {
                        "type": "tool_start",
                        "tool": event.get("name", ""),
                        "arguments": data.get("input", {}),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_tool_end":
                    payload = {
                        "type": "tool_end",
                        "tool": event.get("name", ""),
                        "result": str(data.get("output", "")),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                    # Final state — emit the complete response
                    output = data.get("output", {})
                    msgs = output.get("messages", [])
                    trace = build_trace(msgs)
                    structured = extract_structured_data(trace)
                    final_answer = ""
                    from langchain_core.messages import AIMessage
                    for msg in reversed(msgs):
                        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", []):
                            final_answer = msg.content if isinstance(msg.content, str) else str(msg.content)
                            break
                    if not final_answer:
                        logger.error("Agent stream ended without a final assistant response")
                        yield f"data: {json.dumps({'type': 'error', 'message': 'The agent did not produce a final text response.'})}\n\n"
                        completed = True
                        continue
                    payload = {
                        "type": "complete",
                        "answer": final_answer,
                        "feasible": structured["feasible"],
                        "total_cost": structured["total_cost"],
                        "budget": structured["budget"],
                        "remaining": structured["remaining"],
                        "overage": structured["overage"],
                        "currency": structured["currency"],
                        "trace": [t.model_dump() for t in trace],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                    completed = True

        except Exception as exc:
            logger.exception("Streaming travel budget agent failed")
            yield f"data: {json.dumps({'type': 'error', 'message': 'The travel budget agent failed while processing the request.'})}\n\n"
        else:
            if not completed:
                logger.error("Agent event stream ended without a final graph response")
                yield f"data: {json.dumps({'type': 'error', 'message': 'The agent stream ended before a result was produced.'})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled application exception for %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(error="Internal server error").model_dump(),
    )
