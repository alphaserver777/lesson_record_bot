export function Pill({ label, value, tone = 'default' }) {
  return (
    <div className={`pill ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}
