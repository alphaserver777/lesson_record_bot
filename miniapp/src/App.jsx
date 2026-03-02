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
  const [activeTab, setActiveTab] = useState('records')
  const [manageSection, setManageSection] = useState('clients')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
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
  const [userEdit, setUserEdit] = useState({ telegram_id: '', full_name: '', telephone: '', price: '', balance_set: '', balance_add: '' })

  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10))
  const [adminMonth, setAdminMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [scheduleMode, setScheduleMode] = useState('booked')
  const [scheduleAssignMode, setScheduleAssignMode] = useState('single')
  const [scheduleDuration, setScheduleDuration] = useState(60)
  const [scheduleMonthDays, setScheduleMonthDays] = useState([])
  const [schedule, setSchedule] = useState([])
  const [freeSlots, setFreeSlots] = useState([])
  const [selectedFreeTime, setSelectedFreeTime] = useState('')

  const [lessonForm, setLessonForm] = useState({ telegram_id: '' })

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
  const [unclosedLessons, setUnclosedLessons] = useState([])
  const [unclosedDaysBack, setUnclosedDaysBack] = useState(21)
  const [selectedUnclosedKeys, setSelectedUnclosedKeys] = useState([])

  const [broadcast, setBroadcast] = useState('')
  const [broadcastOnlyUnpaid, setBroadcastOnlyUnpaid] = useState(false)

  const [statsPeriod, setStatsPeriod] = useState('day')
  const [stats, setStats] = useState(null)

  const [systemHealth, setSystemHealth] = useState(null)
  const [backupStatus, setBackupStatus] = useState(null)
  const [workScheduleDays, setWorkScheduleDays] = useState([])
  const [workImpact, setWorkImpact] = useState(null)
  const [workImpactRange, setWorkImpactRange] = useState({
    date_from: new Date().toISOString().slice(0, 10),
    date_to: new Date(Date.now() + 1000 * 60 * 60 * 24 * 30).toISOString().slice(0, 10),
  })

  const adminTabs = [
    ['records', 'Записи', '▥'],
    ['work_schedule', 'Расписание', '▦'],
    ['manage', 'Управление', '◫'],
    ['analytics', 'Аналитика', '◷'],
    ['settings', 'Настройки', '⚙'],
  ]

  async function loadUsers(page = usersPage, q = query) {
    const path = `/api/admin/users?page=${page}&page_size=20${q ? `&query=${encodeURIComponent(q)}` : ''}`
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
      telegram_id: String(data.telegram_id ?? ''),
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

  async function saveUserPatch(fields, successMessage = 'Сохранено') {
    if (!selectedUser?.telegram_id) return
    const data = await api(`/api/admin/users/${selectedUser.telegram_id}`, { token, method: 'PATCH', body: fields })
    const nextId = Number(data?.item?.telegram_id || selectedUser.telegram_id)
    await selectUser(nextId)
    await loadUsers()
    setSuccess(successMessage)
  }

  async function toggleUserBlock() {
    if (!selectedUser?.telegram_id) return
    await saveUserPatch({ blocked: !selectedUser.blocked }, selectedUser.blocked ? 'Клиент разблокирован' : 'Клиент заблокирован')
  }

  async function deleteSelectedUser() {
    if (!selectedUser?.telegram_id) return
    if (!window.confirm('Удалить клиента из активной базы? История оплат сохранится.')) return
    await api(`/api/admin/users/${selectedUser.telegram_id}`, { token, method: 'DELETE' })
    setSelectedUser(null)
    setSelectedUserUpcoming([])
    setSelectedUserArchive([])
    setUserEdit({ telegram_id: '', full_name: '', telephone: '', price: '', balance_set: '', balance_add: '' })
    await loadUsers(1, query).catch(() => {})
    setUsersPage(1)
    setSuccess('Клиент удален')
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

  async function deleteScheduleItem(item, scope = 'single') {
    if (!item?.telegram_id) return
    const time = `${String(item.hour).padStart(2, '0')}:${String(item.minute).padStart(2, '0')}`
    await api(
      `/api/admin/lessons/0?date=${day}&time=${time}&telegram_id=${item.telegram_id}&scope=${scope}`,
      { token, method: 'DELETE' },
    )
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

  async function markDebtPaid(paymentId) {
    await api(`/api/admin/payments/${paymentId}/mark-paid`, {
      token,
      method: 'POST',
    })
    await loadDebtors().catch(() => {})
    await loadStats().catch(() => {})
  }

  async function loadUnclosedLessons() {
    const data = await api(`/api/admin/lessons/unclosed?limit=200&days_back=${unclosedDaysBack}`, { token })
    setUnclosedLessons(data.items || [])
    setSelectedUnclosedKeys([])
  }

  async function closeLessonDecision(item, decision, source = 'manual') {
    const amount = Number(item?.expected_amount ?? item?.price ?? 0)
    await api('/api/admin/lessons/close', {
      token,
      method: 'POST',
      body: {
        telegram_id: Number(item.telegram_id),
        date: item.date,
        time: item.time,
        decision,
        amount,
        duration: Number(item.duration || 60),
        source,
      },
    })
    await loadUnclosedLessons().catch(() => {})
    await loadDebtors().catch(() => {})
  }

  function unclosedKey(item, idx) {
    return `${item.telegram_id}|${item.date}|${item.time}|${idx}`
  }

  async function closeSelectedUnclosed(decision) {
    const selectedItems = (unclosedLessons || []).filter((item, idx) => selectedUnclosedKeys.includes(unclosedKey(item, idx)))
    if (!selectedItems.length) return
    await api('/api/admin/lessons/close-bulk', {
      token,
      method: 'POST',
      body: {
        decision,
        items: selectedItems.map(item => ({
          telegram_id: Number(item.telegram_id),
          date: item.date,
          time: item.time,
          duration: Number(item.duration || 60),
          amount: Number(item.expected_amount ?? item.price ?? 0),
        })),
      },
    })
    await loadUnclosedLessons().catch(() => {})
    await loadDebtors().catch(() => {})
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

  function ensureWeekDays(days) {
    const byDay = new Map((days || []).map(d => [Number(d.weekday), d]))
    const result = []
    for (let i = 0; i < 7; i += 1) {
      const item = byDay.get(i)
      if (item) {
        result.push({
          weekday: i,
          enabled: !!item.enabled,
          intervals: Array.isArray(item.intervals) ? item.intervals : [],
        })
      } else {
        result.push({ weekday: i, enabled: false, intervals: [] })
      }
    }
    return result
  }

  async function loadWorkSchedule() {
    const data = await api('/api/admin/work-schedule', { token })
    setWorkScheduleDays(ensureWeekDays(data.days))
  }

  function patchWorkDay(weekday, patch) {
    setWorkScheduleDays(prev => prev.map(dayItem => {
      if (dayItem.weekday !== weekday) return dayItem
      return { ...dayItem, ...patch }
    }))
  }

  function addWorkInterval(weekday) {
    setWorkScheduleDays(prev => prev.map(dayItem => {
      if (dayItem.weekday !== weekday) return dayItem
      const next = [...dayItem.intervals, { start: '10:00', end: '11:00' }]
      return { ...dayItem, enabled: true, intervals: next }
    }))
  }

  function removeWorkInterval(weekday, idx) {
    setWorkScheduleDays(prev => prev.map(dayItem => {
      if (dayItem.weekday !== weekday) return dayItem
      const next = dayItem.intervals.filter((_, i) => i !== idx)
      return { ...dayItem, intervals: next }
    }))
  }

  function updateWorkInterval(weekday, idx, key, value) {
    setWorkScheduleDays(prev => prev.map(dayItem => {
      if (dayItem.weekday !== weekday) return dayItem
      const next = dayItem.intervals.map((it, i) => (i === idx ? { ...it, [key]: value } : it))
      return { ...dayItem, intervals: next }
    }))
  }

  async function saveWorkSchedule() {
    const payload = { days: workScheduleDays }
    await api('/api/admin/work-schedule', { token, method: 'PUT', body: payload })
    await loadWorkSchedule()
    setWorkImpact(null)
  }

  async function previewWorkImpact() {
    const data = await api('/api/admin/work-schedule/preview-impact', {
      token,
      method: 'POST',
      body: {
        days: workScheduleDays,
        date_from: workImpactRange.date_from,
        date_to: workImpactRange.date_to,
      },
    })
    setWorkImpact(data)
  }

  async function applyWorkImpact() {
    const ids = (workImpact?.affected || []).map(i => Number(i.record_id))
    if (!ids.length) return
    await api('/api/admin/work-schedule/apply-impact', {
      token,
      method: 'POST',
      body: {
        affected_ids: ids,
        notify_users: true,
        reason: 'изменение рабочего расписания',
      },
    })
    await loadSchedule().catch(() => {})
    await loadScheduleMonth().catch(() => {})
    await previewWorkImpact().catch(() => {})
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
      await loadUnclosedLessons().catch(() => {})
      await loadSystem().catch(() => {})
      await loadWorkSchedule().catch(() => {})
    })()
  }, [])

  useEffect(() => {
    loadUsers().catch(e => setError(String(e.message || e)))
  }, [usersPage])

  useEffect(() => {
    loadScheduleMonth().catch(() => {})
  }, [adminMonth, scheduleDuration])

  useEffect(() => {
    if (activeTab !== 'records') return
    if (scheduleMode === 'booked') {
      loadSchedule().catch(() => {})
    } else if (scheduleMode === 'free') {
      loadFreeSlots().catch(() => {})
    } else {
      loadApprovals().catch(() => {})
    }
  }, [activeTab, scheduleMode, day, scheduleDuration])

  useEffect(() => {
    if (activeTab === 'manage' && manageSection === 'finance') {
      loadUnclosedLessons().catch(() => {})
      loadDebtors().catch(() => {})
    }
  }, [activeTab, manageSection, unclosedDaysBack])

  useEffect(() => {
    if (!success) return
    const t = setTimeout(() => setSuccess(''), 2200)
    return () => clearTimeout(t)
  }, [success])

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
        {activeTab === 'records' ? (
          <div className="stack">
            <Card title="Календарь расписания" subtitle={scheduleMode === 'booked' ? 'Просмотр записанных клиентов' : scheduleMode === 'free' ? 'Свободные слоты для назначения' : 'Заявки на согласование'}>
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
                <button
                  className={scheduleMode === 'requests' ? 'seg active' : 'seg'}
                  onClick={() => { setScheduleMode('requests'); loadApprovals().catch(() => {}) }}
                >
                  Заявки
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
                        } else if (scheduleMode === 'free') {
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

            {scheduleMode === 'requests' ? (
              <>
                <Card title="Заявки на занятие" subtitle="Ожидают согласования">
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
                    </div>
                  </Card>
                ) : null}
              </>
            ) : null}

            {scheduleMode === 'booked' ? (
              <Card title={`Записи на ${day}`} subtitle="Клиенты и время">
                <button className="btn secondary" onClick={() => loadSchedule().catch(e => setError(String(e.message || e)))}>Обновить</button>
                <ul className="list list-compact">
                  {schedule.map((s, idx) => (
                    <li key={`${s.hour}-${s.minute}-${idx}`}>
                      <strong>{String(s.hour).padStart(2, '0')}:{String(s.minute).padStart(2, '0')}</strong>
                      <span>{s.full_name}</span>
                      <small>{s.kind}</small>
                      {s.telegram_id && s.kind_code !== 'block' ? (
                        s.kind_code === 'regular' ? (
                          <div className="mini-actions-row">
                            <button className="btn secondary" onClick={() => deleteScheduleItem(s, 'single').catch(e => setError(String(e.message || e)))}>
                              Удалить только это
                            </button>
                            <button className="btn secondary" onClick={() => deleteScheduleItem(s, 'all_regular').catch(e => setError(String(e.message || e)))}>
                              Удалить все регулярные
                            </button>
                          </div>
                        ) : (
                          <button className="btn secondary" onClick={() => deleteScheduleItem(s, 'single').catch(e => setError(String(e.message || e)))}>
                            Удалить
                          </button>
                        )
                      ) : null}
                    </li>
                  ))}
                </ul>
              </Card>
            ) : null}

            {scheduleMode === 'free' ? (
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
            ) : null}
          </div>
        ) : null}

        {activeTab === 'work_schedule' ? (
          <div className="stack">
            <Card title="Моё рабочее расписание" subtitle="Выберите дни и интервалы работы">
              <div className="stack">
                {workScheduleDays.map(dayItem => (
                  <div key={`work-day-${dayItem.weekday}`} className="work-day-card">
                    <div className="work-day-head">
                      <strong>{weekDays[dayItem.weekday]}</strong>
                      <label className="work-toggle">
                        <input type="checkbox" checked={!!dayItem.enabled} onChange={e => patchWorkDay(dayItem.weekday, { enabled: e.target.checked })} />
                        <span>{dayItem.enabled ? 'Рабочий' : 'Выходной'}</span>
                      </label>
                    </div>
                    {dayItem.enabled ? (
                      <div className="work-intervals">
                        {dayItem.intervals.map((interval, idx) => (
                          <div key={`interval-${dayItem.weekday}-${idx}`} className="work-interval-row">
                            <input className="input" value={interval.start} onChange={e => updateWorkInterval(dayItem.weekday, idx, 'start', e.target.value)} />
                            <span>—</span>
                            <input className="input" value={interval.end} onChange={e => updateWorkInterval(dayItem.weekday, idx, 'end', e.target.value)} />
                            <button className="btn secondary" onClick={() => removeWorkInterval(dayItem.weekday, idx)}>✕</button>
                          </div>
                        ))}
                        <div className="mini-actions-row">
                          <button className="btn secondary" onClick={() => addWorkInterval(dayItem.weekday)}>Добавить интервал</button>
                          <button className="btn secondary" onClick={() => patchWorkDay(dayItem.weekday, { intervals: [{ start: '10:00', end: '18:00' }] })}>Сбросить</button>
                        </div>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </Card>

            <Card title="Последствия изменений" subtitle="Проверьте какие занятия выйдут за пределы графика">
              <div className="custom-row">
                <input type="date" className="input" value={workImpactRange.date_from} onChange={e => setWorkImpactRange(prev => ({ ...prev, date_from: e.target.value }))} />
                <input type="date" className="input" value={workImpactRange.date_to} onChange={e => setWorkImpactRange(prev => ({ ...prev, date_to: e.target.value }))} />
              </div>
              <div className="mini-actions-row">
                <button className="btn secondary" onClick={() => previewWorkImpact().catch(e => setError(String(e.message || e)))}>Проверить влияние</button>
                <button className="btn" onClick={() => saveWorkSchedule().catch(e => setError(String(e.message || e)))}>Сохранить расписание</button>
              </div>
              {workImpact ? (
                <div className="stack">
                  <small>Затронуто записей: {workImpact.total || 0}</small>
                  <ul className="list list-compact">
                    {(workImpact.affected || []).slice(0, 25).map(item => (
                      <li key={`impact-${item.record_id}`}>
                        <span>{item.date} {item.time}</span>
                        <small>{item.full_name || item.telegram_id}</small>
                      </li>
                    ))}
                  </ul>
                  {(workImpact.total || 0) > 0 ? (
                    <button className="btn secondary" onClick={() => applyWorkImpact().catch(e => setError(String(e.message || e)))}>Отменить затронутые и уведомить</button>
                  ) : null}
                </div>
              ) : null}
            </Card>
          </div>
        ) : null}

        {activeTab === 'manage' ? (
          <div className="stack">
            <Card title="Управление" subtitle="Клиенты, финансы, рассылки">
              <div className="segmented">
                <button className={manageSection === 'clients' ? 'seg active' : 'seg'} onClick={() => setManageSection('clients')}>Клиенты</button>
                <button className={manageSection === 'finance' ? 'seg active' : 'seg'} onClick={() => setManageSection('finance')}>Финансы</button>
                <button className={manageSection === 'broadcast' ? 'seg active' : 'seg'} onClick={() => setManageSection('broadcast')}>Рассылки</button>
              </div>
            </Card>

            {manageSection === 'clients' ? (
              <>
                {selectedUser ? (
                  <Card title={`Карточка: ${selectedUser.full_name || String(selectedUser.telegram_id)}`} subtitle={`Текущий Telegram ID: ${selectedUser.telegram_id}`}>
                    <div className="stack">
                      <small>Telegram ID</small>
                      <input
                        className="input"
                        value={userEdit.telegram_id}
                        onChange={e => setUserEdit(v => ({ ...v, telegram_id: e.target.value }))}
                        placeholder="Например: 123456789"
                      />
                      <small>ФИО</small>
                      <input className="input" value={userEdit.full_name} onChange={e => setUserEdit(v => ({ ...v, full_name: e.target.value }))} placeholder="Имя и фамилия" />
                      <small>Телефон</small>
                      <input className="input" value={userEdit.telephone} onChange={e => setUserEdit(v => ({ ...v, telephone: e.target.value }))} placeholder="+7..." />
                      <small>Цена за 60 мин (₽)</small>
                      <input className="input" value={userEdit.price} onChange={e => setUserEdit(v => ({ ...v, price: e.target.value }))} placeholder="Например: 1500" />
                      <div className="mini-actions-row">
                        <button className="btn" onClick={() => saveUserPatch({
                          telegram_id_new: Number(userEdit.telegram_id || selectedUser.telegram_id),
                          full_name: userEdit.full_name,
                          telephone: userEdit.telephone,
                          price: userEdit.price === '' ? null : Number(userEdit.price),
                        }, 'Профиль сохранен').catch(e => setError(String(e.message || e)))}>
                          Сохранить профиль
                        </button>
                        <button className="btn secondary" onClick={() => toggleUserBlock().catch(e => setError(String(e.message || e)))}>
                          {selectedUser.blocked ? 'Разблокировать' : 'Заблокировать'}
                        </button>
                        <button className="btn secondary" onClick={() => deleteSelectedUser().catch(e => setError(String(e.message || e)))}>
                          Удалить клиента
                        </button>
                      </div>
                      <small>Баланс клиента (текущий: {selectedUser.balance_lessons ?? 0} ₽)</small>
                      <div className="custom-row">
                        <input className="input" value={userEdit.balance_set} onChange={e => setUserEdit(v => ({ ...v, balance_set: e.target.value }))} placeholder="Установить баланс, ₽" />
                        <button className="btn secondary" onClick={() => saveUserPatch({ balance_lessons_set: Number(userEdit.balance_set || 0) }, 'Баланс установлен').catch(e => setError(String(e.message || e)))}>Установить</button>
                      </div>
                      <div className="custom-row">
                        <input className="input" value={userEdit.balance_add} onChange={e => setUserEdit(v => ({ ...v, balance_add: e.target.value }))} placeholder="Изменить баланс, ₽ (можно -)" />
                        <button className="btn secondary" onClick={() => saveUserPatch({ balance_lessons_add: Number(userEdit.balance_add || 0) }, 'Баланс изменен').catch(e => setError(String(e.message || e)))}>Изменить</button>
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

                <Card title="Пользователи" subtitle="Поиск и карточка клиента">
                  <div className="custom-row">
                    <input className="input" value={query} onChange={e => setQuery(e.target.value)} placeholder="Имя/телефон" />
                    <button
                      className="btn"
                      onClick={() => {
                        setUsersPage(1)
                        loadUsers(1, query).catch(e => setError(String(e.message || e)))
                      }}
                    >
                      Поиск
                    </button>
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
              </>
            ) : null}

            {manageSection === 'finance' ? (
              <>
                <Card title="Manual payment" subtitle="Ручная оплата">
                  <input className="input" value={manualPay.telegram_id} onChange={e => setManualPay(v => ({ ...v, telegram_id: e.target.value }))} placeholder="Telegram ID" />
                  <input type="date" className="input" value={manualPay.date} onChange={e => setManualPay(v => ({ ...v, date: e.target.value }))} />
                  <input className="input" value={manualPay.time} onChange={e => setManualPay(v => ({ ...v, time: e.target.value }))} placeholder="HH:MM" />
                  <input className="input" value={manualPay.amount} onChange={e => setManualPay(v => ({ ...v, amount: e.target.value }))} placeholder="Сумма" />
                  <button className="btn" onClick={() => addManualPayment().catch(e => setError(String(e.message || e)))}>Сохранить оплату</button>
                </Card>
                <Card title="Незакрытые занятия" subtitle="Прошедшие занятия, где еще не выбрано: оплачено/долг/отмена">
                  <div className="mini-actions-row">
                    <select className="input" value={unclosedDaysBack} onChange={e => setUnclosedDaysBack(Number(e.target.value || 21))}>
                      <option value={7}>За 7 дней</option>
                      <option value={14}>За 14 дней</option>
                      <option value={21}>За 21 день</option>
                      <option value={30}>За 30 дней</option>
                      <option value={60}>За 60 дней</option>
                    </select>
                    <button className="btn secondary" onClick={() => loadUnclosedLessons().catch(e => setError(String(e.message || e)))}>Обновить</button>
                  </div>
                  <div className="mini-actions-row">
                    <button
                      className="btn secondary"
                      onClick={() => setSelectedUnclosedKeys((unclosedLessons || []).map((item, idx) => unclosedKey(item, idx)))}
                    >
                      Выбрать все
                    </button>
                    <button className="btn secondary" onClick={() => setSelectedUnclosedKeys([])}>Снять выбор</button>
                    <button className="btn secondary" disabled={!selectedUnclosedKeys.length} onClick={() => closeSelectedUnclosed('paid').catch(e => setError(String(e.message || e)))}>
                      Массово: Оплачено
                    </button>
                    <button className="btn secondary" disabled={!selectedUnclosedKeys.length} onClick={() => closeSelectedUnclosed('unpaid').catch(e => setError(String(e.message || e)))}>
                      Массово: В долг
                    </button>
                  </div>
                  <ul className="list list-compact">
                    {unclosedLessons.map((d, idx) => (
                      <li key={`unclosed-${d.telegram_id}-${d.date}-${d.time}-${idx}`}>
                        <input
                          type="checkbox"
                          checked={selectedUnclosedKeys.includes(unclosedKey(d, idx))}
                          onChange={e => {
                            const key = unclosedKey(d, idx)
                            setSelectedUnclosedKeys(prev => e.target.checked ? [...prev, key] : prev.filter(v => v !== key))
                          }}
                        />
                        <span>{d.full_name || d.telegram_id}</span>
                        <small>{d.date} {d.time} • {d.duration || 60} мин • {d.kind === 'regular' ? 'Регулярное' : 'Разовое'}</small>
                        <div className="mini-actions-row">
                          <strong>{d.expected_amount ?? d.price ?? 0} ₽</strong>
                          {d.can_pay_from_balance ? (
                            <button className="btn secondary" onClick={() => closeLessonDecision(d, 'paid', 'balance').catch(e => setError(String(e.message || e)))}>
                              Списать с баланса ({d.balance_lessons || 0} ₽)
                            </button>
                          ) : null}
                          <button className="btn secondary" onClick={() => closeLessonDecision(d, 'paid').catch(e => setError(String(e.message || e)))}>
                            Оплачено
                          </button>
                          <button className="btn secondary" onClick={() => closeLessonDecision(d, 'unpaid').catch(e => setError(String(e.message || e)))}>
                            В долг
                          </button>
                          <button className="btn secondary" onClick={() => closeLessonDecision(d, 'canceled').catch(e => setError(String(e.message || e)))}>
                            Отмена
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                </Card>
                <Card title="Долги" subtitle="Занятия, отмеченные как 'В долг'">
                  <div className="mini-actions-row">
                    <button className="btn secondary" onClick={() => loadDebtors().catch(e => setError(String(e.message || e)))}>
                      Обновить
                    </button>
                    <strong>
                      Всего: {debtors.length} • Сумма: {(debtors || []).reduce((sum, d) => sum + Number(d.amount || 0), 0)} ₽
                    </strong>
                  </div>
                  {!debtors.length ? (
                    <div className="placeholder-box">Нет долгов.</div>
                  ) : (
                    <ul className="list list-compact">
                      {debtors.map((d, idx) => (
                        <li key={`debt-${d.payment_id || `${d.telegram_id}-${d.date}-${d.time}-${idx}`}`}>
                          <span>{d.full_name || d.telegram_id}</span>
                          <small>{d.date} {d.time}</small>
                          <div className="mini-actions-row">
                            <strong>{Number(d.amount || 0)} ₽</strong>
                            <button
                              className="btn secondary"
                              onClick={() => markDebtPaid(d.payment_id).catch(e => setError(String(e.message || e)))}
                            >
                              Отметить оплачено
                            </button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </>
            ) : null}

            {manageSection === 'broadcast' ? (
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
            ) : null}
          </div>
        ) : null}

        {activeTab === 'analytics' ? (
          <div className="stack">
            <Card title="Аналитика" subtitle="KPI и графики">
              <div className="pill-row">
                <Pill label="Доход мес." value={`${dashboardKpi?.month_income ?? 0} ₽`} tone="mint" />
                <Pill label="Доход дня" value={`${dashboardKpi?.today_income ?? 0} ₽`} tone="blue" />
                <Pill label="Заявок" value={dashboardKpi?.pending_approvals ?? 0} tone="violet" />
              </div>
            </Card>

            <Card title="Доход и занятия по дням" subtitle="Текущий месяц">
              <div className="bar-chart">
                {(monthActivity || []).map(dayItem => {
                  const maxRevenue = Math.max(1, ...monthActivity.map(d => d.revenue || 0))
                  const maxLessons = Math.max(1, ...monthActivity.map(d => d.lessons_done || 0))
                  const hRevenue = Math.max(4, Math.round(((dayItem.revenue || 0) / maxRevenue) * 48))
                  const hLessons = Math.max(4, Math.round(((dayItem.lessons_done || 0) / maxLessons) * 48))
                  return (
                    <div className="bar-col" key={`analytics-${dayItem.date}`} title={`${dayItem.date}: ${dayItem.revenue} ₽ / ${dayItem.lessons_done} занятий`}>
                      <div className="bar-wrap">
                        <span className="bar bar-revenue" style={{ height: `${hRevenue}px` }} />
                        <span className="bar bar-lessons" style={{ height: `${hLessons}px` }} />
                      </div>
                      <small>{dayItem.day}</small>
                    </div>
                  )
                })}
              </div>
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

        {activeTab === 'settings' ? (
          <div className="stack">
            <Card title="System" subtitle="Health / backup status (read-only)">
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

        {!!success && <div className="toast success">{success}</div>}
        {!!normalizeErrorMessage(error) && <div className="toast error">{normalizeErrorMessage(error)}</div>}
      </div>

      <nav className="bottom-nav bottom-nav-five">
        {adminTabs.map(([key, label, icon]) => (
          <button key={key} className={`bottom-item ${activeTab === key ? 'active' : ''}`} onClick={() => setActiveTab(key)}>
            <span className="bottom-ico">{icon}</span>
            <span>{label}</span>
          </button>
        ))}
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
