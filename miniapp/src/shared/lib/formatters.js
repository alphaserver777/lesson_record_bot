export function dayName(index) {
  return ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][index] || '—'
}

export function nearestBooking(singleBookings) {
  const now = new Date()
  const future = (singleBookings || [])
    .map(b => ({ ...b, at: new Date(`${b.date}T${b.time}:00`) }))
    .filter(b => !Number.isNaN(b.at.getTime()) && b.at >= now)
    .sort((a, b) => a.at - b.at)
  return future[0] || null
}

export function formatDateRu(isoDate) {
  try {
    return new Date(`${isoDate}T00:00:00`).toLocaleDateString('ru-RU', { day: '2-digit', month: 'long', year: 'numeric' })
  } catch {
    return isoDate
  }
}

export function formatShortLessonLabel(isoDate, time) {
  try {
    const dt = new Date(`${isoDate}T${time || '00:00'}:00`)
    const weekday = dt.toLocaleDateString('ru-RU', { weekday: 'short' })
    const dateShort = dt.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' }).replace('.', '')
    return `${weekday}, ${dateShort} • ${time || '--:--'}`
  } catch {
    return `${isoDate} • ${time || '--:--'}`
  }
}

export function shiftMonth(ym, diff) {
  const [y, m] = ym.split('-').map(Number)
  const dt = new Date(y, (m - 1) + diff, 1)
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}`
}

export function formatMonthRu(ym) {
  const [y, m] = ym.split('-').map(Number)
  try {
    return new Date(y, m - 1, 1).toLocaleDateString('ru-RU', { month: 'long' })
  } catch {
    return ym
  }
}

export function normalizeErrorMessage(raw) {
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
