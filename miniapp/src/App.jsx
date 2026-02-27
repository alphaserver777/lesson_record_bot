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
  const [activeTab, setActiveTab] = useState('main')
  const [error, setError] = useState('')
  const [dashboardToday, setDashboardToday] = useState([])
  const [dashboardKpi, setDashboardKpi] = useState(null)
  const [monthActivity, setMonthActivity] = useState([])

  const [query, setQuery] = useState('')
  const [usersPage, setUsersPage] = useState(1)
  const [users, setUsers] = useState([])
  const [usersTotal, setUsersTotal] = useState(0)
  const [clientOptions, setClientOptions] = useState([])
  const [clientSearch, setClientSearch] = useState('')
  const [selectedUser, setSelectedUser] = useState(null)
  const [selectedUserUpcoming, setSelectedUserUpcoming] = useState([])
  const [selectedUserArchive, setSelectedUserArchive] = useState([])
  const [userEdit, setUserEdit] = useState({ full_name: '', telephone: '', price: '', balance_set: '', balance_add: '' })

  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10))
  const [adminMonth, setAdminMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [scheduleMode, setScheduleMode] = useState('booked')
  const [scheduleAssignMode, setScheduleAssignMode] = useState('single')
  const [scheduleDuration, setScheduleDuration] = useState(60)
  const [scheduleMonthDays, setScheduleMonthDays] = useState([])
  const [schedule, setSchedule] = useState([])
  const [freeSlots, setFreeSlots] = useState([])
  const [selectedFreeTime, setSelectedFreeTime] = useState('')

  const [lessonForm, setLessonForm] = useState({
    telegram_id: '',
  })

  const [approvals, setApprovals] = useState([])
  const [selectedApproval, setSelectedApproval] = useState(null)

  const [manualPay, setManualPay] = useState({
    telegram_id: '',
    date: new Date().toISOString().slice(0, 10),
    time: '18:00',
    amount: '',
    duration: 60,
  })
  const [debtors, setDebtors] = useState([])

  const [broadcast, setBroadcast] = useState('')
  const [broadcastOnlyUnpaid, setBroadcastOnlyUnpaid] = useState(false)

  const [statsPeriod, setStatsPeriod] = useState('day')
  const [stats, setStats] = useState(null)

  const [systemHealth, setSystemHealth] = useState(null)
  const [backupStatus, setBackupStatus] = useState(null)

  const adminTabs = [
    ['main', 'Главная'],
    ['requests', 'Заявки'],
    ['schedule', 'Расписание'],
    ['clients', 'Клиенты'],
    ['finance', 'Финансы'],
    ['more', 'Ещё'],
  ]

  async function loadUsers() {
    const path = `/api/admin/users?page=${usersPage}&page_size=20${query ? `&query=${encodeURIComponent(query)}` : ''}`
    const data = await api(path, { token })
    setUsers(data.items || [])
    setUsersTotal(data.total || 0)
  }

  async function loadClientOptions() {
    const data = await api('/api/admin/users?page=1&page_size=500', { token })
    setClientOptions(data.items || [])
  }

  async function loadDashboard() {
    const today = await api('/api/admin/dashboard/today', { token })
    setDashboardToday(today.agenda || [])
    setDashboardKpi(today.kpi || null)

    const now = new Date()
    const year = now.getFullYear()
    const month = now.getMonth() + 1
    const activity = await api(`/api/admin/stats/month/activity?year=${year}&month=${month}`, { token })
    setMonthActivity(activity.days || [])
  }

  async function selectUser(telegramId) {
    const data = await api(`/api/admin/users/${telegramId}`, { token })
    setSelectedUser(data)
    setUserEdit({
      full_name: data.full_name || '',
      telephone: data.phone || '',
      price: String(data.price ?? ''),
      balance_set: String(data.balance_lessons ?? ''),
      balance_add: '',
    })
    const upcoming = await api(`/api/admin/users/${telegramId}/bookings?scope=upcoming`, { token })
    const archive = await api(`/api/admin/users/${telegramId}/bookings?scope=archive`, { token })
    setSelectedUserUpcoming(upcoming.items || [])
    setSelectedUserArchive(archive.items || [])
  }

  async function saveUserPatch(fields) {
    if (!selectedUser?.telegram_id) return
    await api(`/api/admin/users/${selectedUser.telegram_id}`, { token, method: 'PATCH', body: fields })
    await selectUser(selectedUser.telegram_id)
    await loadUsers()
  }

  async function toggleUserBlock() {
    if (!selectedUser?.telegram_id) return
    await saveUserPatch({ blocked: !selectedUser.blocked })
  }

  async function loadSchedule() {
    const data = await api(`/api/admin/schedule/day?date=${day}`, { token })
    setSchedule(data.items || [])
  }

  async function loadScheduleMonth() {
    const data = await api(`/api/admin/schedule/month?month=${adminMonth}&duration=${scheduleDuration}`, { token })
    setScheduleMonthDays(data.days || [])
  }

  async function loadFreeSlots() {
    const data = await api(`/api/admin/schedule/free?date=${day}&duration=${scheduleDuration}`, { token })
    setFreeSlots(data.slots || [])
    setSelectedFreeTime('')
  }

  async function loadApprovals() {
    const data = await api('/api/admin/approvals?status=pending&page=1&page_size=50', { token })
    setApprovals(data.items || [])
    if (!data.items?.length) {
      setSelectedApproval(null)
      return
    }
    if (!selectedApproval) {
      await openApproval(data.items[0].record_id)
    }
  }

  async function openApproval(recordId) {
    const data = await api(`/api/admin/approvals/${recordId}`, { token })
    setSelectedApproval(data)
  }

  async function decideApproval(recordId, action) {
    await api(`/api/admin/approvals/${recordId}/${action}`, { token, method: 'POST' })
    await loadApprovals()
    setSelectedApproval(null)
  }

  async function deleteScheduleItem(item) {
    if (!item?.telegram_id) return
    const time = `${String(item.hour).padStart(2, '0')}:${String(item.minute).padStart(2, '0')}`
    await api(`/api/admin/lessons/0?date=${day}&time=${time}&telegram_id=${item.telegram_id}`, { token, method: 'DELETE' })
    await loadSchedule()
  }

  async function addManualPayment() {
    if (!manualPay.telegram_id || !manualPay.amount) throw new Error('Заполните telegram_id и сумму')
    await api('/api/admin/payments/manual', {
      token,
      method: 'POST',
      body: {
        telegram_id: Number(manualPay.telegram_id),
        date: manualPay.date,
        time: manualPay.time,
        amount: Number(manualPay.amount),
        duration: Number(manualPay.duration),
      },
    })
    setManualPay(prev => ({ ...prev, amount: '' }))
  }

  async function loadDebtors() {
    const data = await api('/api/admin/payments/debtors', { token })
    setDebtors(data.items || [])
  }

  async function sendBroadcast() {
    await api('/api/admin/broadcast', {
      token,
      method: 'POST',
      body: { message: broadcast, only_unpaid: broadcastOnlyUnpaid },
    })
    setBroadcast('')
  }

  async function loadStats() {
    if (statsPeriod === 'day') {
      setStats(await api(`/api/admin/stats/day?date=${day}`, { token }))
      return
    }
    if (statsPeriod === 'week') {
      setStats(await api(`/api/admin/stats/week?date=${day}`, { token }))
      return
    }
    const [y, m] = day.split('-')
    setStats(await api(`/api/admin/stats/month?year=${Number(y)}&month=${Number(m)}`, { token }))
  }

  async function loadSystem() {
    setSystemHealth(await api('/api/admin/system/health', { token }))
    setBackupStatus(await api('/api/admin/system/backup', { token }))
  }

  useEffect(() => {
    ;(async () => {
      await loadDashboard().catch(() => {})
      await loadUsers().catch(e => setError(String(e.message || e)))
      await loadClientOptions().catch(() => {})
      await loadSchedule().catch(() => {})
      await loadScheduleMonth().catch(() => {})
      await loadStats().catch(() => {})
      await loadApprovals().catch(() => {})
      await loadDebtors().catch(() => {})
      await loadSystem().catch(() => {})
    })()
  }, [])

  useEffect(() => {
    loadUsers().catch(e => setError(String(e.message || e)))
  }, [usersPage])

  useEffect(() => {
    loadScheduleMonth().catch(() => {})
  }, [adminMonth, scheduleDuration])

  useEffect(() => {
    if (activeTab !== 'schedule') return
    if (scheduleMode === 'booked') {
      loadSchedule().catch(() => {})
    } else {
      loadFreeSlots().catch(() => {})
    }
  }, [activeTab, scheduleMode, day, scheduleDuration])

  const filteredClients = (clientOptions || [])
    .filter(c => {
      const q = clientSearch.trim().toLowerCase()
      if (!q) return true
      return (
        String(c.telegram_id || '').includes(q) ||
        String(c.full_name || '').toLowerCase().includes(q) ||
        String(c.phone || '').toLowerCase().includes(q) ||
        String(c.username || '').toLowerCase().includes(q)
      )
    })
    .slice(0, 200)
  const groupedFreeSlots = (freeSlots || []).reduce((acc, t) => {
    const hour = String(t).slice(0, 2)
    if (!acc[hour]) acc[hour] = []
    acc[hour].push(t)
    return acc
  }, {})
  const groupedFreeHourKeys = Object.keys(groupedFreeSlots).sort((a, b) => Number(a) - Number(b))
  const selectedFreeHour = selectedFreeTime ? selectedFreeTime.slice(0, 2) : ''

  const [adminYear, adminMon] = adminMonth.split('-').map(Number)
  const adminFirstWeekday = new Date(adminYear, adminMon - 1, 1).getDay()
  const adminLeadingEmpty = (adminFirstWeekday + 6) % 7
  const adminCalendarCells = [...Array(adminLeadingEmpty).fill(null), ...(scheduleMonthDays || [])]
  const weekDays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

  async function assignClientToFreeSlot(timeValue) {
    if (!timeValue || !lessonForm.telegram_id) return
    if (scheduleAssignMode === 'single') {
      await api('/api/admin/lessons/single', {
        token,
        method: 'POST',
        body: {
          telegram_id: Number(lessonForm.telegram_id),
          date: day,
          time: timeValue,
          duration: Number(scheduleDuration),
        },
      })
    } else {
      const jsWeekDay = new Date(`${day}T00:00:00`).getDay()
      const dayOfWeek = (jsWeekDay + 6) % 7
      await api('/api/admin/lessons/regular', {
        token,
        method: 'POST',
        body: {
          telegram_id: Number(lessonForm.telegram_id),
          day_of_week: dayOfWeek,
          time: timeValue,
          duration: Number(scheduleDuration),
        },
      })
    }
    await loadScheduleMonth().catch(() => {})
    await loadFreeSlots().catch(() => {})
    setSelectedFreeTime('')
  }

  return (
    <div className="mini-layout">
      <section className="mini-cover">
        <div className="mini-cover-overlay" />
        <div className="mini-cover-head">
          <div className="mini-brand">
            <div className="brand-logo">AD</div>
            <div className="brand-meta">
              <strong>ADMIN DESK</strong>
              <span>управление в miniapp</span>
            </div>
          </div>
          <button className="circle-btn">◌</button>
        </div>
      </section>

      <div className="mini-body">
        <div className="admin-tabs">
          {adminTabs.map(([key, label]) => (
            <button key={key} className={activeTab === key ? 'admin-tab active' : 'admin-tab'} onClick={() => setActiveTab(key)}>
              {label}
            </button>
          ))}
        </div>

        {activeTab === 'main' ? (
          <div className="stack">
            <Card title="Сегодня" subtitle="Занятия на текущий день">
              <div className="pill-row">
                <Pill label="Занятий" value={dashboardKpi?.today_lessons ?? 0} tone="mint" />
                <Pill label="Ожидает" value={dashboardKpi?.pending_approvals ?? 0} tone="blue" />
                <Pill label="Доход дня" value={`${dashboardKpi?.today_income ?? 0} ₽`} tone="violet" />
              </div>
              <ul className="list list-compact">
                {(dashboardToday || []).slice(0, 12).map((i, idx) => (
                  <li key={`td-${idx}`}>
                    <strong>{i.time}</strong>
                    <span>{i.full_name || '—'}</span>
                    <small>{i.kind} • {i.duration}м • {i.status === 'completed' ? 'проведено' : 'запланировано'}</small>
                  </li>
                ))}
              </ul>
            </Card>

            <Card title="Статистика месяца" subtitle="Доход и проведённые занятия">
              <div className="pill-row">
                <Pill label="Доход мес." value={`${dashboardKpi?.month_income ?? 0} ₽`} tone="mint" />
                <Pill label="Должники" value={dashboardKpi?.debtors ?? 0} tone="blue" />
                <Pill label="Клиенты" value={usersTotal || users.length || 0} tone="violet" />
              </div>
              <div className="bar-chart">
                {(monthActivity || []).map(day => {
                  const maxRevenue = Math.max(1, ...monthActivity.map(d => d.revenue || 0))
                  const maxLessons = Math.max(1, ...monthActivity.map(d => d.lessons_done || 0))
                  const hRevenue = Math.max(4, Math.round(((day.revenue || 0) / maxRevenue) * 48))
                  const hLessons = Math.max(4, Math.round(((day.lessons_done || 0) / maxLessons) * 48))
                  return (
                    <div className="bar-col" key={`m-${day.date}`} title={`${day.date}: ${day.revenue} ₽ / ${day.lessons_done} занятий`}>
                      <div className="bar-wrap">
                        <span className="bar bar-revenue" style={{ height: `${hRevenue}px` }} />
                        <span className="bar bar-lessons" style={{ height: `${hLessons}px` }} />
                      </div>
                      <small>{day.day}</small>
                    </div>
                  )
                })}
              </div>
            </Card>

            <Card title="Быстрые действия" subtitle="Ежедневные операции">
              <div className="mini-actions-row">
                <button className="btn" onClick={() => setActiveTab('requests')}>Согласовать заявки</button>
                <button className="btn secondary" onClick={() => setActiveTab('schedule')}>Открыть расписание</button>
              </div>
            </Card>
          </div>
        ) : null}

        {activeTab === 'clients' ? (
          <div className="stack">
            <Card title="Пользователи" subtitle="Поиск и карточка клиента">
              <div className="custom-row">
                <input className="input" value={query} onChange={e => setQuery(e.target.value)} placeholder="Имя/телефон" />
                <button className="btn" onClick={() => loadUsers().catch(e => setError(String(e.message || e)))}>Поиск</button>
              </div>
              <div className="mini-actions-row">
                <button className="btn secondary" disabled={usersPage <= 1} onClick={() => { setUsersPage(p => Math.max(1, p - 1)) }}>← Стр.</button>
                <button className="btn secondary" onClick={() => { setUsersPage(p => p + 1) }}>Стр. →</button>
              </div>
              <small>Всего: {usersTotal}</small>
              <ul className="list list-compact">
                {users.map(u => (
                  <li key={u.telegram_id}>
                    <button className="btn secondary" onClick={() => selectUser(u.telegram_id).catch(e => setError(String(e.message || e)))}>
                      {(u.full_name || u.telegram_id)} {u.blocked ? '🔒' : ''}
                    </button>
                  </li>
                ))}
              </ul>
            </Card>

            {selectedUser ? (
              <Card title={selectedUser.full_name || String(selectedUser.telegram_id)} subtitle={`ID: ${selectedUser.telegram_id}`}>
                <div className="stack">
                  <input className="input" value={userEdit.full_name} onChange={e => setUserEdit(v => ({ ...v, full_name: e.target.value }))} placeholder="Имя" />
                  <input className="input" value={userEdit.telephone} onChange={e => setUserEdit(v => ({ ...v, telephone: e.target.value }))} placeholder="Телефон" />
                  <input className="input" value={userEdit.price} onChange={e => setUserEdit(v => ({ ...v, price: e.target.value }))} placeholder="Цена" />
                  <div className="mini-actions-row">
                    <button className="btn" onClick={() => saveUserPatch({
                      full_name: userEdit.full_name,
                      telephone: userEdit.telephone,
                      price: userEdit.price === '' ? null : Number(userEdit.price),
                    }).catch(e => setError(String(e.message || e)))}>
                      Сохранить профиль
                    </button>
                    <button className="btn secondary" onClick={() => toggleUserBlock().catch(e => setError(String(e.message || e)))}>
                      {selectedUser.blocked ? 'Разблокировать' : 'Заблокировать'}
                    </button>
                  </div>
                  <div className="custom-row">
                    <input className="input" value={userEdit.balance_set} onChange={e => setUserEdit(v => ({ ...v, balance_set: e.target.value }))} placeholder="Баланс (set)" />
                    <button className="btn secondary" onClick={() => saveUserPatch({ balance_lessons_set: Number(userEdit.balance_set || 0) }).catch(e => setError(String(e.message || e)))}>Set</button>
                  </div>
                  <div className="custom-row">
                    <input className="input" value={userEdit.balance_add} onChange={e => setUserEdit(v => ({ ...v, balance_add: e.target.value }))} placeholder="Баланс (+/-)" />
                    <button className="btn secondary" onClick={() => saveUserPatch({ balance_lessons_add: Number(userEdit.balance_add || 0) }).catch(e => setError(String(e.message || e)))}>Add</button>
                  </div>
                  <div className="stack">
                    <strong>Ближайшие</strong>
                    <ul className="list list-compact">
                      {(selectedUserUpcoming || []).slice(0, 5).map((b, i) => <li key={`up-${i}`}><span>{b.date} {b.time}</span><small>{b.kind}</small></li>)}
                    </ul>
                    <strong>Архив</strong>
                    <ul className="list list-compact">
                      {(selectedUserArchive || []).slice(0, 5).map((b, i) => <li key={`ar-${i}`}><span>{b.date} {b.time}</span><small>{b.kind}</small></li>)}
                    </ul>
                  </div>
                </div>
              </Card>
            ) : null}
          </div>
        ) : null}

        {activeTab === 'schedule' ? (
          <div className="stack">
            <Card title="Календарь расписания" subtitle={scheduleMode === 'booked' ? 'Просмотр записанных клиентов' : 'Свободные слоты для назначения'}>
              <div className="segmented">
                <button
                  className={scheduleMode === 'booked' ? 'seg active' : 'seg'}
                  onClick={() => { setScheduleMode('booked'); loadSchedule().catch(() => {}) }}
                >
                  Записанные
                </button>
                <button
                  className={scheduleMode === 'free' ? 'seg active' : 'seg'}
                  onClick={() => { setScheduleMode('free'); loadFreeSlots().catch(() => {}) }}
                >
                  Свободные слоты
                </button>
              </div>
              <div className="month-switch">
                <button className="chip ok" onClick={() => setAdminMonth(prev => shiftMonth(prev, -1))}>{'<'}</button>
                <strong>{formatMonthRu(adminMonth)}</strong>
                <button className="chip ok" onClick={() => setAdminMonth(prev => shiftMonth(prev, 1))}>{'>'}</button>
              </div>
              <div className="weekdays">
                {weekDays.map(w => <div key={`adm-${w}`}>{w}</div>)}
              </div>
              <div className="calendar-grid">
                {adminCalendarCells.map((cell, idx) => (
                  cell ? (
                    <button
                      key={cell.date}
                      className={`calendar-day ${day === cell.date ? 'selected' : ''} ${cell.past ? 'off' : 'on'}`}
                      onClick={async () => {
                        setDay(cell.date)
                        if (scheduleMode === 'booked') {
                          await loadSchedule().catch(() => {})
                        } else {
                          await loadFreeSlots().catch(() => {})
                        }
                      }}
                      title={scheduleMode === 'booked' ? `Записей: ${cell.booked_count}` : `Свободно: ${cell.free_count}`}
                    >
                      <span>{Number(cell.date.slice(8))}</span>
                    </button>
                  ) : (
                    <div key={`adm-empty-${idx}`} className="calendar-day empty" />
                  )
                ))}
              </div>
            </Card>

            {scheduleMode === 'booked' ? (
              <Card title={`Записи на ${day}`} subtitle="Клиенты и время">
                <button className="btn secondary" onClick={() => loadSchedule().catch(e => setError(String(e.message || e)))}>Обновить</button>
                <ul className="list list-compact">
                  {schedule.map((s, idx) => (
                    <li key={`${s.hour}-${s.minute}-${idx}`}>
                      <strong>{String(s.hour).padStart(2, '0')}:{String(s.minute).padStart(2, '0')}</strong>
                      <span>{s.full_name}</span>
                      <small>{s.kind}</small>
                      {s.telegram_id ? (
                        <button className="btn secondary" onClick={() => deleteScheduleItem(s).catch(e => setError(String(e.message || e)))}>Удалить</button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </Card>
            ) : (
              <Card title={`Свободные слоты на ${day}`} subtitle="Выберите слот и назначьте клиента">
                <input className="input" value={clientSearch} onChange={e => setClientSearch(e.target.value)} placeholder="Поиск клиента: имя / телефон / id" />
                <select
                  className="input"
                  value={lessonForm.telegram_id}
                  onChange={e => setLessonForm(v => ({ ...v, telegram_id: e.target.value }))}
                >
                  <option value="">Выберите клиента</option>
                  {filteredClients.map(c => (
                    <option key={`free-client-${c.telegram_id}`} value={c.telegram_id}>
                      {(c.full_name || 'Без имени')} • {c.telegram_id}
                    </option>
                  ))}
                </select>
                <div className="segmented">
                  <button className={scheduleAssignMode === 'single' ? 'seg active' : 'seg'} onClick={() => setScheduleAssignMode('single')}>Разовое</button>
                  <button className={scheduleAssignMode === 'regular' ? 'seg active' : 'seg'} onClick={() => setScheduleAssignMode('regular')}>Регулярное</button>
                </div>
                <div className="segmented">
                  <button className={scheduleDuration === 60 ? 'seg active' : 'seg'} onClick={() => setScheduleDuration(60)}>60 мин</button>
                  <button className={scheduleDuration === 90 ? 'seg active' : 'seg'} onClick={() => setScheduleDuration(90)}>90 мин</button>
                  <button className={scheduleDuration === 120 ? 'seg active' : 'seg'} onClick={() => setScheduleDuration(120)}>120 мин</button>
                </div>
                <button className="btn secondary" onClick={() => loadFreeSlots().catch(e => setError(String(e.message || e)))}>Обновить слоты</button>
                <div className="slots-hours">
                  {groupedFreeHourKeys.map(hour => (
                    <div key={`free-hour-${hour}`} className="slots-hour-block">
                      <div className="slots-hour-title">{hour}:00</div>
                      <div className="slots-grid">
                        {groupedFreeSlots[hour].map(t => (
                          <button key={`free-${t}`} className={`chip ok ${selectedFreeTime === t ? 'active' : ''}`} onClick={() => setSelectedFreeTime(t)}>
                            {t}
                          </button>
                        ))}
                      </div>
                      {selectedFreeHour === hour ? (
                        <div className="slot-confirm-panel">
                          <div className="slot-confirm-meta">
                            Выбрано: <strong>{selectedFreeTime}</strong> • {scheduleDuration} мин
                          </div>
                          <button
                            className="btn slot-confirm-btn"
                            disabled={!selectedFreeTime || !lessonForm.telegram_id}
                            onClick={() => assignClientToFreeSlot(selectedFreeTime).catch(e => setError(String(e.message || e)))}
                          >
                            {scheduleAssignMode === 'single' ? 'Подтвердить разовое' : 'Подтвердить регулярное'}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </Card>
            )}
          </div>
        ) : null}

        {activeTab === 'requests' ? (
          <div className="stack">
            <Card title="Approvals" subtitle="Заявки на согласование">
              <button className="btn secondary" onClick={() => loadApprovals().catch(e => setError(String(e.message || e)))}>Обновить заявки</button>
              <ul className="list list-compact">
                {approvals.map(a => (
                  <li key={a.record_id}>
                    <button className="btn secondary" onClick={() => openApproval(a.record_id).catch(e => setError(String(e.message || e)))}>
                      {a.date} {a.time} • {a.full_name || a.telegram_id}
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
            {selectedApproval ? (
              <Card title={`Заявка #${selectedApproval.record_id}`} subtitle={`${selectedApproval.date} ${selectedApproval.time} • ${selectedApproval.duration} мин`}>
                <div className="stack">
                  <div><strong>Клиент:</strong> {selectedApproval.full_name || selectedApproval.telegram_id}</div>
                  <div><strong>Тип:</strong> {selectedApproval.kind}</div>
                  <div><strong>До:</strong></div>
                  <ul className="list list-compact">
                    {(selectedApproval.neighbors_before || []).map((n, i) => <li key={`b-${i}`}><span>{n.time}</span><small>{n.full_name || n.kind}</small></li>)}
                  </ul>
                  <div><strong>После:</strong></div>
                  <ul className="list list-compact">
                    {(selectedApproval.neighbors_after || []).map((n, i) => <li key={`a-${i}`}><span>{n.time}</span><small>{n.full_name || n.kind}</small></li>)}
                  </ul>
                  <div className="mini-actions-row">
                    <button className="btn" onClick={() => decideApproval(selectedApproval.record_id, 'approve').catch(e => setError(String(e.message || e)))}>Approve</button>
                    <button className="btn secondary" onClick={() => decideApproval(selectedApproval.record_id, 'reject').catch(e => setError(String(e.message || e)))}>Reject</button>
                  </div>
                  <button className="btn secondary" onClick={() => { setDay(selectedApproval.date); setActiveTab('schedule') }}>Open in schedule day</button>
                </div>
              </Card>
            ) : null}
          </div>
        ) : null}

        {activeTab === 'finance' ? (
          <div className="stack">
            <Card title="Manual payment" subtitle="Ручная оплата">
              <input className="input" value={manualPay.telegram_id} onChange={e => setManualPay(v => ({ ...v, telegram_id: e.target.value }))} placeholder="Telegram ID" />
              <input type="date" className="input" value={manualPay.date} onChange={e => setManualPay(v => ({ ...v, date: e.target.value }))} />
              <input className="input" value={manualPay.time} onChange={e => setManualPay(v => ({ ...v, time: e.target.value }))} placeholder="HH:MM" />
              <input className="input" value={manualPay.amount} onChange={e => setManualPay(v => ({ ...v, amount: e.target.value }))} placeholder="Сумма" />
              <button className="btn" onClick={() => addManualPayment().catch(e => setError(String(e.message || e)))}>Сохранить оплату</button>
            </Card>
            <Card title="Debtors" subtitle="Должники">
              <button className="btn secondary" onClick={() => loadDebtors().catch(e => setError(String(e.message || e)))}>Обновить</button>
              <ul className="list list-compact">
                {debtors.map(d => (
                  <li key={d.payment_id}>
                    <span>{d.full_name || d.telegram_id}</span>
                    <small>{d.date} {d.time}</small>
                    <strong>{d.amount || 0} ₽</strong>
                  </li>
                ))}
              </ul>
            </Card>

            <Card title="Статистика" subtitle="День / неделя / месяц">
              <div className="segmented">
                <button className={statsPeriod === 'day' ? 'seg active' : 'seg'} onClick={() => setStatsPeriod('day')}>Day</button>
                <button className={statsPeriod === 'week' ? 'seg active' : 'seg'} onClick={() => setStatsPeriod('week')}>Week</button>
                <button className={statsPeriod === 'month' ? 'seg active' : 'seg'} onClick={() => setStatsPeriod('month')}>Month</button>
              </div>
              <div className="custom-row">
                <input type="date" className="input" value={day} onChange={e => setDay(e.target.value)} />
                <button className="btn" onClick={() => loadStats().catch(e => setError(String(e.message || e)))}>Обновить</button>
              </div>
              <ul className="list list-compact">
                <li><span>Всего платежей</span><strong>{stats?.total_payments ?? 0}</strong></li>
                <li><span>Оплачено</span><strong>{stats?.paid_count ?? 0}</strong></li>
                <li><span>Выручка</span><strong>{stats?.earned_total ?? 0} ₽</strong></li>
                <li><span>Начислено</span><strong>{stats?.amount_total ?? 0} ₽</strong></li>
              </ul>
            </Card>
          </div>
        ) : null}

        {activeTab === 'more' ? (
          <div className="stack">
            <Card title="Broadcast" subtitle="Рассылка пользователям">
              <textarea className="input" rows={4} value={broadcast} onChange={e => setBroadcast(e.target.value)} placeholder="Текст сообщения" />
              <label className="broadcast-check">
                <input type="checkbox" checked={broadcastOnlyUnpaid} onChange={e => setBroadcastOnlyUnpaid(e.target.checked)} />
                Только должникам
              </label>
              <button className="btn" disabled={!broadcast.trim()} onClick={() => sendBroadcast().catch(e => setError(String(e.message || e)))}>
                Отправить
              </button>
            </Card>
            <Card title="System" subtitle="Health / backup status">
              <button className="btn secondary" onClick={() => loadSystem().catch(e => setError(String(e.message || e)))}>Refresh</button>
              <ul className="list list-compact">
                <li><span>API/DB</span><strong>{systemHealth?.status || '—'}</strong></li>
                <li><span>DB</span><strong>{systemHealth?.db || '—'}</strong></li>
                <li><span>Approvals flag</span><strong>{String(systemHealth?.approvals_enabled ?? '—')}</strong></li>
                <li><span>Legacy bot flag</span><strong>{String(systemHealth?.bot_legacy_enabled ?? '—')}</strong></li>
                <li><span>Last backup</span><strong>{backupStatus?.last_backup || 'n/a'}</strong></li>
              </ul>
            </Card>
          </div>
        ) : null}

        {!!normalizeErrorMessage(error) && <div className="toast error">{normalizeErrorMessage(error)}</div>}
      </div>

      <nav className="bottom-nav bottom-nav-two">
        <button className={`bottom-item ${activeTab === 'main' ? 'active' : ''}`} onClick={() => setActiveTab('main')}><span className="bottom-ico">⌂</span><span>Главная</span></button>
        <button className={`bottom-item ${activeTab === 'requests' ? 'active' : ''}`} onClick={() => setActiveTab('requests')}><span className="bottom-ico">◷</span><span>Заявки</span></button>
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
