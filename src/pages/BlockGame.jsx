import { useState, useEffect, useRef, useCallback } from 'react'
import { Link } from 'react-router-dom'
import './BlockGame.css'

const GRID_SIZE = 8

const PIECES = [
  { cells:[[0,0]],                                                                             color:'#f472b6' },
  { cells:[[0,0],[0,1]],                                                                       color:'#4ade80' },
  { cells:[[0,0],[1,0]],                                                                       color:'#4ade80' },
  { cells:[[0,0],[0,1],[0,2]],                                                                 color:'#60a5fa' },
  { cells:[[0,0],[1,0],[2,0]],                                                                 color:'#60a5fa' },
  { cells:[[0,0],[0,1],[0,2],[0,3]],                                                           color:'#22d3ee' },
  { cells:[[0,0],[1,0],[2,0],[3,0]],                                                           color:'#22d3ee' },
  { cells:[[0,0],[0,1],[0,2],[0,3],[0,4]],                                                     color:'#a3e635' },
  { cells:[[0,0],[1,0],[2,0],[3,0],[4,0]],                                                     color:'#a3e635' },
  { cells:[[0,0],[0,1],[1,0],[1,1]],                                                           color:'#fbbf24' },
  { cells:[[0,0],[0,1],[0,2],[1,0],[1,1],[1,2],[2,0],[2,1],[2,2]],                             color:'#fde047' },
  { cells:[[0,0],[0,1],[0,2],[1,0],[1,1],[1,2]],                                               color:'#fb923c' },
  { cells:[[0,0],[0,1],[1,0],[1,1],[2,0],[2,1]],                                               color:'#fb923c' },
  { cells:[[0,0],[1,0],[2,0],[2,1]],                                                           color:'#c084fc' },
  { cells:[[0,1],[1,1],[2,0],[2,1]],                                                           color:'#c084fc' },
  { cells:[[0,0],[0,1],[1,0],[2,0]],                                                           color:'#c084fc' },
  { cells:[[0,0],[0,1],[1,1],[2,1]],                                                           color:'#c084fc' },
  { cells:[[0,0],[0,1],[0,2],[1,1]],                                                           color:'#e879f9' },
  { cells:[[0,0],[1,0],[2,0],[1,1]],                                                           color:'#e879f9' },
  { cells:[[0,1],[0,2],[1,0],[1,1]],                                                           color:'#f87171' },
  { cells:[[0,0],[0,1],[1,1],[1,2]],                                                           color:'#f87171' },
  { cells:[[0,1],[1,0],[1,1],[1,2],[2,1]],                                                     color:'#38bdf8' },
  { cells:[[0,0],[0,1],[1,0]],                                                                 color:'#34d399' },
  { cells:[[0,0],[0,1],[1,1]],                                                                 color:'#34d399' },
  { cells:[[0,0],[1,0],[1,1]],                                                                 color:'#34d399' },
  { cells:[[0,1],[1,0],[1,1]],                                                                 color:'#34d399' },
]

function randPiece() { return PIECES[Math.floor(Math.random() * PIECES.length)] }
function makeGrid()  { return Array.from({ length: GRID_SIZE }, () => Array(GRID_SIZE).fill(null)) }
function lighten(hex) {
  const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16)
  return `rgba(${Math.min(255,r+70)},${Math.min(255,g+70)},${Math.min(255,b+70)},.55)`
}
function canPlace(grid, piece, sr, sc) {
  for (const [dr,dc] of piece.cells) {
    const r=sr+dr, c=sc+dc
    if (r<0||r>=GRID_SIZE||c<0||c>=GRID_SIZE||grid[r][c]) return false
  }
  return true
}
function hasAnyMove(grid, pieces) {
  for (const p of pieces) {
    if (!p) continue
    for (let r=0;r<GRID_SIZE;r++) for (let c=0;c<GRID_SIZE;c++) if (canPlace(grid,p,r,c)) return true
  }
  return false
}

function PieceMini({ piece }) {
  if (!piece) return null
  const rs = piece.cells.map(([r]) => r)
  const cs = piece.cells.map(([,c]) => c)
  const maxR = Math.max(...rs), maxC = Math.max(...cs)
  const cells = []
  for (let r=0; r<=maxR; r++) {
    for (let c=0; c<=maxC; c++) {
      const filled = piece.cells.some(([pr,pc]) => pr===r && pc===c)
      cells.push(
        <div
          key={r*10+c}
          className="bg-pc"
          style={{
            background: filled ? piece.color : 'transparent',
            boxShadow: filled ? `inset 0 2px 0 ${lighten(piece.color)}` : 'none',
          }}
        />
      )
    }
  }
  return (
    <div
      className="bg-piece-grid"
      style={{
        gridTemplateColumns: `repeat(${maxC+1}, 14px)`,
        gridTemplateRows: `repeat(${maxR+1}, 14px)`,
      }}
    >
      {cells}
    </div>
  )
}

