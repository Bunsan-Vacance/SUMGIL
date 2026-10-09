// @vitest-environment jsdom

import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CongestionBatch, CongestionBatchRepository } from '../../api/congestion'
import type { NearbyStation } from '../../api/contracts'
import { useNearbyStationCongestion } from './useNearbyStationCongestion'

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

const station = (stationId: string): NearbyStation => ({
  stationId,
  stationName: `역${stationId}`,
  lat: 37.5,
  lng: 127,
  distanceMeters: 100,
  lines: [{ lineId: '1002', lineName: '2호선' }],
})
const slot = (level: number | null) => ({
  departureTime: '2026-10-09T09:00:00',
  dowType: 0,
  timeSlot: 18,
  level,
  source: level === null ? null : 'stat',
  updatedAt: level === null ? null : '2026-10-01T03:00:00Z',
})
const batchOf = (levels: Record<string, number | null>): CongestionBatch => ({
  targetType: 'STATION',
  departureTimes: ['2026-10-09T09:00:00'],
  targets: Object.entries(levels).map(([targetId, level]) => ({ targetId, slots: [slot(level)] })),
})

const center = { lat: 37.5, lng: 127 }
const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(300)))

function repos(
  options: { stations?: NearbyStation[]; levels?: Record<string, number | null> } = {},
) {
  const nearby = vi.fn(
    async (_request: unknown, _signal: AbortSignal) =>
      options.stations ?? [station('A'), station('B'), station('C')],
  )
  const batch = vi.fn(async () => batchOf(options.levels ?? { A: 20, B: 85, C: null }))
  return {
    nearby,
    batch,
    stationRepo: { nearby },
    batchRepo: { batch } as CongestionBatchRepository,
  }
}

