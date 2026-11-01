function fmt(num, currency) {
  if (num == null) return '—'
  const sym = { INR: '₹', EUR: '€', USD: '$', GBP: '£' }[currency] || ''
  return `${sym}${num.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

export default function ResultCard({ result }) {
  const { answer, feasible, total_cost, budget, currency } = result

  const isFeasible = feasible === true
  const isNotFeasible = feasible === false
  const isUnknown = feasible == null

  return (
    <div className="result-card" id="result-card">
      <div className="result-header">
        <span className="result-header-label">Analysis Result</span>
        {isFeasible && (
          <span className="feasibility-badge feasible" id="badge-feasible">
            ✓ Feasible
          </span>
        )}
        {isNotFeasible && (
          <span className="feasibility-badge not-feasible" id="badge-not-feasible">
            ✗ Not Feasible
          </span>
        )}
        {isUnknown && (
          <span className="feasibility-badge unknown" id="badge-unknown">
            ? Undetermined
          </span>
        )}
      </div>

      <p className="result-request"><strong>Submitted question:</strong> {result.query}</p>

      <div className="stat-row">
        <div className="stat-item">
          <div className="stat-label">Trip Cost</div>
          <div className="stat-value" id="stat-cost">
            {fmt(total_cost, currency)}
          </div>
        </div>
        <div className="stat-item">
          <div className="stat-label">Budget</div>
          <div className="stat-value" id="stat-budget">
            {fmt(budget, currency)}
          </div>
        </div>
        <div className="stat-item">
          <div className="stat-label">{isFeasible ? 'Remaining' : isNotFeasible ? 'Over Budget' : 'Status'}</div>
          <div className={`stat-value ${isFeasible ? 'positive' : isNotFeasible ? 'negative' : ''}`} id="stat-remaining">
            {isFeasible ? fmt(result.remaining, currency)
             : isNotFeasible ? fmt(result.overage, currency)
             : '—'}
          </div>
        </div>
      </div>

      <div className="result-answer" id="result-answer">
        {answer}
      </div>
    </div>
  )
}
