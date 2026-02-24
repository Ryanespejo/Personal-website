import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import './TennisLive.css'

const WIDGET_BASE = 'https://tnnslive.com/widgets'

const STYLE_PARAM = JSON.stringify({
  accent: 'rgba(202,243,76,1)',
  backgroundColor: 'black',
  color_border: 'rgba(0,0,0,0.04)',
  hide_top_border: true,
  color: 'black',
  color_view_all: 'white',
})

const WIDGETS = [
  { id: 'scores', label: 'Live Scores', path: '/scores' },
  { id: 'schedule', label: 'Schedule', path: '/schedule' },
  { id: 'results', label: 'Results', path: '/results' },
  { id: 'rankings', label: 'Rankings', path: '/rankings' },
]

function buildWidgetUrl(path) {
  return `${WIDGET_BASE}${path}?style=${encodeURIComponent(STYLE_PARAM)}`
}

export default function TennisLive() {
  const [activeWidget, setActiveWidget] = useState('scores')
  const [iframeLoaded, setIframeLoaded] = useState({})
  const iframeRef = useRef(null)

  useEffect(() => {
    document.body.style.background = '#0a0a0a'
    return () => { document.body.style.background = '' }
  }, [])

  useEffect(() => {
    setIframeLoaded(prev => ({ ...prev, [activeWidget]: false }))
  }, [activeWidget])

  const active = WIDGETS.find(w => w.id === activeWidget)
  const widgetUrl = active ? buildWidgetUrl(active.path) : ''

  return (
    <div className="tl-page">
      <div className="tl-app">
        <div className="tl-topbar">
          <div className="tl-brand">
            <h1>tennis live</h1>
            <span className="tl-powered">powered by tnnslive</span>
          </div>
          <Link to="/" className="tl-home-link">&larr; home</Link>
        </div>

        <div className="tl-tabs">
          {WIDGETS.map(w => (
            <button
              key={w.id}
              className={`tl-tab${activeWidget === w.id ? ' active' : ''}`}
              onClick={() => setActiveWidget(w.id)}
            >
              {w.label}
            </button>
          ))}
        </div>

        <div className="tl-widget-container">
          {!iframeLoaded[activeWidget] && (
            <div className="tl-loading">
              <div className="tl-spinner" />
              <span>Loading {active?.label}...</span>
            </div>
          )}
          <iframe
            ref={iframeRef}
            key={activeWidget}
            src={widgetUrl}
            className={`tl-iframe${iframeLoaded[activeWidget] ? ' loaded' : ''}`}
            title={active?.label || 'Tennis Widget'}
            allow="autoplay"
            onLoad={() => setIframeLoaded(prev => ({ ...prev, [activeWidget]: true }))}
          />
        </div>
      </div>
    </div>
  )
}
