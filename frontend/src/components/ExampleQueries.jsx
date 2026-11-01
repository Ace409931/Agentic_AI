const EXAMPLES = [
  {
    id: 'feasible',
    label: '✅ Feasible',
    badgeClass: 'badge-green',
    text: 'I have a budget of ₹100,000 and my estimated trip cost is €900. Can I afford it?',
  },
  {
    id: 'not-feasible',
    label: '⚠️ Not Feasible',
    badgeClass: 'badge-amber',
    text: 'I have a budget of ₹50,000 and my estimated trip cost is €900. Can I afford it?',
  },
]

export default function ExampleQueries({ onSelect, disabled = false }) {
  return (
    <div className="examples-section">
      <span className="examples-label">Try an example</span>
      {EXAMPLES.map((ex) => (
        <button
          key={ex.id}
          id={`example-${ex.id}`}
          className="btn-example"
          onClick={() => onSelect(ex.text)}
          title={ex.text}
          disabled={disabled}
        >
          <span className={`example-badge ${ex.badgeClass}`}>{ex.label}</span>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {ex.text}
          </span>
        </button>
      ))}
    </div>
  )
}
