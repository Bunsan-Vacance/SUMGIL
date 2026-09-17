import type { Mode } from './types'
export const modes: { id: Mode; label: string }[] = [
  { id: 'walk', label: '도보' },
  { id: 'bike', label: '따릉이' },
  { id: 'bus', label: '버스' },
  { id: 'subway', label: '지하철' },
]
