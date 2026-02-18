import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { Link } from 'react-router-dom'
import '../styles/sports.css'
import './CBB.css'

const REFRESH_SEC = 30
const CIRCUMFERENCE = 56.5
const ESPN_URL = 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard'

const CONFERENCES = [
  ['', 'All Conferences'], ['50', 'ACC'], ['46', 'Big 12'], ['7', 'Big East'],
  ['4', 'Big Ten'], ['8', 'SEC'], ['21', 'AAC'], ['62', 'A-10'],
  ['1', 'America East'], ['2', 'Big Sky'], ['3', 'Big South'], ['5', 'Big West'],
  ['6', 'Colonial'], ['9', 'Conference USA'], ['10', 'Horizon'], ['11', 'Ivy League'],
  ['12', 'MAAC'], ['13', 'MAC'], ['14', 'MEAC'], ['16', 'Missouri Valley'],
  ['18', 'Mountain West'], ['19', 'Northeast'], ['20', 'Ohio Valley'], ['22', 'Pac-12'],
  ['23', 'Patriot League'], ['24', 'SoCon'], ['25', 'Southland'], ['26', 'SWAC'],
  ['27', 'Summit League'], ['29', 'Sun Belt'], ['30', 'WAC'], ['31', 'WCC'],
]

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
  const date = (comp.date || event.date || '').slice(0, 10)
  const broadcasts = []
  for (const b of comp.broadcasts || []) broadcasts.push(...(b.names || []))
  const confObj = comp.groups || {}
  const conference = confObj.name || ''
  const teams = competitors.map(c => {
    const t = c.team || {}
    const records = c.records || []
    const curated = c.curatedRank || {}
    let rank = curated.current || 0
    if (!rank && c.rank) rank = c.rank
    if (rank > 25) rank = 0
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
      halves: (c.linescores || []).map(l => l.value != null ? String(Math.round(l.value)) : '—'),
      rank,
    }
  })
  teams.sort((a, b) => a.homeAway === 'away' ? -1 : 1)
  const venue = comp.venue || {}
  const odds = (comp.odds || [])[0]
  const away = teams[0] || {}
  const home = teams[1] || {}
  return {
    id: String(comp.id || ''), date,
    status: detail, clock: st.displayClock || '', period: st.period || 0,
    isLive: state === 'in', isComplete: state === 'post',
    teams, venue: venue.fullName || '', broadcasts,
    odds: odds ? odds.details || '' : '',
    conference, awayRank: away.rank || 0, homeRank: home.rank || 0,
  }
}

function StatusBadge({ game }) {
  if (game.isLive) return <span className="badge badge-live">Live</span>
  if (game.isComplete) return <span className="badge badge-final">Final</span>
  return <span className="badge badge-scheduled">Upcoming</span>
}

function TeamLogo({ team }) {
  const [err, setErr] = useState(false)
  if (team.logo && !err) return <img className="team-logo" src={team.logo} alt={team.abbreviation} loading="lazy" onError={() => setErr(true)} />
  return <span className="team-logo-placeholder">{team.abbreviation}</span>
}

