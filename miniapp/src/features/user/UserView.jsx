import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { useFloatingToasts } from '../../shared/hooks/useFloatingToasts'
import {
  dayName,
  formatDateRu,
  formatMonthRu,
  formatShortLessonLabel,
  nearestBooking,
  normalizeErrorMessage,
  shiftMonth,
} from '../../shared/lib/formatters'
import { Card } from '../../shared/ui/Card'
import { ToastViewport } from '../../shared/ui/ToastViewport'

function UserView({ token, appUser, tgUser }) {
  const currentMonth = new Date().toISOString().slice(0, 7)
  const [month, setMonth] = useState(() => currentMonth)
  const [calendar, setCalendar] = useState([])
  const [date, setDate] = useState('')
  const [slots, setSlots] = useState([])
  const [selectedTime, setSelectedTime] = useState('')
  const [bookings, setBookings] = useState({ single: [], regular: [] })
  const [profile, setProfile] = useState(null)
  const [registerForm, setRegisterForm] = useState({ first_name: '', last_name: '', telephone: '' })
  const [registerLoading, setRegisterLoading] = useState(false)
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
  const toastItems = useFloatingToasts({
    success,
    error,
    onClearSuccess: () => setSuccess(''),
    onClearError: () => setError(''),
    normalizeError: normalizeErrorMessage,
  })

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
      const p = data.profile || null
      setProfile(p)
      if (p) {
        setRegisterForm({
          first_name: p.first_name || '',
          last_name: p.last_name || '',
          telephone: p.telephone || '',
        })
      }
      setError('')
    } finally {
      setProfileLoading(false)
    }
  }

  async function saveProfileRegistration() {
    const first_name = (registerForm.first_name || '').trim()
    const last_name = (registerForm.last_name || '').trim()
    const telephone = (registerForm.telephone || '').trim()
    if (!first_name || !last_name || !telephone) {
      setError('Заполните имя, фамилию и телефон.')
      return
    }
    setRegisterLoading(true)
    try {
      const data = await api('/api/user/profile', {
        token,
        method: 'POST',
        body: { first_name, last_name, telephone },
      })
      setProfile(prev => ({ ...(prev || {}), ...(data.profile || {}) }))
      setSuccess('Профиль сохранён')
      setError('')
    } catch (e) {
      setError(normalizeErrorMessage(e.message || e))
    } finally {
      setRegisterLoading(false)
    }
  }

  async function book(time) {
    setError('')
    setSuccess('')
    try {
      await api('/api/user/book', {
        token,
        method: 'POST',
        body: { date, time, duration, mode: lessonType },
      })
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
  const displayName = [profile?.last_name, profile?.first_name].filter(Boolean).join(' ') || profile?.full_name || `ID ${appUser?.telegram_id || ''}`
  const username = profile?.username || appUser?.username || tgUser?.username || ''
  const profileCompleted = profileLoading ? true : Boolean(profile?.profile_completed)
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
              {!profileLoading && !profileCompleted ? (
                <div className="stack" style={{ marginTop: 0 }}>
                  <div className="toast error">Заполните профиль перед записью на занятия.</div>
                  <small>Имя</small>
                  <input
                    className="input"
                    value={registerForm.first_name}
                    onChange={e => setRegisterForm(v => ({ ...v, first_name: e.target.value }))}
                    placeholder="Имя"
                  />
                  <small>Фамилия</small>
                  <input
                    className="input"
                    value={registerForm.last_name}
                    onChange={e => setRegisterForm(v => ({ ...v, last_name: e.target.value }))}
                    placeholder="Фамилия"
                  />
                  <small>Телефон</small>
                  <input
                    className="input"
                    value={registerForm.telephone}
                    onChange={e => setRegisterForm(v => ({ ...v, telephone: e.target.value }))}
                    placeholder="+7..."
                  />
                  <button className="btn" onClick={saveProfileRegistration} disabled={registerLoading}>
                    {registerLoading ? 'Сохраняем...' : 'Сохранить профиль'}
                  </button>
                </div>
              ) : null}
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
            {!profileCompleted ? (
              <Card title="Профиль не заполнен" subtitle="Сначала заполните имя, фамилию и телефон на вкладке «Профиль».">
                <div className="empty">После сохранения профиля откроется запись на занятия.</div>
              </Card>
            ) : null}
            {profileCompleted ? (
              <>
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
              </>
            ) : null}
          </div>
        ) : null}

        <ToastViewport
          items={toastItems}
          onDismiss={id => {
            if (id === 'success') setSuccess('')
            if (id === 'error') setError('')
          }}
        />
      </div>

      <nav className="bottom-nav bottom-nav-two">
        <button className={`bottom-item ${activeTab === 'home' ? 'active' : ''}`} onClick={() => setActiveTab('home')}><span className="bottom-ico">⌂</span><span>Профиль</span></button>
        <button className={`bottom-item ${activeTab === 'book' ? 'active' : ''}`} onClick={() => setActiveTab('book')}><span className="bottom-ico">◷</span><span>Записаться</span></button>
      </nav>
    </div>
  )
}

export function RoutedUserView({ token, user }) {
  const tgUser = window.Telegram?.WebApp?.initDataUnsafe?.user || null
  return <UserView token={token} appUser={user} tgUser={tgUser} />
}