export default function BlockGame() {
  // game state stored in a ref to avoid stale closures in async callbacks
  const G = useRef(null)
  const [tick, setTick] = useState(0)
  const rerender = useCallback(() => setTick(t => t+1), [])

  const gridRef = useRef(null)

  function getState() { return G.current }

  const startGame = useCallback(() => {
    G.current = {
      grid:       makeGrid(),
      score:      0,
      linesCleared: 0,
      streak:     0,
      pieces:     [randPiece(), randPiece(), randPiece()],
      selIdx:     null,
      hoverR:     null,
      hoverC:     null,
      placing:    false,
      flashCells: new Set(),
      gameOverMsg: null,
      comboText:  '',
      best:       parseInt(localStorage.getItem('bb_best') || '0'),
    }
    rerender()
  }, [rerender])

  // init on mount
  useEffect(() => { startGame() }, [startGame])

  // keyboard
  useEffect(() => {
    const handler = e => {
      if (e.key === 'Escape') {
        const g = getState(); if (!g) return
        g.selIdx = null
        rerender()
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [rerender])

  // non-passive touch listeners on grid
  useEffect(() => {
    const el = gridRef.current
    if (!el) return
    const onTouchMove = e => {
      e.preventDefault()
      const g = getState(); if (!g || g.selIdx === null) return
      const pos = cellFromTouch(e, el)
      if (pos) { g.hoverR=pos.r; g.hoverC=pos.c; rerender() }
    }
    const onTouchEnd = e => {
      e.preventDefault()
      const g = getState(); if (!g) return
      const pos = cellFromTouch(e, el)
      if (pos) drop(pos.r, pos.c)
      g.hoverR = null; g.hoverC = null
    }
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    el.addEventListener('touchend',  onTouchEnd,  { passive: false })
    return () => {
      el.removeEventListener('touchmove', onTouchMove)
      el.removeEventListener('touchend',  onTouchEnd)
    }
  }) // re-bind after every render so tick always reflects latest state

  function cellFromTouch(e, el) {
    const touch = e.touches[0] || e.changedTouches[0]
    const rect  = el.getBoundingClientRect()
    const cellPx = (rect.width - 12 - 7*3) / 8
    const c = Math.floor((touch.clientX - rect.left  - 6) / (cellPx + 3))
    const r = Math.floor((touch.clientY - rect.top   - 6) / (cellPx + 3))
    if (r<0||r>=GRID_SIZE||c<0||c>=GRID_SIZE) return null
    return { r, c }
  }

  function selectPiece(idx) {
    const g = getState(); if (!g) return
    if (!g.pieces[idx]) return
    g.selIdx = g.selIdx === idx ? null : idx
    rerender()
  }

  function drop(r, c) {
    const g = getState(); if (!g) return
    if (g.placing || g.selIdx === null) return
    const p = g.pieces[g.selIdx]
    if (!canPlace(g.grid, p, r, c)) return

    g.placing = true
    for (const [dr,dc] of p.cells) g.grid[r+dr][c+dc] = p.color
    g.score += p.cells.length
    g.pieces[g.selIdx] = null
    g.selIdx = null
    rerender()

    clearLines(() => {
      g.placing = false
      if (g.pieces.every(x => !x)) {
        g.pieces = [randPiece(), randPiece(), randPiece()]
      }
      if (g.score > g.best) {
        g.best = g.score
        localStorage.setItem('bb_best', g.best)
      }
      if (!hasAnyMove(g.grid, g.pieces)) {
        if (g.score > g.best) { g.best = g.score; localStorage.setItem('bb_best', g.best) }
        const isNew = g.score >= g.best && g.score > 0
        g.gameOverMsg = `Score: ${g.score.toLocaleString()}${isNew ? ' 🏆 New best!' : ''}`
      }
      rerender()
    })
  }

  function clearLines(done) {
    const g = getState()
    const rowsToClear = [], colsToClear = []
    for (let r=0; r<GRID_SIZE; r++) if (g.grid[r].every(v=>v)) rowsToClear.push(r)
    for (let c=0; c<GRID_SIZE; c++) if (g.grid.every(row=>row[c])) colsToClear.push(c)

    const count = rowsToClear.length + colsToClear.length
    if (!count) { g.streak=0; g.comboText=''; done(); return }

    g.streak++
    const bonus = g.streak > 1 ? g.streak : 1
    const pts = count * GRID_SIZE * 10 * bonus
    g.score += pts
    g.linesCleared += count
    if (g.score > g.best) { g.best=g.score; localStorage.setItem('bb_best', g.best) }

    const labels = ['','','DOUBLE!','TRIPLE!','QUAD!','MEGA COMBO!']
    g.comboText = g.streak > 1
      ? (labels[Math.min(g.streak, labels.length-1)] || `${g.streak}× COMBO!`)
      : ''

    const toFlash = new Set()
    rowsToClear.forEach(r => { for (let c=0;c<GRID_SIZE;c++) toFlash.add(r*GRID_SIZE+c) })
    colsToClear.forEach(c => { for (let r=0;r<GRID_SIZE;r++) toFlash.add(r*GRID_SIZE+c) })
    g.flashCells = toFlash
    rerender()

    setTimeout(() => {
      rowsToClear.forEach(r => { for (let c=0;c<GRID_SIZE;c++) g.grid[r][c]=null })
      colsToClear.forEach(c => { for (let r=0;r<GRID_SIZE;r++) g.grid[r][c]=null })
      g.flashCells = new Set()
      g.comboText = ''
      done()
    }, 380)
  }

  // ── render ──────────────────────────────────────────────────────────────────
  const g = G.current
  if (!g) return null

  // build preview map
  const preview = new Map()
  if (g.selIdx !== null && g.hoverR !== null) {
    const p = g.pieces[g.selIdx]
    const ok = canPlace(g.grid, p, g.hoverR, g.hoverC)
    for (const [dr,dc] of p.cells) {
      const r=g.hoverR+dr, c=g.hoverC+dc
      if (r>=0&&r<GRID_SIZE&&c>=0&&c<GRID_SIZE)
        preview.set(r*GRID_SIZE+c, ok ? p.color : 'bad')
    }
  }

  // build grid cells
  const gridCells = []
  for (let r=0; r<GRID_SIZE; r++) {
    for (let c=0; c<GRID_SIZE; c++) {
      const key = r*GRID_SIZE+c
      const filled = g.grid[r][c]
      const prev   = preview.get(key)
      const flash  = g.flashCells.has(key)

      let className = 'bg-cell'
      let style = {}

      if (flash) {
        className += ' flash'
      } else if (filled) {
        className += ' filled'
        style = { background: filled, boxShadow: `inset 0 2px 0 ${lighten(filled)}` }
      } else if (prev) {
        if (prev === 'bad') {
          className += ' bad'
        } else {
          className += ' preview'
          style = { background: prev, boxShadow: `inset 0 2px 0 ${lighten(prev)}` }
        }
      }

      gridCells.push(
        <div
          key={key}
          className={className}
          style={style}
          onMouseEnter={() => {
            if (g.selIdx === null) return
            g.hoverR=r; g.hoverC=c; rerender()
          }}
          onClick={() => drop(r, c)}
        />
      )
    }
  }

  return (
    <div className="bg-page">
      <header className="bg-header">
        <Link to="/" className="bg-back">← Home</Link>
        <h1>Block Game</h1>
        <div style={{ width: 52 }} />
      </header>

      <div className="bg-score-bar">
        <div className="bg-score-item">
          <div className="bg-score-label">Score</div>
          <div className={`bg-score-value${tick ? ' bump' : ''}`} key={`s${g.score}`}>{g.score.toLocaleString()}</div>
        </div>
        <div className="bg-score-item">
          <div className="bg-score-label">Best</div>
          <div className="bg-score-value">{g.best.toLocaleString()}</div>
        </div>
        <div className="bg-score-item">
          <div className="bg-score-label">Lines</div>
          <div className="bg-score-value">{g.linesCleared}</div>
        </div>
      </div>

      <div className={`bg-combo-banner${g.comboText ? ' show' : ''}`}>{g.comboText}</div>

      <div className="bg-grid-wrap">
        <div
          className="bg-grid"
          ref={gridRef}
          onMouseLeave={() => { g.hoverR=null; g.hoverC=null; rerender() }}
        >
          {gridCells}
        </div>
      </div>

      <div className="bg-tray">
        {[0,1,2].map(i => (
          <div
            key={i}
            className={`bg-slot${i===g.selIdx ? ' selected' : ''}${!g.pieces[i] ? ' used' : ''}`}
            onClick={() => selectPiece(i)}
          >
            <PieceMini piece={g.pieces[i]} />
          </div>
        ))}
      </div>

      {g.gameOverMsg && (
        <div className="bg-overlay show">
          <div className="bg-box">
            <h2>Game Over</h2>
            <p dangerouslySetInnerHTML={{ __html: g.gameOverMsg.replace(
              /Score: ([\d,]+)/,
              'Score: <strong>$1</strong>'
            )}} />
            <button className="bg-btn" onClick={startGame}>Play Again</button>
          </div>
        </div>
      )}
    </div>
  )
}
