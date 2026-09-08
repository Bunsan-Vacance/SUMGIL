import type { ReactNode } from 'react'
import { useBottomSheet } from './useBottomSheet'

type Snap = 'default' | 'expanded' | 'collapsed'
interface Props {
  children: ReactNode
  footer?: ReactNode
  compact?: boolean
  ariaLabel?: string
  initialSnap?: Snap
  preferredSnap?: Snap
}
export default function BottomSheet({
  children,
  footer,
  compact = false,
  ariaLabel = '경로 안내 패널',
  initialSnap = 'default',
  preferredSnap,
}: Props) {
  const { ref, snap, dragHeight, gripProps } = useBottomSheet(initialSnap, preferredSnap)
  return (
    <section
      ref={ref}
      className={`bottom-sheet ${compact ? 'compact-sheet' : ''} ${dragHeight ? 'dragging' : ''}`}
      data-snap={snap}
      style={dragHeight ? { height: dragHeight } : undefined}
      aria-label={ariaLabel}
    >
      <button className="sheet-grip" {...gripProps}>
        <span />
      </button>
      <div className="sheet-body">{children}</div>
      {footer && <div className="sheet-footer">{footer}</div>}
    </section>
  )
}
