import type { ReactNode } from 'react'
import { useBottomSheet } from './useBottomSheet'

interface Props {
  children: ReactNode
  footer?: ReactNode
  compact?: boolean
}
export default function BottomSheet({ children, footer, compact = false }: Props) {
  const { ref, snap, dragHeight, gripProps } = useBottomSheet()
  return (
    <section
      ref={ref}
      className={`bottom-sheet ${compact ? 'compact-sheet' : ''} ${dragHeight ? 'dragging' : ''}`}
      data-snap={snap}
      style={dragHeight ? { height: dragHeight } : undefined}
      aria-label="경로 안내 패널"
    >
      <button className="sheet-grip" {...gripProps}>
        <span />
      </button>
      <div className="sheet-body">{children}</div>
      {footer && <div className="sheet-footer">{footer}</div>}
    </section>
  )
}
