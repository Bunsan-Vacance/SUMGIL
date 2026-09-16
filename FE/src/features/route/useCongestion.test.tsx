// @vitest-environment jsdom

import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CongestionRepository } from '../../api/congestion'
import { useRouteCongestion } from './useCongestion'

const mocked = vi.hoisted(() => ({ repository: null as CongestionRepository | null }))
vi.mock('../../api/congestion', () => ({
  get congestionRepository() {
    return mocked.repository
  },
}))

afterEach(() => {
  cleanup()
  mocked.repository = null
  vi.restoreAllMocks()
})

describe('경로 구간 혼잡도', () => {
  it('지하철 구간의 출발 역 ID로 조회하고 준비중 상태를 유지한다', async () => {
    const repository: CongestionRepository = {
      get: vi.fn().mockResolvedValue({
        targetType: 'STATION',
        targetId: '0221',
        dowType: 0,
        timeSlot: 18,
        level: 72.5,
        source: 'stat',
        updatedAt: '2026-09-15T00:00:00+09:00',
      }),
    }
    mocked.repository = repository
    const legs = [
      { mode: 'walk' as const, title: '출발 → 역삼', note: '도보', minutes: 2 },
      {
        mode: 'subway' as const,
        title: '역삼 → 선릉',
        note: '2호선',
        minutes: 3,
        from: { id: '0221', name: '역삼' },
      },
    ]
    const { result } = renderHook(() => useRouteCongestion(legs, '2026-09-15T00:00:00.000Z'))

    await waitFor(() => expect(result.current.some((item) => item.status === 'ready')).toBe(true))
    expect(repository.get).toHaveBeenCalledWith(
      'STATION',
      '0221',
      '2026-09-15T00:00:00.000Z',
      expect.any(AbortSignal),
    )
  })

  it('조회 실패와 대상 없는 구간은 모두 준비중으로 표시한다', async () => {
    const repository: CongestionRepository = {
      get: vi.fn().mockRejectedValue(new Error('temporary failure')),
    }
    mocked.repository = repository
    const legs = [
      { mode: 'walk' as const, title: 'A → B', note: '도보', minutes: 2 },
      {
        mode: 'subway' as const,
        title: 'B → C',
        note: '2호선',
        minutes: 3,
        from: { id: '0221', name: 'B' },
      },
    ]
    const { result } = renderHook(() => useRouteCongestion(legs))

    await waitFor(() =>
      expect(result.current).toEqual([{ status: 'unavailable' }, { status: 'unavailable' }]),
    )
    expect(result.current).toEqual([{ status: 'unavailable' }, { status: 'unavailable' }])
  })
})
