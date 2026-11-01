const TOOL_META = {
  convert_currency: {
    icon: '💱',
    name: 'Currency Converter',
    id: 'tool-card-currency',
  },
  check_budget_feasibility: {
    icon: '📊',
    name: 'Budget Feasibility',
    id: 'tool-card-budget',
  },
}

export default function ToolCard({ toolName, status }) {
  const meta = TOOL_META[toolName] || {
    icon: '🔧',
    name: toolName,
    id: `tool-card-${toolName}`,
  }

  const statusText = {
    idle: 'Ready',
    running: 'Running…',
    done: 'Done ✓',
  }[status] || 'Ready'

  return (
    <div className={`tool-card ${status === 'running' ? 'running' : status === 'done' ? 'done' : ''}`} id={meta.id}>
      <div className="tool-card-header">
        <span className="tool-icon">{meta.icon}</span>
        <span className="tool-status-dot" />
      </div>
      <div className="tool-name">{meta.name}</div>
      <div className="tool-status-text">{statusText}</div>
    </div>
  )
}
