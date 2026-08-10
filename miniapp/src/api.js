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
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data))
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
