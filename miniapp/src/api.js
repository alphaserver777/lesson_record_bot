const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

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
  return api('/api/webapp/auth/telegram', { method: 'POST', body: { initData } })
}
