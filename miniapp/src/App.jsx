import { useEffect, useState } from 'react'
import { authByTelegram } from './api'
import { AdminView } from './features/admin/AdminView'
import { RoutedUserView } from './features/user/UserView'
import { useFloatingToasts } from './shared/hooks/useFloatingToasts'
import { ToastViewport } from './shared/ui/ToastViewport'
import { ViewErrorBoundary } from './shared/ui/ViewErrorBoundary'

export default function App() {
  const [token, setToken] = useState('')
  const [user, setUser] = useState(null)
  const [error, setError] = useState('')
  const toastItems = useFloatingToasts({
    success: '',
    error,
    onClearSuccess: undefined,
    onClearError: () => setError(''),
    normalizeError: value => String(value || ''),
  })

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
      <ToastViewport items={toastItems} onDismiss={() => setError('')} />
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
