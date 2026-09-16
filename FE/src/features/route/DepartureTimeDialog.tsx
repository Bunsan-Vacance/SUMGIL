import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'
import Modal from '../../components/Modal'
import './DepartureTimeDialog.css'

const HOURS = Array.from({ length: 24 }, (_, index) => String(index).padStart(2, '0'))
const MINUTES = Array.from({ length: 60 }, (_, index) => String(index).padStart(2, '0'))
const ITEM_HEIGHT = 52

function isTime(value: string) {
  return /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value)
}

function currentSeoulTime() {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date())
  const valueOf = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value
  return `${valueOf('hour') || '00'}:${valueOf('minute') || '00'}`
}

function Wheel({
  label,
  values,
  value,
  onChange,
}: {
  label: string
  values: string[]
  value: string
  onChange: (value: string) => void
}) {
  const wheel = useRef<HTMLDivElement>(null)
  const idPrefix = useId()
  const selectedIndex = Math.max(0, values.indexOf(value))

  useLayoutEffect(() => {
    if (wheel.current) wheel.current.scrollTop = selectedIndex * ITEM_HEIGHT
  }, [])

  const selectIndex = (index: number) => {
    onChange(values[index])
    if (wheel.current) wheel.current.scrollTop = index * ITEM_HEIGHT
  }

  const move = (offset: number) => {
    const nextIndex = Math.min(values.length - 1, Math.max(0, selectedIndex + offset))
    selectIndex(nextIndex)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      move(1)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      move(-1)
    } else if (event.key === 'Home') {
      event.preventDefault()
      selectIndex(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      selectIndex(values.length - 1)
    }
  }

  return (
    <div className="departure-time-wheel-wrap">
      <span className="departure-time-wheel-label">{label}</span>
      <div
        ref={wheel}
        className="departure-time-wheel"
        role="listbox"
        tabIndex={0}
        aria-label={`${label} 선택`}
        aria-activedescendant={`${idPrefix}-${value}`}
        onKeyDown={onKeyDown}
        onScroll={(event) => {
          const index = Math.min(
            values.length - 1,
            Math.max(0, Math.round(event.currentTarget.scrollTop / ITEM_HEIGHT)),
          )
          if (values[index] !== value) onChange(values[index])
        }}
      >
        {values.map((option) => (
          <button
            key={option}
            id={`${idPrefix}-${option}`}
            type="button"
            role="option"
            tabIndex={-1}
            aria-selected={option === value}
            onClick={() => selectIndex(values.indexOf(option))}
          >
            {option}
          </button>
        ))}
      </div>
      <span className="departure-time-wheel-selection" aria-hidden="true" />
    </div>
  )
}

export interface DepartureTimeDialogProps {
  initialValue: string
  onApply: (value: string) => void
  onClose: () => void
}

export default function DepartureTimeDialog({
  initialValue,
  onApply,
  onClose,
}: DepartureTimeDialogProps) {
  const initial = isTime(initialValue) ? initialValue : currentSeoulTime()
  const [hour, setHour] = useState(initial.slice(0, 2))
  const [minute, setMinute] = useState(initial.slice(3, 5))

  return (
    <Modal title="출발 시간" onClose={onClose}>
      <p className="section-label departure-time-help">오늘 출발할 시간을 선택하세요.</p>
      <div className="departure-time-wheels" aria-label="출발 시간 선택">
        <Wheel label="시" values={HOURS} value={hour} onChange={setHour} />
        <span className="departure-time-colon" aria-hidden="true">
          :
        </span>
        <Wheel label="분" values={MINUTES} value={minute} onChange={setMinute} />
      </div>
      <div className="modal-actions departure-time-actions">
        <button type="button" className="secondary" onClick={onClose}>
          취소
        </button>
        <button type="button" className="primary" onClick={() => onApply(`${hour}:${minute}`)}>
          적용
        </button>
      </div>
    </Modal>
  )
}
