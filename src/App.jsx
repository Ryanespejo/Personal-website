import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import Tennis from './pages/Tennis'
import NBA from './pages/NBA'
import CBB from './pages/CBB'
import CollegeBaseball from './pages/CollegeBaseball'
import BabyCalendar from './pages/BabyCalendar'
import BlockGame from './pages/BlockGame'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/tennis" element={<Tennis />} />
        <Route path="/nba" element={<NBA />} />
        <Route path="/cbb" element={<CBB />} />
        <Route path="/college-baseball" element={<CollegeBaseball />} />
        <Route path="/babycalendar" element={<BabyCalendar />} />
        <Route path="/block-game" element={<BlockGame />} />
      </Routes>
    </BrowserRouter>
  )
}
