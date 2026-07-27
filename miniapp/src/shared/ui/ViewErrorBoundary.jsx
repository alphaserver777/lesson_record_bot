import React from 'react'

export class ViewErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, message: '' }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, message: String(error?.message || error || 'render error') }
  }

  componentDidCatch() {}

  render() {
    if (this.state.hasError) {
      return (
        <div className="toast error">
          Ошибка интерфейса: {this.state.message}
        </div>
      )
    }
    return this.props.children
  }
}
