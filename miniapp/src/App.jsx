import { useCallback, useEffect, useRef, useState } from 'react'
import { authByTelegram, authByTelegramWidget } from './api'
import { AdminView } from './features/admin/AdminView'
import { RoutedUserView } from './features/user/UserView'
import { useFloatingToasts } from './shared/hooks/useFloatingToasts'
import { ToastViewport } from './shared/ui/ToastViewport'
import { ViewErrorBoundary } from './shared/ui/ViewErrorBoundary'

function WebEntry({ onAuthenticated }) {
  const telegramButtonRef = useRef(null)
  const [loginError, setLoginError] = useState('')

  useEffect(() => {
    window.onProffessorTelegramAuth = async telegramUser => {
      setLoginError('')
      try {
        onAuthenticated(await authByTelegramWidget(telegramUser))
      } catch (error) {
        setLoginError(String(error.message || error))
      }
    }
    const script = document.createElement('script')
    script.src = 'https://telegram.org/js/telegram-widget.js?22'
    script.async = true
    script.setAttribute('data-telegram-login', 'proffessorit_bot')
    script.setAttribute('data-size', 'large')
    script.setAttribute('data-radius', '12')
    script.setAttribute('data-onauth', 'onProffessorTelegramAuth(user)')
    telegramButtonRef.current?.appendChild(script)
    return () => {
      delete window.onProffessorTelegramAuth
    }
  }, [onAuthenticated])

  return (
    <section className="web-entry" aria-labelledby="cabinet-title">
      <div className="web-entry-mark">P</div>
      <p className="web-entry-kicker">PROFFESSOR IT</p>
      <h1 id="cabinet-title">Личный кабинет ученика</h1>
      <p>Записывайтесь на занятия, смотрите расписание и управляйте обучением в одном месте.</p>
      {loginError ? <div className="login-error">{loginError}</div> : null}
      <div className="telegram-login" ref={telegramButtonRef} />
      <p className="web-entry-fallback">
        Не открывается вход через Telegram?{' '}
        <a href="https://t.me/proffessorit_bot" target="_blank" rel="noreferrer">Откройте кабинет через бота</a>.
      </p>
      <small>В боте нажмите «Открыть личный кабинет» — это тот же сайт, но вход произойдёт автоматически.</small>
    </section>
  )
}

export default function App() {
  const [token, setToken] = useState('')
  const [user, setUser] = useState(null)
  const [error, setError] = useState('')
  const [telegramContext, setTelegramContext] = useState(false)
  const onAuthenticated = useCallback(data => {
    setToken(data.access_token)
    setUser(data.user)
  }, [])
  const toastItems = useFloatingToasts({
    success: '',
    error,
    onClearSuccess: undefined,
    onClearError: () => setError(''),
    normalizeError: value => String(value || ''),
  })

  useEffect(() => {
    const tg = window.Telegram?.WebApp
    if (tg?.initData) {
      setTelegramContext(true)
      tg.ready()
      tg.expand()
      tg.setHeaderColor('#070a14')
      tg.setBackgroundColor('#070a14')
      authByTelegram()
        .then(data => {
          setToken(data.access_token)
          setUser(data.user)
        })
        .catch(e => setError(String(e.message || e)))
    }
  }, [])

  return (
    <main className="app">
      <ToastViewport items={toastItems} onDismiss={() => setError('')} />
      {!telegramContext && !token ? <WebEntry onAuthenticated={onAuthenticated} /> : null}
      {telegramContext && !token ? <div className="loading">Подключаем кабинет...</div> : null}
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
