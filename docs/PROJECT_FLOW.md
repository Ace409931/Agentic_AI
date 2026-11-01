# Travel Budget Planner — End-to-End Project Flow

## 1. Problem Statement

Planning international travel involves two separate calculations:
1. **Currency conversion** — "How much is €900 in rupees?"
2. **Budget feasibility** — "Is ₹85,500 within my ₹100,000 budget?"

A fixed Python script could call both functions in order, but this would be a *pipeline*, not an agent. The goal of this project is to demonstrate that a **local language model can autonomously decide** to make these two calls — without being told the order or even which tools exist in the query.

---

## 2. Why an Agent Instead of a Fixed Script?

| Fixed Script | Autonomous Agent |
|---|---|
| `convert_currency()` is always called first | The model decides *if* currency conversion is needed |
| `check_budget_feasibility()` is always called second | The model decides when currencies are unified |
| Order is hardcoded in Python | Order is inferred from task + system prompt |
| No real decision-making | Genuine reasoning about the task |

The critical constraint from the spec: **the tool order must never be hardcoded in Python**. Any `convert_currency(...); check_budget_feasibility(...)` call sequence outside the agent loop would violate the project's premise.

---

## 3. Tools

### `convert_currency(amount, from_currency, to_currency) → str`
- Uses a small hardcoded rate table (EUR, USD, INR, GBP).
- Returns a human-readable sentence the LLM can quote in its final answer.
- Handles: same-currency (no-op), unsupported currency, negative amount.
- Decorated with LangChain `@tool` — the docstring is the tool-selection signal.

### `check_budget_feasibility(total_cost, cost_currency, budget, budget_currency) → str`
- Compares two numbers *in the same currency*.
- Requires supported, matching currency codes.
- Returns exact surplus or shortfall — never adjusted to make a trip look feasible.
- Handles invalid amounts with a validation error string. Missing required tool arguments are rejected by the tool schema.

---

## 4. Agent Architecture

```
ChatOllama(qwen2.5:3b, temperature=0)
    └── bind_tools([convert_currency, check_budget_feasibility])
         └── LangGraph StateGraph
                  ├── System prompt (rules, not explicit order) + HumanMessage
                  ├── LLM node → tool_calls → ToolNode
                  ├── ToolMessage (convert_currency result)
                  ├── LLM node → tool_calls → ToolNode
                  ├── ToolMessage (check_budget_feasibility result)
                  └── LLM node → final answer (no tool_calls)
```

**Stopping criterion:** the loop ends when the model emits an `AIMessage` with no `tool_calls`. This is the model's decision — not a fixed step count. `MAX_ITERATIONS` is a purely defensive cap against runaway loops.

---

## 5. System Prompt Design

The system prompt (see `backend/agent.py`) deliberately does *not* say "first call convert_currency, then call check_budget_feasibility". Instead, it states:

> "If the trip cost and the budget are in different currencies, you must convert first."
> "Only call check_budget_feasibility once both numbers are in the same currency."

This forces the model to *infer* the ordering from the rules, rather than following a script. This is what makes the tool selection genuinely autonomous.

---

## 6. Request Lifecycle

```
User types query in React UI
    ↓
POST /api/analyze/stream  (SSE)
    ↓
FastAPI preflight: checks Ollama health
    ↓
agent.run_agent(query)
    ↓
LangGraph runs ReAct loop:
    HumanMessage(query)
    → LLM decides: convert_currency needed
    → ToolNode calls convert_currency
    → ToolMessage: "Converted 900 EUR to 85500 INR…"
    → LLM decides: check_budget_feasibility needed
    → ToolNode calls check_budget_feasibility
    → ToolMessage: "Trip is feasible…"
    → LLM: final answer
    ↓
tracing.build_trace(messages) → list[TraceEvent]
tracing.extract_structured_data(trace) → {feasible, cost, budget, currency}
    ↓
SSE: stream tool_start/tool_end events progressively
SSE: final "complete" event with full response
    ↓
React: updates trace timeline + result card in real time
```

---

## 7. Trace Derivation — Real, Not Fabricated

The trace is built by walking the actual `messages` list returned by LangGraph's `.invoke()`:

| Message type | → Trace event |
|---|---|
| `HumanMessage` | `type: "user_request"` |
| `AIMessage` with `tool_calls` | `type: "agent_decision"` + `type: "tool_call"` per pending call |
| `ToolMessage` | `type: "tool_result"` |
| Final `AIMessage` (no `tool_calls`) | `type: "final_answer"` |

Agent decision descriptions come from a **lookup table keyed by tool name** (`_DECISION_TEMPLATES` in `tracing.py`) — not generated per-request. This satisfies "no fabricated narration" while still explaining the decision in one sentence.

### Structured Data Extraction

`extract_structured_data()` parses `feasible`, `total_cost`, `budget`, and `currency` from **tool result strings** (using regex), not from the LLM's free-text final answer. This is more reliable because tool results have predictable format (they're generated by our own Python functions).

---

## 8. API

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Checks Ollama reachability and model availability |
| `/api/analyze` | POST | Blocking: runs agent, returns full response |
| `/api/analyze/stream` | POST | Streaming SSE: pushes trace events as they arrive |

### Response shape (`/api/analyze`)
```json
{
  "answer": "Yes, the trip is feasible...",
  "feasible": true,
  "total_cost": 85500.0,
  "budget": 100000.0,
  "currency": "INR",
  "trace": [
    { "step": 1, "type": "user_request", "title": "User Query", ... },
    { "step": 2, "type": "agent_decision", "title": "Agent selected next tool", ... },
    ...
  ]
}
```

---

