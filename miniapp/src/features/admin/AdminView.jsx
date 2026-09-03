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

const LOST_REASON_OPTIONS = [
  ['price', 'Стоимость'], ['schedule', 'Не подходит расписание'], ['no_time', 'Нет времени'],
  ['other_teacher', 'Выбрал другого преподавателя'], ['format', 'Не подходит формат'], ['motivation', 'Потерял мотивацию'],
  ['goal_reached', 'Достиг цели'], ['finance', 'Финансовые причины'], ['no_response', 'Не выходит на связь'], ['other', 'Другое'],
]

const CLIENT_TYPE_LABELS = {
  lead: 'Лид',
  student: 'Ученик',
  archived: 'Архив',
}
const WORK_CATEGORY_LABELS = { prep: 'Подготовка', sales: 'Продажи и переписка', content: 'Контент', admin: 'Администрирование' }

function metricValue(value, kind = 'number') {
  if (value === null || value === undefined) return 'нет данных'
  if (kind === 'money') return formatMoneyShort(value)
  if (kind === 'percent') return `${Number(value).toLocaleString('ru-RU')}%`
  if (kind === 'days') return `${Number(value).toLocaleString('ru-RU')} дн.`
  return Number(value).toLocaleString('ru-RU')
}

async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value)
    return
  }
  const area = document.createElement('textarea')
  area.value = value
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  document.execCommand('copy')
  area.remove()
}

function CampaignFunnel({ stages, onSelect }) {
  const colors = ['#3099e8', '#22b573', '#f5a623', '#ffd238', '#f7c995', '#f3aaa7']
  const totalHeight = 510
  const levelHeight = totalHeight / stages.length
  return <div style={{ overflowX: 'auto', padding: '10px 0' }}><svg viewBox="0 0 1000 540" role="img" aria-label="Воронка кампании" style={{ display: 'block', width: 'min(100%, 1000px)', minWidth: 720, margin: '0 auto' }}>
    {stages.map(([label, value, metricKey], index) => {
      const topWidth = 940 - index * 128
      const bottomWidth = 940 - (index + 1) * 128
      const y = 12 + index * levelHeight
      const x1 = (1000 - topWidth) / 2
      const x2 = (1000 - bottomWidth) / 2
      const previous = index ? Number(stages[index - 1][1]) : null
      const conversion = index === 0 ? 'базовый этап' : previous > 0 ? `${Math.round((Number(value) / previous) * 100)}% от предыдущего этапа` : 'нет базы для конверсии'
      return <g key={label} onClick={() => metricKey && onSelect({ label, value, metricKey })} style={{ cursor: metricKey ? 'pointer' : 'default' }}><polygon points={`${x1},${y} ${1000 - x1},${y} ${1000 - x2},${y + levelHeight - 4} ${x2},${y + levelHeight - 4}`} fill={colors[index]} /><text x="500" y={y + levelHeight / 2 - 7} textAnchor="middle" fill="#101820" fontSize="22" fontWeight="700">{label}</text><text x="500" y={y + levelHeight / 2 + 22} textAnchor="middle" fill="#101820" fontSize="17">{value} · {metricKey ? 'нажмите для редактирования' : conversion}</text></g>
    })}
  </svg></div>
}

