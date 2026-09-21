import { useEffect, useRef } from 'react'

export function useScrollbarVisibility<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const hideTimer = useRef<number | null>(null)

  useEffect(() => {
    const element = ref.current
    if (!element) return

    const showScrollbar = () => {
      element.classList.add('scrollbar-visible')
      if (hideTimer.current !== null) window.clearTimeout(hideTimer.current)
      hideTimer.current = window.setTimeout(() => {
        element.classList.remove('scrollbar-visible')
        hideTimer.current = null
      }, 700)
    }

    element.addEventListener('scroll', showScrollbar, { passive: true })
    return () => {
      element.removeEventListener('scroll', showScrollbar)
      if (hideTimer.current !== null) window.clearTimeout(hideTimer.current)
      hideTimer.current = null
      element.classList.remove('scrollbar-visible')
    }
  }, [])

  return ref
}