function GameCard({ game, selected, onSelect }) {
  const maxH = Math.max(...game.teams.map(t => (t.halves || []).length), 2)
  const showHalves = game.isLive || game.isComplete
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
          const halves = t.halves || []
          const scoreClass = game.isLive ? 'live' : t.winner ? 'winner' : 'final'
          return (
            <div key={t.id} style={{
              display: 'grid',
              gridTemplateColumns: `26px 1fr ${showHalves ? `repeat(${maxH}, 2.5rem)` : ''} 2.8rem`,
              gap: '0.38rem',
              alignItems: 'center',
              fontSize: '0.91rem',
            }}>
              <TeamLogo team={t} />
              <span className={`tname${t.winner ? ' winner' : ''}`}>
                {t.rank > 0 && <span className="rank-badge">{t.rank}</span>}
                {t.shortName}
              </span>
              {showHalves && Array.from({ length: maxH }, (_, i) => {
                const val = halves[i] ?? '—'
                const mine = parseInt(val, 10)
                const theirs = parseInt((opp?.halves || [])[i] ?? '0', 10)
                const won = !isNaN(mine) && !isNaN(theirs) && mine > theirs
                return (
                  <span key={i} style={{
                    minWidth: '2.5rem', textAlign: 'center', borderRadius: '5px',
                    border: `1px solid ${won ? 'rgba(59,130,246,0.45)' : 'var(--line)'}`,
                    background: won ? 'rgba(59,130,246,0.08)' : 'transparent',
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
  const maxH = Math.max(away.halves?.length || 0, home.halves?.length || 0, 2)
  const hHeaders = Array.from({ length: maxH }, (_, i) => `H${i + 1}`)
  return (
    <>
      <div className="det-header">
        <div className="det-matchup">
          <div className="det-team">
            {away.logo && <img className="det-team-logo" src={away.logo} alt={away.abbreviation} onError={e => e.target.style.display = 'none'} />}
            {away.rank > 0 && <div className="det-team-rank">#{away.rank}</div>}
            <div className="det-team-name">{away.shortName}</div>
            <div className="det-team-record">{away.record}</div>
            {(game.isLive || game.isComplete) && <div className={`det-team-score${away.winner ? ' winner' : ''}`}>{away.score}</div>}
          </div>
          <div className="det-vs">{game.isLive || game.isComplete ? '' : 'vs'}<br /><span style={{ fontSize: '0.65rem' }}>@</span></div>
          <div className="det-team">
            {home.logo && <img className="det-team-logo" src={home.logo} alt={home.abbreviation} onError={e => e.target.style.display = 'none'} />}
            {home.rank > 0 && <div className="det-team-rank">#{home.rank}</div>}
            <div className="det-team-name">{home.shortName}</div>
            <div className="det-team-record">{home.record}</div>
            {(game.isLive || game.isComplete) && <div className={`det-team-score${home.winner ? ' winner' : ''}`}>{home.score}</div>}
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
                {hHeaders.map(h => <th key={h}>{h}</th>)}
                <th>T</th>
              </tr>
            </thead>
            <tbody>
              {[away, home].map(t => (
                <tr key={t.id} className={t.winner ? 'winner' : ''}>
                  <td>{t.abbreviation}</td>
                  {Array.from({ length: maxH }, (_, i) => <td key={i}>{(t.halves || [])[i] ?? '—'}</td>)}
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
        {game.conference && <div className="info-row"><span className="info-label">Conference</span><span className="info-value">{game.conference}</span></div>}
        {game.broadcasts.length > 0 && <div className="info-row"><span className="info-label">TV</span><span className="info-value">{game.broadcasts.join(', ')}</span></div>}
        {game.odds && <div className="info-row"><span className="info-label">Line</span><span className="info-value">{game.odds}</span></div>}
      </div>
    </>
  )
}

export default function CBB() {
  const today = () => new Date().toISOString().slice(0, 10)
  const FALLBACK = [
    {
      id: 's1', date: today(), status: '2nd · 5:30', clock: '5:30', period: 2, isLive: true, isComplete: false,
      venue: 'Cameron Indoor Stadium', broadcasts: ['ESPN'], odds: '', conference: 'ACC', awayRank: 0, homeRank: 7,
      teams: [
        { id: '1', name: 'North Carolina Tar Heels', shortName: 'North Carolina', abbreviation: 'UNC', logo: '', score: '55', homeAway: 'away', winner: false, record: '18-7', halves: ['28', '27'], rank: 0 },
        { id: '2', name: 'Duke Blue Devils', shortName: 'Duke', abbreviation: 'DUKE', logo: '', score: '61', homeAway: 'home', winner: false, record: '22-4', halves: ['30', '31'], rank: 7 },
      ],
    },
  ]

  const [allGames, setAllGames] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [liveOnly, setLiveOnly] = useState(false)
  const [top25Only, setTop25Only] = useState(false)
  const [confFilter, setConfFilter] = useState('')
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

  const refresh = useCallback(async () => {
    setStatusMsg('Refreshing…')
    setStatusVisible(true)
    const dateStr = dateFilter || localDateStr(0)
    try {
      let result
      try {
        let q = dateStr ? `?date=${dateStr}` : '?'
        if (confFilter) q += `${q.length > 1 ? '&' : ''}conference=${confFilter}`
        if (top25Only) q += `${q.length > 1 ? '&' : ''}top25=true`
        if (q === '?') q = ''
        const res = await fetch(`/api/cbb${q}`, { signal: AbortSignal.timeout(8000) })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        if (!Array.isArray(data.games)) throw new Error('Bad payload')
        result = { games: data.games, source: 'python' }
      } catch (_) {
        try {
          let url = ESPN_URL + '?limit=200'
          if (dateStr) url += `&dates=${dateStr.replace(/-/g, '')}`
          if (confFilter) url += `&groups=${confFilter}`
          const resp = await fetch(url)
          const data = await resp.json()
          let games = []
          for (const event of data.events || []) {
            for (const comp of event.competitions || []) {
              const g = normalizeESPN(comp, event)
              if (g) games.push(g)
            }
          }
          if (top25Only) games = games.filter(g => g.awayRank || g.homeRank)
          result = { games, source: 'direct' }
        } catch (__) {
          result = { games: FALLBACK, source: 'fallback' }
        }
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
  }, [dateFilter, confFilter, top25Only])

  useEffect(() => { refreshFnRef.current = refresh }, [refresh])
  useEffect(() => { refresh() }, [dateFilter, confFilter, top25Only])

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
    if (top25Only) filtered = filtered.filter(g => g.awayRank || g.homeRank)
    return [...filtered].sort((a, b) => {
      if (a.isLive !== b.isLive) return a.isLive ? -1 : 1
      if (a.isComplete !== b.isComplete) return a.isComplete ? 1 : -1
      const aR = (a.awayRank || a.homeRank) ? 1 : 0
      const bR = (b.awayRank || b.homeRank) ? 1 : 0
      if (aR !== bR) return bR - aR
      return 0
    })
  }, [allGames, liveOnly, top25Only])

  // Group by conference
  const groupedGames = useMemo(() => {
    const grouped = {}
    for (const g of filteredGames) {
      const conf = g.conference || 'Other'
      if (!grouped[conf]) grouped[conf] = []
      grouped[conf].push(g)
    }
    const confKeys = Object.keys(grouped).sort((a, b) => {
      const aLive = grouped[a].some(g => g.isLive) ? 0 : 1
      const bLive = grouped[b].some(g => g.isLive) ? 0 : 1
      if (aLive !== bLive) return aLive - bLive
      return a.localeCompare(b)
    })
    return confKeys.map(conf => ({ conf, games: grouped[conf] }))
  }, [filteredGames])

  const liveCount = allGames.filter(g => g.isLive).length
  const selectedGame = allGames.find(g => g.id === selectedId) || null
  const strokeDashoffset = CIRCUMFERENCE * (1 - countdown / REFRESH_SEC)
  const sourcePillClass = source === 'python' ? 'python' : source === 'fallback' ? 'fallback' : 'direct'
  const sourcePillLabel = source === 'python' ? 'Python backend' : source === 'fallback' ? 'Sample data' : 'ESPN direct'

  return (
    <div className="cbb-page sports-page">
      <main className="app">
        <section className="topbar">
          <div className="brand">
            <h1>College Basketball Live</h1>
            <p>{subtitle}</p>
          </div>
          <Link className="home-link" to="/">&larr; Back home</Link>
        </section>

        <section className="filter-bar" aria-label="filters">
          <button className={`chip chip-live${liveOnly ? ' active' : ''}`} onClick={() => setLiveOnly(v => !v)}>
            <span className="live-dot" />Live{liveCount ? ` (${liveCount})` : ''}
          </button>
          <button className={`chip chip-top25${top25Only ? ' active' : ''}`} onClick={() => setTop25Only(v => !v)}>
            Top 25
          </button>
          <select className="conf-select" value={confFilter} onChange={e => setConfFilter(e.target.value)}>
            {CONFERENCES.map(([val, label]) => <option key={val} value={val}>{label}</option>)}
          </select>
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
            <button key={d} className={`chip date-chip${dateFilter === d ? ' active' : ''}`} onClick={() => setDateFilter(d)}>
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
              {groupedGames.length === 0 && !statusVisible && (
                <div className="status-msg">No games match the current filters.</div>
              )}
              {groupedGames.map(({ conf, games }) => (
                <div key={conf}>
                  <div className="conf-group-header">{conf}</div>
                  {games.map(g => (
                    <GameCard key={g.id} game={g} selected={g.id === selectedId}
                      onSelect={() => setSelectedId(id => id === g.id ? null : g.id)} />
                  ))}
                </div>
              ))}
              {updatedAt && <div className="updated-at">Updated {updatedAt.toLocaleTimeString()}</div>}
            </div>
          </article>

          <aside className="details-panel">
            <header className="panel-header"><h2>Game Details</h2></header>
            <div className="details-scroll">
              {selectedGame
                ? <GameDetails game={selectedGame} />
                : <div className="details-empty"><div className="ei-icon">🏀</div><p>Click any game to see the box score, game info, and details.</p></div>
              }
            </div>
          </aside>
        </section>
      </main>
    </div>
  )
}
