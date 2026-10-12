// @vitest-environment jsdom

import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RouteRepository } from '../../api/contracts'
import { useDepartureAlternatives } from './useDepartureAlternatives'
import type { Leg, Mode, Place, Priority, Route } from './types'

const place = (id: string): Place => ({ id, name: id, address: '', kind: 'place' })
const leg: Leg = {
  mode: 'subway',
  title: 'A → B',
  note: '2호선',
  routeId: '1002',
  minutes: 10,
  from: { id: 'A', name: 'A' },
  to: { id: 'B', name: 'B' },
}

function route(id: string, minutes: number, percent: number): Route {
  return {
    id,
    label: id,
    minutes,
    transfers: 0,
    modes: ['subway'],
    legs: [leg],
    departedAt: new Date().toISOString(),
    congestionPrediction: {
      congestionPercent: percent,
      congestionGrade: null,
      dataStatus: 'AVAILABLE',
      predictionBasis: null,
    },
  }
}

const crowded = route('base', 30, 120)
const calm = route('calm', 40, 30)
const departedAt = '2026-10-12T18:40:00+09:00'

interface Props {
  base: Route
  origin: Place
  destination: Place
  modes: Mode[]
  priority: Priority
  departedAt: string
  enabled: boolean
  repository: RouteRepository
}

const propsFor = (search: RouteRepository['search'], overrides: Partial<Props> = {}): Props => ({
  base: crowded,
  origin: place('o'),
  destination: place('d'),
  modes: ['subway'],
  priority: 'fast',
  departedAt,
  enabled: true,
  repository: { search },
  ...overrides,
})

function setup(search: RouteRepository['search'], overrides: Partial<Props> = {}) {
  return renderHook((props: Props) => useDepartureAlternatives(props), {
    initialProps: propsFor(search, overrides),
  })
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe('useDepartureAlternatives', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('600ms 전에는 호출하지 않고 이후 두 오프셋을 조회한다', async () => {
    const search = vi.fn().mockResolvedValue([calm])
    const { result } = setup(search)
    await advance(599)
    expect(search).not.toHaveBeenCalled()
    await advance(1)
    expect(search).toHaveBeenCalledTimes(2)
    const sent = search.mock.calls.map(([request]) => request.departedAt).sort()
    expect(sent).toEqual([
      new Date('2026-10-12T18:50:00+09:00').toISOString(),
      new Date('2026-10-12T19:00:00+09:00').toISOString(),
    ])
    expect(search.mock.calls[0][0].modes).toEqual(['walk', 'subway'])
    expect(result.current.suggestion).toMatchObject({ offsetMin: 10, toGrade: 'RELAXED' })
  })

  it('같은 입력으로 재렌더해도 추가 호출이 없다', async () => {
    const search = vi.fn().mockResolvedValue([calm])
    const { rerender, result } = setup(search)
    await advance(600)
    rerender(propsFor(search, { base: { ...crowded } }))
    await advance(600)
    expect(search).toHaveBeenCalledTimes(2)
    expect(result.current.suggestion).not.toBeNull()
  })

  it('입력이 바뀌면 진행 중 요청을 abort한다', async () => {
    const signals: AbortSignal[] = []
    const search = vi.fn((_request: unknown, signal: AbortSignal) => {
      signals.push(signal)
      return new Promise<Route[]>(() => {})
    })
    const { rerender } = setup(search)
    await advance(600)
    expect(signals).toHaveLength(2)
    rerender(propsFor(search, { destination: place('d2') }))
    expect(signals.every((signal) => signal.aborted)).toBe(true)
  })

  it('한 오프셋이 실패해도 나머지로 제안한다', async () => {
    const search = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce([calm])
    const { result } = setup(search)
    await advance(600)
    expect(result.current.suggestion).not.toBeNull()
  })

  it('모두 실패하면 제안이 없다', async () => {
    const search = vi.fn().mockRejectedValue(new Error('boom'))
    const { result } = setup(search)
    await advance(600)
    expect(result.current.suggestion).toBeNull()
  })

  it('기준이 여유면 호출하지 않는다', async () => {
    const search = vi.fn().mockResolvedValue([calm])
    const { result } = setup(search, { base: route('base', 30, 30) })
    await advance(600)
    expect(search).not.toHaveBeenCalled()
    expect(result.current.suggestion).toBeNull()
  })

  it('enabled가 false면 호출하지 않는다', async () => {
    const search = vi.fn().mockResolvedValue([calm])
    setup(search, { enabled: false })
    await advance(600)
    expect(search).not.toHaveBeenCalled()
  })

  it('캐시에 모두 있으면 지연·호출 없이 즉시 제안한다', async () => {
    const search = vi.fn().mockResolvedValue([calm])
    const { rerender, result } = setup(search)
    await advance(600)
    rerender(propsFor(search, { enabled: false }))
    expect(result.current.suggestion).toBeNull()
    rerender(propsFor(search))
    expect(result.current.suggestion).not.toBeNull()
    expect(search).toHaveBeenCalledTimes(2)
  })
})
