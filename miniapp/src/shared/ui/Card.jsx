export function Card({ title, subtitle, children, actions, ...props }) {
  return (
    <section className="card" {...props}>
      <div className="card-head">
        <div>
          <h3>{title}</h3>
          {subtitle ? <p className="card-subtitle">{subtitle}</p> : null}
        </div>
        {actions}
      </div>
      {children}
    </section>
  )
}
