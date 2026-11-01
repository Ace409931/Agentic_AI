import { useState } from 'react'

const RATES = [
  { from: 'EUR', to: 'INR', rate: '95.0' },
  { from: 'EUR', to: 'USD', rate: '1.08' },
  { from: 'EUR', to: 'GBP', rate: '0.86' },
  { from: 'USD', to: 'INR', rate: '88.0' },
  { from: 'USD', to: 'GBP', rate: '0.79' },
  { from: 'GBP', to: 'INR', rate: '108.5' },
  { from: 'INR', to: 'USD', rate: '0.011' },
]

export default function ExchangeRates() {
  const [open, setOpen] = useState(false)

  return (
    <div className="exchange-rates">
      <button
        id="exchange-rates-toggle"
        className={`exchange-rates-toggle ${open ? 'open' : ''}`}
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <span>💱 Exchange Rates (demonstration)</span>
        <span className="chevron">▾</span>
      </button>
      <div className={`exchange-rates-body ${open ? 'open' : ''}`}>
        <table className="rates-table">
          <thead>
            <tr>
              <th>From</th>
              <th>To</th>
              <th>Rate</th>
            </tr>
          </thead>
          <tbody>
            {RATES.map((r) => (
              <tr key={`${r.from}-${r.to}`}>
                <td>{r.from}</td>
                <td>{r.to}</td>
                <td>{r.rate}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="rates-disclaimer">
          ⚠️ These are fixed demonstration rates, not live market data. Not suitable for real financial decisions.
        </p>
      </div>
    </div>
  )
}
