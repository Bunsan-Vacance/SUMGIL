import { type ReactNode } from 'react'
import { useBottomSheet } from './useBottomSheet'
import { useScrollbarVisibility } from './useScrollbarVisibility'

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
  const bodyRef = useScrollbarVisibility<HTMLDivElement>()
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
      <div ref={bodyRef} className="sheet-body scrollbar-auto">
        {children}
      </div>
      {footer && <div className="sheet-footer">{footer}</div>}
    </section>
  )
}
