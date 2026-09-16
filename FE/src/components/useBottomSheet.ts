import { useEffect, useRef, useState, type ButtonHTMLAttributes } from 'react'

type Snap = 'default' | 'expanded' | 'collapsed'
export function useBottomSheet(initialSnap: Snap = 'default', preferredSnap?: Snap) {
  const [snap, setSnap] = useState<Snap>(initialSnap)
  const [dragHeight, setDragHeight] = useState<number | null>(null)
  const ref = useRef<HTMLElement>(null)
  const drag = useRef<{ y: number; height: number; moved: boolean } | null>(null)
  const suppressClick = useRef(false)
  useEffect(() => {
    if (preferredSnap !== undefined) setSnap(preferredSnap)
  }, [preferredSnap])
  const finish = (cancelled: boolean, y: number) => {
    const current = drag.current
    if (!current) return
    if (!cancelled && current.moved) {
      const delta = current.y - y
      if (Math.abs(delta) > 28)
        setSnap(delta > 0 ? 'expanded' : snap === 'expanded' ? 'default' : 'collapsed')
      suppressClick.current = true
    }
    drag.current = null
    setDragHeight(null)
  }
  const gripProps: ButtonHTMLAttributes<HTMLButtonElement> = {
    'aria-label': snap === 'expanded' ? '바텀시트 접기' : '바텀시트 펼치기',
    'aria-expanded': snap === 'expanded',
    onClick: (event) => {
      if (suppressClick.current && event.detail > 0) {
        suppressClick.current = false
        return
      }
      setSnap(snap === 'expanded' ? 'default' : 'expanded')
    },
    onKeyDown: (event) => {
      if (['ArrowUp', 'ArrowDown', 'Escape'].includes(event.key)) {
        event.preventDefault()
        setSnap(
          event.key === 'ArrowUp'
            ? 'expanded'
            : event.key === 'ArrowDown'
              ? 'collapsed'
              : 'default',
        )
      }
    },
    onPointerDown: (event) => {
      if (event.button !== 0) return
      suppressClick.current = false
      drag.current = {
        y: event.clientY,
        height: ref.current!.getBoundingClientRect().height,
        moved: false,
      }
      event.currentTarget.setPointerCapture(event.pointerId)
    },
    onPointerMove: (event) => {
      const current = drag.current
      if (!current) return
      const delta = current.y - event.clientY
      if (Math.abs(delta) > 6) current.moved = true
      if (current.moved) {
        const max = ref.current!.parentElement!.clientHeight
        setDragHeight(Math.max(max * 0.3, Math.min(max * 0.94, current.height + delta)))
      }
    },
    onPointerUp: (event) => finish(false, event.clientY),
    onPointerCancel: (event) => finish(true, event.clientY),
  }
  return { ref, snap, dragHeight, gripProps }
}