function CampaignDetail({ campaign, sources = [], onSaveSettings = () => {}, onSavePeriod, onSaveMetrics, onOpenLinks = () => {} }) {
  const [selected, setSelected] = useState(null)
  const [name, setName] = useState(campaign.campaign_name || '')
  const [sourceKey, setSourceKey] = useState(campaign.source_key || '')
  const [from, setFrom] = useState(campaign.active_from || '')
  const [to, setTo] = useState(campaign.active_to || '')
  const [targetLabel, setTargetLabel] = useState(campaign.target_action_label || 'Целевое действие')
  const metrics = campaign.manual_metrics || {}
  const stages = [
    ['Просмотры объявления', metrics.views || 0, 'views'], ['Вступили в диалог', metrics.dialogs || 0, 'dialogs'],
    [targetLabel, metrics.target_actions || 0, 'target_actions'], ['Лиды в CRM', campaign.leads, null],
    ['Диагностика проведена', campaign.diagnostics_held, null], ['Первая оплата', campaign.new_clients, null],
  ]
  const status = !from && !to ? 'Период не задан' : to ? 'Завершена' : 'Активна'
  const saveSelected = async () => {
    const next = { views: metrics.views || 0, dialogs: metrics.dialogs || 0, target_actions: metrics.target_actions || 0, [selected.metricKey]: Number(selected.value || 0) }
    await onSaveMetrics(campaign.campaign_id, next)
    if (selected.metricKey === 'target_actions') await onSavePeriod(campaign.campaign_id, from, to, targetLabel)
  }
  return <Card title={`Кампания #${campaign.campaign_id}: ${campaign.campaign_name}`} subtitle="Реклама → лид → продажа">
    <div className="campaign-settings-grid">
      <label>Название<input className="input" value={name} onChange={e => setName(e.target.value)} /></label>
      <label>Источник<select className="input" value={sourceKey} onChange={e => setSourceKey(e.target.value)}>{sources.map(item => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label>
      <label>Старт<input className="input" type="date" value={from} onChange={e => setFrom(e.target.value)} /></label>
      <label>Завершение<input className="input" type="date" value={to} onChange={e => setTo(e.target.value)} /></label>
      <label>Целевое действие<input className="input" value={targetLabel} onChange={e => setTargetLabel(e.target.value)} /></label>
    </div>
    <div className="campaign-actions">
      <button className="btn" disabled={!name.trim()} onClick={() => onSaveSettings(campaign.campaign_id, { name: name.trim(), source_key: sourceKey, active_from: from || null, active_to: to || null, target_action_label: targetLabel.trim() })}>Сохранить кампанию</button>
      <button className="btn secondary" onClick={() => onOpenLinks(campaign.campaign_id)}>Открыть ссылки</button>
      <button className="btn secondary" onClick={() => onSaveSettings(campaign.campaign_id, { is_active: !campaign.is_active })}>{campaign.is_active ? 'В архив' : 'Вернуть в работу'}</button>
    </div>
    <div className="analytics-kpi-grid">
      <div className="analytics-kpi-card"><span>Статус</span><strong>{campaign.is_active ? status : 'В архиве'}</strong><small>{campaign.source_name} · кампания #{campaign.campaign_id}</small></div>
      <div className="analytics-kpi-card"><span>Лиды → клиенты</span><strong>{campaign.leads} → {campaign.new_clients}</strong><small>диагностик проведено: {campaign.diagnostics_held}</small></div>
      <div className="analytics-kpi-card"><span>Потраченный бюджет</span><strong>{metricValue(campaign.spend, 'money')}</strong><small>учитывается из расходов</small></div>
      <div className="analytics-kpi-card"><span>Выручка и эффективность</span><strong>{metricValue(campaign.cash_revenue, 'money')}</strong><small>ROAS {metricValue(campaign.roas)} · ROMI {metricValue(campaign.romi, 'percent')} · LTV/CAC {metricValue(campaign.ltv_cac)}</small></div>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: selected ? 'minmax(0,1fr) 300px' : 'minmax(0,1fr)', gap: 18, marginTop: 18 }}>
      <CampaignFunnel stages={stages} onSelect={setSelected} />
      {selected ? <aside className="analytics-kpi-card" style={{ alignSelf: 'center' }}><span>Этап воронки</span><strong>{selected.label}</strong>{selected.metricKey ? <><label>Значение<input className="input" type="number" min="0" value={selected.value} onChange={e => setSelected(value => ({ ...value, value: e.target.value }))} /></label>{selected.metricKey === 'target_actions' ? <label>Название этапа<input className="input" value={targetLabel} onChange={e => setTargetLabel(e.target.value)} /></label> : null}<div className="custom-row"><button className="btn secondary compact" onClick={() => setSelected(value => ({ ...value, value: Math.max(0, Number(value.value) - 1) }))}>−</button><button className="btn secondary compact" onClick={() => setSelected(value => ({ ...value, value: Number(value.value) + 1 }))}>+</button></div><button className="btn" style={{ width: '100%' }} onClick={() => saveSelected().catch(() => {})}>Сохранить</button></> : <small>Этот этап считается CRM автоматически и не редактируется вручную.</small>}</aside> : null}
    </div>
  </Card>
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
  const [marketingSection, setMarketingSection] = useState('overview')
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
  const [effectiveRate, setEffectiveRate] = useState(null)
  const [workLogForm, setWorkLogForm] = useState(() => ({ worked_on: new Date().toISOString().slice(0, 10), category: 'prep', minutes: '', note: '' }))
  const [analyticsLoading, setAnalyticsLoading] = useState(false)
  const [marketingMetrics, setMarketingMetrics] = useState(null)
  const [longreadAnalytics, setLongreadAnalytics] = useState(null)
  const [websiteAnalyticsLoading, setWebsiteAnalyticsLoading] = useState(false)
  const [websiteFilters, setWebsiteFilters] = useState(() => ({
    date_from: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().slice(0, 10),
    date_to: new Date().toISOString().slice(0, 10),
    campaign_id: '', tracking_link_id: '',
  }))
  const [marketingSources, setMarketingSources] = useState([])
  const [marketingCampaigns, setMarketingCampaigns] = useState([])
  const [marketingLoading, setMarketingLoading] = useState(false)
  const [marketingFilters, setMarketingFilters] = useState(() => ({
    date_from: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().slice(0, 10),
    date_to: new Date().toISOString().slice(0, 10), source_key: '', campaign_id: '', direction: '',
  }))
  const [expenseForm, setExpenseForm] = useState(() => ({
    spent_at: new Date().toISOString().slice(0, 10), source_key: 'avito', campaign_id: '', category: 'placement', amount: '', note: '',
  }))
  const [campaignName, setCampaignName] = useState('')
  const [campaignPeriod, setCampaignPeriod] = useState({ active_from: '', active_to: '' })
  const [campaignDraft, setCampaignDraft] = useState({ source_key: 'avito', name: '', active_from: '', active_to: '', target_action_label: 'Целевое действие' })
  const [campaignQuery, setCampaignQuery] = useState('')
  const [campaignStatus, setCampaignStatus] = useState('active')
  const [selectedMarketingCampaignId, setSelectedMarketingCampaignId] = useState('')
  const [selectedFunnelMetric, setSelectedFunnelMetric] = useState(null)
  const [trackingLinks, setTrackingLinks] = useState([])
  const [trackingLinksLoading, setTrackingLinksLoading] = useState(false)
  const [selectedTrackingLink, setSelectedTrackingLink] = useState(null)
  const [trackingLinkJourneys, setTrackingLinkJourneys] = useState(null)
  const [trackingLinkForm, setTrackingLinkForm] = useState({ campaign_id: '', destination_key: 'it_map', label: '', note: '', expires_at: '' })
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
  const [newLeadOpen, setNewLeadOpen] = useState(false)
  const [contactEdit, setContactEdit] = useState({
    first_name: '', last_name: '', telephone: '', email: '', telegram_username: '', status: 'active', preferred_channel: 'telegram', direction: '', price: '', acquisition_source: 'unknown', acquisition_campaign_id: '',
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
    balance_set: '',
    balance_add: '',
  })
  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10))
  const [adminMonth, setAdminMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [scheduleMode, setScheduleMode] = useState('booked')
  const [scheduleAssignMode, setScheduleAssignMode] = useState('single')
  const [scheduleDuration, setScheduleDuration] = useState(60)
  const [overrideTime, setOverrideTime] = useState('10:00')
  const [rescheduleForm, setRescheduleForm] = useState(null)
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
  const [manualCompletedLesson, setManualCompletedLesson] = useState(() => ({
    telegram_id: '',
    date: new Date().toISOString().slice(0, 10),
    time: '10:00',
    duration: 60,
    note: '',
  }))
  const [debtors, setDebtors] = useState([])
  const [unclosedLessons, setUnclosedLessons] = useState([])
  const [unclosedDaysBack, setUnclosedDaysBack] = useState(21)
  const [selectedUnclosedKeys, setSelectedUnclosedKeys] = useState([])
  const [broadcast, setBroadcast] = useState('')
  const [broadcastOnlyUnpaid, setBroadcastOnlyUnpaid] = useState(false)
  const [systemHealth, setSystemHealth] = useState(null)
  const [leads, setLeads] = useState([])
  const [leadSummary, setLeadSummary] = useState(null)
  const [leadForm, setLeadForm] = useState({ full_name: '', telephone: '', telegram_username: '', price: '', source: 'direct', acquisition_campaign_id: '', direction: '', student_level: '', goal: '', qualification_status: 'new', desired_format: '', next_contact_at: '', stage: 'new', lost_reason: '', notes: '' })
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
      email: contact.email || '',
      telegram_username: contact.telegram_username || '',
      status: contact.status || 'active',
      preferred_channel: contact.preferred_channel || 'telegram',
      direction: contact.direction || '',
      price: String(contact.price ?? 0),
      acquisition_source: contact.acquisition_source || 'unknown',
      acquisition_campaign_id: contact.acquisition_campaign_id ? String(contact.acquisition_campaign_id) : '',
    })
    if (contact.telegram_id) {
      setManualCompletedLesson(prev => ({ ...prev, telegram_id: String(contact.telegram_id) }))
    }
  }

  async function saveContact() {
    const contactId = selectedContact?.contact?.id
    if (!contactId) return
    const current = selectedContact.contact || {}
    const body = {
      ...contactEdit,
      price: Number(contactEdit.price || 0),
      acquisition_campaign_id: contactEdit.acquisition_campaign_id ? Number(contactEdit.acquisition_campaign_id) : null,
    }
    // Не отправляем неизменённую атрибуцию: она не относится к правке имени
    // и не должна мешать сохранению карточек со старыми значениями источника.
    if (contactEdit.acquisition_source === (current.acquisition_source || 'unknown')) {
      delete body.acquisition_source
      if (contactEdit.acquisition_campaign_id === String(current.acquisition_campaign_id || '')) {
        delete body.acquisition_campaign_id
      }
    }
    await api(`/api/admin/contacts/${contactId}`, {
      token,
      method: 'PATCH',
      body,
    })
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

  async function changeContactOpportunityStage(opportunity, stage) {
    const contactId = selectedContact?.contact?.id
    if (!contactId || !opportunity?.id) return
    const currentOpportunity = selectedContact?.opportunities?.find(item => item.id === opportunity.id) || opportunity
    if (stage === 'lost' && !currentOpportunity.lost_reason) {
      throw new Error('Сначала выберите причину отказа')
    }
    await api(`/api/admin/leads/${opportunity.id}`, {
      token,
      method: 'PATCH',
      body: { stage, ...(stage === 'lost' ? { lost_reason: currentOpportunity.lost_reason } : {}) },
    })
    await Promise.all([selectContact(contactId), loadContacts(contactsPage, contactQuery), loadLeads()])
    setSuccess('Этап воронки обновлён')
  }

  async function patchOpportunityMarketing(opportunityId, payload) {
    const contactId = selectedContact?.contact?.id
    setSelectedContact(current => current ? {
      ...current,
      opportunities: (current.opportunities || []).map(item => item.id === opportunityId ? { ...item, ...payload } : item),
    } : current)
    await api(`/api/admin/opportunities/${opportunityId}/marketing`, { token, method: 'PATCH', body: payload })
    if (contactId) await selectContact(contactId)
    setSuccess('Маркетинговые данные сделки обновлены')
  }

  async function moveContactToStage(contactId, stage) {
    if (stage === 'lost') {
      throw new Error('Для отказа откройте карточку лида и выберите причину')
    }
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
    if (leadForm.stage === 'lost' && !leadForm.lost_reason) {
      throw new Error('Для этапа «Неактуально / отказ» выберите причину')
    }
    const payload = Object.fromEntries(Object.entries(leadForm).filter(([, value]) => String(value || '').trim() !== ''))
    if (payload.price !== undefined) payload.price = Number(payload.price)
    payload.acquisition_campaign_id = leadForm.acquisition_campaign_id ? Number(leadForm.acquisition_campaign_id) : null
    const result = await api('/api/admin/leads', { token, method: 'POST', body: payload })
    setLeadForm({ full_name: '', telephone: '', telegram_username: '', price: '', source: 'direct', acquisition_campaign_id: '', direction: '', student_level: '', goal: '', qualification_status: 'new', desired_format: '', next_contact_at: '', stage: 'new', lost_reason: '', notes: '' })
    setNewLeadOpen(false)
    await Promise.all([loadLeads(), loadContacts(1, '')])
    if (result.item?.contact_id) await selectContact(result.item.contact_id)
    setSuccess('Лид создан и привязан к источнику')
  }

  async function openNewLead() {
    const [sources, campaigns] = await Promise.all([api('/api/admin/marketing/sources', { token }), api('/api/admin/marketing/campaigns', { token })])
    setMarketingSources(sources.items || [])
    setMarketingCampaigns(campaigns.items || [])
    setSelectedContact(null)
    setNewLeadOpen(true)
  }

  async function changeLeadStage(lead, stage) {
    if (stage === 'lost' && !lead.lost_reason) {
      throw new Error('Сначала выберите причину отказа в паспорте лида')
    }
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
      const ratePeriod = overviewV2?.period
      const rate = ratePeriod ? await api(`/api/admin/analytics/effective-rate?date_from=${ratePeriod.current_from}&date_to=${ratePeriod.current_to}`, { token }) : null
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
      setEffectiveRate(rate)
    } finally {
      setAnalyticsLoading(false)
    }
  }

  async function addWorkLog() {
    const minutes = Number(workLogForm.minutes)
    if (!Number.isInteger(minutes) || minutes <= 0) return
    await api('/api/admin/analytics/work-logs', { token, method: 'POST', body: { ...workLogForm, minutes } })
    setWorkLogForm(value => ({ ...value, minutes: '', note: '' }))
    await loadAnalyticsV2()
    setSuccess('Рабочие часы добавлены')
  }

  async function deleteWorkLog(logId) {
    await api(`/api/admin/analytics/work-logs/${logId}`, { token, method: 'DELETE' })
    await loadAnalyticsV2()
    setSuccess('Запись рабочих часов удалена')
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
      if (!selectedMarketingCampaignId) {
        const firstCampaign = (metrics?.rows || []).find(item => item.campaign_id)
        if (firstCampaign) setSelectedMarketingCampaignId(String(firstCampaign.campaign_id))
      }
    } finally {
      setMarketingLoading(false)
    }
  }

  async function loadWebsiteAnalytics() {
    setWebsiteAnalyticsLoading(true)
    try {
      const params = new URLSearchParams(Object.entries(websiteFilters).filter(([, value]) => value))
      const report = await api(`/api/admin/analytics/longread?${params}`, { token })
      setLongreadAnalytics(report || null)
    } finally {
      setWebsiteAnalyticsLoading(false)
    }
  }

  async function loadTrackingLinks() {
    setTrackingLinksLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('date_from', marketingFilters.date_from)
      params.set('date_to', marketingFilters.date_to)
      if (marketingFilters.campaign_id) params.set('campaign_id', marketingFilters.campaign_id)
      const data = await api(`/api/admin/marketing/links?${params}`, { token })
      setTrackingLinks(data.items || [])
    } finally {
      setTrackingLinksLoading(false)
    }
  }

  async function createTrackingLink() {
    if (!trackingLinkForm.campaign_id || !trackingLinkForm.label.trim()) {
      setError('Выберите кампанию и укажите название размещения')
      return
    }
    const result = await api('/api/admin/marketing/links', {
      token,
      method: 'POST',
      body: {
        campaign_id: Number(trackingLinkForm.campaign_id),
        destination_key: trackingLinkForm.destination_key,
        label: trackingLinkForm.label.trim(),
        note: trackingLinkForm.note.trim() || null,
        expires_at: trackingLinkForm.expires_at ? new Date(trackingLinkForm.expires_at).toISOString() : null,
      },
    })
    setTrackingLinkForm(value => ({ ...value, label: '', note: '', expires_at: '' }))
    await loadTrackingLinks()
    if (result.item?.public_url) await copyText(result.item.public_url)
    setSuccess('Ссылка создана и скопирована')
  }

  async function patchTrackingLink(linkId, updates) {
    await api(`/api/admin/marketing/links/${linkId}`, { token, method: 'PATCH', body: updates })
    await loadTrackingLinks()
    setSuccess('Ссылка обновлена')
  }

  async function loadTrackingLinkJourneys(item) {
    setSelectedTrackingLink(item)
    const params = new URLSearchParams({ date_from: marketingFilters.date_from, date_to: marketingFilters.date_to })
    const data = await api(`/api/admin/marketing/links/${item.id}/journeys?${params}`, { token })
    setTrackingLinkJourneys(data)
  }

  async function createMarketingExpense() {
    await api('/api/admin/marketing/expenses', { token, method: 'POST', body: { ...expenseForm, campaign_id: expenseForm.campaign_id ? Number(expenseForm.campaign_id) : null, amount: Number(expenseForm.amount) } })
    setExpenseForm(value => ({ ...value, amount: '', note: '' }))
    await loadMarketingAnalytics()
    setSuccess('Маркетинговый расход добавлен')
  }

  async function createMarketingCampaign(draft = null) {
    const value = draft || { source_key: expenseForm.source_key, name: campaignName, ...campaignPeriod }
    if (!value.name?.trim()) {
      setError('Укажите название кампании')
      return
    }
    const result = await api('/api/admin/marketing/campaigns', { token, method: 'POST', body: { ...value, name: value.name.trim(), active_from: value.active_from || null, active_to: value.active_to || null } })
    setCampaignName('')
    setCampaignPeriod({ active_from: '', active_to: '' })
    setCampaignDraft(current => ({ ...current, name: '', active_from: '', active_to: '' }))
    await loadMarketingAnalytics()
    if (result.item?.id) setSelectedMarketingCampaignId(String(result.item.id))
    setSuccess('Кампания добавлена')
  }

  async function patchMarketingCampaign(campaignId, updates) {
    await api(`/api/admin/marketing/campaigns/${campaignId}`, { token, method: 'PATCH', body: updates })
    await loadMarketingAnalytics()
    setSuccess(updates.is_active === false ? 'Кампания перенесена в архив' : updates.is_active === true ? 'Кампания возвращена в работу' : 'Кампания обновлена')
  }

  async function saveCampaignMetrics(campaignId, views, dialogs, targetActions) {
    await api(`/api/admin/marketing/campaigns/${campaignId}/metrics`, { token, method: 'PUT', body: { views: Number(views || 0), dialogs: Number(dialogs || 0), target_actions: Number(targetActions || 0) } })
    await loadMarketingAnalytics()
    setSuccess('Показатели воронки сохранены')
  }

  async function saveCampaignPeriod(campaignId, activeFrom, activeTo, targetActionLabel) {
    await api(`/api/admin/marketing/campaigns/${campaignId}`, { token, method: 'PATCH', body: { active_from: activeFrom || null, active_to: activeTo || null, target_action_label: targetActionLabel } })
    await loadMarketingAnalytics()
    setSuccess('Период кампании сохранён')
  }

  async function incrementCampaignMetric(campaign, metricKey) {
    const current = campaign.manual_metrics || {}
    await saveCampaignMetrics(campaign.campaign_id, current.views || 0, current.dialogs || 0, metricKey === 'target_actions' ? Number(current.target_actions || 0) + 1 : (current.target_actions || 0))
    if (metricKey === 'views') await saveCampaignMetrics(campaign.campaign_id, Number(current.views || 0) + 1, current.dialogs || 0, current.target_actions || 0)
    if (metricKey === 'dialogs') await saveCampaignMetrics(campaign.campaign_id, current.views || 0, Number(current.dialogs || 0) + 1, current.target_actions || 0)
  }

  async function saveSelectedFunnelMetric(campaign, value) {
    const current = campaign.manual_metrics || {}
    const next = { views: current.views || 0, dialogs: current.dialogs || 0, target_actions: current.target_actions || 0, [selectedFunnelMetric.metricKey]: Number(value || 0) }
    await saveCampaignMetrics(campaign.campaign_id, next.views, next.dialogs, next.target_actions)
    setSelectedFunnelMetric(null)
  }

  async function selectUser(telegramId) {
    const data = await api(`/api/admin/users/${telegramId}`, { token })
    setSelectedUser(data)
    setUserEdit({
      telegram_id: String(data.telegram_id ?? ''),
      first_name: data.first_name || '',
      last_name: data.last_name || '',
      telephone: data.phone || '',
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
    setUserEdit({ telegram_id: '', first_name: '', last_name: '', telephone: '', balance_set: '', balance_add: '' })
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

  async function addManualCompletedLesson() {
    if (!manualCompletedLesson.telegram_id) throw new Error('Выберите клиента')
    const result = await api('/api/admin/lessons/manual-completed', {
      token,
      method: 'POST',
      body: {
        ...manualCompletedLesson,
        telegram_id: Number(manualCompletedLesson.telegram_id),
        duration: Number(manualCompletedLesson.duration),
      },
    })
    setManualCompletedLesson(prev => ({ ...prev, note: '' }))
    await Promise.all([loadUnclosedLessons(), loadDebtors(), loadScheduleMonth()])
    if (selectedContact?.contact?.id && Number(selectedContact.contact.telegram_id) === Number(manualCompletedLesson.telegram_id)) {
      await selectContact(selectedContact.contact.id)
    }
    setSuccess(result.status === 'updated'
      ? 'Проведённое занятие исправлено. Финансовый статус пока не выбран.'
      : 'Проведённое занятие внесено. Выберите для него финансовый статус ниже.')
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
        lesson_id: item.lesson_id || null,
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
          lesson_id: item.lesson_id || null,
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
    if (marketingSection === 'links' || marketingSection === 'websites') loadTrackingLinks().catch(e => setError(normalizeErrorMessage(e.message || e)))
    if (marketingSection === 'websites') loadWebsiteAnalytics().catch(e => setError(normalizeErrorMessage(e.message || e)))
  }, [activeTab, marketingSection])

  useEffect(() => {
    if (trackingLinkForm.campaign_id || !marketingCampaigns.length) return
    setTrackingLinkForm(value => ({ ...value, campaign_id: String(marketingCampaigns[0].id) }))
  }, [marketingCampaigns])

  useEffect(() => {
    if (!marketingSources.length || marketingSources.some(item => item.key === campaignDraft.source_key)) return
    setCampaignDraft(value => ({ ...value, source_key: marketingSources[0].key }))
  }, [marketingSources])

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

  async function assignClientToAnySlot() {
    if (!lessonForm.telegram_id || !overrideTime) return
    await api('/api/admin/lessons/override', {
      token,
      method: 'POST',
      body: { telegram_id: Number(lessonForm.telegram_id), date: day, time: overrideTime, duration: Number(scheduleDuration) },
    })
    await Promise.all([loadSchedule(), loadScheduleMonth(), loadFreeSlots()])
    setSuccess('Занятие назначено вне обычного графика')
  }

  async function rescheduleLesson() {
    if (!rescheduleForm) return
    await api('/api/admin/lessons/reschedule', { token, method: 'POST', body: { ...rescheduleForm, telegram_id: Number(rescheduleForm.telegram_id), duration: Number(rescheduleForm.duration) } })
    const targetDay = rescheduleForm.target_date
    setRescheduleForm(null)
    if (targetDay === day) await loadSchedule()
    await Promise.all([loadScheduleMonth(), loadFreeSlots()])
    setSuccess('Занятие перенесено')
  }

  return (
    <div className={`mini-layout admin-layout ${navCollapsed ? 'nav-collapsed' : ''}`}>
      <section className="mini-cover">
        <div className="mini-cover-overlay" />
        <div className="mini-cover-head">
          <div className="mini-brand">
            <img className="brand-logo" src={`${import.meta.env.BASE_URL}professorit-mark.png`} alt="" width="48" height="48" />
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
                      // A full day is still useful: the administrator must be able to
                      // to open it and move an existing lesson.  Only past dates remain
                      // disabled in the "free slots" picker.
                      const cellDisabled = scheduleMode === 'free' && cell.past
                      const cellMuted = cell.past || (scheduleMode === 'free' && !cell.has_free)
                      const cellTitle = scheduleMode === 'booked'
                        ? `Записей: ${cell.booked_count}`
                        : scheduleMode === 'free'
                          ? (cell.has_free ? `Свободно: ${cell.free_count}` : `Занято: ${cell.booked_count}. Нажмите, чтобы открыть записи`)
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
                              if (cell.has_free) {
                                await loadFreeSlots(cell.date).catch(() => {})
                              } else {
                                setScheduleMode('booked')
                                await loadSchedule(cell.date).catch(() => {})
                              }
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
                            <button className="btn secondary compact" onClick={() => setRescheduleForm({ telegram_id: s.telegram_id, source_date: day, source_time: `${String(s.hour).padStart(2, '0')}:${String(s.minute).padStart(2, '0')}`, target_date: day, target_time: '10:00', duration: s.duration || 60 })}>
                              Перенести это
                            </button>
                            <button className="btn secondary compact" onClick={() => deleteScheduleItem(s, 'single').catch(e => setError(String(e.message || e)))}>
                              Удалить это
                            </button>
                            <button className="btn secondary compact" onClick={() => deleteScheduleItem(s, 'all_regular').catch(e => setError(String(e.message || e)))}>
                              Удалить серию
                            </button>
                          </div>
                        ) : (
                          <div className="record-actions">
                            <button className="btn secondary compact" onClick={() => setRescheduleForm({ telegram_id: s.telegram_id, source_date: day, source_time: `${String(s.hour).padStart(2, '0')}:${String(s.minute).padStart(2, '0')}`, target_date: day, target_time: '10:00', duration: s.duration || 60 })}>
                              Перенести
                            </button>
                            <button className="btn secondary compact" onClick={() => deleteScheduleItem(s, 'single').catch(e => setError(String(e.message || e)))}>
                              Удалить
                            </button>
                          </div>
                        )
                      ) : null}
                    </li>
                  ))}
                </ul>
                {rescheduleForm ? <div className="stack" style={{ marginTop: 14 }}><strong>Перенос занятия</strong><small>Новый слот может быть вне рабочего графика, но не может пересекаться с другим занятием или бронью.</small><div className="custom-row"><input className="input" type="date" value={rescheduleForm.target_date} onChange={e => setRescheduleForm(value => ({ ...value, target_date: e.target.value }))} /><input className="input" type="time" step="900" value={rescheduleForm.target_time} onChange={e => setRescheduleForm(value => ({ ...value, target_time: e.target.value }))} /><select className="input" value={rescheduleForm.duration} onChange={e => setRescheduleForm(value => ({ ...value, duration: Number(e.target.value) }))}><option value={60}>60 мин</option><option value={90}>90 мин</option><option value={120}>120 мин</option></select><button className="btn" onClick={() => rescheduleLesson().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Перенести</button><button className="btn secondary" onClick={() => setRescheduleForm(null)}>Отмена</button></div></div> : null}
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
                <div className="custom-row"><input className="input" type="time" step="900" value={overrideTime} onChange={e => setOverrideTime(e.target.value)} aria-label="Время вне графика" /><button className="btn secondary" disabled={!lessonForm.telegram_id || !overrideTime} onClick={() => assignClientToAnySlot().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Назначить в это время вне графика</button></div>
                <small>Админское назначение: доступно даже вне настроенных рабочих часов, но пересечения с существующими занятиями запрещены.</small>
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
              <button className="btn" style={{ marginTop: 14 }} onClick={() => saveWorkSchedule().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Сохранить расписание</button>
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
                  <button className="btn" onClick={() => openNewLead().catch(e => setError(normalizeErrorMessage(e.message || e)))}>
                    + Новый лид
                  </button>
                </div>
                <div className="mini-actions-row">
                  <button className="btn secondary" disabled={contactsPage <= 1} onClick={() => setContactsPage(page => Math.max(1, page - 1))}>← Стр.</button>
                  <button className="btn secondary" disabled={contacts.length < 20} onClick={() => setContactsPage(page => page + 1)}>Стр. →</button>
                </div>
              </div>
            </Card>

            <div className={`contacts-workspace ${(selectedContact || newLeadOpen) ? 'has-selection' : ''}`}>
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
                          <tr><th>Клиент</th><th>Тип</th><th>Телефон</th><th>Telegram</th><th>Этап</th><th>Направление</th><th>Сделки</th></tr>
                        </thead>
                        <tbody>
                          {contacts.map(contact => (
                            <tr key={contact.id} className={selectedContact?.contact?.id === contact.id ? 'selected' : ''} onClick={() => selectContact(contact.id).catch(e => setError(normalizeErrorMessage(e.message || e)))}>
                              <td><strong>{contact.full_name}</strong></td>
                              <td><span className={`contact-badge ${contact.client_type === 'student' ? 'student' : 'lead'}`}>{CLIENT_TYPE_LABELS[contact.client_type] || 'Лид'}</span></td>
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

              {newLeadOpen ? (
                <aside className="contact-side-panel">
                  <div className="contact-panel-head">
                    <div><small>Быстрое создание</small><h2>Новый лид</h2></div>
                    <div className="contact-panel-actions"><button className="contact-panel-close" onClick={() => setNewLeadOpen(false)} aria-label="Закрыть создание лида">×</button></div>
                  </div>
                  <small>Заполните только то, что уже известно. Источник и кампания сохраняются как первое касание и сразу попадут в маркетинговую аналитику.</small>
                  <div className="contact-edit-form" style={{ marginTop: 12 }}>
                    <label className="contact-field-wide">Имя и фамилия<input className="input" autoFocus value={leadForm.full_name} onChange={e => setLeadForm(value => ({ ...value, full_name: e.target.value }))} placeholder="Например, Иван Петров" /></label>
                    <label className="contact-field-wide">Телефон<input className="input" value={leadForm.telephone} onChange={e => setLeadForm(value => ({ ...value, telephone: e.target.value }))} placeholder="89881414232" /></label>
                    <label>Telegram<input className="input" value={leadForm.telegram_username || ''} onChange={e => setLeadForm(value => ({ ...value, telegram_username: e.target.value }))} placeholder="@username" /></label>
                    <label>Цена занятия, ₽<input className="input" type="number" min="0" value={leadForm.price || ''} onChange={e => setLeadForm(value => ({ ...value, price: e.target.value }))} /></label>
                    <label>Источник<select className="input" value={leadForm.source} onChange={e => setLeadForm(value => ({ ...value, source: e.target.value, acquisition_campaign_id: '' }))}>{marketingSources.map(item => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label>
                    <label>Кампания<select className="input" value={leadForm.acquisition_campaign_id} onChange={e => setLeadForm(value => ({ ...value, acquisition_campaign_id: e.target.value }))}><option value="">Без кампании</option>{marketingCampaigns.filter(item => item.source_key === leadForm.source).map(item => <option key={item.id} value={String(item.id)}>#{item.id} · {item.name}</option>)}</select></label>
                    <label>Направление<input className="input" value={leadForm.direction} onChange={e => setLeadForm(value => ({ ...value, direction: e.target.value }))} placeholder="DevOps, ИБ, Хакер" /></label>
                    <label>Уровень<select className="input" value={leadForm.student_level} onChange={e => setLeadForm(value => ({ ...value, student_level: e.target.value }))}><option value="">Не указан</option><option value="zero">С нуля</option><option value="beginner">Начальный</option><option value="intermediate">Средний</option><option value="advanced">Продвинутый</option></select></label>
                    <label>Квалификация<select className="input" value={leadForm.qualification_status} onChange={e => setLeadForm(value => ({ ...value, qualification_status: e.target.value }))}><option value="new">Не оценен</option><option value="qualified">Квалифицирован</option><option value="not_qualified">Не подходит</option></select></label>
                    <label>Формат<input className="input" value={leadForm.desired_format} onChange={e => setLeadForm(value => ({ ...value, desired_format: e.target.value }))} placeholder="2 × 60 минут" /></label>
                    <label>Следующее действие<input className="input" type="datetime-local" value={leadForm.next_contact_at} onChange={e => setLeadForm(value => ({ ...value, next_contact_at: e.target.value }))} /></label>
                    <label>Этап<select className="input" value={leadForm.stage} onChange={e => setLeadForm(value => ({ ...value, stage: e.target.value }))}>{funnelStages.map(stage => <option key={stage.key} value={stage.key}>{stage.name}</option>)}</select></label>
                    <label>Причина отказа<select className="input" value={leadForm.lost_reason} onChange={e => setLeadForm(value => ({ ...value, lost_reason: e.target.value }))}><option value="">Не выбрана</option>{LOST_REASON_OPTIONS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><small>Заполняйте, если этап — «Неактуально / отказ».</small></label>
                    <label className="contact-field-wide">Цель ученика<textarea className="input" rows={3} value={leadForm.goal} onChange={e => setLeadForm(value => ({ ...value, goal: e.target.value }))} placeholder="Работа, подготовка, освоить конкретный навык" /></label>
                    <label className="contact-field-wide">Заметки по обращению<textarea className="input" rows={3} value={leadForm.notes} onChange={e => setLeadForm(value => ({ ...value, notes: e.target.value }))} placeholder="Что сказал клиент, контекст запроса, договорённости" /></label>
                  </div>
                  <button className="btn contact-save" disabled={!leadForm.full_name.trim() && !leadForm.telephone.trim()} onClick={() => createLead().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Создать лид</button>
                </aside>
              ) : null}

              {selectedContact ? (
                <aside className="contact-side-panel">
                    <div className="contact-panel-head">
                      <div><small>Карточка клиента</small><h2>{selectedContact.contact?.full_name || 'Без имени'}</h2></div>
                      <div className="contact-panel-actions"><span className={`contact-badge ${selectedContact.contact?.client_type === 'student' ? 'student' : 'lead'}`}>{CLIENT_TYPE_LABELS[selectedContact.contact?.client_type] || 'Лид'}</span><button className="contact-panel-close" onClick={() => setSelectedContact(null)} aria-label="Закрыть карточку клиента">×</button></div>
                    </div>
                    <div className="contact-edit-form">
                      <label>Имя<input className="input" value={contactEdit.first_name} onChange={e => setContactEdit(value => ({ ...value, first_name: e.target.value }))} /></label>
                      <label>Фамилия<input className="input" value={contactEdit.last_name} onChange={e => setContactEdit(value => ({ ...value, last_name: e.target.value }))} /></label>
                      <label className="contact-field-wide">Телефон<input className="input" value={contactEdit.telephone} onChange={e => setContactEdit(value => ({ ...value, telephone: e.target.value }))} /></label>
                      <label className="contact-field-wide">Почта<input className="input" type="email" value={contactEdit.email} onChange={e => setContactEdit(value => ({ ...value, email: e.target.value }))} /></label>
                      <label className="contact-field-wide">Telegram username<input className="input" value={contactEdit.telegram_username} onChange={e => setContactEdit(value => ({ ...value, telegram_username: e.target.value }))} placeholder="username без @" /></label>
                      <label>Статус<select className="input" value={contactEdit.status} onChange={e => setContactEdit(value => ({ ...value, status: e.target.value }))}><option value="lead">Лид</option><option value="active">Активный</option><option value="student">Ученик</option><option value="archived">Архив</option></select></label>
                      <label>Канал связи<select className="input" value={contactEdit.preferred_channel} onChange={e => setContactEdit(value => ({ ...value, preferred_channel: e.target.value }))}><option value="telegram">Telegram</option><option value="phone">Телефон</option></select></label>
                      {selectedContact.contact?.is_student ? <label className="contact-field-wide">Направление<input className="input" value={contactEdit.direction} onChange={e => setContactEdit(value => ({ ...value, direction: e.target.value }))} placeholder="DevOps, ИБ, Хакер" /></label> : null}
                      {selectedContact.contact?.is_student ? <label className="contact-field-wide">Цена за занятие, ₽<input className="input" type="number" min="0" step="100" value={contactEdit.price} onChange={e => setContactEdit(value => ({ ...value, price: e.target.value }))} /><small>Базовая цена за 60 минут. Для занятий другой длительности сумма рассчитывается пропорционально.</small></label> : null}
                      <label>Первый источник<select className="input" value={contactEdit.acquisition_source} onChange={e => setContactEdit(value => ({ ...value, acquisition_source: e.target.value, acquisition_campaign_id: '' }))}>{marketingSources.map(item => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label>
                      <label>Кампания первого касания<select className="input" value={contactEdit.acquisition_campaign_id} onChange={e => setContactEdit(value => ({ ...value, acquisition_campaign_id: e.target.value }))}><option value="">Без кампании</option>{marketingCampaigns.filter(item => item.source_key === contactEdit.acquisition_source).map(item => <option key={item.id} value={String(item.id)}>#{item.id} · {item.name}</option>)}</select></label>
                    </div>
                    <small>Первое касание хранится один раз у клиента. Кампания выбирается по ID, поэтому одноимённые объявления не смешиваются в аналитике.</small>
                    <button className="btn contact-save" onClick={() => saveContact().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Сохранить изменения</button>
                    {selectedContact.contact?.is_student ? <button className="btn secondary contact-save" onClick={() => archiveContactProfile().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Архивировать профиль</button> : null}

                <div className="detail-grid">
                  <div><small>Telegram</small><strong>{selectedContact.contact?.telegram_username ? `@${selectedContact.contact.telegram_username}` : (selectedContact.contact?.telegram_id || 'не привязан')}</strong></div>
                  <div><small>Почта</small><strong>{selectedContact.contact?.email || 'не указана'}</strong></div>
                  <div><small>Баланс занятий</small><strong>{selectedContact.contact?.balance_lessons ?? 0}</strong></div>
                  <div><small>Оплаты (последние 12)</small><strong>{formatMoneyShort(selectedContact.paid_total_recent)}</strong></div>
                </div>
                {selectedContact.contact?.is_student ? <div className="custom-row" style={{ marginTop: 12 }}><input className="input" type="number" min="1" value={prepaymentAmount} onChange={e => setPrepaymentAmount(e.target.value)} placeholder="Предоплата, ₽" /><button className="btn" onClick={() => addPrepayment().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Внести оплату и пополнить баланс</button></div> : null}
                {selectedContact.contact?.telegram_id ? <div className="stack" style={{ marginTop: 12 }}>
                  <h3 style={{ margin: 0 }}>Проведённое занятие</h3>
                  <small>Внести факт занятия вне расписания. Затем выберите «Оплачено», «В долг» или «Отмена» в финансах.</small>
                  <div className="custom-row">
                    <input type="date" className="input" value={manualCompletedLesson.date} onChange={e => setManualCompletedLesson(v => ({ ...v, date: e.target.value }))} />
                    <input type="time" step="900" className="input" value={manualCompletedLesson.time} onChange={e => setManualCompletedLesson(v => ({ ...v, time: e.target.value }))} />
                    <select className="input" value={manualCompletedLesson.duration} onChange={e => setManualCompletedLesson(v => ({ ...v, duration: Number(e.target.value) }))}><option value={60}>60 мин</option><option value={90}>90 мин</option><option value={120}>120 мин</option></select>
                  </div>
                  <input className="input" value={manualCompletedLesson.note} onChange={e => setManualCompletedLesson(v => ({ ...v, note: e.target.value }))} placeholder="Комментарий (необязательно)" />
                  <button className="btn" onClick={() => addManualCompletedLesson().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Внести проведённое занятие</button>
                </div> : <small>Привяжите Telegram-профиль, чтобы вносить занятия.</small>}

                <h3>Паспорт лида</h3>
                {selectedContact.opportunities?.length ? <ul className="list list-compact">{selectedContact.opportunities.map(item => (
                  <li key={item.id} className="contact-opportunity-row" style={{ display: 'block' }}>
                    <div className="contact-edit-form">
                      <label>Этап<select className="input" value={item.stage} onChange={e => changeContactOpportunityStage(item, e.target.value).catch(err => setError(normalizeErrorMessage(err.message || err)))}>{funnelStages.map(stage => <option key={stage.key} value={stage.key}>{stage.name}</option>)}</select></label>
                      <label>Квалификация<select className="input" defaultValue={item.qualification_status || 'new'} onChange={e => patchOpportunityMarketing(item.id, { qualification_status: e.target.value }).catch(err => setError(normalizeErrorMessage(err.message || err)))}><option value="new">Не оценен</option><option value="qualified">Квалифицирован</option><option value="not_qualified">Не подходит</option></select></label>
                      <label>Направление<input className="input" defaultValue={item.direction || ''} placeholder="DevOps, ИБ, Хакер" onBlur={e => patchOpportunityMarketing(item.id, { direction: e.target.value || null }).catch(err => setError(normalizeErrorMessage(err.message || err)))} /></label>
                      <label>Уровень<select className="input" defaultValue={item.student_level || ''} onChange={e => patchOpportunityMarketing(item.id, { student_level: e.target.value || null }).catch(err => setError(normalizeErrorMessage(err.message || err)))}><option value="">Не указан</option><option value="zero">С нуля</option><option value="beginner">Начальный</option><option value="intermediate">Средний</option><option value="advanced">Продвинутый</option></select></label>
                      <label>Формат<input className="input" defaultValue={item.desired_format || ''} placeholder="2 × 60 минут" onBlur={e => patchOpportunityMarketing(item.id, { desired_format: e.target.value || null }).catch(err => setError(normalizeErrorMessage(err.message || err)))} /></label>
                      <label>Следующее действие<input className="input" type="datetime-local" defaultValue={item.next_contact_at || ''} onBlur={e => patchOpportunityMarketing(item.id, { next_contact_at: e.target.value || null }).catch(err => setError(normalizeErrorMessage(err.message || err)))} /></label>
                      <label>Причина отказа<select className="input" defaultValue={item.lost_reason || ''} onChange={e => patchOpportunityMarketing(item.id, { lost_reason: e.target.value || null }).catch(err => setError(normalizeErrorMessage(err.message || err)))}><option value="">Не выбрана</option>{LOST_REASON_OPTIONS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><small>Нужна для этапа «Неактуально / отказ».</small></label>
                      <label className="contact-field-wide">Цель ученика<input className="input" defaultValue={item.goal || ''} placeholder="Работа, подготовка, освоить навык" onBlur={e => patchOpportunityMarketing(item.id, { goal: e.target.value || null }).catch(err => setError(normalizeErrorMessage(err.message || err)))} /></label>
                      <label className="contact-field-wide">Заметки по обращению<textarea className="input" rows={3} defaultValue={item.notes || ''} placeholder="Контекст, договорённости, детали запроса" onBlur={e => patchOpportunityMarketing(item.id, { notes: e.target.value || null }).catch(err => setError(normalizeErrorMessage(err.message || err)))} /></label>
                    </div>
                    {!['won', 'lost'].includes(item.stage) ? <div className="custom-row" style={{ marginTop: 8 }}><label>Диагностика<input className="input" type="datetime-local" defaultValue={item.diagnostic_scheduled_at || ''} onBlur={e => patchOpportunityMarketing(item.id, { diagnostic_scheduled_at: e.target.value || null }).catch(err => setError(normalizeErrorMessage(err.message || err)))} /></label><button className="btn secondary compact" onClick={() => patchOpportunityMarketing(item.id, { diagnostic_held_at: new Date().toISOString().slice(0, 16) }).catch(err => setError(normalizeErrorMessage(err.message || err)))}>Диагностика проведена</button></div> : null}
                  </li>
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
                            <div className="mini-actions-row">
                              <button className="btn" onClick={() => saveUserPatch({
                                telegram_id_new: Number(userEdit.telegram_id || selectedUser.telegram_id),
                                first_name: userEdit.first_name,
                                last_name: userEdit.last_name,
                                telephone: userEdit.telephone,
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
                <Card title="Проведённое занятие вне расписания" subtitle="Внесите факт занятия — затем оно появится в «Незакрытых занятиях» для выбора оплаты, долга или отмены">
                  <select className="input" value={manualCompletedLesson.telegram_id} onChange={e => setManualCompletedLesson(v => ({ ...v, telegram_id: e.target.value }))}>
                    <option value="">Выберите клиента</option>
                    {clientOptions.map(client => <option key={`manual-lesson-${client.telegram_id}`} value={client.telegram_id}>{client.full_name || 'Без имени'} • {client.telegram_id}</option>)}
                  </select>
                  <div className="custom-row">
                    <input type="date" className="input" value={manualCompletedLesson.date} onChange={e => setManualCompletedLesson(v => ({ ...v, date: e.target.value }))} />
                    <input type="time" step="900" className="input" value={manualCompletedLesson.time} onChange={e => setManualCompletedLesson(v => ({ ...v, time: e.target.value }))} />
                    <select className="input" value={manualCompletedLesson.duration} onChange={e => setManualCompletedLesson(v => ({ ...v, duration: Number(e.target.value) }))}><option value={60}>60 мин</option><option value={90}>90 мин</option><option value={120}>120 мин</option></select>
                  </div>
                  <input className="input" value={manualCompletedLesson.note} onChange={e => setManualCompletedLesson(v => ({ ...v, note: e.target.value }))} placeholder="Комментарий (необязательно)" />
                  <button className="btn" onClick={() => addManualCompletedLesson().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Внести проведённое занятие</button>
                </Card>
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

        {activeTab === 'marketing' ? (
          <Card title="Маркетинг" subtitle="Одна система: кампании, ссылки, поведение на сайте и продажи">
            <div className="segmented" role="tablist" aria-label="Раздел маркетинга">
              <button className={marketingSection === 'overview' ? 'seg active' : 'seg'} onClick={() => setMarketingSection('overview')}>Обзор</button>
              <button className={marketingSection === 'campaigns' ? 'seg active' : 'seg'} onClick={() => setMarketingSection('campaigns')}>Кампании</button>
              <button className={marketingSection === 'links' ? 'seg active' : 'seg'} onClick={() => setMarketingSection('links')}>Ссылки</button>
              <button className={marketingSection === 'websites' ? 'seg active' : 'seg'} onClick={() => setMarketingSection('websites')}>Поведение на сайте</button>
            </div>
          </Card>
        ) : null}

        {activeTab === 'marketing' && marketingSection === 'campaigns' ? (
          <div className="stack analytics-stack">
            <Card title="Новая кампания" subtitle="Кампания объединяет один канал, одну задачу и все конкретные размещения">
              <div className="campaign-settings-grid">
                <label>Источник<select className="input" value={campaignDraft.source_key} onChange={e => setCampaignDraft(value => ({ ...value, source_key: e.target.value }))}>{marketingSources.map(item => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label>
                <label>Название<input className="input" value={campaignDraft.name} onChange={e => setCampaignDraft(value => ({ ...value, name: e.target.value }))} placeholder="YouTube · Карта входа в IT" /></label>
                <label>Старт<input className="input" type="date" value={campaignDraft.active_from} onChange={e => setCampaignDraft(value => ({ ...value, active_from: e.target.value }))} /></label>
                <label>Завершение, если известно<input className="input" type="date" value={campaignDraft.active_to} onChange={e => setCampaignDraft(value => ({ ...value, active_to: e.target.value }))} /></label>
                <label>Целевое действие<input className="input" value={campaignDraft.target_action_label} onChange={e => setCampaignDraft(value => ({ ...value, target_action_label: e.target.value }))} /></label>
              </div>
              <button className="btn" disabled={!campaignDraft.name.trim()} onClick={() => createMarketingCampaign(campaignDraft).catch(e => setError(normalizeErrorMessage(e.message || e)))}>Создать кампанию</button>
            </Card>
            <Card title="Реестр кампаний" subtitle="Активные и архивные кампании не смешиваются; результаты считаются за выбранный период">
              <div className="campaign-registry-toolbar">
                <input className="input" value={campaignQuery} onChange={e => setCampaignQuery(e.target.value)} placeholder="Найти кампанию или источник" />
                <div className="segmented" role="group" aria-label="Статус кампаний">
                  <button className={campaignStatus === 'active' ? 'seg active' : 'seg'} onClick={() => setCampaignStatus('active')}>В работе · {marketingCampaigns.filter(item => item.is_active).length}</button>
                  <button className={campaignStatus === 'archived' ? 'seg active' : 'seg'} onClick={() => setCampaignStatus('archived')}>Архив · {marketingCampaigns.filter(item => !item.is_active).length}</button>
                  <button className={campaignStatus === 'all' ? 'seg active' : 'seg'} onClick={() => setCampaignStatus('all')}>Все · {marketingCampaigns.length}</button>
                </div>
              </div>
              {(() => {
                const query = campaignQuery.trim().toLocaleLowerCase('ru-RU')
                const rows = (marketingMetrics?.rows || []).filter(row => row.campaign_id && (campaignStatus === 'all' || (campaignStatus === 'active') === Boolean(row.is_active))).filter(row => !query || `${row.campaign_name} ${row.source_name} ${row.campaign_id}`.toLocaleLowerCase('ru-RU').includes(query))
                return rows.length ? <div className="contacts-table-wrap campaign-table"><table className="contacts-table"><thead><tr><th>Статус</th><th>Кампания</th><th>Источник</th><th>Период</th><th>Расход</th><th>Лиды</th><th>Диагностики</th><th>Клиенты</th><th>Выручка</th><th>ROMI</th></tr></thead><tbody>{rows.map(row => <tr key={row.campaign_id} className={String(row.campaign_id) === String(selectedMarketingCampaignId) ? 'selected' : ''} onClick={() => setSelectedMarketingCampaignId(String(row.campaign_id))}><td><span className={`campaign-status ${row.is_active ? 'active' : 'archived'}`}>{row.is_active ? 'В работе' : 'Архив'}</span></td><td><strong>{row.campaign_name}</strong><small>#{row.campaign_id}</small></td><td>{row.source_name}</td><td>{row.active_from || 'не задан'} → {row.active_to || 'без даты'}</td><td>{metricValue(row.spend, 'money')}</td><td>{row.leads}</td><td>{row.diagnostics_held}</td><td>{row.new_clients}</td><td>{metricValue(row.cash_revenue, 'money')}</td><td>{metricValue(row.romi, 'percent')}</td></tr>)}</tbody></table></div> : <div className="placeholder-box">Кампаний с такими условиями нет.</div>
              })()}
            </Card>
            {(() => { const campaign = (marketingMetrics?.rows || []).find(row => String(row.campaign_id) === String(selectedMarketingCampaignId)); return campaign ? <CampaignDetail key={`${campaign.campaign_id}-${campaign.updated_at || ''}-${campaign.is_active}`} campaign={campaign} sources={marketingSources} onSaveSettings={(id, updates) => patchMarketingCampaign(id, updates).catch(e => setError(normalizeErrorMessage(e.message || e)))} onSavePeriod={saveCampaignPeriod} onSaveMetrics={(id, metrics) => saveCampaignMetrics(id, metrics.views, metrics.dialogs, metrics.target_actions)} onOpenLinks={id => { setMarketingFilters(value => ({ ...value, campaign_id: String(id) })); setTrackingLinkForm(value => ({ ...value, campaign_id: String(id) })); setMarketingSection('links') }} /> : <div className="placeholder-box">Выберите кампанию в реестре, чтобы открыть её карточку.</div> })()}
          </div>
        ) : null}

        {activeTab === 'marketing' && marketingSection === 'links' ? (
          <div className="stack analytics-stack">
            <Card title="Создать отслеживаемую ссылку" subtitle="Кампания задаёт источник, ссылка — конкретное размещение">
              <div className="custom-row">
                <label>Кампания<select className="input" value={trackingLinkForm.campaign_id} onChange={e => setTrackingLinkForm(value => ({ ...value, campaign_id: e.target.value }))}><option value="">Выберите кампанию</option>{marketingCampaigns.map(item => <option key={item.id} value={String(item.id)}>#{item.id} · {item.name}</option>)}</select></label>
                <label>Куда ведёт<select className="input" value={trackingLinkForm.destination_key} onChange={e => setTrackingLinkForm(value => ({ ...value, destination_key: e.target.value }))}><option value="it_map">Карта входа в IT</option><option value="home">Главный сайт</option></select></label>
                <label>Название размещения<input className="input" value={trackingLinkForm.label} onChange={e => setTrackingLinkForm(value => ({ ...value, label: e.target.value }))} placeholder="YouTube · ролик про DevOps" /></label>
                <label>Отключить после<input className="input" type="datetime-local" value={trackingLinkForm.expires_at} onChange={e => setTrackingLinkForm(value => ({ ...value, expires_at: e.target.value }))} /></label>
              </div>
              <textarea className="input" rows={2} value={trackingLinkForm.note} onChange={e => setTrackingLinkForm(value => ({ ...value, note: e.target.value }))} placeholder="Комментарий: где размещена ссылка или кому отправлена" />
              <button className="btn" style={{ marginTop: 12 }} onClick={() => createTrackingLink().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Создать и скопировать</button>
            </Card>
            <Card title="Отслеживаемые ссылки" subtitle="Открытия, чтение, CTA, заявки и оплаты по каждому размещению">
              <div className="custom-row">
                <label>Период с<input type="date" className="input" value={marketingFilters.date_from} onChange={e => setMarketingFilters(value => ({ ...value, date_from: e.target.value }))} /></label>
                <label>по<input type="date" className="input" value={marketingFilters.date_to} onChange={e => setMarketingFilters(value => ({ ...value, date_to: e.target.value }))} /></label>
                <label>Кампания<select className="input" value={marketingFilters.campaign_id} onChange={e => setMarketingFilters(value => ({ ...value, campaign_id: e.target.value }))}><option value="">Все кампании</option>{marketingCampaigns.map(item => <option key={item.id} value={String(item.id)}>#{item.id} · {item.name}</option>)}</select></label>
                <button className="btn secondary" onClick={() => loadTrackingLinks().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Обновить</button>
              </div>
              {trackingLinksLoading ? <div className="loading">Собираем статистику ссылок...</div> : null}
              {trackingLinks.length ? <div className="contacts-table-wrap" style={{ marginTop: 14 }}><table className="contacts-table"><thead><tr><th>Размещение</th><th>Кампания</th><th>Ссылка</th><th>Открытия</th><th>Читатели</th><th>Часть 4</th><th>CTA</th><th>Заявки</th><th>Оплаты</th><th>Комментарий</th><th>Действия</th></tr></thead><tbody>{trackingLinks.map(item => <tr key={item.id} className={selectedTrackingLink?.id === item.id ? 'selected' : ''}><td><strong>{item.label}</strong><small>{item.is_expired ? 'Срок истёк' : item.is_active ? 'Активна' : 'Отключена'} · {item.destination_path}</small></td><td>#{item.campaign_id} · {item.campaign_name}</td><td><button className="btn secondary compact" onClick={() => copyText(item.public_url).then(() => setSuccess('Ссылка скопирована')).catch(e => setError(normalizeErrorMessage(e.message || e)))}>Копировать</button></td><td>{item.stats?.opens || 0}</td><td>{item.stats?.visitors || 0}</td><td>{item.stats?.part_four || 0}</td><td>{item.stats?.cta || 0}</td><td>{item.stats?.briefs || 0}</td><td>{item.stats?.payments || 0}</td><td><input className="input" defaultValue={item.note || ''} aria-label={`Комментарий ${item.label}`} onBlur={e => { if (e.target.value !== (item.note || '')) patchTrackingLink(item.id, { note: e.target.value || null }).catch(err => setError(normalizeErrorMessage(err.message || err))) }} /></td><td><div className="custom-row"><button className="btn secondary compact" onClick={() => loadTrackingLinkJourneys(item).catch(e => setError(normalizeErrorMessage(e.message || e)))}>Путь</button><button className="btn secondary compact" onClick={() => patchTrackingLink(item.id, { is_active: !item.is_active }).catch(e => setError(normalizeErrorMessage(e.message || e)))}>{item.is_active ? 'Отключить' : 'Включить'}</button></div></td></tr>)}</tbody></table></div> : <div className="placeholder-box">Ссылок пока нет. Создайте первую для конкретного размещения.</div>}
            </Card>
            {selectedTrackingLink ? <Card title={`Путь по ссылке: ${selectedTrackingLink.label}`} subtitle={selectedTrackingLink.public_url}>
              <div className="analytics-kpi-grid"><div className="analytics-kpi-card"><span>Сессии</span><strong>{trackingLinkJourneys?.summary?.sessions ?? 0}</strong></div><div className="analytics-kpi-card"><span>Читатели</span><strong>{trackingLinkJourneys?.summary?.visitors ?? 0}</strong></div><div className="analytics-kpi-card"><span>Дошли до финала</span><strong>{trackingLinkJourneys?.summary?.completed_series ?? 0}</strong></div><div className="analytics-kpi-card"><span>Нажали CTA</span><strong>{trackingLinkJourneys?.summary?.cta_sessions ?? 0}</strong></div></div>
              {(trackingLinkJourneys?.sessions || []).length ? <div className="contacts-table-wrap" style={{ marginTop: 14 }}><table className="contacts-table"><thead><tr><th>Начало</th><th>Путь</th><th>Результат</th><th>Активное время</th></tr></thead><tbody>{trackingLinkJourneys.sessions.map(item => <tr key={item.session_id}><td>{new Date(item.first_seen).toLocaleString('ru-RU')}</td><td>{item.visited_parts.join(' → ')}</td><td>{item.outcome}</td><td>{item.engaged_seconds ? `${item.engaged_seconds} сек.` : `≈ ${item.elapsed_seconds || 0} сек.`}</td></tr>)}</tbody></table></div> : <div className="placeholder-box">По этой ссылке ещё нет чтения длинного материала.</div>}
            </Card> : null}
          </div>
        ) : null}

        {activeTab === 'marketing' && marketingSection === 'websites' ? (
          <div className="stack analytics-stack">
            <Card title="Аналитика сайтов" subtitle="Что читатели открыли, до какой части дошли и где остановились">
              <div className="custom-row">
                <label>Период с<input type="date" className="input" value={websiteFilters.date_from} onChange={e => setWebsiteFilters(value => ({ ...value, date_from: e.target.value }))} /></label>
                <label>по<input type="date" className="input" value={websiteFilters.date_to} onChange={e => setWebsiteFilters(value => ({ ...value, date_to: e.target.value }))} /></label>
                <label>Кампания<select className="input" value={websiteFilters.campaign_id} onChange={e => setWebsiteFilters(value => ({ ...value, campaign_id: e.target.value, tracking_link_id: '' }))}><option value="">Все кампании</option>{marketingCampaigns.map(item => <option key={item.id} value={String(item.id)}>#{item.id} · {item.name}</option>)}</select></label>
                <label>Ссылка<select className="input" value={websiteFilters.tracking_link_id} onChange={e => setWebsiteFilters(value => ({ ...value, tracking_link_id: e.target.value }))}><option value="">Все ссылки</option>{trackingLinks.filter(item => !websiteFilters.campaign_id || String(item.campaign_id) === String(websiteFilters.campaign_id)).map(item => <option key={item.id} value={String(item.id)}>{item.label}</option>)}</select></label>
                <button className="btn" onClick={() => loadWebsiteAnalytics().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Обновить</button>
              </div>
              {websiteAnalyticsLoading ? <div className="loading">Собираем путь читателей...</div> : null}
              <div className="analytics-kpi-grid" style={{ marginTop: 16 }}>
                <div className="analytics-kpi-card"><span>Сессии</span><strong>{longreadAnalytics?.summary?.sessions ?? 0}</strong><small>отдельные визиты</small></div>
                <div className="analytics-kpi-card"><span>Уникальные читатели</span><strong>{longreadAnalytics?.summary?.visitors ?? 0}</strong><small>по идентификатору браузера</small></div>
                <div className="analytics-kpi-card"><span>Дошли до финала</span><strong>{longreadAnalytics?.summary?.completed_series ?? 0}</strong><small>прочитали четвёртую часть</small></div>
                <div className="analytics-kpi-card"><span>Нажали CTA</span><strong>{longreadAnalytics?.summary?.cta_sessions ?? 0}</strong><small>перешли к тест-драйву</small></div>
              </div>
            </Card>
            <Card title="Лонгрид «Точка входа в IT — 2026»" subtitle="Путь по четырём частям: от открытия до перехода к тест-драйву">
              <div className="contacts-table-wrap"><table className="contacts-table"><thead><tr><th>Часть</th><th>Открыли</th><th>25%</th><th>50%</th><th>75%</th><th>Дочитали</th><th>Перешли дальше</th><th>CTA</th><th>От предыдущей</th></tr></thead><tbody>{(longreadAnalytics?.parts || []).map(item => <tr key={item.part}><td><strong>Часть {item.part}</strong></td><td>{item.opened}</td><td>{item.depth_25}</td><td>{item.depth_50}</td><td>{item.depth_75}</td><td>{item.completed}</td><td>{item.next_clicked}</td><td>{item.cta_clicked}</td><td>{item.conversion_from_previous == null ? 'база' : `${item.conversion_from_previous}%`}</td></tr>)}</tbody></table></div>
            </Card>
            <Card title="Последние читательские сессии" subtitle="Здесь видно, на какой части и глубине остановился каждый визит">
              {(longreadAnalytics?.sessions || []).length ? <div className="contacts-table-wrap"><table className="contacts-table"><thead><tr><th>Начало</th><th>Источник</th><th>Путь</th><th>Последняя точка</th><th>Активное время</th><th>Кампания</th></tr></thead><tbody>{longreadAnalytics.sessions.map(item => <tr key={item.session_id}><td>{new Date(item.first_seen).toLocaleString('ru-RU')}</td><td>{item.source}{item.medium !== '—' ? ` / ${item.medium}` : ''}</td><td>{item.visited_parts.join(' → ')}</td><td>{item.outcome}</td><td>{item.engaged_seconds ? `${item.engaged_seconds} сек.` : item.elapsed_seconds ? `≈ ${item.elapsed_seconds} сек.` : 'пока нет данных'}</td><td>{item.campaign_id ? `#${item.campaign_id} · ` : ''}{item.campaign}</td></tr>)}</tbody></table></div> : <div className="placeholder-box">За выбранный период читательских сессий нет.</div>}
              <small style={{ display: 'block', marginTop: 12 }}>Отчёт фиксирует успешные загрузки сайта. Если запрос не дошёл до сервера из-за сетевой недоступности, такой визит технически нельзя увидеть без отдельного счётчика выдачи ссылки.</small>
            </Card>
          </div>
        ) : null}

        {(activeTab === 'analytics' || (activeTab === 'marketing' && marketingSection === 'overview')) ? (
          <div className="stack analytics-stack">
            {activeTab === 'marketing' ? (
              <>
                <Card title="Эффективность маркетинга" subtitle="Первое касание клиента определяет источник выручки навсегда">
                  <div className="custom-row">
                    <input type="date" className="input" value={marketingFilters.date_from} onChange={e => setMarketingFilters(v => ({ ...v, date_from: e.target.value }))} />
                    <input type="date" className="input" value={marketingFilters.date_to} onChange={e => setMarketingFilters(v => ({ ...v, date_to: e.target.value }))} />
                    <select className="input" value={marketingFilters.source_key} onChange={e => setMarketingFilters(v => ({ ...v, source_key: e.target.value, campaign_id: '' }))}><option value="">Все источники</option>{marketingSources.map(item => <option key={item.key} value={item.key}>{item.name}</option>)}</select>
                    <select className="input" value={marketingFilters.campaign_id} onChange={e => setMarketingFilters(v => ({ ...v, campaign_id: e.target.value }))}><option value="">Все кампании</option>{marketingCampaigns.filter(item => !marketingFilters.source_key || item.source_key === marketingFilters.source_key).map(item => <option key={item.id} value={String(item.id)}>#{item.id} · {item.name}</option>)}</select>
                    <input className="input" value={marketingFilters.direction} onChange={e => setMarketingFilters(v => ({ ...v, direction: e.target.value }))} placeholder="Направление" />
                    <button className="btn" onClick={() => loadMarketingAnalytics().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Обновить</button>
                  </div>
                  {marketingLoading ? <div className="loading">Считаем маркетинг...</div> : null}
                  {marketingMetrics ? <div className="analytics-kpi-grid" style={{ marginTop: 14 }}>
                    {[
                      ['Расходы', marketingMetrics.kpi?.spend, 'money'], ['Лиды', marketingMetrics.kpi?.leads], ['Квалифицированы', marketingMetrics.kpi?.qualified], ['Диагностики назначены', marketingMetrics.kpi?.diagnostics_scheduled], ['Диагностики проведены', marketingMetrics.kpi?.diagnostics_held], ['Новые клиенты', marketingMetrics.kpi?.new_clients], ['Первая выручка', marketingMetrics.kpi?.first_revenue, 'money'], ['Выручка периода', marketingMetrics.kpi?.cash_revenue, 'money'], ['CPL', marketingMetrics.kpi?.cpl, 'money'], ['Стоимость квалиф. лида', marketingMetrics.kpi?.cpql, 'money'], ['CAC', marketingMetrics.kpi?.cac, 'money'], ['Средний первый платёж', marketingMetrics.kpi?.avg_first_payment, 'money'], ['До первой оплаты', marketingMetrics.kpi?.avg_days_to_first_payment, 'days'], ['ROAS', marketingMetrics.kpi?.roas], ['LTV / CAC', marketingMetrics.kpi?.ltv_cac], ['ROMI', marketingMetrics.kpi?.romi, 'percent'],
                    ].map(([label, value, kind]) => <div className="analytics-kpi-card" key={label}><span>{label}</span><strong>{metricValue(value, kind)}</strong></div>)}
                  </div> : <div className="placeholder-box">Выберите период и обновите отчёт.</div>}
                </Card>
                <Card title="Маркетинговая воронка" subtitle="Конверсия от лидов к бизнес-этапу">
                  <div className="analytics-kpi-grid">{(marketingMetrics?.funnel || []).map(item => <div className="analytics-kpi-card" key={item.role}><span>{MARKETING_ROLE_LABELS[item.role] || item.role}</span><strong>{item.count}</strong><small>{item.conversion_from_leads === null ? 'нет данных' : `${item.conversion_from_leads}% от лидов`}</small></div>)}</div>
                </Card>
                {false ? <Card title="Кампания: показатели и воронка" subtitle="Выберите кампанию: сверху — ручные рекламные показатели, ниже — CRM-результат">
                  <select className="input" value={selectedMarketingCampaignId} onChange={e => setSelectedMarketingCampaignId(e.target.value)}>{(marketingMetrics?.rows || []).filter(row => row.campaign_id).map(row => <option key={row.campaign_id} value={row.campaign_id}>#{row.campaign_id} · {row.source_name} · {row.campaign_name}</option>)}</select>
                  {(() => { const row = (marketingMetrics?.rows || []).find(item => String(item.campaign_id) === String(selectedMarketingCampaignId)); return row ? <div style={{ marginTop: 14 }}><div className="custom-row"><strong>#{row.campaign_id} · {row.campaign_name}</strong><small>{row.active_from || 'дата начала не указана'} → {row.active_to || 'кампания активна / дата не указана'}</small><input className="input" type="number" min="0" defaultValue={row.manual_metrics?.views || 0} id="campaign-views" placeholder="Просмотры" /><input className="input" type="number" min="0" defaultValue={row.manual_metrics?.dialogs || 0} id="campaign-dialogs" placeholder="Диалоги" /><button className="btn secondary compact" onClick={() => saveCampaignMetrics(row.campaign_id, document.getElementById('campaign-views')?.value, document.getElementById('campaign-dialogs')?.value).catch(e => setError(normalizeErrorMessage(e.message || e)))}>Сохранить</button></div><div style={{ display: 'grid', gap: 6, marginTop: 14, justifyItems: 'center' }}>{[['Просмотры', row.manual_metrics?.views || 0, '#e3b25e'], ['Диалоги', row.manual_metrics?.dialogs || 0, '#a8c400'], ['Лиды', row.leads, '#5596ea'], ['Диагностики', row.diagnostics_held, '#8e5cf5'], ['Оплаты', row.new_clients, '#54d9a0']].map(([label, value, color], index) => <div key={label} style={{ width: `${Math.max(32, 100 - index * 14)}%`, background: color, color: '#10131a', textAlign: 'center', padding: '10px 14px', clipPath: 'polygon(7% 0,93% 0,100% 100%,0 100%)', fontWeight: 700 }}>{label}: {value}</div>)}</div></div> : <div className="placeholder-box">Создайте кампанию, чтобы вести её воронку.</div> })()}
                </Card> : null}
                {/* Campaign editing lives only in Marketing → Campaigns. */}
                <Card style={{ order: 1 }} title="Источники и кампании" subtitle="Общий реестр: нажмите строку кампании, чтобы открыть её рабочую карточку ниже">
                  {(marketingMetrics?.rows || []).length ? <div className="contacts-table-wrap"><table className="contacts-table"><thead><tr><th>Источник</th><th>Кампания / ID</th><th>Период</th><th>Расход</th><th>Лиды</th><th>Диагн.</th><th>Клиенты</th><th>Выручка</th><th>CAC</th><th>До оплаты</th><th>ROAS</th><th>LTV/CAC</th><th>ROMI</th><th>LTV</th></tr></thead><tbody>{marketingMetrics.rows.map((row, index) => <tr key={`${row.source_key}-${row.campaign_name || 'none'}-${index}`} className={String(row.campaign_id) === String(selectedMarketingCampaignId) ? 'selected' : ''} onClick={() => row.campaign_id && setSelectedMarketingCampaignId(String(row.campaign_id))}><td>{row.source_name}</td><td>{row.campaign_id ? `#${row.campaign_id} · ` : ''}{row.campaign_name || '—'}</td><td>{row.active_from || '—'} → {row.active_to || '—'}</td><td>{metricValue(row.spend, 'money')}</td><td>{row.leads}</td><td>{row.diagnostics_held}</td><td>{row.new_clients}</td><td>{metricValue(row.cash_revenue, 'money')}</td><td>{metricValue(row.cac, 'money')}</td><td>{row.avg_days_to_first_payment === null || row.avg_days_to_first_payment === undefined ? 'нет данных' : `${row.avg_days_to_first_payment} дн.`}</td><td>{metricValue(row.roas)}</td><td>{metricValue(row.ltv_cac)}</td><td>{metricValue(row.romi, 'percent')}</td><td>{metricValue(row.ltv, 'money')}</td></tr>)}</tbody></table></div> : <div className="placeholder-box">Нет источников или расходов за период.</div>}
                </Card>
                {(() => { const campaign = (marketingMetrics?.rows || []).find(row => String(row.campaign_id) === String(selectedMarketingCampaignId)); if (!campaign) return null; const stages = [['Просмотры объявления', campaign.manual_metrics?.views || 0, '#e7b35a'], ['Вступили в диалог', campaign.manual_metrics?.dialogs || 0, '#b4cb35'], ['Целевое действие', campaign.manual_metrics?.target_actions || 0, '#6ca8ef'], ['Лиды в CRM', campaign.leads, '#7d74e8'], ['Диагностика проведена', campaign.diagnostics_held, '#a46fea'], ['Первая оплата', campaign.new_clients, '#58d0a3']]; const max = Math.max(...stages.map(item => Number(item[1])), 1); return <Card title={`Кампания #${campaign.campaign_id}: ${campaign.campaign_name}`} subtitle="Рабочая карточка кампании: реклама → лид → продажа"><div className="analytics-kpi-grid"><div className="analytics-kpi-card"><span>Источник</span><strong>{campaign.source_name}</strong></div><div className="analytics-kpi-card"><span>Период работы</span><strong>{campaign.active_from || 'не указан'} — {campaign.active_to || 'активна'}</strong></div><div className="analytics-kpi-card"><span>Потраченный бюджет</span><strong>{metricValue(campaign.spend, 'money')}</strong><small>вносится через «Добавить расход» ниже</small></div><div className="analytics-kpi-card"><span>Выручка кампании</span><strong>{metricValue(campaign.cash_revenue, 'money')}</strong><small>ROMI {metricValue(campaign.romi, 'percent')}</small></div></div><div className="custom-row" style={{ marginTop: 16 }}><label>Просмотры объявления<input id="campaign-views" className="input" type="number" min="0" defaultValue={campaign.manual_metrics?.views || 0} /></label><label>Вступили в диалог<input id="campaign-dialogs" className="input" type="number" min="0" defaultValue={campaign.manual_metrics?.dialogs || 0} /></label><label>Целевое действие<input id="campaign-target-actions" className="input" type="number" min="0" defaultValue={campaign.manual_metrics?.target_actions || 0} /></label><button className="btn" onClick={() => saveCampaignMetrics(campaign.campaign_id, document.getElementById('campaign-views')?.value, document.getElementById('campaign-dialogs')?.value, document.getElementById('campaign-target-actions')?.value).catch(e => setError(normalizeErrorMessage(e.message || e)))}>Сохранить показатели</button></div><small>«Целевое действие» — нужный результат рекламы до лида: например, клик по контакту, отправка формы или запись на диагностику.</small><div style={{ display: 'grid', gap: 8, marginTop: 18, justifyItems: 'center' }}>{stages.map(([label, value, color], index) => <div key={label} style={{ width: `${Math.max(34, Math.round((Number(value) / max) * 100))}%`, minWidth: 280, background: `linear-gradient(90deg, ${color}, ${color}cc)`, color: '#10131a', borderRadius: '10px 10px 18px 18px', textAlign: 'center', padding: '13px 18px', fontWeight: 700, boxShadow: '0 8px 18px rgba(0,0,0,.18)' }}><span>{label}</span><strong style={{ marginLeft: 12 }}>{value}</strong>{index ? <small style={{ marginLeft: 12 }}>{Math.round((Number(value) / Math.max(Number(stages[index - 1][1]), 1)) * 100)}% от предыдущего этапа</small> : null}</div>)}</div></Card> })()}
                {(() => { const campaign = (marketingMetrics?.rows || []).find(row => String(row.campaign_id) === String(selectedMarketingCampaignId)); if (!campaign) return null; return <Card title="Период работы кампании" subtitle="Укажите дату запуска и остановки объявления"><div className="custom-row"><label>Запуск<input id="campaign-active-from" className="input" type="date" defaultValue={campaign.active_from || ''} /></label><label>Остановка<input id="campaign-active-to" className="input" type="date" defaultValue={campaign.active_to || ''} /></label><button className="btn" onClick={() => saveCampaignPeriod(campaign.campaign_id, document.getElementById('campaign-active-from')?.value, document.getElementById('campaign-active-to')?.value).catch(e => setError(normalizeErrorMessage(e.message || e)))}>Сохранить период</button></div></Card> })()}
                {(() => { const campaign = (marketingMetrics?.rows || []).find(row => String(row.campaign_id) === String(selectedMarketingCampaignId)); if (!campaign) return null; const stages = [['Просмотры объявления', campaign.manual_metrics?.views || 0, 'views'], ['Вступили в диалог', campaign.manual_metrics?.dialogs || 0, 'dialogs'], ['Целевое действие', campaign.manual_metrics?.target_actions || 0, 'target_actions'], ['Лиды в CRM', campaign.leads, null], ['Диагностика проведена', campaign.diagnostics_held, null], ['Первая оплата', campaign.new_clients, null]]; return <Card title="Визуальная воронка кампании" subtitle="Нажмите ручной этап, чтобы открыть редактор справа"><div style={{ display: 'grid', gridTemplateColumns: selectedFunnelMetric ? 'minmax(0, 1fr) 300px' : 'minmax(0, 1fr)', gap: 18 }}><CampaignFunnel stages={stages} onSelect={setSelectedFunnelMetric} />{selectedFunnelMetric ? <aside className="analytics-kpi-card" style={{ alignSelf: 'center' }}><span>Редактирование этапа</span><strong>{selectedFunnelMetric.label}</strong><div className="custom-row" style={{ marginTop: 12 }}><button className="btn secondary compact" onClick={() => setSelectedFunnelMetric(item => ({ ...item, value: Math.max(0, Number(item.value) - 1) }))}>−</button><input className="input" type="number" min="0" value={selectedFunnelMetric.value} onChange={e => setSelectedFunnelMetric(item => ({ ...item, value: e.target.value }))} /><button className="btn secondary compact" onClick={() => setSelectedFunnelMetric(item => ({ ...item, value: Number(item.value) + 1 }))}>+</button></div><button className="btn" style={{ marginTop: 12, width: '100%' }} onClick={() => saveSelectedFunnelMetric(campaign, selectedFunnelMetric.value).catch(e => setError(normalizeErrorMessage(e.message || e)))}>Сохранить</button></aside> : null}</div></Card> })()}
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

            <Card title="Эффективная ставка" subtitle="Выручка проведённых занятий ÷ все учтённые рабочие часы">
              {effectiveRate ? <>
                <div className="analytics-kpi-grid">
                  <div className="analytics-kpi-card"><span>Эффективная ставка</span><strong>{metricValue(effectiveRate.summary?.effective_hourly_rate, 'money')}</strong><small>цель: 3 000 ₽/ч+</small></div>
                  <div className="analytics-kpi-card"><span>Учтённая выручка</span><strong>{metricValue(effectiveRate.summary?.revenue, 'money')}</strong><small>без предоплат, не связанных с уроком</small></div>
                  <div className="analytics-kpi-card"><span>Проведённые занятия</span><strong>{metricValue(effectiveRate.summary?.lesson_hours)} ч</strong><small>по длительности оплаченных уроков</small></div>
                  <div className="analytics-kpi-card"><span>Непроведённая работа</span><strong>{metricValue(effectiveRate.summary?.manual_hours)} ч</strong><small>подготовка, продажи, контент, админ</small></div>
                </div>
                <div className="custom-row" style={{ marginTop: 14 }}>
                  <input type="date" className="input" value={workLogForm.worked_on} onChange={e => setWorkLogForm(value => ({ ...value, worked_on: e.target.value }))} />
                  <select className="input" value={workLogForm.category} onChange={e => setWorkLogForm(value => ({ ...value, category: e.target.value }))}>{Object.entries(WORK_CATEGORY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
                  <input className="input" type="number" min="1" value={workLogForm.minutes} onChange={e => setWorkLogForm(value => ({ ...value, minutes: e.target.value }))} placeholder="Минуты" />
                  <input className="input" value={workLogForm.note} onChange={e => setWorkLogForm(value => ({ ...value, note: e.target.value }))} placeholder="Что сделано" />
                  <button className="btn" disabled={!workLogForm.minutes} onClick={() => addWorkLog().catch(e => setError(normalizeErrorMessage(e.message || e)))}>Учесть часы</button>
                </div>
                <small>За период: всего {metricValue(effectiveRate.summary?.total_hours)} ч. Вносите только работу вне проведённых занятий — занятия считаются автоматически.</small>
                {(effectiveRate.items || []).length ? <ul className="list list-compact" style={{ marginTop: 12 }}>{effectiveRate.items.slice(0, 8).map(item => <li key={item.id}><div><strong>{item.worked_on} · {WORK_CATEGORY_LABELS[item.category] || item.category}</strong><small>{item.minutes} мин{item.note ? ` · ${item.note}` : ''}</small></div><button className="btn secondary compact" onClick={() => deleteWorkLog(item.id).catch(e => setError(normalizeErrorMessage(e.message || e)))}>Удалить</button></li>)}</ul> : <div className="placeholder-box" style={{ marginTop: 12 }}>Добавьте подготовку, продажи, контент или администрирование — это сделает ставку честной.</div>}
              </> : <div className="placeholder-box">Загружаем расчёт рабочей ставки.</div>}
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

      <nav className="bottom-nav bottom-nav-seven">
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
