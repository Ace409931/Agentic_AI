export default function Header({ health }) {
  return (
    <header className="header">
      <div className="header-brand">
        <div className="header-icon">✈️</div>
        <div>
          <h1 className="header-title">Travel Budget Planner</h1>
          <p className="header-subtitle">Autonomous AI Agent — Currency &amp; Feasibility Analysis</p>
        </div>
      </div>
      <div className="header-caption">
        {health?.ollama_reachable && health?.model_available && (
          <span className="header-dot" title="Ollama connected" />
        )}
        <span>Powered by Ollama</span>
        <span>·</span>
        <span>{health?.model || 'Local LLM'}</span>
        <span>·</span>
        <span>LangGraph</span>
      </div>
    </header>
  )
}
