import { useEffect, useRef, type ReactNode } from 'react'
import { useBottomSheet } from './useBottomSheet'

type Snap = 'default' | 'expanded' | 'collapsed'
interface Props {
  children: ReactNode
  footer?: ReactNode
  compact?: boolean
  ariaLabel?: string
  initialSnap?: Snap
  preferredSnap?: Snap
  className?: string
}
export default function BottomSheet({
  children,
  footer,
  compact = false,
  ariaLabel = '경로 안내 패널',
  initialSnap = 'default',
  preferredSnap,
  className = '',
}: Props) {
  const { ref, snap, dragHeight, gripProps } = useBottomSheet(initialSnap, preferredSnap)
  const bodyRef = useRef<HTMLDivElement>(null)
  const scrollHideTimer = useRef<number | null>(null)
  useEffect(() => {
    const body = bodyRef.current
    if (!body) return
    const showScrollbar = () => {
      body.classList.add('scrollbar-visible')
      if (scrollHideTimer.current !== null) window.clearTimeout(scrollHideTimer.current)
      scrollHideTimer.current = window.setTimeout(() => {
        body.classList.remove('scrollbar-visible')
        scrollHideTimer.current = null
      }, 700)
    }
    body.addEventListener('scroll', showScrollbar, { passive: true })
    return () => {
      body.removeEventListener('scroll', showScrollbar)
      if (scrollHideTimer.current !== null) window.clearTimeout(scrollHideTimer.current)
      scrollHideTimer.current = null
      body.classList.remove('scrollbar-visible')
    }
  }, [])
  return (
    <section
      ref={ref}
      className={`bottom-sheet ${className} ${compact ? 'compact-sheet' : ''} ${dragHeight ? 'dragging' : ''}`}
      data-snap={snap}
      style={dragHeight ? { height: dragHeight } : undefined}
      aria-label={ariaLabel}
    >
      <button className="sheet-grip" {...gripProps}>
        <span />
      </button>
      <div ref={bodyRef} className="sheet-body">
        {children}
      </div>
      {footer && <div className="sheet-footer">{footer}</div>}
    </section>
  )
}
