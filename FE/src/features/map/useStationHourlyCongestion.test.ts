// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CongestionBatch, CongestionBatchRepository } from '../../api/congestion'
import { hourlyDepartureTimes, useStationHourlyCongestion } from './useStationHourlyCongestion'

afterEach(cleanup)

// 서울 2026-10-09 18:37 = UTC 09:37
const seoul1837 = () => new Date('2026-10-09T09:37:00.000Z')

const batchOf = (levels: Array<number | null>, times: string[]): CongestionBatch => ({
  targetType: 'STATION',
  departureTimes: times,
  targets: [
    {
      targetId: '222',
      slots: levels.map((level, index) => ({
        departureTime: times[index],
        dowType: 0,
        timeSlot: 0,
        level,
        source: level === null ? null : 'stat',
        updatedAt: null,
      })),
    },
  ],
})

describe('시간대별 요청 시각', () => {
  it('서울 정시로 내려 지난 1시간부터 4시간 뒤까지 만든다', () => {
    const times = hourlyDepartureTimes(seoul1837())
    expect(times).toEqual([
      '2026-10-09T08:00:00.000Z',
      '2026-10-09T09:00:00.000Z',
      '2026-10-09T10:00:00.000Z',
      '2026-10-09T11:00:00.000Z',
      '2026-10-09T12:00:00.000Z',
      '2026-10-09T13:00:00.000Z',
    ])
    // 서울 17시~22시
    expect(
      times.map((time) => new Date(new Date(time).getTime() + 9 * 3600000).getUTCHours()),
    ).toEqual([17, 18, 19, 20, 21, 22])
  })

  it('자정을 넘기면 시를 24로 나눈 값으로 표시한다', async () => {
    // 서울 23:10 = UTC 14:10
    const now = () => new Date('2026-10-09T14:10:00.000Z')
    const times = hourlyDepartureTimes(now())
    const repository: CongestionBatchRepository = {
      batch: vi.fn(async () => batchOf([10, 20, 30, 40, 50, 60], times)),
    }
    const { result } = renderHook(() => useStationHourlyCongestion('222', repository, now))
    await waitFor(() => expect(result.current.status).toBe('success'))
    expect(result.current.bars.map((bar) => bar.hour)).toEqual([22, 23, 0, 1, 2, 3])
    expect(result.current.bars.map((bar) => bar.label)).toEqual([
      '22시',
      '지금',
      '0시',
      '1시',
      '2시',
      '3시',
    ])
  })
})

describe('역 시간대별 혼잡도 조회', () => {
  it('막대 6개를 만들고 null을 보존한다', async () => {
    const times = hourlyDepartureTimes(seoul1837())
    const batch = vi.fn(async () => batchOf([20, 85, null, 45, 110, 30], times))
    const { result } = renderHook(() =>
      useStationHourlyCongestion('222', { batch } as CongestionBatchRepository, seoul1837),
    )
    await waitFor(() => expect(result.current.status).toBe('success'))
    expect(result.current.bars).toHaveLength(6)
    expect(result.current.bars[1]).toMatchObject({ label: '지금', level: 85, grade: 'CONGESTED' })
    expect(result.current.bars[2]).toMatchObject({ level: null, grade: null, label: '19시' })
    expect(result.current.bars[4].grade).toBe('SATURATED')
    expect(batch).toHaveBeenCalledWith(
      { targetType: 'STATION', targetIds: ['222'], departureTimes: times },
      expect.any(AbortSignal),
    )
  })

  it('역 ID나 저장소가 없으면 unavailable이고 요청하지 않는다', () => {
    const batch = vi.fn()
    const noStation = renderHook(() =>
      useStationHourlyCongestion(null, { batch } as unknown as CongestionBatchRepository),
    )
    expect(noStation.result.current.status).toBe('unavailable')
    const noRepository = renderHook(() => useStationHourlyCongestion('222', null))
    expect(noRepository.result.current.status).toBe('unavailable')
    expect(batch).not.toHaveBeenCalled()
  })

  it('조회가 실패하면 error이고 retry로 다시 조회한다', async () => {
    const times = hourlyDepartureTimes(seoul1837())
    const batch = vi
      .fn()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValue(batchOf([20, 20, 20, 20, 20, 20], times))
    const { result } = renderHook(() =>
      useStationHourlyCongestion('222', { batch } as CongestionBatchRepository, seoul1837),
    )
    await waitFor(() => expect(result.current.status).toBe('error'))
    act(() => result.current.retry())
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current.status).toBe('success'))
    expect(batch).toHaveBeenCalledTimes(2)
  })

  it('역이 바뀌면 이전 요청을 취소하고 늦은 응답을 무시한다', async () => {
    const times = hourlyDepartureTimes(seoul1837())
    let resolveFirst!: (value: CongestionBatch) => void
    const signals: AbortSignal[] = []
    const batch = vi.fn((request: { targetIds: string[] }, signal: AbortSignal) => {
      signals.push(signal)
      if (request.targetIds[0] === 'A') {
        return new Promise<CongestionBatch>((resolve) => {
          resolveFirst = resolve
        })
      }
      return Promise.resolve(batchOf([90, 90, 90, 90, 90, 90], times))
    })
    const { result, rerender } = renderHook(
      ({ id }) => useStationHourlyCongestion(id, { batch } as CongestionBatchRepository, seoul1837),
      { initialProps: { id: 'A' } },
    )
    rerender({ id: 'B' })
    expect(signals[0].aborted).toBe(true)
    await waitFor(() => expect(result.current.status).toBe('success'))
    await act(async () => resolveFirst(batchOf([10, 10, 10, 10, 10, 10], times)))
    expect(result.current.bars[0].level).toBe(90)
  })
})
