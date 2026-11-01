import TraceStep from './TraceStep.jsx'
import ToolCard from './ToolCard.jsx'

function getToolStatus(toolName, trace) {
  const toolEvents = trace.filter(e => e.tool === toolName)
  if (toolEvents.some(e => e.type === 'tool_result')) return 'done'
  if (toolEvents.some(e => e.type === 'tool_call' || e.type === 'agent_decision')) return 'running'
  return 'idle'
}

export default function ExecutionTrace({ trace, loading, submittedQuery }) {
  const currencyStatus = getToolStatus('convert_currency', trace)
  const budgetStatus = getToolStatus('check_budget_feasibility', trace)

  if (loading && trace.length === 0) {
    return (
      <div className="trace-section">
        <div className="trace-header">
          <span className="trace-title">⚡ Agent Execution Trace</span>
        </div>
        <div className="loading-trace">
          {[1, 2, 3].map(i => (
            <div className="skeleton-step" key={i}>
              <div className="skeleton-circle" />
              <div className="skeleton-lines">
                <div className="skeleton-line short" />
                <div className="skeleton-line medium" />
                <div className="skeleton-line long" />
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (trace.length === 0) return null

  return (
    <div className="trace-section">
      <div className="trace-header">
        <span className="trace-title">
          ⚡ Agent Execution Trace
          <span className="trace-count">{trace.length} steps</span>
        </span>
      </div>
      {submittedQuery && (
        <p className="trace-request"><strong>Submitted request:</strong> {submittedQuery}</p>
      )}

      {/* Tool status cards */}
      <div className="tool-cards" style={{ marginBottom: '1.25rem' }}>
        <ToolCard toolName="convert_currency" status={currencyStatus} />
        <ToolCard toolName="check_budget_feasibility" status={budgetStatus} />
      </div>

      {/* Timeline */}
      <div className="trace-timeline" id="trace-timeline">
        {trace.map((event, idx) => (
          <TraceStep key={`${event.step}-${event.type}`} event={event} index={idx} />
        ))}
      </div>
    </div>
  )
}
