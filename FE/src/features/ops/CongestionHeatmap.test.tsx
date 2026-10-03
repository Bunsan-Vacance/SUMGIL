// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import CongestionHeatmap, { slotLabel } from './CongestionHeatmap'
import type { CongestionHeatmap as Data } from './types'

afterEach(cleanup)

function build(): Data {
  const cells = []
  for (let slot = 10; slot <= 47; slot += 1) {
    cells.push(
      slot === 12
        ? { timeSlot: slot, level: null, nLinks: null, nFallback: null, maxLevel: null }
        : { timeSlot: slot, level: 95, nLinks: 20, nFallback: 2, maxLevel: 120 },
    )
  }
  return {
    date: '2026-10-03',
    source: 'congestion_pred',
    generatedAt: null,
    predictorVersions: [],
    slotFrom: 10,
    slotTo: 47,
    lines: [{ lineId: '2', lineName: '2호선', cells }],
  }
}

describe('혼잡도 히트맵', () => {
  it('슬롯 라벨을 HH:MM으로 만든다', () => {
    expect(slotLabel(10)).toBe('05:00')
    expect(slotLabel(17)).toBe('08:30')
    expect(slotLabel(47)).toBe('23:30')
  })

  it('호선당 38개 셀과 2슬롯마다 시각 헤더를 그린다', () => {
    const { container } = render(<CongestionHeatmap data={build()} />)
    expect(container.querySelectorAll('.ops-heat-cell')).toHaveLength(38)
    expect(screen.getByText('05:00')).toBeTruthy()
    expect(screen.queryByText('05:30')).toBeNull()
    expect(screen.getByText('06:00')).toBeTruthy()
  })

  it('값 없는 셀은 회색 클래스와 "–"로 구분한다', () => {
    const { container } = render(<CongestionHeatmap data={build()} />)
    const none = container.querySelectorAll('button.ops-heat-none')
    expect(none).toHaveLength(1)
    expect(none[0].textContent).toBe('–')
    expect(container.querySelectorAll('button.ops-heat-tone-3')).toHaveLength(37)
  })

  it('title과 aria-label에 상세를 담고 클릭하면 상태 영역에 보여준다', () => {
    render(<CongestionHeatmap data={build()} />)
    const cell = screen.getByLabelText(
      '2호선 05:00 · 혼잡도 95% · 링크 20 (보정 폴백 2) · 최대 120%',
    )
    expect(cell.getAttribute('title')).toBe(cell.getAttribute('aria-label'))
    fireEvent.click(cell)
    expect(screen.getByRole('status').textContent).toContain('혼잡도 95%')
  })

  it('범례를 표시한다', () => {
    render(<CongestionHeatmap data={build()} />)
    expect(screen.getByLabelText('범례').querySelectorAll('li')).toHaveLength(6)
  })
})
