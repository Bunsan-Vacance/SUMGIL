import { useState } from 'react'
import Modal from '../../components/Modal'
import { modes } from './constants'
import { modeIcons } from './ModeIcon'
import type { Mode } from './types'

export default function FilterDialog({
  enabled,
  onApply,
  onClose,
}: {
  enabled: Mode[]
  onApply: (modes: Mode[]) => void
  onClose: () => void
}) {
  const [draft, setDraft] = useState([...enabled])
  return (
    <Modal title="이동수단 선택" onClose={onClose}>
      <div className="mode-options">
        {modes.map((mode) => {
          const Icon = modeIcons[mode.id]
          return (
            <button
              key={mode.id}
              role="switch"
              aria-checked={draft.includes(mode.id)}
              onClick={() =>
                setDraft(
                  draft.includes(mode.id)
                    ? draft.filter((m) => m !== mode.id)
                    : [...draft, mode.id],
                )
              }
            >
              <span className="row">
                <Icon size={21} />
                {mode.label}
              </span>
              <span className={`switch ${draft.includes(mode.id) ? 'on' : ''}`} />
            </button>
          )
        })}
      </div>
      {!draft.length && (
        <p className="error" role="alert">
          이동수단을 하나 이상 선택해 주세요.
        </p>
      )}
      <button className="primary" disabled={!draft.length} onClick={() => onApply(draft)}>
        적용
      </button>
    </Modal>
  )
}
