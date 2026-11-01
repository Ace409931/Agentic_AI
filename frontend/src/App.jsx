import { useState, useEffect, useCallback } from 'react'
import Header from './components/Header.jsx'
import ChatInput from './components/ChatInput.jsx'
import ExampleQueries from './components/ExampleQueries.jsx'
import ExchangeRates from './components/ExchangeRates.jsx'
import ResultCard from './components/ResultCard.jsx'
import ExecutionTrace from './components/ExecutionTrace.jsx'
import TripPlanningPanel from './components/TripPlanningPanel.jsx'

const API_BASE = '/api'

export default function App() {
  const [activeView, setActiveView] = useState('planner')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [trace, setTrace] = useState([])
  const [error, setError] = useState(null)
  const [health, setHealth] = useState(null)

  // ── Health check on mount ──────────────────────────────────────────────
  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then(response => {
        if (!response.ok) throw new Error(`Health check failed (${response.status})`)
        return response.json()
      })
      .then(setHealth)
      .catch(() => setHealth({ ollama_reachable: false, model_available: false, message: 'Backend not reachable.' }))
  }, [])

  const updateQuery = useCallback((nextQuery) => {
    if (loading) return
    setQuery(nextQuery)
    setResult(null)
    setSubmittedQuery('')
    setTrace([])
    setError(null)
  }, [loading])

  // ── Submit handler using streaming endpoint ────────────────────────────
  const handleSubmit = useCallback(async () => {
    if (!query.trim() || loading) return

    const requestQuery = query.trim()
    setLoading(true)
    setResult(null)
    setSubmittedQuery(requestQuery)
    setTrace([])
    setError(null)

    try {
      const response = await fetch(`${API_BASE}/analyze/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: requestQuery }),
      })

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(err.detail || 'Request failed')
      }

      if (!response.body) {
        throw new Error('The server did not provide a response stream.')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let receivedComplete = false

      // SSE parse loop — pushes trace events progressively
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() // keep incomplete line

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (raw === '[DONE]') continue

          try {
            const evt = JSON.parse(raw)

            if (evt.type === 'error') {
              setError(evt.message)
              setLoading(false)
              return
            }

            if (evt.type === 'complete') {
              receivedComplete = true
              setResult({
                query: requestQuery,
                answer:     evt.answer,
                feasible:   evt.feasible,
                total_cost: evt.total_cost,
                budget:     evt.budget,
                remaining:  evt.remaining,
                overage:    evt.overage,
                currency:   evt.currency,
              })
              setTrace(evt.trace || [])
              setLoading(false)
            }

            // Progressive trace events from tool_start / tool_end
            if (evt.type === 'tool_start') {
              setTrace(prev => [
                ...prev,
                {
                  step:        prev.length + 1,
                  type:        'agent_decision',
                  title:       'Agent selected next tool',
                  description: `Invoking tool: ${evt.tool}`,
                  tool:        evt.tool,
                  arguments:   evt.arguments || {},
                  result:      null,
                  timestamp:   new Date().toISOString(),
                  status:      'complete',
                },
              ])
            }

            if (evt.type === 'tool_end') {
              setTrace(prev => [
                ...prev,
                {
                  step:        prev.length + 1,
                  type:        'tool_result',
                  title:       `Result: ${evt.tool}`,
                  description: evt.result,
                  tool:        evt.tool,
                  arguments:   null,
                  result:      evt.result,
                  timestamp:   new Date().toISOString(),
                  status:      'complete',
                },
              ])
            }
          } catch (parseError) {
            if (parseError instanceof SyntaxError) {
              throw new Error('The server sent an invalid response event.')
            }
            throw parseError
          }
        }
      }

      if (!receivedComplete) {
        throw new Error('The response stream ended before the analysis was complete.')
      }
    } catch (err) {
      setError(err.message || 'An unexpected error occurred.')
      setLoading(false)
    }
  }, [query, loading])

  // ── Health warning banners ─────────────────────────────────────────────
  const HealthBanner = () => {
    if (!health) return null
    if (!health.ollama_reachable) {
      return (
        <div className="health-banner error" id="health-banner-ollama">
          <span className="banner-icon">⚠️</span>
          <div>
            <div className="banner-title">Ollama not reachable</div>
            <div>{health.message}</div>
            <div>Run: <code>ollama serve</code></div>
          </div>
        </div>
      )
    }
    if (!health.model_available) {
      return (
        <div className="health-banner warning" id="health-banner-model">
          <span className="banner-icon">📦</span>
          <div>
            <div className="banner-title">Model not pulled</div>
            <div>{health.message}</div>
            <div>Run: <code>ollama pull {health.model || 'qwen2.5:3b'}</code></div>
          </div>
        </div>
      )
    }
    return null
  }

  // ── Empty state ────────────────────────────────────────────────────────
  const EmptyState = () => (
    <div className="empty-state">
      <div className="empty-icon">✈️</div>
      <div className="empty-title">Ready to plan your trip</div>
      <p className="empty-desc">
        Ask about your travel budget and the AI agent will autonomously convert currencies
        and check feasibility — no manual tool selection needed.
      </p>
    </div>
  )

  return (
    <div className="app-wrapper">
      <Header health={health} />

      <nav className="app-mode-tabs" aria-label="Application mode">
        <button
          type="button"
          className={activeView === 'planner' ? 'active' : ''}
          aria-current={activeView === 'planner' ? 'page' : undefined}
          onClick={() => setActiveView('planner')}
        >
          Trip Preferences &amp; Multi-Agent Planner
        </button>
        <button
          type="button"
          className={activeView === 'currency' ? 'active' : ''}
          aria-current={activeView === 'currency' ? 'page' : undefined}
          onClick={() => setActiveView('currency')}
        >
          Currency Feasibility Agent
        </button>
      </nav>

      {activeView === 'planner' ? (
        <TripPlanningPanel />
      ) : (
        <main className="main-content">
          <aside className="panel-left">
            <HealthBanner />
            <ChatInput
              query={query}
              setQuery={updateQuery}
              onSubmit={handleSubmit}
              loading={loading}
            />
            <ExampleQueries onSelect={updateQuery} disabled={loading} />
            <ExchangeRates />
          </aside>

          <section className="panel-right">
            {error && (
              <div className="health-banner error" id="error-banner">
                <span className="banner-icon">❌</span>
                <div>
                  <div className="banner-title">Error</div>
                  <div>{error}</div>
                </div>
              </div>
            )}

            {!result && !loading && !error && <EmptyState />}

            {result && <ResultCard result={result} />}

            {(trace.length > 0 || loading) && (
              <ExecutionTrace
                trace={trace}
                loading={loading}
                submittedQuery={submittedQuery}
              />
            )}
          </section>
        </main>
      )}
    </div>
  )
}
