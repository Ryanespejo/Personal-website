import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { Link } from 'react-router-dom'
import '../styles/sports.css'
import './NBA.css'

const REFRESH_SEC = 30
const CIRCUMFERENCE = 56.5
const ESPN_URL = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard'

function localDateStr(dayOffset = 0) {
  const d = new Date()
  d.setDate(d.getDate() + dayOffset)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fmtDateLabel(d) {
  if (d === localDateStr(0)) return 'Today'
  if (d === localDateStr(-1)) return 'Yesterday'
  if (d === localDateStr(1)) return 'Tomorrow'
  return new Date(d + 'T12:00:00Z').toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
}

function normalizeESPN(comp, event) {
  const competitors = comp.competitors || []
  if (competitors.length < 2) return null
  const st = comp.status || {}
  const stType = st.type || {}
  const state = stType.state || ''
  const detail = stType.shortDetail || stType.detail || stType.description || 'Scheduled'
  const clock = st.displayClock || ''
  const period = st.period || 0
  const date = (comp.date || event.date || '').slice(0, 10)
  const broadcasts = []
  for (const b of comp.broadcasts || []) broadcasts.push(...(b.names || []))
  const teams = competitors.map(c => {
    const t = c.team || {}
    const records = c.records || []
    return {
      id: String(t.id || ''),
      name: t.displayName || t.name || '',
      shortName: t.shortDisplayName || t.name || '',
      abbreviation: t.abbreviation || '',
      logo: t.logo || '',
      score: String(c.score || '—'),
      homeAway: c.homeAway || '',
      winner: !!c.winner,
      record: records.length ? records[0].summary || '' : '',
      quarters: (c.linescores || []).map(l => l.value != null ? String(Math.round(l.value)) : '—'),
    }
  })
  teams.sort((a, b) => a.homeAway === 'away' ? -1 : 1)
  const venue = comp.venue || {}
  const odds = (comp.odds || [])[0]
  return {
    id: String(comp.id || ''), date, status: detail, clock, period,
    isLive: state === 'in', isComplete: state === 'post', teams,
    venue: venue.fullName || '', broadcasts,
    odds: odds ? odds.details || '' : '',
  }
}

function StatusBadge({ game }) {
  if (game.isLive) return <span className="badge badge-live">Live</span>
  if (game.isComplete) return <span className="badge badge-final">Final</span>
  return <span className="badge badge-scheduled">Upcoming</span>
}

function TeamLogo({ team }) {
  const [err, setErr] = useState(false)
  if (team.logo && !err) {
    return <img className="team-logo" src={team.logo} alt={team.abbreviation} loading="lazy" onError={() => setErr(true)} />
  }
  return <span className="team-logo-placeholder">{team.abbreviation}</span>
}

function GameCard({ game, selected, onSelect }) {
  const maxQ = Math.max(...game.teams.map(t => t.quarters.length), 4)
  const showQuarters = game.isLive || game.isComplete
  return (
    <div className={`game${selected ? ' selected' : ''}`} onClick={onSelect}>
      <div className="game-meta">
        <span className="game-broadcast">{game.broadcasts.join(', ')}</span>
        {game.isLive && <span className="game-status-text">{game.status}</span>}
        <StatusBadge game={game} />
      </div>
      <div className="teams">
        {game.teams.map((t, ti) => {
          const opp = game.teams[1 - ti]
          const scoreClass = game.isLive ? 'live' : t.winner ? 'winner' : 'final'
          return (
            <div key={t.id} style={{
              display: 'grid',
              gridTemplateColumns: `26px 1fr ${showQuarters ? `repeat(${maxQ}, 2rem)` : ''} 2.8rem`,
              gap: '0.38rem',
              alignItems: 'center',
              fontSize: '0.91rem',
            }}>
              <TeamLogo team={t} />
              <span className={`tname${t.winner ? ' winner' : ''}`}>{t.shortName}</span>
              {showQuarters && Array.from({ length: maxQ }, (_, i) => {
                const val = t.quarters[i] ?? '—'
                const mine = parseInt(val, 10)
                const theirs = parseInt(opp?.quarters[i] ?? '0', 10)
                const won = !isNaN(mine) && !isNaN(theirs) && mine > theirs
                return (
                  <span key={i} style={{
                    minWidth: '2rem', textAlign: 'center', borderRadius: '5px',
                    border: `1px solid ${won ? 'rgba(249,115,22,0.45)' : 'var(--line)'}`,
                    background: won ? 'rgba(249,115,22,0.08)' : 'transparent',
                    color: won ? 'var(--accent)' : '#dce4ff',
                    fontVariantNumeric: 'tabular-nums', fontSize: '0.82rem',
                    padding: '0.12rem 0.15rem',
                  }}>{val}</span>
                )
              })}
              {game.isLive || game.isComplete
                ? <span className={`total-score ${scoreClass}`}>{t.score}</span>
                : <span className="total-score" style={{ color: 'var(--muted)', fontSize: '0.78rem' }}>{t.record}</span>
              }
            </div>
          )
        })}
      </div>
      {game.venue && <div className="game-venue">{game.venue}</div>}
    </div>
  )
}

function GameDetails({ game }) {
  const [away, home] = game.teams
  const maxQ = Math.max(away.quarters.length, home.quarters.length, 4)
  const qHeaders = Array.from({ length: maxQ }, (_, i) => i < 4 ? `Q${i + 1}` : `OT${i - 3}`)

  return (
    <>
      <div className="det-header">
        <div className="det-matchup">
          <div className="det-team">
            {away.logo && <img className="det-team-logo" src={away.logo} alt={away.abbreviation} onError={e => e.target.style.display = 'none'} />}
            <div className="det-team-name">{away.shortName}</div>
            <div className="det-team-record">{away.record}</div>
            {(game.isLive || game.isComplete) && (
              <div className={`det-team-score${away.winner ? ' winner' : ''}`}>{away.score}</div>
            )}
          </div>
          <div className="det-vs">
            {game.isLive || game.isComplete ? '' : 'vs'}
            <br /><span style={{ fontSize: '0.65rem' }}>@</span>
          </div>
          <div className="det-team">
            {home.logo && <img className="det-team-logo" src={home.logo} alt={home.abbreviation} onError={e => e.target.style.display = 'none'} />}
            <div className="det-team-name">{home.shortName}</div>
            <div className="det-team-record">{home.record}</div>
            {(game.isLive || game.isComplete) && (
              <div className={`det-team-score${home.winner ? ' winner' : ''}`}>{home.score}</div>
            )}
          </div>
        </div>
        <div className="det-sub">{game.status}</div>
        <div className="det-status-badge"><StatusBadge game={game} /></div>
      </div>

      {(game.isLive || game.isComplete) && (
        <div className="det-section">
          <div className="det-title">Box Score</div>
          <table className="box-score">
            <thead>
              <tr>
                <th>Team</th>
                {qHeaders.map(q => <th key={q}>{q}</th>)}
                <th>T</th>
              </tr>
            </thead>
            <tbody>
              {[away, home].map(t => (
                <tr key={t.id} className={t.winner ? 'winner' : ''}>
                  <td>{t.abbreviation}</td>
                  {Array.from({ length: maxQ }, (_, i) => <td key={i}>{t.quarters[i] ?? '—'}</td>)}
                  <td className="total">{t.score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="det-section">
        <div className="det-title">Game Info</div>
        {game.venue && <div className="info-row"><span className="info-label">Venue</span><span className="info-value">{game.venue}</span></div>}
        {game.broadcasts.length > 0 && <div className="info-row"><span className="info-label">TV</span><span className="info-value">{game.broadcasts.join(', ')}</span></div>}
        {game.odds && <div className="info-row"><span className="info-label">Line</span><span className="info-value">{game.odds}</span></div>}
        {away.record && <div className="info-row"><span className="info-label">{away.abbreviation} Record</span><span className="info-value">{away.record}</span></div>}
        {home.record && <div className="info-row"><span className="info-label">{home.abbreviation} Record</span><span className="info-value">{home.record}</span></div>}
      </div>
    </>
  )
}

export default function NBA() {
  const today = () => new Date().toISOString().slice(0, 10)
  const FALLBACK = [
    {
      id: 's1', date: today(), status: '4th · 2:30', clock: '2:30', period: 4, isLive: true, isComplete: false,
      venue: 'Madison Square Garden', broadcasts: ['ESPN'], odds: '',
      teams: [
        { id: '1', name: 'Boston Celtics', shortName: 'Celtics', abbreviation: 'BOS', logo: '', score: '108', homeAway: 'away', winner: false, record: '35-15', quarters: ['28', '30', '25', '25'] },
        { id: '2', name: 'New York Knicks', shortName: 'Knicks', abbreviation: 'NYK', logo: '', score: '105', homeAway: 'home', winner: false, record: '32-18', quarters: ['30', '22', '28', '25'] },
      ],
    },
  ]

  const [allGames, setAllGames] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [liveOnly, setLiveOnly] = useState(false)
  const [dateFilter, setDateFilter] = useState(localDateStr(0))
  const [statusMsg, setStatusMsg] = useState('Fetching scoreboard…')
  const [statusVisible, setStatusVisible] = useState(true)
  const [subtitle, setSubtitle] = useState('Connecting to live feed…')
  const [source, setSource] = useState(null)
  const [updatedAt, setUpdatedAt] = useState(null)
  const [countdown, setCountdown] = useState(REFRESH_SEC)
  const [showCountdown, setShowCountdown] = useState(false)

  const countdownRef = useRef(null)
  const refreshFnRef = useRef(null)

  const dates = useMemo(() => Array.from({ length: 7 }, (_, i) => localDateStr(i - 3)), [])

  async function fetchFromPython(dateStr) {
    const q = dateStr ? `?date=${dateStr}` : ''
    const res = await fetch(`/api/nba${q}`, { signal: AbortSignal.timeout(8000) })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    if (!Array.isArray(data.games)) throw new Error('Bad payload')
    return { games: data.games, source: 'python' }
  }

  async function fetchDirectESPN(dateStr) {
    let url = ESPN_URL
    if (dateStr) url += `?dates=${dateStr.replace(/-/g, '')}`
    const resp = await fetch(url)
    const data = await resp.json()
    const games = []
    for (const event of data.events || []) {
      for (const comp of event.competitions || []) {
        const g = normalizeESPN(comp, event)
        if (g) games.push(g)
      }
    }
    return { games, source: 'direct' }
  }

  const refresh = useCallback(async () => {
    setStatusMsg('Refreshing…')
    setStatusVisible(true)
    const dateStr = dateFilter || localDateStr(0)
    try {
      let result
      try { result = await fetchFromPython(dateStr) }
      catch (_) {
        try { result = await fetchDirectESPN(dateStr) }
        catch (__) { result = { games: FALLBACK, source: 'fallback' } }
      }
      const { games, source: src } = result
      setAllGames(games)
      setSource(src)
      const isFallback = src === 'fallback'
      setStatusMsg(isFallback ? 'Live feed unavailable — showing sample data.' : 'Feed connected.')
      setSubtitle(isFallback ? 'Showing sample data' : `${src === 'python' ? 'Python backend' : 'ESPN direct'} · auto-refresh 30s`)
      setUpdatedAt(new Date())
      if (!isFallback) setTimeout(() => setStatusVisible(false), 2000)
    } catch (err) {
      setStatusMsg(`Error: ${err.message}`)
    }
    setCountdown(REFRESH_SEC)
    setShowCountdown(true)
  }, [dateFilter])

  useEffect(() => { refreshFnRef.current = refresh }, [refresh])
  useEffect(() => { refresh() }, [dateFilter])

  useEffect(() => {
    if (!showCountdown) return
    clearInterval(countdownRef.current)
    countdownRef.current = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) { clearInterval(countdownRef.current); refreshFnRef.current?.(); return REFRESH_SEC }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(countdownRef.current)
  }, [showCountdown])

  const filteredGames = useMemo(() => {
    let filtered = allGames
    if (liveOnly) filtered = filtered.filter(g => g.isLive)
    return [...filtered].sort((a, b) => {
      if (a.isLive !== b.isLive) return a.isLive ? -1 : 1
      if (a.isComplete !== b.isComplete) return a.isComplete ? 1 : -1
      return 0
    })
  }, [allGames, liveOnly])

  const liveCount = allGames.filter(g => g.isLive).length
  const selectedGame = allGames.find(g => g.id === selectedId) || null
  const strokeDashoffset = CIRCUMFERENCE * (1 - countdown / REFRESH_SEC)
  const sourcePillClass = source === 'python' ? 'python' : source === 'fallback' ? 'fallback' : 'direct'
  const sourcePillLabel = source === 'python' ? 'Python backend' : source === 'fallback' ? 'Sample data' : 'ESPN direct'

  return (
    <div className="nba-page sports-page">
      <main className="app">
        <section className="topbar">
          <div className="brand">
            <h1>NBA Live Games</h1>
            <p>{subtitle}</p>
          </div>
          <Link className="home-link" to="/">&larr; Back home</Link>
        </section>

        <section className="filter-bar" aria-label="filters">
          <button
            className={`chip chip-live${liveOnly ? ' active' : ''}`}
            onClick={() => setLiveOnly(v => !v)}
          >
            <span className="live-dot" />
            Live{liveCount ? ` (${liveCount})` : ''}
          </button>
          {showCountdown && (
            <div className="countdown">
              <svg className="countdown-ring" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="9" />
                <circle className="progress" cx="12" cy="12" r="9"
                  strokeDasharray={CIRCUMFERENCE} strokeDashoffset={strokeDashoffset} />
              </svg>
              <span>{countdown}s</span>
              <span className={`source-pill ${sourcePillClass}`}>{sourcePillLabel}</span>
            </div>
          )}
        </section>

        <div className="date-row">
          {dates.map(d => (
            <button key={d}
              className={`chip date-chip${dateFilter === d ? ' active' : ''}`}
              onClick={() => setDateFilter(d)}>
              {fmtDateLabel(d)}
            </button>
          ))}
        </div>

        <section className="layout">
          <article className="games-panel">
            <header className="panel-header">
              <h2>Games</h2>
              <span className="live-count badge badge-live">
                {liveCount ? `${liveCount} Live` : `${allGames.length} Games`}
              </span>
            </header>
            <div className="games-scroll">
              {statusVisible && <div className="status-msg">{statusMsg}</div>}
              {filteredGames.length === 0 && !statusVisible && (
                <div className="status-msg">No games for this date.</div>
              )}
              {filteredGames.map(g => (
                <GameCard key={g.id} game={g} selected={g.id === selectedId}
                  onSelect={() => setSelectedId(id => id === g.id ? null : g.id)} />
              ))}
              {updatedAt && <div className="updated-at">Updated {updatedAt.toLocaleTimeString()}</div>}
            </div>
          </article>

          <aside className="details-panel" id="details-panel">
            <header className="panel-header">
              <h2>Game Details</h2>
            </header>
            <div className="details-scroll">
              {selectedGame
                ? <GameDetails game={selectedGame} />
                : (
                  <div className="details-empty">
                    <div className="ei-icon">🏀</div>
                    <p>Click any game to see the box score, game info, and details.</p>
                  </div>
                )
              }
            </div>
          </aside>
        </section>
      </main>
    </div>
  )
}
