import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { useFloatingToasts } from '../../shared/hooks/useFloatingToasts'
import { dayName, formatMonthRu, normalizeErrorMessage, shiftMonth } from '../../shared/lib/formatters'
import { Card } from '../../shared/ui/Card'
import { Pill } from '../../shared/ui/Pill'
import { ToastViewport } from '../../shared/ui/ToastViewport'

const ANALYTICS_SHARE_COLORS = ['#67e8a5', '#7aa8ff', '#f6b95a', '#ff8ba7', '#91f1ff', '#c29bff', '#868b98']
const FALLBACK_FUNNEL_STAGES = [
  { key: 'new', name: 'Новые' },
  { key: 'qualified', name: 'Квалификация' },
  { key: 'diagnostic_booked', name: 'Диагностика' },
  { key: 'diagnostic_done', name: 'После диагностики' },
  { key: 'offer_sent', name: 'Предложение' },
  { key: 'won', name: 'Оплата / ученик' },
  { key: 'lost', name: 'Неактуально' },
]

function funnelStageLabel(stage, stages = FALLBACK_FUNNEL_STAGES) {
  return stages.find(item => item.key === stage)?.name || 'Без этапа'
}

function formatMoneyShort(value) {
  return `${Number(value || 0).toLocaleString('ru-RU')} ₽`
}

function formatMetricCompact(value, kind = 'number') {
  const numeric = Number(value || 0)
  if (kind === 'money') {
    if (Math.abs(numeric) >= 1000) {
      return `${(numeric / 1000).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}к`
    }
    return String(numeric)
  }
  return String(numeric)
}

function analyticsDayLabel(isoDate, mode) {
  try {
    const dt = new Date(`${isoDate}T00:00:00`)
    if (mode === 'week') {
      return dt.toLocaleDateString('ru-RU', { weekday: 'short' }).replace('.', '')
    }
    return String(dt.getDate())
  } catch {
    return String(isoDate || '')
  }
}

function analyticsModeLabel(mode) {
  if (mode === 'quarter') return 'квартал'
  return mode === 'week' ? 'неделя' : 'месяц'
}

const MARKETING_ROLE_LABELS = {
  new: 'Новые лиды', qualified: 'Квалифицированы', diagnostic_scheduled: 'Диагностика назначена',
  diagnostic_held: 'Диагностика проведена', offer: 'Предложение', won: 'Оплата', lost: 'Потеря',
}

function metricValue(value, kind = 'number') {
  if (value === null || value === undefined) return 'нет данных'
  if (kind === 'money') return formatMoneyShort(value)
  if (kind === 'percent') return `${Number(value).toLocaleString('ru-RU')}%`
  return Number(value).toLocaleString('ru-RU')
}

function signalLabel(signal) {
  if (signal === 'progress') return 'Прогресс'
  if (signal === 'regress') return 'Регресс'
  if (signal === 'stagnation') return 'Стагнация'
  return 'Смешано'
}

function buildRevenueDonut(items) {
  if (!items?.length) return 'conic-gradient(#2a2b31 0deg 360deg)'
  let cursor = 0
  const segments = items.map((item, idx) => {
    const degrees = Math.max(3, (Number(item.share_pct || 0) / 100) * 360)
    const start = cursor
    const end = Math.min(360, cursor + degrees)
    cursor = end
    return `${ANALYTICS_SHARE_COLORS[idx % ANALYTICS_SHARE_COLORS.length]} ${start}deg ${end}deg`
  })
  if (cursor < 360) {
    segments.push(`#2a2b31 ${cursor}deg 360deg`)
  }
  return `conic-gradient(${segments.join(', ')})`
}

