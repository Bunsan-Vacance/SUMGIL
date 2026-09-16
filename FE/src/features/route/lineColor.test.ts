import { expect, it } from 'vitest'
import { lineColor } from './lineColor'

it('노선 ID와 구분점이 있는 노선명을 같은 색으로 표시하고 다른 이동수단은 유지한다', () => {
  const leg = { mode: 'subway' as const, title: '', note: '', minutes: 1 }
  const colors = [
    '#0052A4',
    '#00A84D',
    '#EF7C1C',
    '#00A5DE',
    '#996CAC',
    '#CD7C2F',
    '#747F00',
    '#E6186C',
    '#BDB092',
  ]
  colors.forEach((color, index) =>
    expect(lineColor({ ...leg, routeId: String(1001 + index) })).toBe(color),
  )
  expect(lineColor({ ...leg, note: '경의·중앙선' })).toBe('#77C4A3')
  expect(lineColor({ ...leg, note: '수인·분당선' })).toBe('#F5A200')
  expect(lineColor({ ...leg, mode: 'walk', note: '2호선', transfer: true })).toBeUndefined()
  expect(lineColor(leg)).toBeUndefined()
})
