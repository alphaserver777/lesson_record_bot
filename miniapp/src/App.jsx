import React, { useEffect, useState } from 'react'
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
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [calendar, setCalendar] = useState([])
  const [date, setDate] = useState('')
  const [slots, setSlots] = useState([])
  const [customTime, setCustomTime] = useState('')
  const [bookings, setBookings] = useState({ single: [], regular: [] })
  const [profile, setProfile] = useState(null)
  const [activeTab, setActiveTab] = useState('home')
  const [lessonType, setLessonType] = useState('single')
  const [duration, setDuration] = useState(60)
  const [now, setNow] = useState(() => new Date())
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  async function loadCalendar() {
    const data = await api(`/api/user/calendar?month=${month}`, { token })
    setCalendar(data.days)
    setError('')
  }

  async function loadSlots(d) {
    setDate(d)
    const data = await api(`/api/user/slots?date=${d}`, { token })
    setSlots(data.slots)
    setError('')
  }

  async function loadBookings() {
    const data = await api('/api/user/bookings', { token })
    setBookings({
      single: Array.isArray(data?.single) ? data.single : [],
      regular: Array.isArray(data?.regular) ? data.regular : [],
    })
    setError('')
  }

  async function loadMe() {
    const data = await api('/api/me', { token })
    setProfile(data.profile || null)
    setError('')
  }

  async function book(time, mode = 'preset') {
    setError('')
    setSuccess('')
    try {
      await api('/api/user/book', {
        token,
        method: 'POST',
        body: { date, time, duration, mode: lessonType === 'single' ? mode : lessonType }
      })
      await loadSlots(date)
      await loadBookings()
      setSuccess(`Запись создана: ${date} ${time}`)
    } catch (e) {
      setError(normalizeErrorMessage(e.message || e))
    }
  }

  useEffect(() => {
    loadCalendar().catch(e => setError(normalizeErrorMessage(e.message || e)))
  }, [month])

  useEffect(() => {
    ;(async () => {
      await loadBookings().catch(() => {})
      await loadMe().catch(() => {})
    })()
  }, [])

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 30000)
    return () => clearInterval(timer)
  }, [])

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
  const upcoming = [
    ...singleBookings.slice(0, 5).map(s => ({ label: `${formatDateRu(s.date)} • ${s.time}`, type: 'Разовое' })),
    ...regularBookings.slice(0, 5).map(r => ({ label: `${dayName(r.day_of_week)} • ${r.time || '--:--'}`, type: 'Регулярное' })),
  ].slice(0, 5)
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
            </Card>

            <Card title="Ваши занятия" subtitle="Дата, время и тип">
              {upcoming.length ? (
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
              actions={<input type="month" value={month} onChange={e => setMonth(e.target.value)} className="input" />}
            >
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
            </Card>

            <Card title={date ? `Время на ${formatDateRu(date)}` : 'Выберите дату'} subtitle="Слоты + нестандартное время">
              <div className="segmented">
                <button className={duration === 45 ? 'seg active' : 'seg'} onClick={() => setDuration(45)}>45 мин</button>
                <button className={duration === 60 ? 'seg active' : 'seg'} onClick={() => setDuration(60)}>60 мин</button>
                <button className={duration === 90 ? 'seg active' : 'seg'} onClick={() => setDuration(90)}>90 мин</button>
              </div>
              {!date ? (
                <div className="empty">Сначала выберите день.</div>
              ) : availableSlots.length ? (
                <div className="slots-grid">
                  {availableSlots.map(s => (
                    <button key={s.time} className="chip ok" onClick={() => book(s.time)}>
                      {s.time}
                    </button>
                  ))}
                </div>
              ) : (
                <div className="empty">На выбранную дату свободного времени нет.</div>
              )}
              <div className="custom-row">
                <input value={customTime} onChange={e => setCustomTime(e.target.value)} placeholder="Нестандартное время HH:MM" className="input" />
                <button className="btn" disabled={!date || !customTime} onClick={() => book(customTime, 'custom')}>Записаться</button>
              </div>
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
