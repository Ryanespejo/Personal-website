import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { Link } from 'react-router-dom'
import '../styles/sports.css'
import './Tennis.css'

const REFRESH_SEC = 30
const CIRCUMFERENCE = 56.5

const ESPN = {
  atp: 'https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard',
  wta: 'https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard',
}

const PRED_SOURCES = [
  { id: 'tennistonic', name: 'Tennis Tonic H2H', color: '#62f2a6' },
  { id: 'grandstand', name: 'The Grandstand', color: '#7dd3fc', url: 'https://tenngrand.com/category/match-previews/' },
  { id: 'lwos', name: 'Last Word on Sports', color: '#f9a8d4', url: 'https://lastwordonsports.com/tennis/' },
]

function localDateStr(dayOffset = 0) {
  const d = new Date()
  d.setDate(d.getDate() + dayOffset)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fmtDate(d) {
  if (d === localDateStr(0)) return 'Today'
  if (d === localDateStr(-1)) return 'Yesterday'
  if (d === localDateStr(1)) return 'Tomorrow'
  return new Date(d + 'T12:00:00Z').toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
}

function normalizeESPN(comp, tour, eventName) {
  const competitors = comp.competitors || []
  if (competitors.length < 2) return null
  const st = comp.status?.type || {}
  const status = st.shortDetail || st.description || 'Scheduled'
  const state = st.state || ''
  const roundName = comp.round?.displayName || ''
  let tournament = `${tour.toUpperCase()} · ${eventName}`
  if (roundName) tournament += ` · ${roundName}`
  const sorted = [...competitors].sort((a, b) => (a.order ?? 99) - (b.order ?? 99))
  const players = sorted.map(c => ({
    name: c.athlete?.shortName || c.athlete?.displayName || c.roster?.shortDisplayName || c.name || 'Player',
    fullName: c.athlete?.displayName || c.athlete?.shortName || c.roster?.displayName || c.name || 'Player',
    sets: (c.linescores || []).map(l => l.value != null ? String(Math.round(l.value)) : '—'),
    game: String(c.score || '—'),
    serving: !!c.status?.isCurrent,
    winner: !!c.winner,
  }))
  const playerIds = sorted.map(c => String(c.id || ''))
  const date = (comp.startDate || comp.date || '').slice(0, 10)
  return {
    id: String(comp.id || ''), tour, tournamentName: eventName, round: roundName,
    tournament, date, playerIds, status,
    isLive: state === 'in', isComplete: state === 'post', players,
  }
}

function StatusBadge({ match }) {
  if (match.isLive) return <span className="badge badge-live">Live</span>
  if (match.isComplete) return <span className="badge badge-final">Final</span>
  return <span className="badge badge-scheduled">Upcoming</span>
}

function MatchCard({ match, selected, onSelect, onPlayerClick }) {
  const maxSets = Math.max(...match.players.map(p => p.sets.length), 2)
  return (
    <div
      className={`match${selected ? ' selected' : ''}`}
      onClick={onSelect}
    >
      <div className="match-meta">
        <span className="match-round">{match.round || '—'}</span>
        {match.isLive && <span className="match-status-text">{match.status}</span>}
        <StatusBadge match={match} />
      </div>
      <div className="players">
        {match.players.map((p, pi) => {
          const opp = match.players[1 - pi]
          return (
            <div key={pi} className="row" style={{ '--sets': maxSets }}>
              <span
                className={`pname pname-clickable${p.winner ? ' winner' : ''}`}
                onClick={e => { e.stopPropagation(); onPlayerClick?.(p.fullName || p.name, match.tour) }}
                title="View Elo profile"
              >
                {p.serving ? '🎾 ' : ''}{p.name}
              </span>
              {Array.from({ length: maxSets }, (_, i) => {
                const val = p.sets[i] ?? '—'
                const mine = parseInt(val, 10)
                const theirs = parseInt(opp?.sets[i] ?? '0', 10)
                const won = !isNaN(mine) && !isNaN(theirs) && mine > theirs
                return (
                  <span key={i} className={`set-score${won ? ' won' : ''}`}>{val}</span>
                )
              })}
              <span className="game-score">{match.isComplete ? '' : p.game}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function PlayerProfile({ playerName, tour, onClose }) {
  const [elo, setElo] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    setElo(null)
    const enc = encodeURIComponent(playerName)
    fetch(`/api/tennis-elo?player=${enc}&tour=${tour || 'atp'}`, {
      signal: AbortSignal.timeout(10000),
    })
      .then(r => r.json())
      .then(data => {
        const results = data.results || []
        setElo(results.length > 0 ? results[0] : null)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [playerName, tour])

  const surfaceBar = (label, eloVal, rank, color) => {
    const maxElo = 2400
    const minElo = 1000
    const pct = eloVal ? Math.max(0, Math.min(100, ((eloVal - minElo) / (maxElo - minElo)) * 100)) : 0
    return (
      <div className="elo-surface-row">
        <span className="elo-surface-label">{label}</span>
        <div className="elo-surface-track">
          <div className="elo-surface-fill" style={{ width: `${pct}%`, background: color }} />
        </div>
        <span className="elo-surface-value">{eloVal != null ? eloVal.toFixed(1) : '—'}</span>
        <span className="elo-surface-rank">#{rank ?? '—'}</span>
      </div>
    )
  }

  return (
    <div className="player-profile-overlay" onClick={onClose}>
      <div className="player-profile" onClick={e => e.stopPropagation()}>
        <div className="pp-header">
          <div className="pp-title-row">
            <h3 className="pp-name">{playerName}</h3>
            <button className="pp-close" onClick={onClose}>&times;</button>
          </div>
          <span className="pp-tour-badge" data-tour={tour}>{(tour || 'atp').toUpperCase()}</span>
        </div>

        {loading ? (
          <div className="pp-loading">Loading Elo ratings...</div>
        ) : !elo ? (
          <div className="pp-empty">No Elo data found for this player.</div>
        ) : (
          <div className="pp-body">
            <div className="pp-overview">
              <div className="pp-stat-card pp-stat-main">
                <span className="pp-stat-label">Overall Elo</span>
                <span className="pp-stat-value">{elo.elo?.toFixed(1) ?? '—'}</span>
                <span className="pp-stat-sub">Rank #{elo.elo_rank ?? '—'}</span>
              </div>
              <div className="pp-stat-card">
                <span className="pp-stat-label">Peak Elo</span>
                <span className="pp-stat-value pp-peak">{elo.peak_elo?.toFixed(1) ?? '—'}</span>
                <span className="pp-stat-sub">{elo.peak_month || '—'}</span>
              </div>
              <div className="pp-stat-card">
                <span className="pp-stat-label">ATP Rank</span>
                <span className="pp-stat-value">#{elo.atp_rank ?? '—'}</span>
                <span className="pp-stat-sub">Age {elo.age?.toFixed(1) ?? '—'}</span>
              </div>
            </div>

            <div className="pp-surfaces">
              <div className="pp-section-title">Surface Elo Ratings</div>
              {surfaceBar('Hard', elo.hard_elo, elo.hard_elo_rank, '#7dd3fc')}
              {surfaceBar('Clay', elo.clay_elo, elo.clay_elo_rank, '#f9a8d4')}
              {surfaceBar('Grass', elo.grass_elo, elo.grass_elo_rank, '#62f2a6')}
            </div>

            <div className="pp-footer">
              Source: Tennis Abstract &middot; Updated weekly
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function InsightsEmpty() {
  return (
    <div className="insights-empty">
      <div className="ei-icon">📊</div>
      <p>Click any match to see H2H record, recent form, live rankings, and prediction sources.</p>
    </div>
  )
}

function InsightsPanel({ match, allMatches, onPlayerClick }) {
  const [rankings, setRankings] = useState(null)
  const [mlData, setMlData] = useState(null)
  const [mlLoading, setMlLoading] = useState(true)
  const [articles, setArticles] = useState(null)
  const [articlesLoading, setArticlesLoading] = useState(true)

  const [p1, p2] = match.players
  const [id1, id2] = match.playerIds || ['', '']

  // Compute H2H from cached matches
  const h2h = useMemo(() => {
    if (!id1 || !id2) return { wins1: 0, wins2: 0, total: 0 }
    let wins1 = 0, wins2 = 0
    for (const m of allMatches) {
      if (!m.isComplete) continue
      const ids = m.playerIds || []
      if (!ids.includes(id1) || !ids.includes(id2)) continue
      const idx1 = ids.indexOf(id1)
      if (m.players[idx1]?.winner) wins1++
      else wins2++
    }
    return { wins1, wins2, total: wins1 + wins2 }
  }, [allMatches, id1, id2])

  // Compute recent form
  const form1 = useMemo(() => {
    if (!id1) return []
    const results = []
    for (const m of allMatches) {
      if (!m.isComplete) continue
      const idx = (m.playerIds || []).indexOf(id1)
      if (idx === -1) continue
      const p = m.players[idx]
      const opp = m.players[1 - idx]
      if (!p) continue
      results.push({ won: !!p.winner, opp: opp?.name || '?', tourn: m.tournamentName, round: m.round })
      if (results.length >= 8) break
    }
    return results
  }, [allMatches, id1])

  const form2 = useMemo(() => {
    if (!id2) return []
    const results = []
    for (const m of allMatches) {
      if (!m.isComplete) continue
      const idx = (m.playerIds || []).indexOf(id2)
      if (idx === -1) continue
      const p = m.players[idx]
      const opp = m.players[1 - idx]
      if (!p) continue
      results.push({ won: !!p.winner, opp: opp?.name || '?', tourn: m.tournamentName, round: m.round })
      if (results.length >= 8) break
    }
    return results
  }, [allMatches, id2])

  useEffect(() => {
    // Fetch rankings
    if (id1 && id2) {
      Promise.all([
        fetch(`/api/tennis-athlete?tour=${match.tour}&athleteId=${id1}`).then(r => r.json()).then(d => d?.athlete?.rank ?? null).catch(() => null),
        fetch(`/api/tennis-athlete?tour=${match.tour}&athleteId=${id2}`).then(r => r.json()).then(d => d?.athlete?.rank ?? null).catch(() => null),
      ]).then(([r1, r2]) => setRankings([r1, r2])).catch(() => setRankings([null, null]))
    } else {
      setRankings([null, null])
    }

    // Fetch ML prediction
    setMlLoading(true)
    setMlData(null)
    const p1enc = encodeURIComponent(p1.fullName || p1.name)
    const p2enc = encodeURIComponent(p2.fullName || p2.name)
    fetch(`/api/tennis-analytics?action=predict&player1=${p1enc}&player2=${p2enc}&tour=${match.tour}&surface=hard`, {
      signal: AbortSignal.timeout(15000),
    }).then(r => r.json()).then(d => { setMlData(d); setMlLoading(false) }).catch(() => setMlLoading(false))

    // Fetch prediction articles
    setArticlesLoading(true)
    setArticles(null)
    const year = (match.date || '').slice(0, 4)
    const fn1 = encodeURIComponent(p1.fullName || p1.name)
    const fn2 = encodeURIComponent(p2.fullName || p2.name)
    const t = encodeURIComponent(match.tournamentName || '')
    fetch(`/api/tennis-news?player1=${encodeURIComponent(p1.name)}&player2=${encodeURIComponent(p2.name)}&fullname1=${fn1}&fullname2=${fn2}&tournament=${t}&year=${encodeURIComponent(year)}`, {
      signal: AbortSignal.timeout(12000),
    }).then(r => r.json()).then(data => {
      const arts = (data.sources || []).flatMap(s =>
        (s.articles || []).map(a => ({ ...a, sourceName: s.name, sourceColor: s.color }))
      )
      setArticles(arts)
      setArticlesLoading(false)
    }).catch(() => setArticlesLoading(false))
  }, [match.id])

  const f1 = Math.max(h2h.wins1, 0.5)
  const f2 = Math.max(h2h.wins2, 0.5)

  const ttSlug = (n) => (n || '').replace(/\s+/g, '-')
  const ttH2h = `https://tennistonic.com/head-to-head-compare/${ttSlug(p1.fullName || p1.name)}-Vs-${ttSlug(p2.fullName || p2.name)}/`

  return (
    <>
      <div className="ins-match-header">
        <div className="ins-players">
          <span className="ins-p ins-p-clickable" onClick={() => onPlayerClick?.(p1.fullName || p1.name)}>{p1.name}</span>
          <span className="ins-vs">vs</span>
          <span className="ins-p right ins-p-clickable" onClick={() => onPlayerClick?.(p2.fullName || p2.name)}>{p2.name}</span>
        </div>
        <div className="ins-sub">{match.tournamentName}{match.round ? ' · ' + match.round : ''}</div>
        <div className="ins-status-badge">
          <StatusBadge match={match} />
          {' '}
          <span style={{ fontSize: '0.78rem', color: 'var(--muted)' }}>{match.status}</span>
        </div>
      </div>

      <div className="ins-section">
        <div className="ins-title">Rankings</div>
        {!rankings ? (
          <span className="rank-msg">Fetching…</span>
        ) : rankings[0] == null && rankings[1] == null ? (
          <span className="rank-msg">Rankings unavailable</span>
        ) : (
          <>
            <div className="rank-row">
              <span className="rank-pname">{p1.name}</span>
              <span className="rank-num">{rankings[0] != null ? '#' + rankings[0] : '—'}</span>
            </div>
            <div className="rank-row">
              <span className="rank-pname">{p2.name}</span>
              <span className="rank-num">{rankings[1] != null ? '#' + rankings[1] : '—'}</span>
            </div>
          </>
        )}
      </div>

      <div className="ins-section">
        <div className="ins-title">Head to Head</div>
        <div className="h2h-labels">
          <span>{h2h.wins1}</span>
          <span>{h2h.wins2}</span>
        </div>
        <div className="h2h-bar">
          <div className="h2h-seg p1" style={{ flex: f1 }} />
          <div className="h2h-seg p2" style={{ flex: f2 }} />
        </div>
        <div className="h2h-note">
          {mlData?.h2h?.total
            ? `${mlData.h2h.total} meeting${mlData.h2h.total > 1 ? 's' : ''} (Sackmann + RapidAPI)`
            : h2h.total
              ? `${h2h.total} meeting${h2h.total > 1 ? 's' : ''} in current data`
              : 'No previous meetings found'}
        </div>
      </div>

      <div className="ins-section">
        <div className="ins-title">Recent Form — {p1.name}</div>
        <div className="form-line">
          {form1.length === 0
            ? <span className="form-empty">Not enough data in current feed</span>
            : <div className="form-badges">
              {form1.map((r, i) => (
                <span key={i} className={`fb ${r.won ? 'W' : 'L'}`} title={`${r.won ? 'Win' : 'Loss'} vs ${r.opp} · ${r.tourn}`}>
                  {r.won ? 'W' : 'L'}
                </span>
              ))}
            </div>
          }
        </div>
      </div>

      <div className="ins-section">
        <div className="ins-title">Recent Form — {p2.name}</div>
        <div className="form-line">
          {form2.length === 0
            ? <span className="form-empty">Not enough data in current feed</span>
            : <div className="form-badges">
              {form2.map((r, i) => (
                <span key={i} className={`fb ${r.won ? 'W' : 'L'}`} title={`${r.won ? 'Win' : 'Loss'} vs ${r.opp} · ${r.tourn}`}>
                  {r.won ? 'W' : 'L'}
                </span>
              ))}
            </div>
          }
        </div>
      </div>

      <div className="ml-section">
        <div className="ml-title">ML Prediction <span className="ml-badge">BETA</span></div>
        {mlLoading
          ? <span className="ml-msg">Analyzing…</span>
          : mlData
            ? <MLPrediction data={mlData} p1name={p1.name} p2name={p2.name} />
            : <span className="ml-msg">ML prediction unavailable</span>
        }
      </div>

      {mlData?.fav_underdog && (
        <div className="ins-section">
          <div className="ins-title">Favorite vs Underdog Record <span style={{ fontWeight: 400, opacity: 0.7 }}>(Elo-based)</span></div>
          <FavDogSection data={mlData.fav_underdog} p1name={p1.name} p2name={p2.name} />
        </div>
      )}

      <div className="ins-section">
        <div className="ins-title">Prediction Sources</div>
        <div className="pred-links">
          <a className="pred-link" href={ttH2h} target="_blank" rel="noopener"
            style={{ color: '#62f2a6', borderColor: 'rgba(98,242,166,0.25)', background: 'rgba(98,242,166,0.09)' }}>
            Tennis Tonic H2H
          </a>
          {PRED_SOURCES.slice(1).map(s => (
            <a key={s.id} className="pred-link" href={s.url} target="_blank" rel="noopener"
              style={{ color: s.color, borderColor: `${s.color}40`, background: `${s.color}12` }}>
              {s.name}
            </a>
          ))}
          <a className="pred-link" href={`https://x.com/search?q=${encodeURIComponent(`${p1.name} ${p2.name} ${match.tournamentName} ${(match.date || '').slice(0, 4)}`)}&f=live`}
            target="_blank" rel="noopener"
            style={{ color: '#e2e8f0', borderColor: 'rgba(226,232,240,0.25)', background: 'rgba(226,232,240,0.07)' }}>
            𝕏 Search
          </a>
        </div>
        {articlesLoading
          ? <span className="pred-msg">Loading previews…</span>
          : articles && articles.length > 0
            ? articles.map((a, i) => (
              <div key={i} className="pred-article">
                <a className="pred-article-title" href={a.url} target="_blank" rel="noopener">{a.title}</a>
                {a.snippet && <p className="pred-snippet">{a.snippet}</p>}
                <div className="pred-source-label" style={{ color: a.sourceColor }}>{a.sourceName}</div>
              </div>
            ))
            : <span className="pred-msg">No previews found — use the links above to browse directly.</span>
        }
      </div>
    </>
  )
}

function MLPrediction({ data, p1name, p2name }) {
  const p1Pct = Math.round(data.p1_win_prob * 100)
  const p2Pct = Math.round(data.p2_win_prob * 100)
  const confPct = Math.round(data.confidence * 100)
  const p1Fav = data.p1_win_prob >= data.p2_win_prob
  const modelInfo = data.model_info || {}
  const accText = modelInfo.accuracy ? `${Math.round(modelInfo.accuracy * 100)}% accuracy` : ''
  const trainedDate = modelInfo.trained_at ? new Date(modelInfo.trained_at) : null
  const hasValidDate = trainedDate && !Number.isNaN(trainedDate.getTime())
  const dateText = hasValidDate ? trainedDate.toLocaleDateString() : ''
  const infoLine = [accText, dateText].filter(Boolean).join(' · ')
  const modelAgeDays = hasValidDate
    ? Math.floor((Date.now() - trainedDate.getTime()) / (1000 * 60 * 60 * 24))
    : null
  const staleModel = Number.isFinite(modelAgeDays) && modelAgeDays > 120

  const custom = data.custom_analytics || {}
  const customModel = custom.custom_model || {}
  const customP1 = Number.isFinite(customModel.p1_win_prob) ? Math.round(customModel.p1_win_prob * 100) : null
  const customP2 = Number.isFinite(customModel.p2_win_prob) ? Math.round(customModel.p2_win_prob * 100) : null
  const ensemble = data.ensemble_win_prob || {}
  const ensP1 = Number.isFinite(ensemble.p1) ? Math.round(ensemble.p1 * 100) : null
  const ensP2 = Number.isFinite(ensemble.p2) ? Math.round(ensemble.p2 * 100) : null

  return (
    <>
      <div className="ml-prob-row">
        <span className={`ml-prob-pct${p1Fav ? ' fav' : ''}`}>{p1name} {p1Pct}%</span>
        <span className={`ml-prob-pct${!p1Fav ? ' fav' : ''}`}>{p2Pct}% {p2name}</span>
      </div>
      <div className="ml-bar">
        <div className="ml-seg p1" style={{ flex: Math.max(data.p1_win_prob, 0.05) }} />
        <div className="ml-seg p2" style={{ flex: Math.max(data.p2_win_prob, 0.05) }} />
      </div>
      <div className="ml-confidence">
        Confidence: {confPct}%
        <span className="ml-confidence-fill" style={{ width: `${confPct}px` }} />
      </div>
      {data.key_factors && data.key_factors.length > 0 && (
        <>
          <div className="ins-title" style={{ marginTop: '0.3rem' }}>Key Factors</div>
          <ul className="ml-factors">
            {data.key_factors.map((f, i) => (
              <li key={i}>
                <span className={`arrow ${f.direction === 'favors_p1' ? 'p1' : 'p2'}`}>
                  {f.direction === 'favors_p1' ? '▲' : '▼'}
                </span>
                {f.label}
              </li>
            ))}
          </ul>
        </>
      )}
      {infoLine && (
        <div className="ml-model-info">
          Model: {infoLine}
          {staleModel && <span style={{ color: 'var(--gold)' }}> (stale: {modelAgeDays} days old)</span>}
        </div>
      )}
      <div className="ml-model-info">Live enrichment: {custom.neo4j_enabled || custom.rapidapi_enabled ? `enabled via ${custom.neo4j_enabled ? 'Neo4j' : 'RapidAPI'} (24h cache)` : 'disabled (set RAPIDAPI_KEY)'}</div>
      {customP1 != null && customP2 != null && (
        <div className="ml-model-info">Custom model: {p1name} {customP1}% · {customP2}% {p2name}</div>
      )}
      {ensP1 != null && ensP2 != null && (
        <div className="ml-model-info">Ensemble blend: {p1name} {ensP1}% · {ensP2}% {p2name}</div>
      )}
    </>
  )
}

function FavDogSection({ data, p1name, p2name }) {
  const renderPlayer = (pName, stats) => {
    if (!stats || (!stats.fav_total && !stats.dog_total)) {
      return (
        <div key={pName} className="fav-dog-row">
          <div className="fav-dog-name">{pName}</div>
          <span className="fav-dog-msg">No data available</span>
        </div>
      )
    }
    const favTotal = stats.fav_total || 0
    const dogTotal = stats.dog_total || 0
    const favWPct = favTotal ? Math.round((stats.fav_wins / favTotal) * 100) : 0
    const favLPct = favTotal ? 100 - favWPct : 0
    const dogWPct = dogTotal ? Math.round((stats.dog_wins / dogTotal) * 100) : 0
    const dogLPct = dogTotal ? 100 - dogWPct : 0
    const eloLabel = stats.current_elo ? ` — Elo ${stats.current_elo}` : ''

    return (
      <div key={pName} className="fav-dog-row">
        <div className="fav-dog-name">
          {pName}
          {eloLabel && <span style={{ fontWeight: 400, color: 'var(--muted)', fontSize: '0.7rem' }}>{eloLabel}</span>}
        </div>
        <div className="fav-dog-bars">
          <div className="fav-dog-bar-wrap">
            <span className="fav-dog-label">Favorite</span>
            <div className="fav-dog-track">
              <div className="fav-dog-fill-w fav" style={{ width: `${favWPct}%` }} />
              <div className="fav-dog-fill-l fav" style={{ width: `${favLPct}%` }} />
            </div>
            <span className="fav-dog-stat">{stats.fav_wins}W-{stats.fav_losses}L ({favWPct}%)</span>
          </div>
          <div className="fav-dog-bar-wrap">
            <span className="fav-dog-label">Underdog</span>
            <div className="fav-dog-track">
              <div className="fav-dog-fill-w dog" style={{ width: `${dogWPct}%` }} />
              <div className="fav-dog-fill-l dog" style={{ width: `${dogLPct}%` }} />
            </div>
            <span className="fav-dog-stat">{stats.dog_wins}W-{stats.dog_losses}L ({dogWPct}%)</span>
          </div>
        </div>
      </div>
    )
  }

  const fdSource = (data.p1 || data.p2 || {}).source || ''
  const fdSourceLabel = fdSource === 'rapidapi' ? 'Source: RapidAPI match history'
    : fdSource === 'sackmann' ? 'Source: Sackmann historical data' : ''

  return (
    <>
      {renderPlayer(p1name, data.p1)}
      {renderPlayer(p2name, data.p2)}
      <div className="fav-dog-legend">
        <span><span className="fav-dog-legend-dot" style={{ background: 'var(--accent)' }} />Win</span>
        <span><span className="fav-dog-legend-dot" style={{ background: 'rgba(255,106,123,0.45)' }} />Loss</span>
        <span><span className="fav-dog-legend-dot" style={{ background: 'var(--gold)' }} />Upset win</span>
      </div>
      {fdSourceLabel && (
        <div style={{ fontSize: '0.63rem', color: 'var(--muted)', marginTop: '0.3rem', opacity: 0.7 }}>{fdSourceLabel}</div>
      )}
    </>
  )
}

export default function Tennis() {
  const today = () => new Date().toISOString().slice(0, 10)
  const FALLBACK = [
    {
      id: 's1', tour: 'atp', tournamentName: 'Sample', round: 'Final', tournament: 'ATP · Sample',
      status: 'Set 3 · 5-4', isLive: true, isComplete: false, date: today(), playerIds: ['1', '2'],
      players: [
        { name: 'C. Alcaraz', sets: ['6', '3', '5'], game: '40', serving: true, winner: false },
        { name: 'L. Musetti', sets: ['4', '6', '4'], game: '30', serving: false, winner: false },
      ],
    },
    {
      id: 's2', tour: 'wta', tournamentName: 'Sample', round: 'Final', tournament: 'WTA · Sample',
      status: 'Set 2 · 2-1', isLive: true, isComplete: false, date: today(), playerIds: ['3', '4'],
      players: [
        { name: 'I. Swiatek', sets: ['6', '2'], game: 'Ad', serving: true, winner: false },
        { name: 'D. Kasatkina', sets: ['1', '1'], game: '40', serving: false, winner: false },
      ],
    },
  ]

  const [allMatches, setAllMatches] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [tourFilter, setTourFilter] = useState('all')
  const [liveOnly, setLiveOnly] = useState(false)
  const [dateFilter, setDateFilter] = useState(null)
  const [tournamentFilter, setTournamentFilter] = useState('')
  const [statusMsg, setStatusMsg] = useState('Fetching scoreboard…')
  const [statusVisible, setStatusVisible] = useState(true)
  const [subtitle, setSubtitle] = useState('Connecting to live feed…')
  const [source, setSource] = useState(null)
  const [updatedAt, setUpdatedAt] = useState(null)
  const [countdown, setCountdown] = useState(REFRESH_SEC)
  const [showCountdown, setShowCountdown] = useState(false)
  const [profilePlayer, setProfilePlayer] = useState(null)
  const [profileTour, setProfileTour] = useState('atp')

  const countdownRef = useRef(null)
  const refreshFnRef = useRef(null)

  const openProfile = useCallback((name, tour) => {
    setProfilePlayer(name)
    setProfileTour(tour || 'atp')
  }, [])

  async function fetchFromPython() {
    const res = await fetch('/api/tennis', { signal: AbortSignal.timeout(8000) })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    if (!Array.isArray(data.matches)) throw new Error('Bad payload')
    return { matches: data.matches, source: 'python' }
  }

  async function fetchDirectESPN() {
    const [a, w] = await Promise.all([
      fetch(ESPN.atp).then(r => r.json()),
      fetch(ESPN.wta).then(r => r.json()),
    ])
    const matches = []
    for (const [data, tour] of [[a, 'atp'], [w, 'wta']]) {
      for (const event of data.events || []) {
        const eventName = event.shortName || event.name || 'Tournament'
        for (const grouping of event.groupings || []) {
          for (const comp of grouping.competitions || []) {
            const m = normalizeESPN(comp, tour, eventName)
            if (m) matches.push(m)
          }
        }
      }
    }
    return { matches, source: 'direct' }
  }

  const loadMatches = useCallback(async () => {
    try { return await fetchFromPython() }
    catch (_) {
      try { return await fetchDirectESPN() }
      catch (__) { return { matches: FALLBACK, source: 'fallback' } }
    }
  }, [])

  const refresh = useCallback(async () => {
    setStatusMsg('Refreshing…')
    setStatusVisible(true)
    try {
      const { matches, source: src } = await loadMatches()
      setAllMatches(matches)
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
  }, [loadMatches])

  // Store refresh in ref so countdown can call it
  useEffect(() => { refreshFnRef.current = refresh }, [refresh])

  // Initial load
  useEffect(() => { refresh() }, [])

  // Countdown timer
  useEffect(() => {
    if (!showCountdown) return
    clearInterval(countdownRef.current)
    countdownRef.current = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          clearInterval(countdownRef.current)
          refreshFnRef.current?.()
          return REFRESH_SEC
        }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(countdownRef.current)
  }, [showCountdown])

  // Derived: available dates
  const availableDates = useMemo(() =>
    [...new Set(allMatches.map(m => m.date).filter(Boolean))].sort(),
    [allMatches]
  )

  // Derived: available tournaments (filtered by tour)
  const availableTournaments = useMemo(() => {
    const scoped = tourFilter === 'all' ? allMatches : allMatches.filter(m => m.tour === tourFilter)
    return [...new Set(scoped.map(m => m.tournamentName).filter(Boolean))].sort()
  }, [allMatches, tourFilter])

  // Derived: filtered matches
  const filteredMatches = useMemo(() => {
    let filtered = allMatches
    if (tourFilter !== 'all') filtered = filtered.filter(m => m.tour === tourFilter)
    if (liveOnly) filtered = filtered.filter(m => m.isLive)
    if (dateFilter) filtered = filtered.filter(m => m.date === dateFilter)
    if (tournamentFilter) filtered = filtered.filter(m => m.tournamentName === tournamentFilter)
    return filtered
  }, [allMatches, tourFilter, liveOnly, dateFilter, tournamentFilter])

  // Derived: grouped matches
  const groupedMatches = useMemo(() => {
    const groups = new Map()
    for (const m of filteredMatches) {
      const key = `${m.tour}|${m.tournamentName}`
      if (!groups.has(key)) groups.set(key, { tour: m.tour, name: m.tournamentName || '', matches: [] })
      groups.get(key).matches.push(m)
    }
    return [...groups.values()].sort((a, b) => {
      const aL = a.matches.some(m => m.isLive) ? 1 : 0
      const bL = b.matches.some(m => m.isLive) ? 1 : 0
      if (bL !== aL) return bL - aL
      return a.tour.localeCompare(b.tour)
    })
  }, [filteredMatches])

  const liveCount = allMatches.filter(m => m.isLive).length
  const selectedMatch = allMatches.find(m => m.id === selectedId) || null

  const strokeDashoffset = CIRCUMFERENCE * (1 - countdown / REFRESH_SEC)

  const sourcePillClass = source === 'python' ? 'python' : source === 'fallback' ? 'fallback' : 'direct'
  const sourcePillLabel = source === 'python' ? '🐍 Python backend' : source === 'fallback' ? 'Sample data' : 'ESPN direct'

  return (
    <div className="tennis-page sports-page">
      <main className="app">
        <section className="topbar">
          <div className="brand">
            <h1>Tennis Live Center</h1>
            <p>{subtitle}</p>
          </div>
          <Link className="home-link" to="/">&larr; Back home</Link>
        </section>

        <section className="filter-bar" aria-label="filters">
          {['all', 'atp', 'wta'].map(t => (
            <button key={t} className={`chip${tourFilter === t ? ' active' : ''}`}
              onClick={() => { setTourFilter(t); setTournamentFilter('') }}>
              {t.toUpperCase() === 'ALL' ? 'All' : t.toUpperCase()}
            </button>
          ))}
          <button
            className={`chip chip-live${liveOnly ? ' active' : ''}`}
            onClick={() => setLiveOnly(v => !v)}
          >
            <span className="live-dot" />
            Live{liveCount ? ` (${liveCount})` : ''}
          </button>
          <select className="tourn-select" value={tournamentFilter}
            onChange={e => setTournamentFilter(e.target.value)}>
            <option value="">All Tournaments</option>
            {availableTournaments.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          {showCountdown && (
            <div className="countdown">
              <svg className="countdown-ring" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="9" />
                <circle className="progress" cx="12" cy="12" r="9"
                  strokeDasharray={CIRCUMFERENCE}
                  strokeDashoffset={strokeDashoffset} />
              </svg>
              <span>{countdown}s</span>
              <span className={`source-pill ${sourcePillClass}`}>{sourcePillLabel}</span>
            </div>
          )}
        </section>

        <div className="date-row">
          <button
            className={`chip date-chip${dateFilter === null ? ' active' : ''}`}
            onClick={() => setDateFilter(null)}
          >All</button>
          {availableDates.map(d => (
            <button key={d}
              className={`chip date-chip${dateFilter === d ? ' active' : ''}`}
              onClick={() => setDateFilter(d)}>
              {fmtDate(d)}
            </button>
          ))}
        </div>

        <section className="layout">
          <article className="matches-panel">
            <header className="panel-header">
              <h2>Matches</h2>
              <span className="live-count badge badge-live">
                {liveCount ? `${liveCount} Live` : `${allMatches.length} total`}
              </span>
            </header>
            <div className="matches-scroll">
              {statusVisible && <div className="status-msg">{statusMsg}</div>}
              {groupedMatches.length === 0 && !statusVisible && (
                <div className="status-msg">No matches for this filter.</div>
              )}
              {groupedMatches.map(g => {
                const liveCount = g.matches.filter(m => m.isLive).length
                return (
                  <div key={`${g.tour}|${g.name}`} className="tournament-section">
                    <div className="tournament-header">
                      <span className={`tour-label ${g.tour}`}>{g.tour.toUpperCase()}</span>
                      <span className="tourn-name">{g.name}</span>
                      {liveCount > 0 && (
                        <span className="tourn-live-pill">
                          <span className="dot" />{liveCount} live
                        </span>
                      )}
                    </div>
                    {g.matches.map(m => (
                      <MatchCard
                        key={m.id}
                        match={m}
                        selected={m.id === selectedId}
                        onSelect={() => {
                          if (selectedId === m.id) setSelectedId(null)
                          else setSelectedId(m.id)
                        }}
                        onPlayerClick={(name) => openProfile(name, m.tour)}
                      />
                    ))}
                  </div>
                )
              })}
              {updatedAt && (
                <div className="updated-at">Updated {updatedAt.toLocaleTimeString()}</div>
              )}
            </div>
          </article>

          <aside className="insights-panel">
            <header className="panel-header">
              <h2>Match Insights</h2>
            </header>
            <div className="insights-scroll">
              {selectedMatch
                ? <InsightsPanel match={selectedMatch} allMatches={allMatches} onPlayerClick={(name) => openProfile(name, selectedMatch.tour)} />
                : <InsightsEmpty />
              }
            </div>
          </aside>
        </section>
      </main>

      {profilePlayer && (
        <PlayerProfile
          playerName={profilePlayer}
          tour={profileTour}
          onClose={() => setProfilePlayer(null)}
        />
      )}
    </div>
  )
}