describe('주변 역 혼잡도 조회', () => {
  it('주변 역과 혼잡도를 합쳐 등급으로 바꾼다', async () => {
    const { nearby, batch, stationRepo, batchRepo } = repos()
    const { result } = renderHook(() =>
      useNearbyStationCongestion(center, true, stationRepo, batchRepo),
    )
    await flush()
    expect(result.current.status).toBe('ready')
    expect(result.current.stations.map((item) => [item.stationId, item.level, item.grade])).toEqual(
      [
        ['A', 20, 'RELAXED'],
        ['B', 85, 'CONGESTED'],
        ['C', null, null],
      ],
    )
    expect(nearby).toHaveBeenCalledWith(
      { lat: 37.5, lng: 127, radiusMeters: 1500, limit: 30 },
      expect.any(AbortSignal),
    )
    expect(batch).toHaveBeenCalledWith(
      { targetType: 'STATION', targetIds: ['A', 'B', 'C'] },
      expect.any(AbortSignal),
    )
  })

  it('혼잡도 조회가 실패하거나 저장소가 없으면 등급 없음으로 ready다', async () => {
    const failing = repos()
    failing.batch.mockRejectedValue(new Error('boom'))
    const first = renderHook(() =>
      useNearbyStationCongestion(center, true, failing.stationRepo, failing.batchRepo),
    )
    await flush()
    expect(first.result.current.status).toBe('ready')
    expect(first.result.current.stations.every((item) => item.grade === null)).toBe(true)

    const none = repos()
    const second = renderHook(() =>
      useNearbyStationCongestion(center, true, none.stationRepo, null),
    )
    await flush()
    expect(second.result.current.status).toBe('ready')
    expect(second.result.current.stations).toHaveLength(3)
    expect(second.result.current.stations[0].level).toBeNull()
  })

  it('역 조회가 실패하면 error이고 이전 목록을 유지한다', async () => {
    const { nearby, stationRepo, batchRepo } = repos()
    const { result, rerender } = renderHook(
      ({ lat }) => useNearbyStationCongestion({ lat, lng: 127 }, true, stationRepo, batchRepo),
      { initialProps: { lat: 37.5 } },
    )
    await flush()
    expect(result.current.stations).toHaveLength(3)
    nearby.mockRejectedValueOnce(new Error('boom'))
    rerender({ lat: 37.6 })
    await flush()
    expect(result.current.status).toBe('error')
    expect(result.current.stations).toHaveLength(3)
  })

  it('소수 3자리가 같은 중심으로는 다시 조회하지 않는다', async () => {
    const { nearby, stationRepo, batchRepo } = repos()
    const { rerender } = renderHook(
      ({ lat }) => useNearbyStationCongestion({ lat, lng: 127 }, true, stationRepo, batchRepo),
      { initialProps: { lat: 37.5001 } },
    )
    await flush()
    rerender({ lat: 37.5003 })
    await flush()
    expect(nearby).toHaveBeenCalledTimes(1)
    rerender({ lat: 37.52 })
    await flush()
    expect(nearby).toHaveBeenCalledTimes(2)
  })

  it('디바운스 안에 중심이 두 번 바뀌면 한 번만 조회한다', async () => {
    const { nearby, stationRepo, batchRepo } = repos()
    const { rerender } = renderHook(
      ({ lat }) => useNearbyStationCongestion({ lat, lng: 127 }, true, stationRepo, batchRepo),
      { initialProps: { lat: 37.5 } },
    )
    await act(async () => void (await vi.advanceTimersByTimeAsync(100)))
    rerender({ lat: 37.55 })
    await flush()
    expect(nearby).toHaveBeenCalledTimes(1)
    expect(nearby.mock.calls[0][0]).toMatchObject({ lat: 37.55 })
  })

  it('enabled가 꺼지면 진행 중 요청을 취소하고 목록은 유지한다', async () => {
    const signals: AbortSignal[] = []
    const stationRepo = {
      nearby: vi.fn(async (_request: unknown, signal: AbortSignal) => {
        signals.push(signal)
        return [station('A')]
      }),
    }
    const batchRepo = { batch: vi.fn(async () => batchOf({ A: 20 })) } as CongestionBatchRepository
    const { result, rerender } = renderHook(
      ({ enabled }) => useNearbyStationCongestion(center, enabled, stationRepo, batchRepo),
      { initialProps: { enabled: true } },
    )
    await flush()
    expect(result.current.stations).toHaveLength(1)
    rerender({ enabled: false })
    expect(result.current.stations).toHaveLength(1)
    rerender({ enabled: true })
    await flush()
    // 같은 위치라 재조회하지 않는다.
    expect(stationRepo.nearby).toHaveBeenCalledTimes(1)
  })

  it('조회 중 enabled가 꺼지면 signal을 abort한다', async () => {
    let captured: AbortSignal | undefined
    const stationRepo = {
      nearby: vi.fn((_request: unknown, signal: AbortSignal) => {
        captured = signal
        return new Promise<NearbyStation[]>(() => {})
      }),
    }
    const { rerender } = renderHook(
      ({ enabled }) => useNearbyStationCongestion(center, enabled, stationRepo, null),
      { initialProps: { enabled: true } },
    )
    await flush()
    rerender({ enabled: false })
    expect(captured?.aborted).toBe(true)
  })

  it('retry는 같은 위치도 다시 조회한다', async () => {
    const { nearby, stationRepo, batchRepo } = repos()
    const { result } = renderHook(() =>
      useNearbyStationCongestion(center, true, stationRepo, batchRepo),
    )
    await flush()
    act(() => result.current.retry())
    await flush()
    expect(nearby).toHaveBeenCalledTimes(2)
  })

  it('역이 없으면 빈 목록으로 ready다', async () => {
    const { batch, stationRepo, batchRepo } = repos({ stations: [] })
    const { result } = renderHook(() =>
      useNearbyStationCongestion(center, true, stationRepo, batchRepo),
    )
    await flush()
    expect(result.current.stations).toEqual([])
    expect(result.current.status).toBe('ready')
    expect(batch).not.toHaveBeenCalled()
  })
})