## 9. Error Handling

| Case | Behavior |
|---|---|
| Unsupported currency | Tool returns a clear string; LLM includes it in final answer; HTTP 200 |
| Negative amount | Same — validation string from tool |
| Missing budget/cost | Agent asks user for the missing value; `feasible: null` in response |
| Ollama not running | `/api/health` reports unreachable; analyze endpoints return 503 with a useful message |
| Model not pulled | 503 with an `ollama pull <configured-model>` instruction |
| Runaway loop | `MAX_ITERATIONS` cap (default 6); treated as an unexpected error |

---

## 10. Frontend / Backend / API Flow

```
React (Vite, :5173)
  → Vite proxy → FastAPI (:8000)
  → /api/analyze/stream  (SSE)
  ← tool_start events  (progressive)
  ← tool_end events    (progressive)
  ← complete event     (final result + full trace)

React state:
  trace[]    updated progressively as SSE events arrive
  result{}   set on "complete" event
  loading    true until "complete" or error
```

## 11. Persistent Preference, RAG, and Bidding Flow

Trip preferences are validated with Pydantic and saved per trip/thread identifier in SQLite. A local guide lookup retrieves the exact destination section and records its source filename, section, currency, assumptions, and price tiers. Missing destinations and unsupported currency conversions return explicit errors rather than invented estimates.

The LangGraph supervisor uses the SQLite checkpointer (`langgraph-checkpoint-sqlite`) with the same stable trip identifier as `thread_id`. It retains the message history, prior selected decisions, and latest preferences across requests/restarts. Separate identifiers are isolated. After retrieval and deterministic currency normalization, the independent Budget Agent and Itinerary Agent graph nodes run in parallel. The supervisor validates itemized sums, checks hard constraints, computes feasibility using arithmetic, and selects the lowest-cost valid bid within the budget.

The illustrative guide contains sample estimates only, not live prices or booking availability. See [UNIT3_UNIT4_EVIDENCE.md](./UNIT3_UNIT4_EVIDENCE.md) for the reproducible scenario and explicit limitation of the reconstructed TA1 comparison.

---

## 12. Testing Strategy

| Test file | Requires Ollama? | What it tests |
|---|---|---|
| `test_tools.py` | No | Unit: both tools, all edge cases |
| `test_agent.py` | Yes (mark: integration) | E2E: tool order, feasibility, trace structure |
| `test_agent_unit.py` | No | Agent construction and error handling with a mocked LLM |
| `test_trip_planner.py` | No | Retrieval, currency normalization, budget/itinerary bids, constraints |
| `test_supervisor_memory.py` | No | Persistent thread memory and isolation |
| `test_api.py` | No | FastAPI request validation, planner endpoints, and health behavior |

---

## 13. Feasible Scenario

Query: *"I have a budget of ₹100,000 and my estimated trip cost is €900. Can I afford it?"*

Steps:
1. LLM recognises currencies differ (EUR vs INR).
2. Calls `convert_currency(900, "EUR", "INR")` → `"Converted 900.0 EUR to 85500.0 INR using the demonstration rate 1 EUR = 95.0 INR."`
3. Calls `check_budget_feasibility(85500.0, 100000.0)` → `"Trip is feasible. Total cost is 85500.0 and the budget is 100000.0. Remaining budget: 14500.0."`
4. Final answer: confirms feasibility with numbers.

---

## 14. Non-Feasible Scenario

Query: *"I have a budget of ₹50,000 and my estimated trip cost is €900. Can I afford it?"*

Steps:
1–2. Same conversion: 900 EUR → 85,500 INR.
3. `check_budget_feasibility(85500.0, 50000.0)` → `"Trip is NOT feasible. Total cost is 85500.0 but the budget is 50000.0. Over budget by 35500.0."`
4. Final answer: reports infeasibility — the agent never adjusts numbers to make the trip look affordable.

---

## 15. Limitations

- **Hardcoded FX rates** — not live; go stale; not suitable for real financial decisions.
- **Small-model reliability** — Qwen 2.5 3B occasionally fails multi-step tool reasoning. Mitigated by `temperature=0` and a tight system prompt.
- **No streaming from Ollama to client** — final LLM response arrives all at once; only tool events stream progressively.

---

## 16. Future Improvements

- Live FX rates behind an environment flag (e.g. `USE_LIVE_RATES=true`).
- More tools: hotel cost estimation, flight price lookup, per-day budget breakdown.
- Full token-level streaming from the LLM to the client.
- Multi-currency budgets (e.g. part in USD, part in EUR).
- Auth / user sessions for saved trip analyses.

---

## Jury Q&A

1. **Why hardcoded exchange rates instead of a live API?** — Reproducibility, no API-key dependency, predictable grading. Trade-off: rates go stale; not suitable for real financial use.
2. **Where exactly did the agent decide to call the second tool?** — The `agent_decision` trace event between the two `tool_call` events (marked with the `🤖 Agent selected next tool` chip in the UI). This event is derived from the real `AIMessage` with `tool_calls` in the LangGraph message list — not fabricated.
3. **Why is this "autonomous"?** — The user never named a tool or an order. The model inferred both from the system prompt's rules and the structure of the task.
4. **Why Ollama / why Qwen 2.5 3B?** — Local, private, free, runs on student hardware. Trade-off: smaller models are less reliable at multi-step tool reasoning than larger cloud models — which is why `temperature=0` and a tight system prompt matter here.
5. **Why LangGraph instead of fixed orchestration?** — Calling `convert_currency()` then `check_budget_feasibility()` directly in Python would be a fixed pipeline with no real decision-making. The point of the project is that *the model* chooses what to call.
