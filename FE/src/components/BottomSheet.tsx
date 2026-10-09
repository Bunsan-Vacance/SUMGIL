import { type ReactNode } from 'react'
import { useBottomSheet } from './useBottomSheet'
import { useScrollbarVisibility } from './useScrollbarVisibility'

type Snap = 'default' | 'expanded' | 'collapsed' | 'closed'
type SheetChildren = ReactNode | ((api: { snap: Snap; setSnap: (snap: Snap) => void }) => ReactNode)
interface Props {
  children: SheetChildren
  footer?: ReactNode
  compact?: boolean
  ariaLabel?: string
  initialSnap?: Snap
  preferredSnap?: Snap
  draggable?: boolean
  className?: string
  collapsedHeight?: number
  onDismiss?: () => void
}
export default function BottomSheet({
  children,
  footer,
  compact = false,
  ariaLabel = '경로 안내 패널',
  initialSnap = 'default',
  preferredSnap,
  draggable = true,
  className = '',
  collapsedHeight,
  onDismiss,
}: Props) {
  const { ref, snap, setSnap, dragHeight, gripProps } = useBottomSheet(initialSnap, preferredSnap, {
    collapsedHeight,
    onDismiss,
  })
  const bodyRef = useScrollbarVisibility<HTMLDivElement>()
  return (
    <section
      ref={ref}
      className={`bottom-sheet ${className} ${compact ? 'compact-sheet' : ''} ${dragHeight !== null ? 'dragging' : ''}`}
      data-snap={snap}
      style={dragHeight !== null ? { height: dragHeight } : undefined}
      aria-hidden={snap === 'closed' ? true : undefined}
      aria-label={ariaLabel}
    >
      {draggable && (
        <button className="sheet-grip" tabIndex={snap === 'closed' ? -1 : undefined} {...gripProps}>
          <span />
        </button>
      )}
      <div ref={bodyRef} className="sheet-body scrollbar-auto">
        {typeof children === 'function' ? children({ snap, setSnap }) : children}
      </div>
      {footer && <div className="sheet-footer">{footer}</div>}
    </section>
  )
}
