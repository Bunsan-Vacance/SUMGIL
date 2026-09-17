// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import { RepositoryError } from './errors'
import {
  createBackendGuidanceRepository,
  mockGuidanceRepository,
  type ReplanRequest,
} from './guidance'
import { places, routes } from './mock/fixtures'

afterEach(() => {
  vi.unstubAllGlobals()
})

const request: ReplanRequest = {
  currentRoute: routes[0],
  step: 0,
  currentBoundary: { id: 'origin-node', name: '출발 지점' },
  currentLeg: { mode: 'walk', from: { id: 'origin-node' }, to: { id: 'next-node' } },
  destination: places[1],
  conditions: {
    modes: ['walk', 'subway'],
    priority: 'fast',
    requestedAt: '2026-09-17T09:00:00+09:00',
  },
}

describe('guidance repository', () => {
  it('도착 후보의 식별자·방향·시각·출처를 검증하고 요청 query를 보낸다', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        data: [
          {
            trainId: 'train-1',
            direction: '성수 방면',
            arrivalTime: '2026-09-17T09:42:00+09:00',
            updatedAt: '2026-09-17T09:39:00+09:00',
            source: 'LIVE',
          },
        ],
      }),
    }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      createBackendGuidanceRepository('http://be.test').arrivals(
        { stationId: '221', routeId: '1002', routeName: '2호선' },
        new AbortController().signal,
      ),
    ).resolves.toMatchObject([{ trainId: 'train-1', source: 'LIVE' }])
    expect(fetchMock).toHaveBeenCalledWith(
      'http://be.test/api/transit/arrivals?stationId=221&routeId=1002',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('시간대가 없는 도착 시각은 빈 결과로 숨기지 않고 invalid-response로 거부한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          data: [
            {
              trainId: 'train-1',
              direction: '성수 방면',
              arrivalTime: '2026-09-17T09:42:00',
              updatedAt: '2026-09-17T09:39:00+09:00',
              source: 'LIVE',
            },
          ],
        }),
      })),
    )

    await expect(
      createBackendGuidanceRepository('http://be.test').arrivals(
        { stationId: '221', routeId: '1002' },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'invalid-response' })
  })

  it('재탐색은 최소 안내 정보와 조건을 보내고 빈 후보를 성공으로 반환한다', async () => {
    const fetchMock = vi.fn(async (_url, init) => {
      expect(JSON.parse(String(init?.body))).toMatchObject({
        currentRoute: { id: routes[0].id },
        step: 0,
        currentBoundary: request.currentBoundary,
        destination: {
          name: request.destination.name,
        },
        conditions: request.conditions,
      })
      return { ok: true, status: 200, json: async () => ({ success: true, data: [] }) }
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      createBackendGuidanceRepository('http://be.test').replan(
        request,
        new AbortController().signal,
      ),
    ).resolves.toEqual([])
    expect(fetchMock).toHaveBeenCalledWith(
      'http://be.test/api/routes/replan',
      expect.objectContaining({ method: 'POST', signal: expect.any(AbortSignal) }),
    )
  })

  it('재탐색 후보의 잔여 시간과 경계가 현재 요청과 맞지 않으면 거부한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          data: [
            {
              reason: '검증용 후보',
              source: 'ALGORITHM',
              route: {
                routeType: 'ALTERNATIVE',
                totalMinutes: 10,
                source: 'ALGORITHM',
                legs: [
                  {
                    mode: 'WALK',
                    minutes: 6,
                    fromNodeId: 'origin-node',
                    toNodeId: 'dogok',
                  },
                ],
              },
            },
          ],
        }),
      })),
    )

    await expect(
      createBackendGuidanceRepository('http://be.test').replan(
        { ...request, destination: { ...places[1], stationId: 'dogok' } },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject<Partial<RepositoryError>>({ code: 'invalid-response' })
  })

  it('mock 재탐색은 현재 경계와 목적지로 연결된 다른 잔여 후보를 반환한다', async () => {
    const result = await mockGuidanceRepository.replan(request, new AbortController().signal)
    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({ source: 'MOCK', route: { id: 'fast-replan' } })
    expect(result[0].route.legs[0].from).toEqual(request.currentBoundary)
    expect(result[0].route.legs.at(-1)?.to?.id).toBe(places[1].id)
    expect(result[0].route.minutes).toBeGreaterThan(routes[0].minutes)
  })
})
