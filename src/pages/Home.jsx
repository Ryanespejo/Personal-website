import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import './Home.css'

export default function Home() {
  const canvasRef = useRef(null)

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    document.body.style.background = '#0a0a0a'
    return () => {
      document.body.style.overflow = ''
      document.body.style.background = ''
    }
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')

    let width = (canvas.width = window.innerWidth)
    let height = (canvas.height = window.innerHeight)
    let mouse = { x: -1000, y: -1000 }
    const BEAN_COUNT = 35
    const MOUSE_RADIUS = 120
    const MOUSE_FORCE = 0.8

    class Bean {
      constructor() {
        this.reset()
        this.x = Math.random() * width
        this.y = Math.random() * height
      }

      reset() {
        this.x = Math.random() * width
        this.y = Math.random() * height
        this.size = 12 + Math.random() * 18
        this.rotation = Math.random() * Math.PI * 2
        this.rotationSpeed = (Math.random() - 0.5) * 0.02
        this.vx = (Math.random() - 0.5) * 0.5
        this.vy = (Math.random() - 0.5) * 0.5
        this.baseVx = this.vx
        this.baseVy = this.vy
        this.opacity = 0.3 + Math.random() * 0.4
        this.color = this.pickColor()
      }

      pickColor() {
        const colors = [
          '#6F4E37', '#8B6914', '#5C4033',
          '#3E2723', '#795548', '#4E342E', '#A0522D',
        ]
        return colors[Math.floor(Math.random() * colors.length)]
      }

      update() {
        const dx = this.x - mouse.x
        const dy = this.y - mouse.y
        const dist = Math.sqrt(dx * dx + dy * dy)

        if (dist < MOUSE_RADIUS && dist > 0) {
          const force = (1 - dist / MOUSE_RADIUS) * MOUSE_FORCE
          this.vx += (dx / dist) * force
          this.vy += (dy / dist) * force
        }

        this.vx += (this.baseVx - this.vx) * 0.02
        this.vy += (this.baseVy - this.vy) * 0.02

        this.x += this.vx
        this.y += this.vy
        this.rotation += this.rotationSpeed

        if (this.x < -this.size) this.x = width + this.size
        if (this.x > width + this.size) this.x = -this.size
        if (this.y < -this.size) this.y = height + this.size
        if (this.y > height + this.size) this.y = -this.size
      }

      draw() {
        ctx.save()
        ctx.translate(this.x, this.y)
        ctx.rotate(this.rotation)
        ctx.globalAlpha = this.opacity

        const s = this.size

        ctx.fillStyle = this.color
        ctx.beginPath()
        ctx.ellipse(0, 0, s * 0.55, s, 0, 0, Math.PI * 2)
        ctx.fill()

        ctx.strokeStyle = 'rgba(0,0,0,0.3)'
        ctx.lineWidth = 1
        ctx.stroke()

        ctx.beginPath()
        ctx.moveTo(0, -s * 0.8)
        ctx.bezierCurveTo(s * 0.2, -s * 0.3, -s * 0.2, s * 0.3, 0, s * 0.8)
        ctx.strokeStyle = 'rgba(0,0,0,0.4)'
        ctx.lineWidth = 1.5
        ctx.stroke()

        ctx.beginPath()
        ctx.ellipse(-s * 0.15, -s * 0.2, s * 0.15, s * 0.35, -0.3, 0, Math.PI * 2)
        ctx.fillStyle = 'rgba(255,255,255,0.07)'
        ctx.fill()

        ctx.restore()
      }
    }

    const beans = Array.from({ length: BEAN_COUNT }, () => new Bean())
    let animId

    function animate() {
      ctx.clearRect(0, 0, width, height)
      for (const bean of beans) {
        bean.update()
        bean.draw()
      }
      animId = requestAnimationFrame(animate)
    }

    const onMouseMove = (e) => { mouse.x = e.clientX; mouse.y = e.clientY }
    const onTouchMove = (e) => {
      if (e.touches.length > 0) {
        mouse.x = e.touches[0].clientX
        mouse.y = e.touches[0].clientY
      }
    }
    const onMouseLeave = () => { mouse.x = -1000; mouse.y = -1000 }
    const onResize = () => {
      width = canvas.width = window.innerWidth
      height = canvas.height = window.innerHeight
    }

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('touchmove', onTouchMove, { passive: true })
    window.addEventListener('mouseleave', onMouseLeave)
    window.addEventListener('resize', onResize)

    animate()

    return () => {
      cancelAnimationFrame(animId)
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('touchmove', onTouchMove)
      window.removeEventListener('mouseleave', onMouseLeave)
      window.removeEventListener('resize', onResize)
    }
  }, [])

  return (
    <>
      <canvas ref={canvasRef} id="beans" />
      <div className="center-content">
        <h1>hola bean</h1>
        <Link to="/babycalendar" className="nav-link">how big is baby? &rarr;</Link>
        <Link to="/tennis" className="nav-link">tennis live center &rarr;</Link>
        <Link to="/nba" className="nav-link">nba live games &rarr;</Link>
        <Link to="/cbb" className="nav-link">college basketball live &rarr;</Link>
        <Link to="/college-baseball" className="nav-link">college baseball live &rarr;</Link>
        <Link to="/block-game" className="nav-link">block game &rarr;</Link>
      </div>
    </>
  )
}
