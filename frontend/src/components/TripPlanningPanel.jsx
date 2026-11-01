import { useCallback, useEffect, useState } from 'react'

const API_BASE = '/api'

function createThreadId() {
  return globalThis.crypto?.randomUUID?.() || `trip-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function initialDates() {
  const start = new Date()
  start.setDate(start.getDate() + 30)
  const end = new Date(start)
  end.setDate(end.getDate() + 5)
  return {
    start_date: start.toISOString().slice(0, 10),
    end_date: end.toISOString().slice(0, 10),
  }
}

const DEFAULT_PREFERENCES = {
  destination: 'Goa',
  ...initialDates(),
  travelers: 2,
  budget: 30000,
  currency: 'INR',
  budget_style: 'moderate',
  preferred_accommodation_type: 'hotel',
  food_preferences: '',
  interests: '',
  hard_constraints: [],
}

function formatMoney(amount, currency) {
  return amount == null
    ? '—'
    : `${currency} ${Number(amount).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

export default function TripPlanningPanel() {
  const [tripId, setTripId] = useState(() => {
    const saved = localStorage.getItem('travel-planner-thread-id')
    const id = saved || createThreadId()
    localStorage.setItem('travel-planner-thread-id', id)
    return id
  })
  const [preferences, setPreferences] = useState(DEFAULT_PREFERENCES)
  const [destinations, setDestinations] = useState([])
  const [query, setQuery] = useState('Plan my trip and compare lower-cost options.')
  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    fetch(`${API_BASE}/destinations`)
      .then(async response => {
        if (!response.ok) throw new Error('Could not load the local destination guide.')
        return response.json()
      })
      .then(values => { if (!cancelled) setDestinations(values) })
      .catch(err => { if (!cancelled) setError(err.message) })

    fetch(`${API_BASE}/trips/${encodeURIComponent(tripId)}/preferences`)
      .then(async response => {
        if (response.status === 404) return null
        if (!response.ok) throw new Error('Could not restore saved trip preferences.')
        return response.json()
      })
      .then(async saved => {
        if (!saved || cancelled) return
        if (!cancelled) {
          setPreferences({
            ...saved,
            food_preferences: saved.food_preferences.join(', '),
            interests: saved.interests.join(', '),
          })
        }
        const response = await fetch(`${API_BASE}/trips/${encodeURIComponent(tripId)}/plan`)
        if (response.status === 404) return
        if (!response.ok) throw new Error('Could not restore the previous trip plan.')
        const restored = await response.json()
        if (!cancelled) setPlan(restored)
      })
      .catch(err => { if (!cancelled) setError(err.message) })

    return () => { cancelled = true }
  }, [tripId])

  const updatePreference = (event) => {
    const { name, value } = event.target
    setPlan(null)
    setPreferences(current => ({ ...current, [name]: value }))
  }

  const updatePlanningQuery = (event) => {
    setPlan(null)
    setQuery(event.target.value)
  }

  const startNewThread = () => {
    const id = createThreadId()
    localStorage.setItem('travel-planner-thread-id', id)
    setTripId(id)
    setPreferences(DEFAULT_PREFERENCES)
    setPlan(null)
    setError('')
    setQuery('Plan my trip and compare lower-cost options.')
  }

  const submitPlan = useCallback(async (event) => {
    event.preventDefault()
    if (!query.trim() || loading) return
    setLoading(true)
    setError('')
    setPlan(null)
    try {
      const payload = {
        ...preferences,
        travelers: Number(preferences.travelers),
        budget: Number(preferences.budget),
        food_preferences: typeof preferences.food_preferences === 'string'
          ? preferences.food_preferences.split(',').map(value => value.trim()).filter(Boolean)
          : preferences.food_preferences,
        interests: typeof preferences.interests === 'string'
          ? preferences.interests.split(',').map(value => value.trim()).filter(Boolean)
          : preferences.interests,
      }
      const saved = await fetch(`${API_BASE}/trips/${encodeURIComponent(tripId)}/preferences`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!saved.ok) {
        const detail = await saved.json()
        throw new Error(detail.detail || 'Trip preferences could not be saved.')
      }

      const response = await fetch(`${API_BASE}/trips/${encodeURIComponent(tripId)}/plan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail || 'Trip planning failed.')
      setPlan(body)
      setPreferences({
        ...body.preferences,
        food_preferences: body.preferences.food_preferences.join(', '),
        interests: body.preferences.interests.join(', '),
      })
      setQuery('')
    } catch (err) {
      setError(err.message || 'Trip planning failed.')
    } finally {
      setLoading(false)
    }
  }, [loading, preferences, query, tripId])

  return (
    <section className="planner-section" aria-labelledby="planner-title">
      <div className="planner-heading">
        <div>
          <p className="planner-eyebrow">PERSISTENT MULTI-AGENT TRIP PLANNER</p>
          <h2 id="planner-title">Plan a trip with grounded estimates</h2>
          <p>Illustrative cost-guide estimates only; no bookings or live prices.</p>
        </div>
        <button className="btn-secondary" type="button" onClick={startNewThread}>New trip</button>
      </div>

      <div className="thread-meta">
        <span>Thread / trip ID</span>
        <code>{tripId}</code>
        <span>Preferences and conversation are saved locally.</span>
      </div>

      <nav className="planner-section-tabs" aria-label="Trip planning sections">
        <a href="#trip-preferences">Trip Preferences</a>
        <a href="#planning-chat">Planning Chat</a>
        <a href="#agent-bids">Agent Bids</a>
        <a href="#evidence">Evidence</a>
      </nav>

      <form id="trip-preferences" className="preferences-form" onSubmit={submitPlan}>
        <label>Destination
          <select name="destination" value={preferences.destination} onChange={updatePreference} required>
            {destinations.map(destination => <option key={destination}>{destination}</option>)}
          </select>
        </label>
        <label>Start date
          <input type="date" name="start_date" value={preferences.start_date} onChange={updatePreference} required />
        </label>
        <label>End date
          <input type="date" name="end_date" value={preferences.end_date} onChange={updatePreference} required />
        </label>
        <label>Travelers
          <input type="number" min="1" max="20" name="travelers" value={preferences.travelers} onChange={updatePreference} required />
        </label>
        <label>Total budget
          <input type="number" min="1" step="0.01" name="budget" value={preferences.budget} onChange={updatePreference} required />
        </label>
        <label>Currency
          <select name="currency" value={preferences.currency} onChange={updatePreference}>
            {['INR', 'EUR', 'USD', 'GBP'].map(currency => <option key={currency}>{currency}</option>)}
          </select>
        </label>
        <label>Budget style
          <select name="budget_style" value={preferences.budget_style} onChange={updatePreference}>
            {['budget', 'moderate', 'luxury'].map(style => <option key={style}>{style}</option>)}
          </select>
        </label>
        <label>Accommodation
          <select name="preferred_accommodation_type" value={preferences.preferred_accommodation_type} onChange={updatePreference}>
            {['hotel', 'hostel', 'rental'].map(value => <option key={value}>{value}</option>)}
          </select>
        </label>
        <label>Food preferences
          <input name="food_preferences" value={preferences.food_preferences} onChange={updatePreference} placeholder="Vegetarian, allergies..." />
        </label>
        <label>Interests
          <input name="interests" value={preferences.interests} onChange={updatePreference} placeholder="Beaches, museums..." />
        </label>
        <fieldset className="constraint-field">
          <legend>Hard constraints</legend>
          <label><input type="checkbox" checked={preferences.hard_constraints.includes('keep_accommodation')} onChange={event => {
            setPlan(null)
            setPreferences(current => ({
            ...current,
            hard_constraints: event.target.checked
              ? [...current.hard_constraints, 'keep_accommodation']
              : current.hard_constraints.filter(value => value !== 'keep_accommodation'),
          }))
          }} /> Keep accommodation tier</label>
          <label><input type="checkbox" checked={preferences.hard_constraints.includes('no_activity_reduction')} onChange={event => {
            setPlan(null)
            setPreferences(current => ({
            ...current,
            hard_constraints: event.target.checked
              ? [...current.hard_constraints, 'no_activity_reduction']
              : current.hard_constraints.filter(value => value !== 'no_activity_reduction'),
          }))
          }} /> Do not remove activity days</label>
        </fieldset>
        <label id="planning-chat" className="planning-query">Conversation message
          <textarea value={query} onChange={updatePlanningQuery} rows={2}
            placeholder="Plan this trip, reduce my budget, or ask what if two more people join?" />
        </label>
        <button className="btn-primary planning-submit" type="submit" disabled={loading || !query.trim()}>
          {loading ? 'Planning…' : 'Save preferences and plan'}
        </button>
      </form>

      {error && <div className="health-banner error" role="alert">{error}</div>}

      {plan && (
        <div className="planning-results">
          <div className={`plan-answer ${plan.feasibility}`}>
            <strong>{plan.feasibility === 'feasible' ? 'Feasible proposal selected' : 'No feasible proposal'}</strong>
            <p>{plan.answer}</p>
            <p>{plan.rationale}</p>
            {plan.selected_bid && (
              <div className="selected-cost">
                <span>Selected estimate: <strong>{formatMoney(plan.selected_bid.proposed_total_cost, plan.selected_bid.comparison_currency)}</strong></span>
                <span>Savings: {formatMoney(plan.selected_bid.savings_amount, plan.selected_bid.comparison_currency)}</span>
              </div>
            )}
          </div>

          <div className="planner-columns">
            <section id="evidence" className="planner-card">
              <h3>Retrieved cost evidence</h3>
              {plan.evidence.map(item => (
                <div key={`${item.destination}-${item.section}`}>
                  <p><strong>{item.destination}</strong> · {item.currency} · {item.section}</p>
                  <p className="muted">Source: {item.source_file}; illustrative estimates only.</p>
                  <p className="muted">Hotel prices are per traveler per night; food, transport, and activity estimates are per traveler per day.</p>
                  <div className="evidence-grid">
                    {Object.entries(item.estimates).map(([category, levels]) => (
                      <div key={category}><strong>{category}</strong>
                        {Object.entries(levels).map(([style, amount]) => (
                          <span key={style}>{style}: {formatMoney(amount, item.currency)}</span>
                        ))}
                      </div>
                    ))}
                  </div>
                  <ul>{item.assumptions.map(assumption => <li key={assumption}>{assumption}</li>)}</ul>
                </div>
              ))}
            </section>

            <section className="planner-card">
              <h3>Reconstructed single-agent vs multi-agent</h3>
              <p className="muted">The prior tool-calling agent does not produce cost-guide bids; this comparison uses the same deterministic baseline estimate, not an authentic TA1 rerun.</p>
              <div className="comparison-grid">
                <span>Workflow</span><span>Estimated total</span><span>Feasible</span><span>Proposals</span>
                <strong>Single-agent baseline</strong>
                <span>{formatMoney(plan.comparison.baseline_total_cost, plan.preferences.currency)}</span>
                <span>{plan.comparison.baseline_feasible ? 'Yes' : 'No'}</span>
                <span>{plan.comparison.baseline_proposal_count}</span>
                <strong>Supervisor</strong>
                <span>{formatMoney(plan.comparison.selected_total_cost, plan.preferences.currency)}</span>
                <span>{plan.comparison.selected_feasible ? 'Yes' : 'No'}</span>
                <span>{plan.comparison.multi_agent_proposal_count}</span>
              </div>
            </section>
          </div>

          <section id="agent-bids" className="planner-card bid-card">
            <h3>Auditable bid comparison</h3>
            <div className="table-scroll">
              <table className="bid-table">
                <thead><tr>
                  <th>Agent</th><th>Changes</th><th>Estimated total</th><th>Savings</th>
                  <th>Original estimate / rates</th><th>Budget</th><th>Feasible</th><th>Constraint violations</th><th>Decision</th>
                </tr></thead>
                <tbody>{plan.bids.map(bid => (
                  <tr key={bid.bid_id} className={plan.selected_bid?.bid_id === bid.bid_id ? 'selected-row' : ''}>
                    <td>{bid.agent_name}</td>
                    <td>{bid.proposed_changes.length ? bid.proposed_changes.join(' ') : 'Original trip estimate'}</td>
                    <td>{formatMoney(bid.proposed_total_cost, bid.comparison_currency)}</td>
                    <td>{formatMoney(bid.savings_amount, bid.comparison_currency)}</td>
                    <td>{formatMoney(Object.values(bid.original_itemized_costs).reduce((sum, value) => sum + value, 0), bid.original_currency)}; demo rates: {Object.entries(bid.exchange_rates).map(([category, rate]) => `${category} ${rate}`).join(', ')}</td>
                    <td>{formatMoney(bid.budget_limit, bid.comparison_currency)}</td>
                    <td>{bid.feasible ? 'Yes' : 'No'}</td>
                    <td>{bid.constraint_violations.length ? bid.constraint_violations.join(', ') : 'None'}</td>
                    <td>{bid.decision_reason}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </section>

          {plan.selected_bid && (
            <section className="planner-card">
              <h3>Selected itemized estimate · {plan.selected_bid.comparison_currency}</h3>
              <div className="evidence-grid">
                {Object.entries(plan.selected_bid.itemized_costs).map(([category, amount]) => (
                  <div key={category}><strong>{category}</strong><span>{formatMoney(amount, plan.selected_bid.comparison_currency)}</span></div>
                ))}
              </div>
            </section>
          )}

          <section className="planner-card">
            <h3>Suggested itinerary · estimates, not bookings</h3>
            <ol className="supervisor-trace">
              {plan.itinerary.map(day => (
                <li key={day.day}>
                  <strong>Day {day.day} · {day.date}</strong> — {day.plan}
                  <span> Estimated activities: {formatMoney(day.estimated_activity_cost, day.currency)} per traveler.</span>
                </li>
              ))}
            </ol>
          </section>

          <section className="planner-card">
            <h3>Planning conversation · {plan.conversation.length} messages</h3>
            <ol className="conversation-list">
              {plan.conversation.map((message, index) => (
                <li key={`${index}-${message.role}`}><strong>{message.role}:</strong> {message.content}</li>
              ))}
            </ol>
          </section>

          {plan.prior_decisions.length > 0 && (
            <section className="planner-card">
              <h3>Earlier decisions retained in this thread</h3>
              <ol className="conversation-list">
                {plan.prior_decisions.map((decision, index) => (
                  <li key={index}>
                    <strong>{decision.selected_bid?.agent_name || 'No feasible bid'}</strong>
                    {' — '}{decision.rationale}
                    {decision.selected_bid && (
                      <span> Selected estimate: {formatMoney(decision.selected_bid.proposed_total_cost, decision.currency)}.</span>
                    )}
                  </li>
                ))}
              </ol>
            </section>
          )}

          <section className="planner-card">
            <h3>Supervisor execution trace</h3>
            <ol className="supervisor-trace">
              {plan.trace.map(item => <li key={item.step}><strong>{item.agent}</strong> — {item.event}</li>)}
            </ol>
          </section>
        </div>
      )}
    </section>
  )
}
