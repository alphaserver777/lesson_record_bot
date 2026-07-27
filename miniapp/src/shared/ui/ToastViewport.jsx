export function ToastViewport({ items, onDismiss }) {
  if (!items.length) return null
  return (
    <div className="toast-viewport" aria-live="polite" aria-atomic="true">
      {items.map(item => (
        <button
          key={item.id}
          type="button"
          className={`floating-toast ${item.type}`}
          onClick={() => onDismiss?.(item.id)}
        >
          <span className={`floating-toast-icon ${item.type}`}>{item.type === 'success' ? '✓' : item.type === 'error' ? '!' : 'i'}</span>
          <span className="floating-toast-copy">
            {item.title ? <strong>{item.title}</strong> : null}
            <span>{item.message}</span>
          </span>
        </button>
      ))}
    </div>
  )
}
