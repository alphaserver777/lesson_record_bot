import React, { useEffect, useRef, useState } from 'react'
import { api, authByTelegram } from './api'

class ViewErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, message: '' }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, message: String(error?.message || error || 'render error') }
  }

  componentDidCatch() {}

  render() {
    if (this.state.hasError) {
      return (
        <div className="toast error">
          Ошибка интерфейса: {this.state.message}
        </div>
      )
    }
    return this.props.children
  }
}

function Card({ title, subtitle, children, actions, ...props }) {
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

function Pill({ label, value, tone = 'default' }) {
  return (
    <div className={`pill ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function dayName(index) {
  return ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][index] || '—'
}

function nearestBooking(singleBookings) {
  const now = new Date()
  const future = (singleBookings || [])
    .map(b => ({ ...b, at: new Date(`${b.date}T${b.time}:00`) }))
    .filter(b => !Number.isNaN(b.at.getTime()) && b.at >= now)
    .sort((a, b) => a.at - b.at)
  return future[0] || null
}

function formatDateRu(isoDate) {
  try {
    return new Date(`${isoDate}T00:00:00`).toLocaleDateString('ru-RU', { day: '2-digit', month: 'long', year: 'numeric' })
  } catch {
    return isoDate
  }
}

function formatShortLessonLabel(isoDate, time) {
  try {
    const dt = new Date(`${isoDate}T${time || '00:00'}:00`)
    const weekday = dt.toLocaleDateString('ru-RU', { weekday: 'short' })
    const dateShort = dt.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' }).replace('.', '')
    return `${weekday}, ${dateShort} • ${time || '--:--'}`
  } catch {
    return `${isoDate} • ${time || '--:--'}`
  }
}

function shiftMonth(ym, diff) {
  const [y, m] = ym.split('-').map(Number)
  const dt = new Date(y, (m - 1) + diff, 1)
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}`
}

function formatMonthRu(ym) {
  const [y, m] = ym.split('-').map(Number)
  try {
    return new Date(y, m - 1, 1).toLocaleDateString('ru-RU', { month: 'long' })
  } catch {
    return ym
  }
}

function normalizeErrorMessage(raw) {
  const text = String(raw || '').trim()
  if (!text || text === '{}' || text === 'null' || text === 'undefined') {
    return ''
  }
  if (text.includes('OUTSIDE_WORKING_HOURS')) {
    return 'Это время вне рабочего расписания.'
  }
  if (text.includes('INVALID_TIME_STEP')) {
    return 'Неверный шаг времени. Используйте формат HH:MM с шагом 5 минут.'
  }
  if (text.includes('SLOT_BUSY')) {
    return 'Слот уже занят. Выберите другое время.'
  }
  return text
}

function UserView({ token, appUser, tgUser }) {
  const currentMonth = new Date().toISOString().slice(0, 7)
  const [month, setMonth] = useState(() => currentMonth)
  const [calendar, setCalendar] = useState([])
  const [date, setDate] = useState('')
  const [slots, setSlots] = useState([])
  const [selectedTime, setSelectedTime] = useState('')
  const [bookings, setBookings] = useState({ single: [], regular: [] })
  const [profile, setProfile] = useState(null)
  const [activeTab, setActiveTab] = useState('home')
  const [lessonType, setLessonType] = useState('single')
  const [duration, setDuration] = useState(60)
  const [now, setNow] = useState(() => new Date())
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [calendarLoading, setCalendarLoading] = useState(true)
  const [calendarReady, setCalendarReady] = useState(false)
  const [calendarRetryTick, setCalendarRetryTick] = useState(0)
  const [bookingsLoading, setBookingsLoading] = useState(true)
  const [profileLoading, setProfileLoading] = useState(true)
  const [bookingsReady, setBookingsReady] = useState(false)
  const [bookingsRetryTick, setBookingsRetryTick] = useState(0)
  const calendarReqRef = useRef(0)

  async function loadCalendar() {
    const reqId = ++calendarReqRef.current
    setCalendarLoading(true)
    try {
      const data = await api(`/api/user/calendar?month=${month}`, { token })
      if (reqId !== calendarReqRef.current) return
      setCalendar(data.days)
      setCalendarReady(true)
      setError('')
      return true
    } finally {
      if (reqId === calendarReqRef.current) setCalendarLoading(false)
    }
  }

  async function loadSlots(d) {
    setDate(d)
    setSelectedTime('')
    const data = await api(`/api/user/slots?date=${d}&duration=${duration}`, { token })
    setSlots(data.slots)
    setError('')
  }

  async function loadBookings(silent = false) {
    if (!silent) setBookingsLoading(true)
    try {
      const data = await api('/api/user/bookings', { token })
      setBookings({
        single: Array.isArray(data?.single) ? data.single : [],
        regular: Array.isArray(data?.regular) ? data.regular : [],
      })
      setBookingsReady(true)
      setError('')
      return true
    } finally {
      if (!silent) setBookingsLoading(false)
    }
  }

  async function loadMe() {
    setProfileLoading(true)
    try {
      const data = await api('/api/me', { token })
      setProfile(data.profile || null)
      setError('')
    } finally {
      setProfileLoading(false)
    }
  }

  async function book(time) {
    setError('')
    setSuccess('')
    try {
      await api('/api/user/book', {
        token,
        method: 'POST',
        body: { date, time, duration, mode: lessonType }
      })
      // Optimistic update so booking is visible in "Ваши занятия" immediately.
      setBookingsLoading(false)
      setBookings(prev => {
        const nextSingle = Array.isArray(prev?.single) ? [...prev.single] : []
        const exists = nextSingle.some(
          item => item?.date === date && item?.time === time && String(item?.status || '') === 'pending'
        )
        if (!exists) {
          nextSingle.unshift({
            date,
            time,
            duration,
            status: 'pending',
            kind: lessonType === 'regular' ? 'regular' : 'single',
          })
        }
        return { ...(prev || {}), single: nextSingle }
      })
      await loadSlots(date)
      await loadBookings()
      setSelectedTime('')
      setSuccess(`Заявка отправлена на согласование: ${date} ${time}`)
    } catch (e) {
      setError(normalizeErrorMessage(e.message || e))
    }
  }

  useEffect(() => {
    setCalendarReady(false)
    loadCalendar().catch(e => setError(normalizeErrorMessage(e.message || e)))
  }, [month])

  useEffect(() => {
    if (calendarReady || calendarLoading) return
    const timer = setTimeout(() => setCalendarRetryTick(v => v + 1), 1800)
    return () => clearTimeout(timer)
  }, [calendarReady, calendarLoading, calendarRetryTick])

  useEffect(() => {
    if (!calendarReady && !calendarLoading) {
      loadCalendar().catch(e => setError(normalizeErrorMessage(e.message || e)))
    }
  }, [calendarRetryTick])

  useEffect(() => {
    ;(async () => {
      await loadBookings().catch(() => {})
      await loadMe().catch(() => {})
    })()
  }, [])

  useEffect(() => {
    if (bookingsReady || bookingsLoading) return
    const timer = setTimeout(() => setBookingsRetryTick(v => v + 1), 1800)
    return () => clearTimeout(timer)
  }, [bookingsReady, bookingsLoading, bookingsRetryTick])

  useEffect(() => {
    if (!bookingsReady && !bookingsLoading) {
      loadBookings().catch(() => {})
    }
  }, [bookingsRetryTick])

  useEffect(() => {
    const timer = setInterval(() => {
      loadBookings(true).catch(() => {})
    }, 20000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (activeTab === 'home') {
      loadBookings(true).catch(() => {})
    }
  }, [activeTab])

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 30000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!date) return
    loadSlots(date).catch(e => setError(normalizeErrorMessage(e.message || e)))
  }, [duration])

  const singleBookings = Array.isArray(bookings?.single) ? bookings.single : []
  const regularBookings = Array.isArray(bookings?.regular) ? bookings.regular : []
  const nextLesson = nearestBooking(singleBookings)
  const hasAvatar = Boolean(tgUser?.photo_url)
  const displayName = profile?.full_name || appUser?.full_name || tgUser?.first_name || `ID ${appUser?.telegram_id || ''}`
  const username = appUser?.username || tgUser?.username || ''
  const initials = (displayName || 'U')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map(chunk => chunk[0]?.toUpperCase())
    .join('')
  const availableSlots = slots.filter(s => s.available)
  const groupedSlots = availableSlots.reduce((acc, slot) => {
    const hour = slot.time.slice(0, 2)
    if (!acc[hour]) acc[hour] = []
    acc[hour].push(slot)
    return acc
  }, {})
  const groupedHourKeys = Object.keys(groupedSlots).sort((a, b) => Number(a) - Number(b))
  const selectedHour = selectedTime ? selectedTime.slice(0, 2) : ''
  const nowTs = Date.now()
  const upcomingSingles = singleBookings
    .filter(s => {
      if (String(s?.status || '') === 'pending') return true
      const ts = new Date(`${s.date}T${s.time}:00`).getTime()
      return !Number.isNaN(ts) && ts >= nowTs
    })
    .sort((a, b) => new Date(`${a.date}T${a.time}:00`) - new Date(`${b.date}T${b.time}:00`))
  const archivedSingles = singleBookings
    .filter(s => {
      if (String(s?.status || '') === 'pending') return false
      const ts = new Date(`${s.date}T${s.time}:00`).getTime()
      return !Number.isNaN(ts) && ts < nowTs
    })
    .sort((a, b) => new Date(`${b.date}T${b.time}:00`) - new Date(`${a.date}T${a.time}:00`))

  const upcoming = [
    ...upcomingSingles.slice(0, 8).map(s => ({
      label: formatShortLessonLabel(s.date, s.time),
      type: s.status === 'pending' ? 'На согласовании' : (s.kind === 'regular' ? 'Регулярное' : 'Разовое'),
    })),
    ...regularBookings.slice(0, 8).map(r => ({ label: `${dayName(r.day_of_week)} • ${r.time || '--:--'}`, type: 'Регулярное' })),
  ].slice(0, 8)
  const archive = archivedSingles.slice(0, 10).map(s => ({
    label: formatShortLessonLabel(s.date, s.time),
    type: s.kind === 'regular' ? 'Регулярное' : 'Разовое',
  }))
  const nowDate = now.toLocaleDateString('ru-RU', { day: '2-digit', month: 'long', year: 'numeric' })
  const nowTime = now.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  const [year, mon] = month.split('-').map(Number)
  const firstWeekday = new Date(year, mon - 1, 1).getDay()
  const leadingEmpty = (firstWeekday + 6) % 7
  const calendarCells = [...Array(leadingEmpty).fill(null), ...calendar]
  const weekDays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

  return (
    <div className="mini-layout">
      <section className="mini-cover">
        <div className="mini-cover-overlay" />
        <div className="mini-cover-head">
          <div className="mini-brand">
            <div className="brand-logo">LP</div>
            <div className="brand-meta">
              <strong>LESSON PLANNER</strong>
              <span>мини-приложение</span>
            </div>
          </div>
          <button className="circle-btn">◌</button>
        </div>
      </section>

      <div className="mini-body">
        {activeTab === 'home' ? (
          <div className="stack">
            <Card title={`Привет, ${displayName}`} subtitle="Общая информация">
              {profileLoading ? (
                <div className="home-skeleton">
                  <div className="skeleton-row">
                    <div className="skeleton-box skeleton-avatar" />
                    <div className="skeleton-col">
                      <div className="skeleton-box skeleton-line-lg" />
                      <div className="skeleton-box skeleton-line-md" />
                      <div className="skeleton-box skeleton-line-sm" />
                    </div>
                  </div>
                  <div className="skeleton-row">
                    <div className="skeleton-box skeleton-badge" />
                    <div className="skeleton-box skeleton-badge" />
                  </div>
                </div>
              ) : (
                <>
                  <div className="welcome">
                    <div className="avatar-wrap">
                      {hasAvatar ? (
                        <img src={tgUser.photo_url} alt={displayName} className="avatar" />
                      ) : (
                        <div className="avatar avatar-fallback">{initials}</div>
                      )}
                    </div>
                    <div className="welcome-meta">
                      <strong>{displayName}</strong>
                      <span>{username ? `@${username.replace('@', '')}` : `Telegram ID: ${appUser?.telegram_id || '—'}`}</span>
                      <span>{profile?.telephone ? `Телефон: ${profile.telephone}` : 'Телефон не указан'}</span>
                    </div>
                  </div>
                  <div className="lesson-strip">
                    <div className="lesson-badge">
                      <small>Текущая дата и время</small>
                      <strong>{nowDate} • {nowTime}</strong>
                    </div>
                    <div className="lesson-badge">
                      <small>Ближайшее занятие</small>
                      <strong>{nextLesson ? `${formatDateRu(nextLesson.date)} • ${nextLesson.time}` : 'Пока не запланировано'}</strong>
                    </div>
                  </div>
                </>
              )}
            </Card>

            <Card title="Ваши занятия" subtitle="Дата, время и тип">
              {!bookingsReady || bookingsLoading ? (
                <div className="home-skeleton">
                  <div className="skeleton-box skeleton-line-lg" />
                  <div className="skeleton-box skeleton-line-lg" />
                  <div className="skeleton-box skeleton-line-lg" />
                </div>
              ) : upcoming.length ? (
                <ul className="list">
                  {upcoming.map((item, idx) => (
                    <li key={`${item.label}-${idx}`}>
                      <span>{item.label}</span>
                      <strong>{item.type}</strong>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="empty">Пока нет занятий. Перейдите на вкладку «Записаться».</div>
              )}
            </Card>

            <Card title="Архив" subtitle="История прошедших занятий">
              {!bookingsReady || bookingsLoading ? (
                <div className="home-skeleton">
                  <div className="skeleton-box skeleton-line-lg" />
                  <div className="skeleton-box skeleton-line-lg" />
                </div>
              ) : archive.length ? (
                <ul className="list">
                  {archive.map((item, idx) => (
                    <li key={`${item.label}-${idx}`}>
                      <span>{item.label}</span>
                      <strong>{item.type}</strong>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="empty">Пока нет прошедших занятий.</div>
              )}
            </Card>
          </div>
        ) : null}

        {activeTab === 'book' ? (
          <div className="stack">
            <Card title="Тип занятия" subtitle="Выберите формат">
              <div className="segmented">
                <button className={lessonType === 'single' ? 'seg active' : 'seg'} onClick={() => setLessonType('single')}>Разовое</button>
                <button className={lessonType === 'regular' ? 'seg active' : 'seg'} onClick={() => setLessonType('regular')}>Регулярное</button>
              </div>
            </Card>

            <Card
              title="Выбор даты"
              subtitle="Серые даты недоступны. Нажмите активную дату для выбора времени."
              actions={
                <div className="month-switch">
                  <button
                    className="chip ok"
                    onClick={() => setMonth(prev => shiftMonth(prev, -1))}
                    disabled={month <= currentMonth || calendarLoading}
                    aria-label="Предыдущий месяц"
                  >
                    {'<'}
                  </button>
                  <strong>{formatMonthRu(month)}</strong>
                  <button
                    className="chip ok"
                    onClick={() => setMonth(prev => shiftMonth(prev, 1))}
                    disabled={calendarLoading}
                    aria-label="Следующий месяц"
                  >
                    {'>'}
                  </button>
                </div>
              }
            >
              {!calendarReady || calendarLoading ? (
                <div className="calendar-skeleton">
                  {Array.from({ length: 35 }).map((_, idx) => (
                    <div key={`cal-skeleton-${idx}`} className="skeleton-box skeleton-day" />
                  ))}
                </div>
              ) : (
                <>
                  <div className="weekdays">
                    {weekDays.map(w => <div key={w}>{w}</div>)}
                  </div>
                  <div className="calendar-grid">
                    {calendarCells.map((day, idx) => (
                      day ? (
                        <button
                          key={day.date}
                          disabled={!day.available}
                          className={`calendar-day ${day.available ? 'on' : 'off'} ${date === day.date ? 'selected' : ''}`}
                          onClick={() => loadSlots(day.date)}
                          title={day.available ? `${day.slots_count || 0} свободно` : day.reason || 'Недоступно'}
                        >
                          <span>{Number(day.date.slice(8))}</span>
                        </button>
                      ) : (
                        <div key={`empty-${idx}`} className="calendar-day empty" />
                      )
                    ))}
                  </div>
                </>
              )}
            </Card>

            <Card title={date ? `Время на ${formatDateRu(date)}` : 'Выберите дату'} subtitle="Только свободные слоты">
              <div className="segmented">
                <button className={duration === 60 ? 'seg active' : 'seg'} onClick={() => setDuration(60)}>60 мин</button>
                <button className={duration === 90 ? 'seg active' : 'seg'} onClick={() => setDuration(90)}>90 мин</button>
                <button className={duration === 120 ? 'seg active' : 'seg'} onClick={() => setDuration(120)}>120 мин</button>
              </div>
              {!date ? (
                <div className="empty">Сначала выберите день.</div>
              ) : availableSlots.length ? (
                <div className="slots-hours">
                  {groupedHourKeys.map(hour => (
                    <div key={hour} className="slots-hour-block">
                      <div className="slots-hour-title">{hour}:00</div>
                      <div className="slots-grid">
                        {groupedSlots[hour].map(s => (
                          <button
                            key={s.time}
                            className={`chip ok ${selectedTime === s.time ? 'active' : ''}`}
                            onClick={() => setSelectedTime(s.time)}
                          >
                            {s.time}
                          </button>
                        ))}
                      </div>
                      {selectedHour === hour ? (
                        <div className="slot-confirm-panel">
                          <div className="slot-confirm-meta">
                            Выбрано: <strong>{selectedTime}</strong> • {duration} мин
                          </div>
                          <button className="btn slot-confirm-btn" onClick={() => book(selectedTime)}>
                            Подтвердить запись
                          </button>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty">На выбранную дату свободного времени нет.</div>
              )}
            </Card>
          </div>
        ) : null}

        {!!success && <div className="toast success">{success}</div>}
        {!!normalizeErrorMessage(error) && <div className="toast error">{normalizeErrorMessage(error)}</div>}
      </div>

      <nav className="bottom-nav bottom-nav-two">
        <button className={`bottom-item ${activeTab === 'home' ? 'active' : ''}`} onClick={() => setActiveTab('home')}><span className="bottom-ico">⌂</span><span>Профиль</span></button>
        <button className={`bottom-item ${activeTab === 'book' ? 'active' : ''}`} onClick={() => setActiveTab('book')}><span className="bottom-ico">◷</span><span>Записаться</span></button>
      </nav>
    </div>
  )
}

function RoutedUserView({ token, user }) {
  const tgUser = window.Telegram?.WebApp?.initDataUnsafe?.user || null
  return <UserView token={token} appUser={user} tgUser={tgUser} />
}

function AdminView({ token }) {
  const [query, setQuery] = useState('')
  const [users, setUsers] = useState([])
  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10))
  const [schedule, setSchedule] = useState([])
  const [broadcast, setBroadcast] = useState('')
  const [stats, setStats] = useState(null)
  const [activeTab, setActiveTab] = useState('home')
  const [error, setError] = useState('')

  async function loadUsers() {
    const path = query ? `/api/admin/users?query=${encodeURIComponent(query)}` : '/api/admin/users'
    const data = await api(path, { token })
    setUsers(data.items || [])
  }

  async function loadSchedule() {
    const data = await api(`/api/admin/schedule/day?date=${day}`, { token })
    setSchedule(data.items || [])
  }

  async function loadStats() {
    const data = await api(`/api/admin/stats/day?date=${day}`, { token })
    setStats(data)
  }

  async function sendBroadcast() {
    await api('/api/admin/broadcast', { token, method: 'POST', body: { message: broadcast, only_unpaid: false } })
    setBroadcast('')
  }

  useEffect(() => {
    ;(async () => {
      await loadUsers().catch(e => setError(String(e.message || e)))
      await loadSchedule().catch(() => {})
      await loadStats().catch(() => {})
    })()
  }, [])

  return (
    <div className="mini-layout">
      <section className="mini-cover">
        <div className="mini-cover-overlay" />
        <div className="mini-cover-head">
          <div className="mini-brand">
            <div className="brand-logo">AD</div>
            <div className="brand-meta">
              <strong>ADMIN DESK</strong>
              <span>управление ботом</span>
            </div>
          </div>
          <button className="circle-btn">◌</button>
        </div>
      </section>

      <div className="mini-body">
        {activeTab === 'home' ? (
          <div className="stack">
            <Card title="Сводка" subtitle="Быстрые показатели">
              <div className="pill-row">
                <Pill label="Клиентов" value={users.length} tone="mint" />
                <Pill label="Слотов в дне" value={schedule.length} tone="blue" />
                <Pill label="Выручка (день)" value={`${stats?.earned_total ?? 0} ₽`} tone="violet" />
              </div>
            </Card>
          </div>
        ) : null}

        {activeTab === 'users' ? (
          <div className="stack">
            <Card title="Пользователи" subtitle="Поиск по имени и телефону" actions={<button className="btn secondary" onClick={loadUsers}>Обновить</button>}>
              <div className="custom-row">
                <input className="input" value={query} onChange={e => setQuery(e.target.value)} placeholder="Поиск имя/телефон" />
                <button className="btn" onClick={loadUsers}>Поиск</button>
              </div>
              <ul className="list list-compact">
                {users.map(u => (
                  <li key={u.telegram_id}>
                    <span>{u.full_name || u.telegram_id}</span>
                    <small>{u.phone || '—'}</small>
                    <strong className={u.blocked ? 'badge bad' : 'badge good'}>{u.blocked ? 'blocked' : 'active'}</strong>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        ) : null}

        {activeTab === 'schedule' ? (
          <div className="stack">
            <Card title="Расписание" subtitle="Срез по выбранному дню" actions={<input type="date" className="input" value={day} onChange={e => setDay(e.target.value)} />}>
              <button
                className="btn"
                onClick={async () => {
                  await loadSchedule()
                  await loadStats()
                }}
              >
                Обновить день
              </button>
              <ul className="list list-compact">
                {schedule.map((s, idx) => (
                  <li key={`${s.hour}-${s.minute}-${idx}`}>
                    <strong>{String(s.hour).padStart(2, '0')}:{String(s.minute).padStart(2, '0')}</strong>
                    <span>{s.full_name}</span>
                    <small>{s.kind}</small>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        ) : null}

        {activeTab === 'system' ? (
          <div className="stack">
            <Card title="Рассылка" subtitle="Единое сообщение всем клиентам">
              <textarea className="input" rows={4} value={broadcast} onChange={e => setBroadcast(e.target.value)} placeholder="Текст сообщения" />
              <button className="btn" disabled={!broadcast.trim()} onClick={() => sendBroadcast().catch(e => setError(String(e.message || e)))}>Отправить</button>
            </Card>
          </div>
        ) : null}

        {!!error && <div className="toast error">{error}</div>}
      </div>

      <nav className="bottom-nav">
        <button className={`bottom-item ${activeTab === 'home' ? 'active' : ''}`} onClick={() => setActiveTab('home')}><span className="bottom-ico">⌂</span><span>Главная</span></button>
        <button className={`bottom-item ${activeTab === 'users' ? 'active' : ''}`} onClick={() => setActiveTab('users')}><span className="bottom-ico">◉</span><span>Клиенты</span></button>
        <button className={`bottom-item ${activeTab === 'schedule' ? 'active' : ''}`} onClick={() => setActiveTab('schedule')}><span className="bottom-ico">▦</span><span>Расписание</span></button>
        <button className={`bottom-item ${activeTab === 'system' ? 'active' : ''}`} onClick={() => setActiveTab('system')}><span className="bottom-ico">⚙</span><span>Система</span></button>
      </nav>
    </div>
  )
}

export default function App() {
  const [token, setToken] = useState('')
  const [user, setUser] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const tg = window.Telegram?.WebApp
    if (tg) {
      tg.ready()
      tg.expand()
      tg.setHeaderColor('#070a14')
      tg.setBackgroundColor('#070a14')
    }

    authByTelegram()
      .then(data => {
        setToken(data.access_token)
        setUser(data.user)
      })
      .catch(e => setError(String(e.message || e)))
  }, [])

  return (
    <main className="app">
      {error ? <div className="toast error">{error}</div> : null}
      {!token ? <div className="loading">Подключаем Mini App...</div> : null}
      {token && user?.role === 'admin' ? (
        <ViewErrorBoundary>
          <AdminView token={token} />
        </ViewErrorBoundary>
      ) : null}
      {token && user?.role !== 'admin' ? (
        <ViewErrorBoundary>
          <RoutedUserView token={token} user={user} />
        </ViewErrorBoundary>
      ) : null}
    </main>
  )
}
