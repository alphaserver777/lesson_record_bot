export function Card({ title, subtitle, children, actions, ...props }) {
  const legacyCampaignCard = title === 'Период работы кампании' || title === 'Визуальная воронка кампании' || subtitle === 'Рабочая карточка кампании: реклама → лид → продажа'
  if (legacyCampaignCard) return null
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
