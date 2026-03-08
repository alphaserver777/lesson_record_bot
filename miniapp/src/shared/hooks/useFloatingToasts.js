import { useEffect } from 'react'

export function useFloatingToasts({
  success,
  error,
  onClearSuccess,
  onClearError,
  normalizeError = v => String(v || ''),
}) {
  const normalizedError = normalizeError(error)

  useEffect(() => {
    if (!success) return
    const t = setTimeout(() => onClearSuccess?.(), 2200)
    return () => clearTimeout(t)
  }, [success, onClearSuccess])

  useEffect(() => {
    if (!normalizedError) return
    const t = setTimeout(() => onClearError?.(), 4200)
    return () => clearTimeout(t)
  }, [normalizedError, onClearError])

  const items = []
  if (success) {
    items.push({ id: 'success', type: 'success', title: 'Готово', message: success })
  }
  if (normalizedError) {
    items.push({ id: 'error', type: 'error', title: 'Что-то пошло не так', message: normalizedError })
  }
  return items
}
