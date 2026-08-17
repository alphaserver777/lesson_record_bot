// In production the API is served behind the same public host as the cabinet.
// A relative default keeps local development simple and prevents CORS issues.
const API_BASE = (import.meta.env.VITE_API_BASE || '/cabinet').replace(/\/$/, '')

export async function api(path, { token, method = 'GET', body } = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: body ? JSON.stringify(body) : undefined
  })
  const raw = await res.text()
  let data = {}
  try {
    data = raw ? JSON.parse(raw) : {}
  } catch {
    data = {}
  }
  if (!res.ok) {
    if ([502, 503, 504].includes(res.status)) {
      throw new Error('Сервис авторизации перезапускается. Обновите страницу через несколько секунд.')
    }
    if (typeof data.detail === 'string') throw new Error(data.detail)
    if (Array.isArray(data.detail)) {
      throw new Error(data.detail.map(item => item?.msg).filter(Boolean).join('. ') || `Ошибка авторизации (${res.status})`)
    }
    throw new Error(raw && !raw.trim().startsWith('<') ? raw : `Ошибка авторизации (${res.status})`)
  }
  return data
}

export async function authByTelegram() {
  const tg = window.Telegram?.WebApp
  const initData = tg?.initData || ''
  if (!initData) {
    throw new Error('TELEGRAM_AUTH_REQUIRED')
  }
  return api('/api/webapp/auth/telegram', { method: 'POST', body: { initData } })
}

export async function authByTelegramWidget(payload) {
  return api('/api/auth/telegram/login-widget', { method: 'POST', body: payload })
}