export function AdminView({ token }) {
  const [activeTab, setActiveTab] = useState('records')
  const [manageSection, setManageSection] = useState('finance')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [analyticsMode, setAnalyticsMode] = useState('week')
  const [analyticsAnchorDate, setAnalyticsAnchorDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [analyticsOverview, setAnalyticsOverview] = useState(null)
  const [analyticsDelta, setAnalyticsDelta] = useState({ new_active: [], became_inactive: [] })
  const [analyticsSeries, setAnalyticsSeries] = useState([])
  const [analyticsSeriesSummary, setAnalyticsSeriesSummary] = useState(null)
  const [analyticsRevenueShare, setAnalyticsRevenueShare] = useState({ total_paid: 0, items: [] })
  const [analyticsV2, setAnalyticsV2] = useState(null)
  const [analyticsLoading, setAnalyticsLoading] = useState(false)
  const [marketingMetrics, setMarketingMetrics] = useState(null)
  const [marketingSources, setMarketingSources] = useState([])
  const [marketingCampaigns, setMarketingCampaigns] = useState([])
  const [marketingLoading, setMarketingLoading] = useState(false)
  const [marketingFilters, setMarketingFilters] = useState(() => ({
    date_from: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().slice(0, 10),
    date_to: new Date().toISOString().slice(0, 10), source_key: '', campaign: '', direction: '',
  }))
  const [expenseForm, setExpenseForm] = useState(() => ({
    spent_at: new Date().toISOString().slice(0, 10), source_key: 'avito', campaign_id: '', category: 'placement', amount: '', note: '',
  }))
  const [campaignName, setCampaignName] = useState('')
  const [campaignPeriod, setCampaignPeriod] = useState({ active_from: '', active_to: '' })
  const [query, setQuery] = useState('')
  const [usersPage, setUsersPage] = useState(1)
  const [users, setUsers] = useState([])
  const [usersTotal, setUsersTotal] = useState(0)
  const [contactQuery, setContactQuery] = useState('')
  const [contacts, setContacts] = useState([])
  const [contactsBoard, setContactsBoard] = useState([])
  const [contactsTotal, setContactsTotal] = useState(0)
  const [contactsPage, setContactsPage] = useState(1)
  const [contactsView, setContactsView] = useState('table')
  const [funnelStages, setFunnelStages] = useState(FALLBACK_FUNNEL_STAGES)
  const [stageSettingsOpen, setStageSettingsOpen] = useState(false)
  const [newStageName, setNewStageName] = useState('')
  const [draggedContactId, setDraggedContactId] = useState(null)
  const [navCollapsed, setNavCollapsed] = useState(false)
  const [selectedContact, setSelectedContact] = useState(null)
  const [contactEdit, setContactEdit] = useState({
    first_name: '', last_name: '', telephone: '', telegram_username: '', status: 'active', preferred_channel: 'telegram', direction: '', acquisition_source: 'unknown', acquisition_campaign: '',
  })
  const [prepaymentAmount, setPrepaymentAmount] = useState('')
  const [clientOptions, setClientOptions] = useState([])
  const [clientSearch, setClientSearch] = useState('')
  const [selectedUser, setSelectedUser] = useState(null)
  const [selectedUserUpcoming, setSelectedUserUpcoming] = useState([])
  const [selectedUserArchive, setSelectedUserArchive] = useState([])
  const [userEdit, setUserEdit] = useState({
    telegram_id: '',
    first_name: '',
    last_name: '',
    telephone: '',
    price: '',
    balance_set: '',
    balance_add: '',
  })
  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10))
  const [adminMonth, setAdminMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [scheduleMode, setScheduleMode] = useState('booked')
  const [scheduleAssignMode, setScheduleAssignMode] = useState('single')
  const [scheduleDuration, setScheduleDuration] = useState(60)
  const [scheduleMonthDays, setScheduleMonthDays] = useState([])
  const [schedule, setSchedule] = useState([])
  const [freeSlots, setFreeSlots] = useState([])
  const [scheduleMonthLoading, setScheduleMonthLoading] = useState(true)
  const [scheduleLoading, setScheduleLoading] = useState(false)
  const [freeSlotsLoading, setFreeSlotsLoading] = useState(false)
  const [blocksLoading, setBlocksLoading] = useState(false)
  const [extraAvailability, setExtraAvailability] = useState([])
  const [showExtraAvailabilityForm, setShowExtraAvailabilityForm] = useState(false)
  const [extraAvailabilityForm, setExtraAvailabilityForm] = useState({ start_time: '12:00', end_time: '14:00', note: '' })
  const [selectedFreeTime, setSelectedFreeTime] = useState('')
  const [dayBlocks, setDayBlocks] = useState([])
  const [blockPreview, setBlockPreview] = useState(null)
  const [blockForm, setBlockForm] = useState({
    mode: 'period',
    start_time: '18:30',
    end_time: '19:30',
    note: '',
    strategy: 'block_only',
    notify_reason_template: 'illness',
    notify_reason_custom: '',
  })
  const [lessonForm, setLessonForm] = useState({ telegram_id: '' })
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
  const [systemHealth, setSystemHealth] = useState(null)
  const [leads, setLeads] = useState([])
  const [leadSummary, setLeadSummary] = useState(null)
  const [leadForm, setLeadForm] = useState({ full_name: '', telephone: '', source: 'direct', direction: '', goal: '', stage: 'new', notes: '' })
  const [backupStatus, setBackupStatus] = useState(null)
  const [workScheduleDays, setWorkScheduleDays] = useState([])
  const [workImpact, setWorkImpact] = useState(null)
  const [workImpactRange, setWorkImpactRange] = useState({
    date_from: new Date().toISOString().slice(0, 10),
    date_to: new Date(Date.now() + 1000 * 60 * 60 * 24 * 30).toISOString().slice(0, 10),
  })
  const toastItems = useFloatingToasts({
    success,
    error,
    onClearSuccess: () => setSuccess(''),
    onClearError: () => setError(''),
    normalizeError: normalizeErrorMessage,
  })
  const scheduleMonthReqRef = useRef(0)
  const scheduleReqRef = useRef(0)
  const freeSlotsReqRef = useRef(0)
  const blocksReqRef = useRef(0)
  const adminTabs = [
    ['records', 'Записи', '▥'],
    ['work_schedule', 'Расписание', '▦'],
    ['contacts', 'Клиенты', '◌'],
    ['manage', 'Управление', '◫'],
    ['analytics', 'Аналитика', '◷'],
    ['marketing', 'Маркетинг', '◒'],
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

  async function loadLeads() {
    const [list, summary] = await Promise.all([
      api('/api/admin/leads', { token }),
      api('/api/admin/leads/summary', { token }),
    ])
    setLeads(list.items || [])
    setLeadSummary(summary || null)
  }

  async function loadContacts(page = contactsPage, q = contactQuery) {
    const path = `/api/admin/contacts?page=${page}&page_size=20${q ? `&query=${encodeURIComponent(q)}` : ''}`
    const boardPath = `/api/admin/contacts?page=1&page_size=100${q ? `&query=${encodeURIComponent(q)}` : ''}`
    const [data, board, stages] = await Promise.all([api(path, { token }), api(boardPath, { token }), api('/api/admin/funnel/stages', { token })])
    setContacts(data.items || [])
    setContactsTotal(data.total || 0)
    setContactsBoard(board.items || [])
    setFunnelStages(stages.items?.length ? stages.items : FALLBACK_FUNNEL_STAGES)
  }

  async function selectContact(contactId) {
    const [data, sources, campaigns] = await Promise.all([api(`/api/admin/contacts/${contactId}`, { token }), api('/api/admin/marketing/sources', { token }), api('/api/admin/marketing/campaigns', { token })])
    setMarketingSources(sources.items || [])
    setMarketingCampaigns(campaigns.items || [])
    setSelectedContact(data)
    const contact = data.contact || {}
    setContactEdit({
      first_name: contact.first_name || '',
      last_name: contact.last_name || '',
      telephone: contact.telephone || '',
      telegram_username: contact.telegram_username || '',
      status: contact.status || 'active',
      preferred_channel: contact.preferred_channel || 'telegram',
      direction: contact.direction || '',
      acquisition_source: contact.acquisition_source || 'unknown',
      acquisition_campaign: contact.acquisition_campaign || '',
    })
  }

  async function saveContact() {
    const contactId = selectedContact?.contact?.id
    if (!contactId) return
    await api(`/api/admin/contacts/${contactId}`, { token, method: 'PATCH', body: contactEdit })
    await Promise.all([selectContact(contactId), loadContacts(contactsPage, contactQuery)])
    setSuccess('Карточка клиента обновлена')
  }

  async function archiveContactProfile() {
    const contactId = selectedContact?.contact?.id
    if (!contactId) return
    if (!window.confirm('Архивировать профиль ученика? Занятия, оплаты и история останутся в базе.')) return
    await api(`/api/admin/contacts/${contactId}/profile`, { token, method: 'DELETE' })
    setSelectedContact(null)
    await loadContacts(contactsPage, contactQuery)
    setSuccess('Профиль архивирован, история сохранена')
  }

  async function addPrepayment() {
    const contactId = selectedContact?.contact?.id
    const amount = Number(prepaymentAmount)
    if (!contactId || !Number.isFinite(amount) || amount <= 0) return
    await api(`/api/admin/contacts/${contactId}/prepayments`, { token, method: 'POST', body: { amount } })
    setPrepaymentAmount('')
    await Promise.all([selectContact(contactId), loadContacts(contactsPage, contactQuery)])
    setSuccess('Предоплата внесена, баланс пополнен')
  }

  async function changeContactOpportunityStage(opportunityId, stage) {
    const contactId = selectedContact?.contact?.id
    if (!contactId) return
    await api(`/api/admin/leads/${opportunityId}`, { token, method: 'PATCH', body: { stage } })
    await Promise.all([selectContact(contactId), loadContacts(contactsPage, contactQuery), loadLeads()])
    setSuccess('Этап воронки обновлён')
  }

  async function patchOpportunityMarketing(opportunityId, payload) {
    const contactId = selectedContact?.contact?.id
    await api(`/api/admin/opportunities/${opportunityId}/marketing`, { token, method: 'PATCH', body: payload })
    if (contactId) await selectContact(contactId)
    setSuccess('Маркетинговые данные сделки обновлены')
  }

  async function moveContactToStage(contactId, stage) {
    await api(`/api/admin/contacts/${contactId}/funnel-stage`, { token, method: 'PATCH', body: { stage } })
    await loadContacts(contactsPage, contactQuery)
    if (selectedContact?.contact?.id === contactId) await selectContact(contactId)
    setSuccess('Клиент перенесён на другой этап')
  }

  async function saveStage(stage) {
    await api(`/api/admin/funnel/stages/${stage.key}`, { token, method: 'PATCH', body: { name: stage.name, metric_role: stage.metric_role || 'new' } })
    await loadContacts(contactsPage, contactQuery)
  }

  async function addStage() {
    const name = newStageName.trim()
    if (!name) return
    await api('/api/admin/funnel/stages', { token, method: 'POST', body: { name } })
    setNewStageName('')
    await loadContacts(contactsPage, contactQuery)
  }

  async function deleteStage(stageKey) {
    await api(`/api/admin/funnel/stages/${stageKey}`, { token, method: 'DELETE' })
    await loadContacts(contactsPage, contactQuery)
  }

  async function createLead() {
    const payload = Object.fromEntries(Object.entries(leadForm).filter(([, value]) => String(value || '').trim() !== ''))
    await api('/api/admin/leads', { token, method: 'POST', body: payload })
    setLeadForm({ full_name: '', telephone: '', source: 'direct', direction: '', goal: '', stage: 'new', notes: '' })
    await loadLeads()
    setSuccess('Лид добавлен в воронку')
  }

  async function changeLeadStage(lead, stage) {
    await api(`/api/admin/leads/${lead.id}`, { token, method: 'PATCH', body: { stage } })
    await loadLeads()
  }

  async function loadAnalyticsV2(mode = analyticsMode, anchorDate = analyticsAnchorDate) {
    setAnalyticsLoading(true)
    try {
      const [overview, delta, series, revenueShare, overviewV2] = await Promise.all([
        api(`/api/admin/analytics/overview?anchor_date=${anchorDate}&mode=${mode}`, { token }),
        api(`/api/admin/analytics/clients-delta?anchor_date=${anchorDate}&mode=${mode}`, { token }),
        api(`/api/admin/analytics/timeseries?anchor_date=${anchorDate}&mode=${mode}`, { token }),
        api(`/api/admin/analytics/revenue-share?anchor_date=${anchorDate}&mode=${mode}`, { token }),
        api(`/api/admin/analytics/overview-v2?anchor_date=${anchorDate}&mode=${mode}`, { token }),
      ])
      setAnalyticsOverview(overview || null)
      setAnalyticsDelta({
        new_active: Array.isArray(delta?.new_active) ? delta.new_active : [],
        became_inactive: Array.isArray(delta?.became_inactive) ? delta.became_inactive : [],
      })
      setAnalyticsSeries(Array.isArray(series?.points) ? series.points : [])
      setAnalyticsSeriesSummary(series?.summary || null)
      setAnalyticsRevenueShare({
        total_paid: Number(revenueShare?.total_paid || 0),
        items: Array.isArray(revenueShare?.items) ? revenueShare.items : [],
      })
      setAnalyticsV2(overviewV2 || null)
    } finally {
      setAnalyticsLoading(false)
    }
  }

  async function loadMarketingAnalytics() {
    setMarketingLoading(true)
    try {
      const params = new URLSearchParams(Object.entries(marketingFilters).filter(([, value]) => value))
      const [metrics, sources, campaigns] = await Promise.all([
        api(`/api/admin/analytics/marketing?${params}`, { token }),
        api('/api/admin/marketing/sources', { token }),
        api('/api/admin/marketing/campaigns', { token }),
      ])
      setMarketingMetrics(metrics || null)
      setMarketingSources(sources.items || [])
      setMarketingCampaigns(campaigns.items || [])
    } finally {
      setMarketingLoading(false)
    }
  }

  async function createMarketingExpense() {
    await api('/api/admin/marketing/expenses', { token, method: 'POST', body: { ...expenseForm, campaign_id: expenseForm.campaign_id ? Number(expenseForm.campaign_id) : null, amount: Number(expenseForm.amount) } })
    setExpenseForm(value => ({ ...value, amount: '', note: '' }))
    await loadMarketingAnalytics()
    setSuccess('Маркетинговый расход добавлен')
  }

  async function createMarketingCampaign() {
    if (!campaignName.trim()) return
    await api('/api/admin/marketing/campaigns', { token, method: 'POST', body: { source_key: expenseForm.source_key, name: campaignName.trim(), ...campaignPeriod } })
    setCampaignName('')
    setCampaignPeriod({ active_from: '', active_to: '' })
    await loadMarketingAnalytics()
    setSuccess('Кампания добавлена')
  }

  async function saveCampaignMetrics(campaignId, views, dialogs) {
    await api(`/api/admin/marketing/campaigns/${campaignId}/metrics`, { token, method: 'PUT', body: { views: Number(views || 0), dialogs: Number(dialogs || 0) } })
    await loadMarketingAnalytics()
    setSuccess('Показатели воронки сохранены')
  }

  async function selectUser(telegramId) {
    const data = await api(`/api/admin/users/${telegramId}`, { token })
    setSelectedUser(data)
    setUserEdit({
      telegram_id: String(data.telegram_id ?? ''),
      first_name: data.first_name || '',
      last_name: data.last_name || '',
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
    try {
      const data = await api(`/api/admin/users/${selectedUser.telegram_id}`, { token, method: 'PATCH', body: fields })
      const nextId = Number(data?.item?.telegram_id || selectedUser.telegram_id)
      await selectUser(nextId)
      await loadUsers()
      setSuccess(successMessage)
    } catch (e) {
      const msg = String(e?.message || e || '')
      if (fields?.telegram_id_new && msg.includes('TELEGRAM_ID_ALREADY_EXISTS')) {
        const okMerge = window.confirm('Этот Telegram ID уже существует. Объединить старый и новый аккаунт (с переносом истории)?')
        if (!okMerge) {
          throw e
        }
        const data = await api(`/api/admin/users/${selectedUser.telegram_id}`, {
          token,
          method: 'PATCH',
          body: { ...fields, merge_if_exists: true },
        })
        const nextId = Number(data?.item?.telegram_id || fields.telegram_id_new || selectedUser.telegram_id)
        await selectUser(nextId)
        await loadUsers()
        setSuccess('Аккаунты объединены')
        return
      }
      throw e
    }
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
    setUserEdit({ telegram_id: '', first_name: '', last_name: '', telephone: '', price: '', balance_set: '', balance_add: '' })
    await loadUsers(1, query).catch(() => {})
    setUsersPage(1)
    setSuccess('Клиент удален')
  }

  async function loadSchedule(targetDay = day) {
    if (!targetDay) {
      setSchedule([])
      return
    }
    const reqId = ++scheduleReqRef.current
    setScheduleLoading(true)
    try {
      const data = await api(`/api/admin/schedule/day?date=${targetDay}`, { token })
      if (reqId !== scheduleReqRef.current) return
      setSchedule(data.items || [])
    } finally {
      if (reqId === scheduleReqRef.current) setScheduleLoading(false)
    }
  }

  async function loadScheduleMonth() {
    const reqId = ++scheduleMonthReqRef.current
    setScheduleMonthLoading(true)
    try {
      const data = await api(`/api/admin/schedule/month?month=${adminMonth}&duration=${scheduleDuration}`, { token })
      if (reqId !== scheduleMonthReqRef.current) return
      setScheduleMonthDays(data.days || [])
    } finally {
      if (reqId === scheduleMonthReqRef.current) setScheduleMonthLoading(false)
    }
  }

  async function loadFreeSlots(targetDay = day) {
    if (!targetDay) {
      setFreeSlots([])
      setSelectedFreeTime('')
      return
    }
    const reqId = ++freeSlotsReqRef.current
    const startedAt = Date.now()
    setFreeSlotsLoading(true)
    try {
      const data = await api(`/api/admin/schedule/free?date=${targetDay}&duration=${scheduleDuration}`, { token })
      if (reqId !== freeSlotsReqRef.current) return
      setFreeSlots(data.slots || [])
      setSelectedFreeTime('')
    } finally {
      const elapsed = Date.now() - startedAt
      const remaining = Math.max(0, 250 - elapsed)
      if (remaining > 0) {
        await new Promise(resolve => window.setTimeout(resolve, remaining))
      }
      if (reqId === freeSlotsReqRef.current) setFreeSlotsLoading(false)
    }
  }

  async function loadExtraAvailability(targetDay = day) {
    const data = await api(`/api/admin/schedule/extra?date=${targetDay}`, { token })
    setExtraAvailability(data.items || [])
  }

  async function loadBlocks(targetDay = day) {
    if (!targetDay) {
      setDayBlocks([])
      return
    }
    const reqId = ++blocksReqRef.current
    setBlocksLoading(true)
    try {
      const data = await api(`/api/admin/blocks?date=${targetDay}`, { token })
      if (reqId !== blocksReqRef.current) return
      setDayBlocks(data.blocks || [])
    } finally {
      if (reqId === blocksReqRef.current) setBlocksLoading(false)
    }
  }

  function buildBlockPayload() {
    return {
      date: day,
      all_day: blockForm.mode === 'all_day',
      start_time: blockForm.mode === 'period' ? blockForm.start_time : null,
      end_time: blockForm.mode === 'period' ? blockForm.end_time : null,
      note: blockForm.note || '',
    }
  }

  async function previewBlock() {
    const data = await api('/api/admin/blocks/preview', {
      token,
      method: 'POST',
      body: buildBlockPayload(),
    })
    setBlockPreview(data)
  }

  async function createBlock() {
    const data = await api('/api/admin/blocks', {
      token,
      method: 'POST',
      body: {
        ...buildBlockPayload(),
        strategy: blockForm.strategy,
        notify_reason_template: blockForm.strategy === 'block_and_cancel_notify' ? blockForm.notify_reason_template : null,
        notify_reason_custom: blockForm.strategy === 'block_and_cancel_notify' ? blockForm.notify_reason_custom : null,
      },
    })
    setDayBlocks(data.blocks || [])
    setBlockPreview(null)
    await loadScheduleMonth().catch(() => {})
    await loadSchedule().catch(() => {})
    await loadFreeSlots().catch(() => {})
    setSuccess(
      data.strategy === 'block_and_cancel_notify'
        ? `Бронь создана, отменено занятий: ${data.canceled}, уведомлений: ${data.notified}`
        : 'Бронь создана'
    )
  }

  async function deleteBlockRange(item) {
    const label = item?.start_time && item?.end_time ? `${item.start_time}-${item.end_time}` : 'весь день'
    if (!window.confirm(`Удалить бронь ${label} на ${day}?`)) return
    const data = await api('/api/admin/blocks', {
      token,
      method: 'DELETE',
      body: {
        date: day,
        all_day: false,
        start_time: item.start_time,
        end_time: item.end_time,
      },
    })
    setDayBlocks(data.blocks || [])
    setBlockPreview(null)
    await loadScheduleMonth().catch(() => {})
    await loadSchedule().catch(() => {})
    await loadFreeSlots().catch(() => {})
    setSuccess('Бронь удалена')
  }

  async function deleteAllBlocksForDay() {
    if (!window.confirm(`Удалить все брони на ${day}?`)) return
    const data = await api('/api/admin/blocks', {
      token,
      method: 'DELETE',
      body: {
        date: day,
        all_day: true,
      },
    })
    setDayBlocks(data.blocks || [])
    setBlockPreview(null)
    await loadScheduleMonth().catch(() => {})
    await loadSchedule().catch(() => {})
    await loadFreeSlots().catch(() => {})
    setSuccess('Все брони на день удалены')
  }

  async function createExtraAvailability() {
    const data = await api('/api/admin/schedule/extra', {
      token,
      method: 'POST',
      body: {
        date: day,
        start_time: extraAvailabilityForm.start_time,
        end_time: extraAvailabilityForm.end_time,
        note: extraAvailabilityForm.note || '',
      },
    })
    setExtraAvailability(data.items || [])
    await loadFreeSlots().catch(() => {})
    setShowExtraAvailabilityForm(false)
    setSuccess('Временные слоты добавлены')
  }

  async function deleteExtraAvailability(itemId) {
    const data = await api(`/api/admin/schedule/extra/${itemId}?date=${day}`, {
      token,
      method: 'DELETE',
    })
    setExtraAvailability(data.items || [])
    await loadFreeSlots().catch(() => {})
    setSuccess('Временные слоты удалены')
  }

  async function deleteScheduleItem(item, scope = 'single') {
    if (!item?.telegram_id) return
    const time = `${String(item.hour).padStart(2, '0')}:${String(item.minute).padStart(2, '0')}`
    const userLabel = item.full_name || String(item.telegram_id)
    const question = scope === 'all_regular'
      ? `Удалить все регулярные занятия клиента ${userLabel} в ${time} (день недели будет очищен)?`
      : `Удалить занятие клиента ${userLabel} на ${day} ${time}?`
    if (!window.confirm(question)) return
    await api(
      `/api/admin/lessons/0?date=${day}&time=${time}&telegram_id=${item.telegram_id}&scope=${scope}`,
      { token, method: 'DELETE' },
    )
    await loadSchedule()
    setSuccess(scope === 'all_regular' ? 'Регулярная серия удалена' : 'Занятие удалено')
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
      await loadUsers().catch(e => setError(String(e.message || e)))
      await loadClientOptions().catch(() => {})
      await loadSchedule().catch(() => {})
      await loadScheduleMonth().catch(() => {})
      await loadBlocks().catch(() => {})
      await loadExtraAvailability().catch(() => {})
      await loadDebtors().catch(() => {})
      await loadUnclosedLessons().catch(() => {})
      await loadSystem().catch(() => {})
      await loadWorkSchedule().catch(() => {})
    })()
  }, [])

  useEffect(() => {
    if (activeTab !== 'work_schedule') return
    loadWorkSchedule().catch(e => setError(String(e.message || e)))
  }, [activeTab])

  useEffect(() => {
    loadUsers().catch(e => setError(String(e.message || e)))
  }, [usersPage])

  useEffect(() => {
    loadScheduleMonth().catch(() => {})
  }, [adminMonth, scheduleDuration])

  useEffect(() => {
    setDay('')
    setSchedule([])
    setFreeSlots([])
    setDayBlocks([])
    setExtraAvailability([])
    setSelectedFreeTime('')
    setScheduleLoading(false)
    setFreeSlotsLoading(false)
    setBlocksLoading(false)
    scheduleReqRef.current += 1
    freeSlotsReqRef.current += 1
    blocksReqRef.current += 1
  }, [adminMonth])

  useEffect(() => {
    if (activeTab !== 'records') return
    if (!day) return
    if (scheduleMode === 'booked') {
      loadSchedule().catch(() => {})
    } else if (scheduleMode === 'free') {
      loadFreeSlots().catch(() => {})
      loadExtraAvailability().catch(() => {})
    } else {
      loadBlocks().catch(() => {})
    }
  }, [activeTab, scheduleMode, day, scheduleDuration])

  useEffect(() => {
    if (activeTab === 'manage' && manageSection === 'finance') {
      loadUnclosedLessons().catch(() => {})
      loadDebtors().catch(() => {})
    }
  }, [activeTab, manageSection, unclosedDaysBack])

  useEffect(() => {
    if (activeTab !== 'analytics') return
    loadAnalyticsV2().catch(e => setError(normalizeErrorMessage(e.message || e)))
  }, [activeTab, analyticsMode, analyticsAnchorDate])

  useEffect(() => {
    if (activeTab !== 'marketing') return
    loadMarketingAnalytics().catch(e => setError(normalizeErrorMessage(e.message || e)))
  }, [activeTab])

  useEffect(() => {
    if (activeTab === 'leads') loadLeads().catch(e => setError(normalizeErrorMessage(e.message || e)))
  }, [activeTab])

  useEffect(() => {
    if (activeTab === 'contacts') loadContacts().catch(e => setError(normalizeErrorMessage(e.message || e)))
  }, [activeTab, contactsPage])

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
  const analyticsPeriodClosed = Boolean(analyticsOverview?.period?.closed)
  const analyticsRevenueDonut = buildRevenueDonut(analyticsRevenueShare?.items || [])
  const analyticsRevenueMax = Math.max(1, ...(analyticsSeries || []).map(point => Math.max(Number(point.paid_amount || 0), Number(point.previous_paid_amount || 0))))
  const analyticsLessonsMax = Math.max(1, ...(analyticsSeries || []).map(point => Math.max(Number(point.lessons_done || 0), Number(point.previous_lessons_done || 0))))
  const analyticsLtvMax = Math.max(1, ...((analyticsV2?.client_value?.ltv_leaderboard || []).map(item => Number(item.total_revenue || 0))))
  const adminCalendarRefreshing = scheduleMonthLoading && scheduleMonthDays.length > 0
  const adminCalendarBusy = scheduleMonthLoading && scheduleMonthDays.length === 0
  const adminScheduleTitle = day
    ? (scheduleMode === 'booked' ? `Записи на ${day}` : scheduleMode === 'free' ? `Свободные слоты на ${day}` : `Бронь на ${day}`)
    : 'Выберите день'

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
    <div className={`mini-layout admin-layout ${navCollapsed ? 'nav-collapsed' : ''}`}>
      <section className="mini-cover">
        <div className="mini-cover-overlay" />
        <div className="mini-cover-head">
          <div className="mini-brand">
            <div className="brand-logo">P</div>
            <div className="brand-meta">
              <strong>PROFFESSOR IT</strong>
              <span>панель управления</span>
            </div>
          </div>
          <button className="circle-btn">◌</button>
        </div>
      </section>

      <div className="mini-body">
        {activeTab === 'records' ? (
          <div className="stack">
            <Card title="Календарь расписания" subtitle={scheduleMode === 'booked' ? 'Просмотр записанных клиентов' : scheduleMode === 'free' ? 'Свободные слоты для назначения' : 'Бронь недоступного времени'}>
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
                  className={scheduleMode === 'block' ? 'seg active' : 'seg'}
                  onClick={() => { setScheduleMode('block'); loadBlocks().catch(() => {}) }}
                >
                  Бронь
                </button>
              </div>
              <div className="month-switch">
                <button className="chip ok" onClick={() => setAdminMonth(prev => shiftMonth(prev, -1))}>{'<'}</button>
                <strong>{formatMonthRu(adminMonth)}</strong>
                <button className="chip ok" onClick={() => setAdminMonth(prev => shiftMonth(prev, 1))}>{'>'}</button>
              </div>
              {adminCalendarRefreshing ? (
                <div className="loading-strip" aria-live="polite">
                  <div className="loading-strip-bar" />
                  <span>Обновляем календарь для {formatMonthRu(adminMonth)}</span>
                </div>
              ) : null}
              <div className="weekdays">
                {weekDays.map(w => <div key={`adm-${w}`}>{w}</div>)}
              </div>
              {adminCalendarBusy ? (
                <div className="calendar-skeleton">
                  {Array.from({ length: 35 }).map((_, idx) => (
                    <div key={`adm-cal-skeleton-${idx}`} className="skeleton-box skeleton-day" />
                  ))}
                </div>
              ) : (
                <div className="calendar-grid">
                  {adminCalendarCells.map((cell, idx) => (
                    cell ? (() => {
                      const cellDisabled = scheduleMode === 'free' && (cell.past || !cell.has_free)
                      const cellMuted = cell.past || (scheduleMode === 'free' && !cell.has_free)
                      const cellTitle = scheduleMode === 'booked'
                        ? `Записей: ${cell.booked_count}`
                        : scheduleMode === 'free'
                          ? (cell.has_free ? `Свободно: ${cell.free_count}` : 'Нет свободных слотов')
                          : `Дата: ${cell.date}`

                      return (
                        <button
                          key={cell.date}
                          disabled={cellDisabled}
                          className={`calendar-day ${day === cell.date ? 'selected' : ''} ${cellDisabled ? 'off' : cellMuted ? 'muted' : 'on'}`}
                          onClick={async () => {
                            setDay(cell.date)
                            if (scheduleMode === 'booked') {
                              await loadSchedule(cell.date).catch(() => {})
                            } else if (scheduleMode === 'free') {
                              await loadFreeSlots(cell.date).catch(() => {})
                            } else {
                              await loadBlocks(cell.date).catch(() => {})
                            }
                          }}
                          title={cellTitle}
                        >
                          <span>{Number(cell.date.slice(8))}</span>
                        </button>
                      )
                    })() : (
                      <div key={`adm-empty-${idx}`} className="calendar-day empty" />
                    )
                  ))}
                </div>
              )}
            </Card>

            {scheduleMode === 'block' ? (
              <Card title={adminScheduleTitle} subtitle="Закрывайте день целиком или только нужный период">
                {blocksLoading ? (
                  <div className="loading-strip compact" aria-live="polite">
                    <div className="loading-strip-bar" />
                    <span>{adminCalendarRefreshing ? 'Ждём данные нового месяца' : 'Загружаем бронь дня'}</span>
                  </div>
                ) : null}
                {!day ? (
                  <div className="empty">Выберите день в календаре.</div>
                ) : (
                <div className="stack">
                  <div className="segmented">
                    <button
                      className={blockForm.mode === 'all_day' ? 'seg active' : 'seg'}
                      onClick={() => {
                        setBlockForm(prev => ({ ...prev, mode: 'all_day' }))
                        setBlockPreview(null)
                      }}
                    >
                      Весь день
                    </button>
                    <button
                      className={blockForm.mode === 'period' ? 'seg active' : 'seg'}
                      onClick={() => {
                        setBlockForm(prev => ({ ...prev, mode: 'period' }))
                        setBlockPreview(null)
                      }}
                    >
                      Период
                    </button>
                  </div>

                  {blockForm.mode === 'period' ? (
                    <div className="custom-row">
                      <input
                        className="input"
                        value={blockForm.start_time}
                        onChange={e => {
                          setBlockForm(prev => ({ ...prev, start_time: e.target.value }))
                          setBlockPreview(null)
                        }}
                        placeholder="18:30"
                      />
                      <input
                        className="input"
                        value={blockForm.end_time}
                        onChange={e => {
                          setBlockForm(prev => ({ ...prev, end_time: e.target.value }))
                          setBlockPreview(null)
                        }}
                        placeholder="20:00"
                      />
                    </div>
                  ) : null}

                  <input
                    className="input"
                    value={blockForm.note}
                    onChange={e => {
                      setBlockForm(prev => ({ ...prev, note: e.target.value }))
                      setBlockPreview(null)
                    }}
                    placeholder="Причина брони для себя"
                  />

                  <div className="mini-actions-row">
                    <button className="btn secondary" onClick={() => loadBlocks().catch(e => setError(String(e.message || e)))}>Обновить брони</button>
                    <button className="btn" onClick={() => previewBlock().catch(e => setError(String(e.message || e)))}>Проверить бронь</button>
                    {dayBlocks.length ? (
                      <button className="btn secondary" onClick={() => deleteAllBlocksForDay().catch(e => setError(String(e.message || e)))}>
                        Очистить день
                      </button>
                    ) : null}
                  </div>

                  <div className="stack">
                    <strong>Текущие блоки</strong>
                    {dayBlocks.length ? (
                      <ul className="list list-compact">
                        {dayBlocks.map(item => (
                          <li key={`block-${item.block_id}`}>
                            <div className="record-main">
                              <strong className="record-time">{item.start_time}-{item.end_time}</strong>
                              <span className="record-name">{item.note || 'Без комментария'}</span>
                            </div>
                            <div className="record-actions">
                              <button className="btn secondary compact" onClick={() => deleteBlockRange(item).catch(e => setError(String(e.message || e)))}>
                                Удалить
                              </button>
                            </div>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <div className="empty">На выбранный день броней нет.</div>
                    )}
                  </div>

                  {blockPreview ? (
                    <div className="stack">
                      <strong>Подтверждение брони</strong>
                      <small>Диапазон: {blockPreview.start_time} - {blockPreview.end_time}</small>
                      <small>Пересечений с занятиями: {blockPreview.conflicts_total || 0}</small>

                      {(blockPreview.conflicts || []).length ? (
                        <>
                          <ul className="list list-compact">
                            {blockPreview.conflicts.map((item, idx) => (
                              <li key={`block-conflict-${idx}`}>
                                <span>{item.time}-{item.end_time}</span>
                                <small>{item.full_name || item.telegram_id} • {item.kind}</small>
                              </li>
                            ))}
                          </ul>

                          <div className="segmented">
                            <button
                              className={blockForm.strategy === 'block_only' ? 'seg active' : 'seg'}
                              onClick={() => setBlockForm(prev => ({ ...prev, strategy: 'block_only' }))}
                            >
                              Только блок
                            </button>
                            <button
                              className={blockForm.strategy === 'block_and_cancel_notify' ? 'seg active' : 'seg'}
                              onClick={() => setBlockForm(prev => ({ ...prev, strategy: 'block_and_cancel_notify' }))}
                            >
                              Блок и отмена
                            </button>
                          </div>

                          {blockForm.strategy === 'block_and_cancel_notify' ? (
                            <div className="stack">
                              <select
                                className="input"
                                value={blockForm.notify_reason_template}
                                onChange={e => setBlockForm(prev => ({ ...prev, notify_reason_template: e.target.value }))}
                              >
                                <option value="illness">Заболел</option>
                                <option value="business_trip">Срочная командировка</option>
                                <option value="force_majeure">Форс-мажор</option>
                              </select>
                              <textarea
                                className="input"
                                value={blockForm.notify_reason_custom}
                                onChange={e => setBlockForm(prev => ({ ...prev, notify_reason_custom: e.target.value }))}
                                placeholder="Или введите свою причину вручную"
                                rows={3}
                              />
                            </div>
                          ) : null}
                        </>
                      ) : (
                        <div className="empty">Пересечений с занятиями нет.</div>
                      )}

                      <div className="mini-actions-row">
                        <button className="btn secondary" onClick={() => setBlockPreview(null)}>Сбросить</button>
                        <button className="btn" onClick={() => createBlock().catch(e => setError(String(e.message || e)))}>
                          Подтвердить бронь
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
                )}
              </Card>
            ) : null}

            {scheduleMode === 'booked' ? (
              <Card title={adminScheduleTitle} subtitle="Клиенты и время">
                {scheduleLoading ? (
                  <div className="loading-strip compact" aria-live="polite">
                    <div className="loading-strip-bar" />
                    <span>{adminCalendarRefreshing ? 'Ждём данные нового месяца' : 'Загружаем записи дня'}</span>
                  </div>
                ) : null}
                {!day ? (
                  <div className="empty">Выберите день в календаре.</div>
                ) : (
                <>
                <button className="btn secondary" onClick={() => loadSchedule().catch(e => setError(String(e.message || e)))}>Обновить</button>
                <ul className="list list-compact">
                  {schedule.map((s, idx) => (
                    <li key={`${s.hour}-${s.minute}-${idx}`} className="record-item">
                      <div className="record-main">
                        <strong className="record-time">
                          {s.kind_code === 'block' && s.end_time
                            ? `${String(s.hour).padStart(2, '0')}:${String(s.minute).padStart(2, '0')}-${s.end_time}`
                            : `${String(s.hour).padStart(2, '0')}:${String(s.minute).padStart(2, '0')}`}
                        </strong>
                        <span className="record-name">{s.full_name}</span>
                      </div>
                      <div className="record-meta">
                        <small>{s.kind} • {s.duration || 60} мин{s.kind_code === 'block' && s.slot_count ? ` • ${s.slot_count} слотов` : ''}</small>
                        {s.kind_code !== 'block' ? <small>{s.amount || 0} ₽</small> : null}
                      </div>
                      {s.telegram_id && s.kind_code !== 'block' ? (
                        s.kind_code === 'regular' ? (
                          <div className="record-actions">
                            <button className="btn secondary compact" onClick={() => deleteScheduleItem(s, 'single').catch(e => setError(String(e.message || e)))}>
                              Удалить это
                            </button>
                            <button className="btn secondary compact" onClick={() => deleteScheduleItem(s, 'all_regular').catch(e => setError(String(e.message || e)))}>
                              Удалить серию
                            </button>
                          </div>
                        ) : (
                          <div className="record-actions">
                            <button className="btn secondary compact" onClick={() => deleteScheduleItem(s, 'single').catch(e => setError(String(e.message || e)))}>
                              Удалить
                            </button>
                          </div>
                        )
                      ) : null}
                    </li>
                  ))}
                </ul>
                </>
                )}
              </Card>
            ) : null}

            {scheduleMode === 'free' ? (
              <Card title={adminScheduleTitle} subtitle="Выберите слот, назначьте клиента или откройте временные окна">
                {freeSlotsLoading ? (
                  <div className="loading-strip compact" aria-live="polite">
                    <div className="loading-strip-bar" />
                    <span>{adminCalendarRefreshing ? 'Ждём данные нового месяца' : 'Загружаем свободные слоты'}</span>
                  </div>
                ) : null}
                {!day ? (
                  <div className="empty">Выберите день в календаре.</div>
                ) : (
                <>
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
                <div className="record-actions">
                  <button className="btn secondary" onClick={() => loadFreeSlots().catch(e => setError(String(e.message || e)))}>Обновить слоты</button>
                  <button className="btn secondary" onClick={() => setShowExtraAvailabilityForm(v => !v)}>
                    {showExtraAvailabilityForm ? 'Скрыть форму' : 'Добавить временные слоты'}
                  </button>
                </div>
                {showExtraAvailabilityForm ? (
                  <div className="stack">
                    <small>Дата берётся из выбранного дня: {day}</small>
                    <div className="record-actions">
                      <input
                        className="input"
                        value={extraAvailabilityForm.start_time}
                        onChange={e => setExtraAvailabilityForm(v => ({ ...v, start_time: e.target.value }))}
                        placeholder="С"
                      />
                      <input
                        className="input"
                        value={extraAvailabilityForm.end_time}
                        onChange={e => setExtraAvailabilityForm(v => ({ ...v, end_time: e.target.value }))}
                        placeholder="По"
                      />
                    </div>
                    <input
                      className="input"
                      value={extraAvailabilityForm.note}
                      onChange={e => setExtraAvailabilityForm(v => ({ ...v, note: e.target.value }))}
                      placeholder="Комментарий"
                    />
                    <button className="btn" onClick={() => createExtraAvailability().catch(e => setError(String(e.message || e)))}>
                      Сохранить временные слоты
                    </button>
                  </div>
                ) : null}
                {extraAvailability.length ? (
                  <div className="stack">
                    <small>Открытые временные окна</small>
                    <ul className="list list-compact">
                      {extraAvailability.map(item => (
                        <li key={`extra-${item.id}`} className="record-item">
                          <div className="record-main">
                            <strong className="record-time">{item.start_time}-{item.end_time}</strong>
                            <span className="record-name">{item.note || 'Временные слоты'}</span>
                          </div>
                          <div className="record-actions">
                            <button className="btn secondary compact" onClick={() => deleteExtraAvailability(item.id).catch(e => setError(String(e.message || e)))}>
                              Удалить
                            </button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
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
                </>
                )}
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

        {activeTab === 'contacts' ? (
          <div className="stack">
            <Card className="contacts-toolbar" title="Клиенты" subtitle="Единый реестр лидов и учеников">
              <div className="contacts-toolbar-controls">
                <div className="contacts-view-switch" role="group" aria-label="Представление клиентов">
                  <button className={contactsView === 'table' ? 'active' : ''} onClick={() => setContactsView('table')}>Таблица</button>
                  <button className={contactsView === 'kanban' ? 'active' : ''} onClick={() => setContactsView('kanban')}>Канбан</button>
                </div>
                <div className="custom-row">
                  <input
                    className="input"
                    value={contactQuery}
                    onChange={e => setContactQuery(e.target.value)}
                    placeholder="Имя, телефон или Telegram username"
                  />
                  <button className="btn" onClick={() => { setContactsPage(1); loadContacts(1, contactQuery).catch(e => setError(normalizeErrorMessage(e.message || e))) }}>
                    Поиск
                  </button>
                </div>
                <div className="mini-actions-row">
                  <button className="btn secondary" disabled={contactsPage <= 1} onClick={() => setContactsPage(page => Math.max(1, page - 1))}>← Стр.</button>
                  <button className="btn secondary" disabled={contacts.length < 20} onClick={() => setContactsPage(page => page + 1)}>Стр. →</button>
                </div>
              </div>
            </Card>

            <div className={`contacts-workspace ${selectedContact ? 'has-selection' : ''}`}>
              <section className="contacts-main-panel">
                {contactsView === 'kanban' ? (
                  <section className="funnel-board" aria-label="Воронка клиентов">
                    <div className="funnel-board-head"><div><small>CRM-воронка</small><h2>Клиенты по этапам</h2></div><div className="funnel-board-actions"><small>Перетащите клиента в нужную колонку</small><button className="btn secondary compact" onClick={() => setStageSettingsOpen(value => !value)}>{stageSettingsOpen ? 'Закрыть этапы' : 'Настроить этапы'}</button></div></div>
                    {stageSettingsOpen ? <div className="stage-settings"><strong>Этапы воронки</strong><small>Название и бизнес-смысл редактируются отдельно; это сохраняет аналитику при переименовании.</small><div className="stage-settings-list">{funnelStages.map(stage => <div className="stage-settings-row" key={stage.key}><input className="input" value={stage.name} onChange={e => setFunnelStages(items => items.map(item => item.key === stage.key ? { ...item, name: e.target.value } : item))} /><select className="input" value={stage.metric_role || 'new'} onChange={e => setFunnelStages(items => items.map(item => item.key === stage.key ? { ...item, metric_role: e.target.value } : item))}>{Object.entries(MARKETING_ROLE_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><button className="btn secondary compact" onClick={() => saveStage(stage).catch(error => setError(normalizeErrorMessage(error.message || error)))}>Сохранить</button><button className="btn secondary compact" onClick={() => deleteStage(stage.key).catch(error => setError(normalizeErrorMessage(error.message || error)))}>Удалить</button></div>)}</div><div className="stage-add-row"><input className="input" value={newStageName} onChange={e => setNewStageName(e.target.value)} placeholder="Новый этап" /><button className="btn compact" onClick={() => addStage().catch(error => setError(normalizeErrorMessage(error.message || error)))}>Добавить</button></div></div> : null}
                    <div className="funnel-columns">
                      {funnelStages.map(stage => {
                        const stageContacts = contactsBoard.filter(contact => contact.current_stage === stage.key)
                        return (
                          <div className="funnel-column" key={stage.key} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); const contactId = Number(event.dataTransfer.getData('text/plain') || draggedContactId); if (contactId) moveContactToStage(contactId, stage.key).catch(error => setError(normalizeErrorMessage(error.message || error))); setDraggedContactId(null) }}>
                            <div className="funnel-column-head"><strong>{stage.name}</strong><span>{stageContacts.length}</span></div>
                            <div className="funnel-cards">
                              {stageContacts.map(contact => (
                                <button className="funnel-card" draggable key={contact.id} onDragStart={event => { setDraggedContactId(contact.id); event.dataTransfer.setData('text/plain', String(contact.id)); event.dataTransfer.effectAllowed = 'move' }} onDragEnd={() => setDraggedContactId(null)} onClick={() => selectContact(contact.id).catch(e => setError(normalizeErrorMessage(e.message || e)))}>
                                  <strong>{contact.full_name}</strong>
                                  <small>{contact.direction || contact.current_source || (contact.is_student ? 'ученик' : 'без направления')}</small>
                                </button>
                              ))}
                              {!stageContacts.length ? <small className="funnel-empty">Пусто</small> : null}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </section>
                ) : (
                  <section className="contacts-table-panel">
                    <div className="contacts-table-meta">Всего: {contactsTotal}</div>
                    <div className="contacts-table-scroll">
                      <table className="contacts-table">
                        <thead>
                          <tr><th>Клиент</th><th>Телефон</th><th>Telegram</th><th>Этап</th><th>Направление</th><th>Сделки</th></tr>
                        </thead>
                        <tbody>
                          {contacts.map(contact => (
                            <tr key={contact.id} className={selectedContact?.contact?.id === contact.id ? 'selected' : ''} onClick={() => selectContact(contact.id).catch(e => setError(normalizeErrorMessage(e.message || e)))}>
                              <td><strong>{contact.full_name}</strong></td>
                              <td>{contact.telephone || '—'}</td>
                              <td>{contact.telegram_username ? `@${contact.telegram_username}` : (contact.telegram_id || '—')}</td>
                              <td><span className={`contact-badge ${contact.current_stage === 'won' ? 'student' : 'lead'}`}>{funnelStageLabel(contact.current_stage, funnelStages)}</span></td>
                              <td>{contact.direction || '—'}</td>
                              <td>{contact.opportunities_count || '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {!contacts.length ? <div className="empty-state">Клиентов пока нет.</div> : null}
                  </section>
                )}
              </section>

              {selectedContact ? (
                <aside className="contact-side-panel">
                    <div className="contact-panel-head">
                      <div><small>Карточка клиента</small><h2>{selectedContact.contact?.full_name || 'Без имени'}</h2></div>
                      <div className="contact-panel-actions"><span className={`contact-badge ${selectedContact.contact?.is_student ? 'student' : 'lead'}`}>{selectedContact.contact?.is_student ? 'Ученик' : 'Лид'}</span><button className="contact-panel-close" onClick={() => setSelectedContact(null)} aria-label="Закрыть карточку клиента">×</button></div>
                    </div>
                    <div className="contact-edit-form">
                      <label>Имя<input className="input" value={contactEdit.first_name} onChange={e => setContactEdit(value => ({ ...value, first_name: e.target.value }))} /></label>
                      <label>Фамилия<input className="input" value={contactEdit.last_name} onChange={e => setContactEdit(value => ({ ...value, last_name: e.target.value }))} /></label>
                      <label className="contact-field-wide">Телефон<input className="input" value={contactEdit.telephone} onChange={e => setContactEdit(value => ({ ...value, telephone: e.target.value }))} /></label>
                      <label className="contact-field-wide">Telegram username<input className="input" value={contactEdit.telegram_username} onChange={e => setContactEdit(value => ({ ...value, telegram_username: e.target.value }))} placeholder="username без @" /></label>
                      <label>Статус<select className="input" value={contactEdit.status} onChange={e => setContactEdit(value => ({ ...value, status: e.target.value }))}><option value="lead">Лид</option><option value="active">Активный</option><option value="student">Ученик</option><option value="archived">Архив</option></select></label>
                      <label>Канал связи<select className="input" value={contactEdit.preferred_channel} onChange={e => setContactEdit(value => ({ ...value, preferred_channel: e.target.value }))}><option value="telegram">Telegram</option><option value="phone">Телефон</option></select></label>
                      {selectedContact.contact?.is_student ? <label className="contact-field-wide">Направление<input className="input" value={contactEdit.direction} onChange={e => setContactEdit(value => ({ ...value, direction: e.target.value }))} placeholder="DevOps, ИБ, Хакер" /></label> : null}
                      <label>Первый источник<select className="input" value={contactEdit.acquisition_source} onChange={e => setContactEdit(value => ({ ...value, acquisition_source: e.target.value, acquisition_campaign: '' }))}>{marketingSources.map(item => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label>
                      <label>Кампания первого касания<select className="input" value={contactEdit.acquisition_campaign} onChange={e => setContactEdit(value => ({ ...value, acquisition_campaign: e.target.value }))}><option value="">Без кампании</option>{contactEdit.acquisition_campaign && !marketingCampaigns.some(item => item.source_key === contactEdit.acquisition_source && item.name === contactEdit.acquisition_campaign) ? <option value={contactEdit.acquisition_campaign}>{contactEdit.acquisition_campaign}</option> : null}{marketingCampaigns.filter(item => item.source_key === contactEdit.acquisition_source).map(item => <option key={item.id} value={item.name}>{item.name}</option>)}</select></label>
                    </div>
                    <small>Источник и кампания связывают клиента с расходами в «Аналитика → Маркетинг». Выберите ту же кампанию, на которую внесён расход.</small>
                    <button className="btn contact-save" onClick={() => saveContact().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Сохранить изменения</button>
                    {selectedContact.contact?.is_student ? <button className="btn secondary contact-save" onClick={() => archiveContactProfile().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Архивировать профиль</button> : null}

                <div className="detail-grid">
                  <div><small>Telegram</small><strong>{selectedContact.contact?.telegram_username ? `@${selectedContact.contact.telegram_username}` : (selectedContact.contact?.telegram_id || 'не привязан')}</strong></div>
                  <div><small>Баланс занятий</small><strong>{selectedContact.contact?.balance_lessons ?? 0}</strong></div>
                  <div><small>Оплаты (последние 12)</small><strong>{formatMoneyShort(selectedContact.paid_total_recent)}</strong></div>
                </div>
                {selectedContact.contact?.is_student ? <div className="custom-row" style={{ marginTop: 12 }}><input className="input" type="number" min="1" value={prepaymentAmount} onChange={e => setPrepaymentAmount(e.target.value)} placeholder="Предоплата, ₽" /><button className="btn" onClick={() => addPrepayment().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Внести оплату и пополнить баланс</button></div> : null}

                <h3>Сделки</h3>
                {selectedContact.opportunities?.length ? <ul className="list list-compact">{selectedContact.opportunities.map(item => (
                  <li key={item.id} className="contact-opportunity-row"><div><strong>{item.direction || 'Направление не указано'}</strong><small>{item.next_contact_at ? `Следующее действие: ${item.next_contact_at}` : 'Этап сделки ведётся отдельно от атрибуции'}</small>{!['won', 'lost'].includes(item.stage) ? <div className="custom-row" style={{ marginTop: 8 }}><input className="input" type="datetime-local" defaultValue={item.diagnostic_scheduled_at || ''} aria-label="Дата диагностики" onBlur={e => patchOpportunityMarketing(item.id, { diagnostic_scheduled_at: e.target.value || null }).catch(err => setError(normalizeErrorMessage(err.message || err)))} /><button className="btn secondary compact" onClick={() => patchOpportunityMarketing(item.id, { diagnostic_held_at: new Date().toISOString().slice(0, 16) }).catch(err => setError(normalizeErrorMessage(err.message || err)))}>Диагностика проведена</button></div> : null}</div><select className="input" value={item.stage} onChange={e => changeContactOpportunityStage(item.id, e.target.value).catch(err => setError(normalizeErrorMessage(err.message || err)))}>{funnelStages.map(stage => <option key={stage.key} value={stage.key}>{stage.name}</option>)}</select></li>
                ))}</ul> : <small>Коммерческих сделок пока нет.</small>}

                <h3>Ближайшая история занятий</h3>
                {selectedContact.lessons?.length ? <ul className="list list-compact">{selectedContact.lessons.map((item, index) => (
                  <li key={`${item.date}-${item.time}-${index}`}><strong>{item.date} · {item.time}</strong><small>{item.duration} мин · {item.booking_status}</small></li>
                ))}</ul> : <small>Занятий пока нет.</small>}

                <h3>Последние оплаты</h3>
                {selectedContact.payments?.length ? <ul className="list list-compact">{selectedContact.payments.map((item, index) => (
                  <li key={`${item.date}-${index}`}><strong>{item.date}</strong><small>{formatMoneyShort(item.amount)} · {item.status}</small></li>
                ))}</ul> : <small>Оплат пока нет.</small>}
                </aside>
              ) : null}
            </div>
          </div>
        ) : null}

        {activeTab === 'manage' ? (
          <div className="stack">
            <Card title="Управление" subtitle="Клиенты, финансы, рассылки">
              <div className="segmented">
                <button className={manageSection === 'finance' ? 'seg active' : 'seg'} onClick={() => setManageSection('finance')}>Финансы</button>
                <button className={manageSection === 'broadcast' ? 'seg active' : 'seg'} onClick={() => setManageSection('broadcast')}>Рассылки</button>
              </div>
            </Card>

            {manageSection === 'clients' ? (
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
                    <li
                      key={u.telegram_id}
                      className={`user-list-item ${u.active_recent ? 'is-active' : 'is-inactive'}`}
                    >
                      <button className="btn secondary" onClick={() => selectUser(u.telegram_id).catch(e => setError(String(e.message || e)))}>
                        {(u.full_name || u.telegram_id)} {u.blocked ? '🔒' : ''}
                      </button>
                      <small className="user-last-lesson">
                        {u.last_lesson_date
                          ? `Последнее занятие: ${u.last_lesson_date} ${u.last_lesson_time || ''}`
                          : 'Последних проведённых занятий нет'}
                      </small>
                      {selectedUser && Number(selectedUser.telegram_id) === Number(u.telegram_id) ? (
                        <div className="inline-user-editor">
                          <div className="stack">
                            {selectedUser.username ? (
                              <a
                                className="username-link"
                                href={`https://t.me/${String(selectedUser.username).replace('@', '')}`}
                                target="_blank"
                                rel="noreferrer"
                              >
                                @{String(selectedUser.username).replace('@', '')}
                              </a>
                            ) : null}
                            <small>Telegram ID</small>
                            <input
                              className="input"
                              value={userEdit.telegram_id}
                              onChange={e => setUserEdit(v => ({ ...v, telegram_id: e.target.value }))}
                              placeholder="Например: 123456789"
                            />
                            <small>Имя</small>
                            <input className="input" value={userEdit.first_name} onChange={e => setUserEdit(v => ({ ...v, first_name: e.target.value }))} placeholder="Имя" />
                            <small>Фамилия</small>
                            <input className="input" value={userEdit.last_name} onChange={e => setUserEdit(v => ({ ...v, last_name: e.target.value }))} placeholder="Фамилия" />
                            <small>Телефон</small>
                            <input className="input" value={userEdit.telephone} onChange={e => setUserEdit(v => ({ ...v, telephone: e.target.value }))} placeholder="+7..." />
                            <small>Цена за 60 мин (₽)</small>
                            <input className="input" value={userEdit.price} onChange={e => setUserEdit(v => ({ ...v, price: e.target.value }))} placeholder="Например: 1500" />
                            <div className="mini-actions-row">
                              <button className="btn" onClick={() => saveUserPatch({
                                telegram_id_new: Number(userEdit.telegram_id || selectedUser.telegram_id),
                                first_name: userEdit.first_name,
                                last_name: userEdit.last_name,
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
                              <strong>Сводка по ученику</strong>
                              <small>Всего записей: {selectedUser.records_count ?? 0} • Регулярных слотов: {(selectedUser.regular || []).length}</small>
                              <strong>Регулярные слоты</strong>
                              {(selectedUser.regular || []).length ? (
                                <ul className="list list-compact">
                                  {(selectedUser.regular || []).slice(0, 8).map((r, i) => (
                                    <li key={`reg-${i}`}>
                                      <span>{dayName(Number(r.day_of_week))} {r.time}</span>
                                      <small>{r.duration || 60} мин</small>
                                    </li>
                                  ))}
                                </ul>
                              ) : (
                                <div className="placeholder-box">Регулярные занятия не настроены.</div>
                              )}
                              <strong>Ближайшие записи</strong>
                              {(selectedUserUpcoming || []).length ? (
                                <ul className="list list-compact">
                                  {(selectedUserUpcoming || []).slice(0, 8).map((b, i) => (
                                    <li key={`up-${i}`}>
                                      <span>{b.date} {b.time}</span>
                                      <small>{b.kind === 'regular' ? 'Регулярное' : 'Разовое'}</small>
                                    </li>
                                  ))}
                                </ul>
                              ) : (
                                <div className="placeholder-box">Ближайших записей пока нет.</div>
                              )}
                              <strong>Архив занятий</strong>
                              {(selectedUserArchive || []).length ? (
                                <ul className="list list-compact">
                                  {(selectedUserArchive || []).slice(0, 8).map((b, i) => (
                                    <li key={`ar-${i}`}>
                                      <span>{b.date} {b.time}</span>
                                      <small>{b.kind === 'regular' ? 'Регулярное' : 'Разовое'}</small>
                                    </li>
                                  ))}
                                </ul>
                              ) : (
                                <div className="placeholder-box">Архив пока пуст.</div>
                              )}
                            </div>
                          </div>
                        </div>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </Card>
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
                  <div className="mini-actions-row mini-actions-row-wrap">
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
                    <button className="btn secondary" disabled={!selectedUnclosedKeys.length} onClick={() => closeSelectedUnclosed('canceled').catch(e => setError(String(e.message || e)))}>
                      Массово: Отмена
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

        {activeTab === 'leads' ? (
          <div className="stack">
            <Card title="Воронка лидов" subtitle="Источники, диагностики и продажи">
              <div className="pill-row">
                <Pill label="Всего лидов" value={leadSummary?.total || 0} tone="blue" />
                <Pill label="Диагностики" value={(leadSummary?.by_source || []).reduce((sum, item) => sum + Number(item.diagnostics || 0), 0)} tone="mint" />
                <Pill label="Продажи" value={(leadSummary?.by_source || []).reduce((sum, item) => sum + Number(item.won || 0), 0)} tone="violet" />
              </div>
              {(leadSummary?.by_source || []).length ? (
                <ul className="list list-compact" style={{ marginTop: 14 }}>
                  {leadSummary.by_source.map(item => <li key={item.source}><span>{item.source}</span><strong>{item.leads} лид. · {item.diagnostics} диагн. · {item.won} прод.</strong></li>)}
                </ul>
              ) : <div className="empty" style={{ marginTop: 14 }}>Добавьте первое обращение или передайте метку источника через Telegram-ссылку.</div>}
            </Card>
            <Card title="Добавить лид" subtitle="Заполняйте сразу после обращения">
              <div className="stack" style={{ marginTop: 0 }}>
                <input className="input" value={leadForm.full_name} onChange={e => setLeadForm(v => ({ ...v, full_name: e.target.value }))} placeholder="Имя" />
                <input className="input" value={leadForm.telephone} onChange={e => setLeadForm(v => ({ ...v, telephone: e.target.value }))} placeholder="Телефон" />
                <input className="input" value={leadForm.source} onChange={e => setLeadForm(v => ({ ...v, source: e.target.value }))} placeholder="Источник: avito_devops / youtube" />
                <input className="input" value={leadForm.direction} onChange={e => setLeadForm(v => ({ ...v, direction: e.target.value }))} placeholder="Направление" />
                <textarea className="input" rows={3} value={leadForm.goal} onChange={e => setLeadForm(v => ({ ...v, goal: e.target.value }))} placeholder="Задача и цель" />
                <button className="btn" onClick={() => createLead().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Добавить в воронку</button>
              </div>
            </Card>
            <Card title="Текущие обращения" subtitle="Меняйте этап прямо здесь">
              {leads.length ? <ul className="list list-compact">{leads.map(lead => (
                <li key={lead.id} className="lead-row"><div><strong>{lead.full_name || lead.telephone || 'Без имени'}</strong><small>{lead.source} · {lead.direction || 'направление не указано'}</small></div><select className="input" value={lead.stage} onChange={e => changeLeadStage(lead, e.target.value).catch(err => setError(normalizeErrorMessage(err.message || err)))}>{funnelStages.map(stage => <option key={stage.key} value={stage.key}>{stage.name}</option>)}</select></li>
              ))}</ul> : <div className="empty">Лидов пока нет.</div>}
            </Card>
          </div>
        ) : null}

        {(activeTab === 'analytics' || activeTab === 'marketing') ? (
          <div className="stack analytics-stack">
            {activeTab === 'marketing' ? (
              <>
                <Card title="Эффективность маркетинга" subtitle="Первое касание клиента определяет источник выручки навсегда">
                  <div className="custom-row">
                    <input type="date" className="input" value={marketingFilters.date_from} onChange={e => setMarketingFilters(v => ({ ...v, date_from: e.target.value }))} />
                    <input type="date" className="input" value={marketingFilters.date_to} onChange={e => setMarketingFilters(v => ({ ...v, date_to: e.target.value }))} />
                    <select className="input" value={marketingFilters.source_key} onChange={e => setMarketingFilters(v => ({ ...v, source_key: e.target.value, campaign: '' }))}><option value="">Все источники</option>{marketingSources.map(item => <option key={item.key} value={item.key}>{item.name}</option>)}</select>
                    <select className="input" value={marketingFilters.campaign} onChange={e => setMarketingFilters(v => ({ ...v, campaign: e.target.value }))}><option value="">Все кампании</option>{marketingCampaigns.filter(item => !marketingFilters.source_key || item.source_key === marketingFilters.source_key).map(item => <option key={item.id} value={item.name}>{item.name}</option>)}</select>
                    <input className="input" value={marketingFilters.direction} onChange={e => setMarketingFilters(v => ({ ...v, direction: e.target.value }))} placeholder="Направление" />
                    <button className="btn" onClick={() => loadMarketingAnalytics().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Обновить</button>
                  </div>
                  {marketingLoading ? <div className="loading">Считаем маркетинг...</div> : null}
                  {marketingMetrics ? <div className="analytics-kpi-grid" style={{ marginTop: 14 }}>
                    {[
                      ['Расходы', marketingMetrics.kpi?.spend, 'money'], ['Лиды', marketingMetrics.kpi?.leads], ['Квалифицированы', marketingMetrics.kpi?.qualified], ['Диагностики назначены', marketingMetrics.kpi?.diagnostics_scheduled], ['Диагностики проведены', marketingMetrics.kpi?.diagnostics_held], ['Новые клиенты', marketingMetrics.kpi?.new_clients], ['Первая выручка', marketingMetrics.kpi?.first_revenue, 'money'], ['Выручка периода', marketingMetrics.kpi?.cash_revenue, 'money'], ['CPL', marketingMetrics.kpi?.cpl, 'money'], ['Стоимость квалиф. лида', marketingMetrics.kpi?.cpql, 'money'], ['CAC', marketingMetrics.kpi?.cac, 'money'], ['Средний первый платёж', marketingMetrics.kpi?.avg_first_payment, 'money'], ['ROMI', marketingMetrics.kpi?.romi, 'percent'],
                    ].map(([label, value, kind]) => <div className="analytics-kpi-card" key={label}><span>{label}</span><strong>{metricValue(value, kind)}</strong></div>)}
                  </div> : <div className="placeholder-box">Выберите период и обновите отчёт.</div>}
                </Card>
                <Card title="Маркетинговая воронка" subtitle="Конверсия от лидов к бизнес-этапу">
                  <div className="analytics-kpi-grid">{(marketingMetrics?.funnel || []).map(item => <div className="analytics-kpi-card" key={item.role}><span>{MARKETING_ROLE_LABELS[item.role] || item.role}</span><strong>{item.count}</strong><small>{item.conversion_from_leads === null ? 'нет данных' : `${item.conversion_from_leads}% от лидов`}</small></div>)}</div>
                </Card>
                <Card title="Воронка объявлений" subtitle="Вносите вручную охват и диалоги; CRM-этапы считаются автоматически">
                  {(marketingMetrics?.rows || []).filter(row => row.campaign_id).map(row => <div key={`funnel-${row.campaign_id}`} style={{ marginBottom: 18 }}><div className="custom-row"><strong>#{row.campaign_id} · {row.campaign_name}</strong><input className="input" type="number" min="0" defaultValue={row.manual_metrics?.views || 0} id={`views-${row.campaign_id}`} placeholder="Просмотры" /><input className="input" type="number" min="0" defaultValue={row.manual_metrics?.dialogs || 0} id={`dialogs-${row.campaign_id}`} placeholder="Диалоги" /><button className="btn secondary compact" onClick={() => saveCampaignMetrics(row.campaign_id, document.getElementById(`views-${row.campaign_id}`)?.value, document.getElementById(`dialogs-${row.campaign_id}`)?.value).catch(e => setError(normalizeErrorMessage(e.message || e)))}>Сохранить</button></div><div style={{ display: 'grid', gap: 5, marginTop: 10, justifyItems: 'center' }}>{[['Просмотры', row.manual_metrics?.views || 0, '#f6b95a'], ['Диалоги', row.manual_metrics?.dialogs || 0, '#a8c400'], ['Лиды', row.leads, '#5596ea'], ['Диагностики', row.diagnostics_held, '#8e5cf5'], ['Оплаты', row.new_clients, '#54d9a0']].map(([label, value, color], index) => <div key={label} style={{ width: `${Math.max(24, 100 - index * 15)}%`, background: color, color: '#10131a', textAlign: 'center', padding: '8px 12px', clipPath: 'polygon(5% 0,95% 0,100% 100%,0 100%)', fontWeight: 700 }}>{label}: {value}</div>)}</div></div>)}
                </Card>
                <Card title="Источники и кампании" subtitle="Расходы и выручка по первому касанию">
                  {(marketingMetrics?.rows || []).length ? <div className="contacts-table-wrap"><table className="contacts-table"><thead><tr><th>Источник</th><th>Кампания / ID</th><th>Период</th><th>Расход</th><th>Лиды</th><th>Диагн.</th><th>Клиенты</th><th>Выручка</th><th>CAC</th><th>ROMI</th><th>LTV</th></tr></thead><tbody>{marketingMetrics.rows.map((row, index) => <tr key={`${row.source_key}-${row.campaign_name || 'none'}-${index}`}><td>{row.source_name}</td><td>{row.campaign_id ? `#${row.campaign_id} · ` : ''}{row.campaign_name || '—'}</td><td>{row.active_from || '—'} → {row.active_to || '—'}</td><td>{metricValue(row.spend, 'money')}</td><td>{row.leads}</td><td>{row.diagnostics_held}</td><td>{row.new_clients}</td><td>{metricValue(row.cash_revenue, 'money')}</td><td>{metricValue(row.cac, 'money')}</td><td>{metricValue(row.romi, 'percent')}</td><td>{metricValue(row.ltv, 'money')}</td></tr>)}</tbody></table></div> : <div className="placeholder-box">Нет источников или расходов за период.</div>}
                </Card>
                <Card title="Качество данных" subtitle="Что нужно заполнить, чтобы решения были точными"><div className="pill-row"><Pill label="Контакты: неизвестный источник" value={marketingMetrics?.data_quality?.contacts_unknown_source ?? '—'} tone="violet" /><Pill label="Нет кампании" value={marketingMetrics?.data_quality?.contacts_missing_campaign ?? '—'} tone="violet" /><Pill label="Нет следующего действия" value={marketingMetrics?.data_quality?.opportunities_missing_next_contact ?? '—'} tone="violet" /></div></Card>
                <Card title="Добавить расход" subtitle="Только маркетинговые вложения: размещение, реклама, контент, подрядчики"><div className="custom-row"><input type="date" className="input" value={expenseForm.spent_at} onChange={e => setExpenseForm(v => ({ ...v, spent_at: e.target.value }))} /><select className="input" value={expenseForm.source_key} onChange={e => setExpenseForm(v => ({ ...v, source_key: e.target.value, campaign_id: '' }))}>{marketingSources.map(item => <option key={item.key} value={item.key}>{item.name}</option>)}</select><select className="input" value={expenseForm.campaign_id} onChange={e => setExpenseForm(v => ({ ...v, campaign_id: e.target.value }))}><option value="">Без кампании</option>{marketingCampaigns.filter(item => item.source_key === expenseForm.source_key).map(item => <option key={item.id} value={item.id}>#{item.id} · {item.name}</option>)}</select><select className="input" value={expenseForm.category} onChange={e => setExpenseForm(v => ({ ...v, category: e.target.value }))}><option value="placement">Размещение</option><option value="advertising">Реклама</option><option value="content">Контент</option><option value="contractor">Подрядчик</option></select><input className="input" type="number" min="1" value={expenseForm.amount} onChange={e => setExpenseForm(v => ({ ...v, amount: e.target.value }))} placeholder="Сумма, ₽" /><input className="input" value={expenseForm.note} onChange={e => setExpenseForm(v => ({ ...v, note: e.target.value }))} placeholder="Комментарий" /><button className="btn" onClick={() => createMarketingExpense().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Добавить</button></div><div className="custom-row" style={{ marginTop: 10 }}><input className="input" value={campaignName} onChange={e => setCampaignName(e.target.value)} placeholder="Название новой кампании" /><input type="date" className="input" value={campaignPeriod.active_from} onChange={e => setCampaignPeriod(v => ({ ...v, active_from: e.target.value }))} /><input type="date" className="input" value={campaignPeriod.active_to} onChange={e => setCampaignPeriod(v => ({ ...v, active_to: e.target.value }))} /><button className="btn secondary" onClick={() => createMarketingCampaign().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Создать кампанию</button></div></Card>
              </>
            ) : <>
            <Card title="Аналитика" subtitle="Клиенты, финансы и динамика">
              <div className="segmented">
                <button className={analyticsMode === 'week' ? 'seg active' : 'seg'} onClick={() => setAnalyticsMode('week')}>Неделя</button>
                <button className={analyticsMode === 'month' ? 'seg active' : 'seg'} onClick={() => setAnalyticsMode('month')}>Месяц</button>
                <button className={analyticsMode === 'quarter' ? 'seg active' : 'seg'} onClick={() => setAnalyticsMode('quarter')}>Квартал</button>
              </div>
              <div className="custom-row">
                <input type="date" className="input" value={analyticsAnchorDate} onChange={e => setAnalyticsAnchorDate(e.target.value)} />
                <button className="btn" onClick={() => { loadAnalyticsV2().catch(e => setError(normalizeErrorMessage(e.message || e))) }}>Обновить</button>
              </div>
              {analyticsLoading ? <div className="loading">Загружаем аналитику...</div> : null}
              {analyticsOverview ? (
                <div className="pill-row">
                  <Pill label={`Доход (${analyticsModeLabel(analyticsMode)})`} value={`${analyticsOverview.finance?.paid_now ?? 0} ₽`} tone="mint" />
                  <Pill label="Активные ученики" value={analyticsOverview.clients?.active_now ?? 0} tone="blue" />
                  <Pill label="Занятия" value={analyticsOverview.ops?.lessons_now ?? 0} tone="violet" />
                  <Pill label="Средний чек" value={`${analyticsOverview.ops?.avg_check_now ?? 0} ₽`} tone="blue" />
                  <Pill label="Новых активных" value={analyticsOverview.clients?.new_active_count ?? 0} tone="mint" />
                  <Pill label="Стали неактивны" value={analyticsPeriodClosed ? (analyticsOverview.clients?.became_inactive_count ?? 0) : '—'} tone="violet" />
                </div>
              ) : null}
            </Card>

            <Card
              title="Сравнение с прошлым периодом"
              subtitle={analyticsOverview?.period ? `${analyticsOverview.period.current_from} → ${analyticsOverview.period.current_to}` : 'Неделя/месяц'}
            >
              {analyticsOverview ? (
                <div className="analytics-kpi-grid">
                  <div className="analytics-kpi-card">
                    <span>Доход</span>
                    <strong>{analyticsOverview.finance?.delta_abs >= 0 ? '+' : ''}{formatMoneyShort(analyticsOverview.finance?.delta_abs ?? 0)}</strong>
                    <small>{analyticsOverview.finance?.delta_pct ?? 0}% к прошлому периоду</small>
                  </div>
                  <div className="analytics-kpi-card">
                    <span>Активные ученики</span>
                    <strong>
                      {analyticsPeriodClosed
                        ? `${(analyticsOverview.clients?.active_now ?? 0) - (analyticsOverview.clients?.active_prev ?? 0) >= 0 ? '+' : ''}${(analyticsOverview.clients?.active_now ?? 0) - (analyticsOverview.clients?.active_prev ?? 0)}`
                        : '—'}
                    </strong>
                    <small>{analyticsPeriodClosed ? 'закрытый период' : 'период еще не закрыт'}</small>
                  </div>
                  <div className="analytics-kpi-card">
                    <span>Проведенные занятия</span>
                    <strong>{(analyticsOverview.ops?.lessons_now ?? 0) - (analyticsOverview.ops?.lessons_prev ?? 0) >= 0 ? '+' : ''}{(analyticsOverview.ops?.lessons_now ?? 0) - (analyticsOverview.ops?.lessons_prev ?? 0)}</strong>
                    <small>сравнение с предыдущим окном</small>
                  </div>
                  <div className="analytics-kpi-card">
                    <span>Доля долгов</span>
                    <strong>{analyticsOverview.ops?.debt_ratio_now ?? 0}%</strong>
                    <small>было {analyticsOverview.ops?.debt_ratio_prev ?? 0}%</small>
                  </div>
                </div>
              ) : (
                <div className="placeholder-box">Выберите период и нажмите «Обновить».</div>
              )}
            </Card>

            <Card title="Кто приносит кэш" subtitle="Доля оплаченной выручки по ученикам">
              {analyticsRevenueShare?.items?.length ? (
                <div className="analytics-share-layout">
                  <div className="analytics-donut-wrap">
                    <div className="analytics-donut" style={{ background: analyticsRevenueDonut }}>
                      <div className="analytics-donut-hole">
                        <small>Всего</small>
                        <strong>{formatMoneyShort(analyticsRevenueShare.total_paid || 0)}</strong>
                      </div>
                    </div>
                  </div>
                  <div className="analytics-share-legend">
                    {(analyticsRevenueShare.items || []).map((item, idx) => (
                      <div className="analytics-share-item" key={`share-${item.telegram_id ?? 'other'}-${idx}`}>
                        <span className="analytics-share-color" style={{ background: ANALYTICS_SHARE_COLORS[idx % ANALYTICS_SHARE_COLORS.length] }} />
                        <div className="analytics-share-meta">
                          <strong>{item.full_name || item.telegram_id}</strong>
                          <small>{formatMoneyShort(item.paid_amount || 0)} • {item.share_pct || 0}% • {item.lessons_count || 0} зан.</small>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="placeholder-box">За выбранный период оплаченной выручки пока нет.</div>
              )}
            </Card>

            <Card title="Доход и занятия по дням" subtitle={analyticsMode === 'week' ? 'Сравнение с прошлой неделей' : analyticsMode === 'month' ? 'Сравнение с прошлым месяцем' : 'Сравнение с прошлым кварталом'}>
              {(analyticsSeries || []).length ? (
                <div className="analytics-compare-stack">
                  <div className="analytics-chart-legend">
                    <span><i className="legend-swatch prev" /> Прошлый период</span>
                    <span><i className="legend-swatch progress" /> Прогресс</span>
                    <span><i className="legend-swatch regress" /> Регресс</span>
                    <span><i className="legend-swatch stagnation" /> Стагнация</span>
                  </div>
                  <div className="analytics-hist-section">
                    <div className="analytics-hist-title-row">
                      <strong>Доход</strong>
                      <small>По каждой дате видно прошлый и текущий день</small>
                    </div>
                    <div className="analytics-histogram">
                      {(analyticsSeries || []).map(point => {
                        const revenueCurrent = Number(point.paid_amount || 0)
                        const revenuePrev = Number(point.previous_paid_amount || 0)
                        const revenueCurrentHeight = Math.max(revenueCurrent > 0 ? 8 : 0, Math.round((revenueCurrent / analyticsRevenueMax) * 108))
                        const revenuePrevHeight = Math.max(revenuePrev > 0 ? 8 : 0, Math.round((revenuePrev / analyticsRevenueMax) * 108))
                        return (
                          <div className="analytics-hist-col" key={`analytics-revenue-${point.date}`} title={`${point.date}: текущий ${revenueCurrent} ₽, прошлый период ${revenuePrev} ₽`}>
                            <div className="analytics-hist-bars">
                              <span className="analytics-hist-bar prev" style={{ height: `${revenuePrevHeight}px` }} />
                              <span className={`analytics-hist-bar current ${point.signal === 'mixed' ? 'stagnation' : (point.signal || 'stagnation')}`} style={{ height: `${revenueCurrentHeight}px` }} />
                            </div>
                            <div className="analytics-hist-label">{analyticsDayLabel(point.date, analyticsMode)}</div>
                            <div className="analytics-hist-values">
                              <small>{formatMetricCompact(revenuePrev, 'money')}</small>
                              <strong>{formatMetricCompact(revenueCurrent, 'money')}</strong>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                  <div className="analytics-hist-section">
                    <div className="analytics-hist-title-row">
                      <strong>Занятия</strong>
                      <small>Тот же день прошлого периода против текущего</small>
                    </div>
                    <div className="analytics-histogram">
                      {(analyticsSeries || []).map(point => {
                        const lessonsCurrent = Number(point.lessons_done || 0)
                        const lessonsPrev = Number(point.previous_lessons_done || 0)
                        const lessonsCurrentHeight = Math.max(lessonsCurrent > 0 ? 8 : 0, Math.round((lessonsCurrent / analyticsLessonsMax) * 108))
                        const lessonsPrevHeight = Math.max(lessonsPrev > 0 ? 8 : 0, Math.round((lessonsPrev / analyticsLessonsMax) * 108))
                        return (
                          <div className="analytics-hist-col" key={`analytics-lessons-${point.date}`} title={`${point.date}: текущий ${lessonsCurrent} занятий, прошлый период ${lessonsPrev} занятий`}>
                            <div className="analytics-hist-bars">
                              <span className="analytics-hist-bar prev lessons" style={{ height: `${lessonsPrevHeight}px` }} />
                              <span className={`analytics-hist-bar current ${point.signal === 'mixed' ? 'stagnation' : (point.signal || 'stagnation')}`} style={{ height: `${lessonsCurrentHeight}px` }} />
                            </div>
                            <div className="analytics-hist-label">{analyticsDayLabel(point.date, analyticsMode)}</div>
                            <div className="analytics-hist-values">
                              <small>{formatMetricCompact(lessonsPrev)}</small>
                              <strong>{formatMetricCompact(lessonsCurrent)}</strong>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="placeholder-box">По выбранному периоду данных пока нет.</div>
              )}
            </Card>

            <Card title="Активность клиентов" subtitle="Кто пришел и кто выпал из периода">
              <div className="analytics-columns">
                <div className="analytics-col">
                  <h4>Новые активные ({analyticsDelta.new_active.length})</h4>
                  {analyticsDelta.new_active.length ? (
                    <ul className="list list-compact">
                      {analyticsDelta.new_active.slice(0, 8).map(item => (
                        <li key={`new-${item.telegram_id}`}>
                          <span>{item.full_name || item.telegram_id}</span>
                          <small>{item.lessons_count} зан. • {item.paid_amount || 0} ₽</small>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="placeholder-box">Нет новых активных клиентов.</div>
                  )}
                </div>
                <div className="analytics-col">
                  <h4>Стали неактивны ({analyticsDelta.became_inactive.length})</h4>
                  {analyticsDelta.became_inactive.length ? (
                    <ul className="list list-compact">
                      {analyticsDelta.became_inactive.slice(0, 8).map(item => (
                        <li key={`inactive-${item.telegram_id}`}>
                          <span>{item.full_name || item.telegram_id}</span>
                          <small>Последнее: {item.last_lesson_date || '—'}</small>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="placeholder-box">Потерь по активности нет.</div>
                  )}
                </div>
              </div>
            </Card>

            <Card title="Сводка для решений" subtitle="Коротко по бизнес-ситуации">
              {analyticsOverview ? (
                <ul className="list list-compact">
                  <li>
                    <span>Сигнал по выручке</span>
                    <strong>{Number(analyticsOverview.finance?.delta_abs || 0) >= 0 ? 'Рост' : 'Снижение'}</strong>
                  </li>
                  <li>
                    <span>Сигнал по базе клиентов</span>
                    <strong>{(analyticsOverview.clients?.new_active_count || 0) >= (analyticsOverview.clients?.became_inactive_count || 0) ? 'База растет' : 'База сжимается'}</strong>
                  </li>
                  <li>
                    <span>Риск по долгам</span>
                    <strong>{(analyticsOverview.ops?.debt_ratio_now || 0) > 25 ? 'Высокий' : 'Контролируемый'}</strong>
                  </li>
                </ul>
              ) : (
                <div className="placeholder-box">Сводка появится после загрузки аналитики.</div>
              )}
            </Card>

            <Card title="Драйверы роста и просадки" subtitle="Кто именно сдвинул выручку относительно прошлого периода">
              {analyticsV2?.executive?.revenue_drivers ? (
                <div className="analytics-columns">
                  <div className="analytics-col">
                    <h4>Рост</h4>
                    {(analyticsV2.executive.revenue_drivers.gainers || []).length ? (
                      <ul className="list list-compact">
                        {(analyticsV2.executive.revenue_drivers.gainers || []).map(item => (
                          <li key={`gainer-${item.telegram_id}`}>
                            <span>{item.full_name}</span>
                            <small>{item.group === 'new' ? 'новый' : 'рост'} • +{formatMoneyShort(item.delta_abs || 0)}</small>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <div className="placeholder-box">Явных драйверов роста пока нет.</div>
                    )}
                  </div>
                  <div className="analytics-col">
                    <h4>Просадка</h4>
                    {(analyticsV2.executive.revenue_drivers.decliners || []).length ? (
                      <ul className="list list-compact">
                        {(analyticsV2.executive.revenue_drivers.decliners || []).map(item => (
                          <li key={`decliner-${item.telegram_id}`}>
                            <span>{item.full_name}</span>
                            <small>{item.group === 'churned' ? 'выпал' : 'снижение'} • {formatMoneyShort(item.delta_abs || 0)}</small>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <div className="placeholder-box">Сильной просадки по клиентам нет.</div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="placeholder-box">Драйверы появятся после загрузки аналитики.</div>
              )}
            </Card>

            <Card title="Ценность учеников" subtitle="LTV и revenue share">
              {analyticsV2 ? (
                <div className="analytics-v2-panel">
                  <div className="analytics-panel-head">
                    <strong>LTV leaderboard</strong>
                    <small>Сколько ученик принёс за всё время</small>
                  </div>
                  {(analyticsV2.client_value?.ltv_leaderboard || []).length ? (
                    <div className="analytics-ltv-list">
                      {(analyticsV2.client_value?.ltv_leaderboard || []).map(item => (
                        <div className="analytics-ltv-item" key={`ltv-${item.telegram_id}`}>
                          <div className="analytics-ltv-meta">
                            <strong>{item.full_name}</strong>
                            <small>{item.total_lessons || 0} зан. • ср. чек {formatMoneyShort(item.avg_revenue_per_lesson || 0)}</small>
                          </div>
                          <div className="analytics-ltv-bar-wrap">
                            <span className="analytics-ltv-bar" style={{ width: `${Math.max(8, Math.round((Number(item.total_revenue || 0) / analyticsLtvMax) * 100))}%` }} />
                          </div>
                          <strong>{formatMoneyShort(item.total_revenue || 0)}</strong>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="placeholder-box">Истории оплат пока недостаточно.</div>
                  )}
                </div>
              ) : (
                <div className="placeholder-box">Блок ценности учеников ещё не загружен.</div>
              )}
            </Card>
            </>}
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

        <ToastViewport
          items={toastItems}
          onDismiss={id => {
            if (id === 'success') setSuccess('')
            if (id === 'error') setError('')
          }}
        />
      </div>

      <nav className="bottom-nav bottom-nav-six">
        <button className="nav-collapse-toggle" onClick={() => setNavCollapsed(value => !value)} aria-label={navCollapsed ? 'Развернуть меню' : 'Свернуть меню'} title={navCollapsed ? 'Развернуть меню' : 'Свернуть меню'}>{navCollapsed ? '›' : '‹'}</button>
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
