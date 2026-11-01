export default function ChatInput({ query, setQuery, onSubmit, loading }) {
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      if (!loading && query.trim()) onSubmit()
    }
  }

  return (
    <div className="input-section">
      <label className="input-label" htmlFor="query-input">
        Your travel budget question
      </label>
      <textarea
        id="query-input"
        className="query-textarea"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="e.g. I have a budget of ₹100,000 and my estimated trip cost is €900. Can I afford it?"
        disabled={loading}
        rows={5}
      />
      <button
        id="analyze-btn"
        className="btn-primary"
        onClick={onSubmit}
        disabled={loading || !query.trim()}
        aria-busy={loading}
      >
        {loading ? (
          <>
            <span className="spinner" />
            Analyzing trip…
          </>
        ) : (
          <>
            <span>🔍</span>
            Analyze Trip
          </>
        )}
      </button>
      {!loading && (
        <p style={{ fontSize: '0.68rem', color: 'var(--text-muted)', textAlign: 'center' }}>
          Ctrl+Enter to submit
        </p>
      )}
    </div>
  )
}
