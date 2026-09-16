import type { Leg } from './types'

const LINES = [
  ['1001', '1호선', '#0052A4'],
  ['1002', '2호선', '#00A84D'],
  ['1003', '3호선', '#EF7C1C'],
  ['1004', '4호선', '#00A5DE'],
  ['1005', '5호선', '#996CAC'],
  ['1006', '6호선', '#CD7C2F'],
  ['1007', '7호선', '#747F00'],
  ['1008', '8호선', '#E6186C'],
  ['1009', '9호선', '#BDB092'],
  ['1063', '경의중앙선', '#77C4A3'],
  ['1075', '수인분당선', '#F5A200'],
] as const

export function lineColor(leg: Leg) {
  if (leg.mode !== 'subway' || leg.transfer) return undefined
  const name = `${leg.note} ${leg.title}`.replace(/[·ㆍ\s]/g, '')
  return (
    LINES.find(([id]) => id === leg.routeId)?.[2] ??
    LINES.find(([, line]) => name.includes(line))?.[2]
  )
}

export function lineTextColor(leg: Leg) {
  const color = lineColor(leg)
  if (!color) return undefined
  return ['#0052A4', '#996CAC', '#E6186C'].includes(color) ? '#fff' : '#17212b'
}
