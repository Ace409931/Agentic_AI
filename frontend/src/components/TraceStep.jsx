import { useState } from 'react'

const STEP_ICONS = {
  user_request:   '💬',
  agent_decision: '🤖',
  tool_call:      '⚡',
  tool_result:    '✅',
  final_answer:   '🎯',
}

export default function TraceStep({ event, index }) {
  const [expanded, setExpanded] = useState(false)
  const isDecision = event.type === 'agent_decision'
  const hasDetail = event.arguments || event.result

  const animationDelay = `${index * 80}ms`

  return (
    <div
      className={`trace-step type-${event.type}`}
      id={`trace-step-${event.step}`}
      style={{ animationDelay }}
    >
      <div className="trace-step-icon-col">
        <div className="trace-step-icon" title={event.type}>
          {STEP_ICONS[event.type] || '•'}
        </div>
      </div>

      <div className="trace-step-content">
        <div className="trace-step-header">
          <span className="trace-step-number">#{event.step}</span>
          <span className="trace-step-title">{event.title}</span>
          {isDecision && (
            <span className="agent-decision-chip" id={`decision-chip-${event.step}`}>
              🤖 Agent selected next tool
            </span>
          )}
        </div>

        <p className="trace-step-desc">{event.description}</p>

        {hasDetail && (
          <button
            className="trace-step-expand-btn"
            onClick={() => setExpanded(!expanded)}
            id={`expand-btn-${event.step}`}
          >
            {expanded ? '▾ Hide details' : '▸ Show details'}
          </button>
        )}

        {expanded && hasDetail && (
          <div className="trace-step-detail">
            {event.tool && (
              <div className="detail-row">
                <span className="detail-key">Tool</span>
                <span className="detail-val">{event.tool}</span>
              </div>
            )}
            {event.arguments && typeof event.arguments === 'object' && !Array.isArray(event.arguments) && Object.entries(event.arguments).map(([k, v]) => (
              <div className="detail-row" key={k}>
                <span className="detail-key">{k}</span>
                <span className="detail-val">{String(v)}</span>
              </div>
            ))}
            {event.result && (
              <div className="detail-row">
                <span className="detail-key">Result</span>
                <span className="detail-val">{event.result}</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
