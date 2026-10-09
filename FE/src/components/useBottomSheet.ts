import { useEffect, useRef, useState, type ButtonHTMLAttributes } from 'react'

type Snap = 'default' | 'expanded' | 'collapsed' | 'closed'
// 기억한 기본 높이가 없을 때 쓰는 기본 높이 비율(홈 시트 36%).
const DEFAULT_HEIGHT_RATIO = 0.36
// 끌어 놓은 높이가 기본 높이의 이 비율 미만이면 닫는다.
const DISMISS_RATIO = 0.5
export function useBottomSheet(
  initialSnap: Snap = 'default',
  preferredSnap?: Snap,
  options?: { collapsedHeight?: number; onDismiss?: () => void },
) {
  const [snap, setSnap] = useState<Snap>(initialSnap)
  const [dragHeight, setDragHeight] = useState<number | null>(null)
  const ref = useRef<HTMLElement>(null)
  const drag = useRef<{ y: number; height: number; moved: boolean } | null>(null)
  const suppressClick = useRef(false)
  const defaultHeight = useRef<number | null>(null)
  useEffect(() => {
    if (preferredSnap !== undefined) setSnap(preferredSnap)
  }, [preferredSnap])
  const finish = (cancelled: boolean, y: number) => {
    const current = drag.current
    if (!current) return
    if (!cancelled && current.moved) {
      const delta = current.y - y
      if (Math.abs(delta) > 28) {
        const dismissible =
          Boolean(options?.onDismiss) && (snap === 'default' || snap === 'collapsed')
        if (delta > 0) setSnap('expanded')
        else if (dismissible) {
          // 기본 높이의 절반 미만까지 끌어 내리면 닫고, 아니면 현재 스냅을 유지한다.
          const base =
            defaultHeight.current ?? ref.current!.parentElement!.clientHeight * DEFAULT_HEIGHT_RATIO
          if (current.height + delta < base * DISMISS_RATIO) {
            setSnap('closed')
            options?.onDismiss?.()
          }
        } else setSnap(snap === 'expanded' ? 'default' : 'collapsed')
      }
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
      // 접힘 → 기본 → 펼침 → 기본 순으로 순환한다.
      setSnap(snap === 'collapsed' ? 'default' : snap === 'default' ? 'expanded' : 'default')
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
      const height = ref.current!.getBoundingClientRect().height
      if (snap === 'default') defaultHeight.current = height
      drag.current = {
        y: event.clientY,
        height,
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
        setDragHeight(
          Math.max(options?.collapsedHeight ?? 0, Math.min(max * 0.94, current.height + delta)),
        )
      }
    },
    onPointerUp: (event) => finish(false, event.clientY),
    onPointerCancel: (event) => finish(true, event.clientY),
  }
  return { ref, snap, setSnap, dragHeight, gripProps }
}
