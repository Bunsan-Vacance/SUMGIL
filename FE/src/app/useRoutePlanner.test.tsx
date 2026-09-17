// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RouteRepository } from '../api/contracts'
import type { GuidanceRepository, ReplanProposal } from '../api/guidance'
import { places, routes } from '../api/mock/fixtures'
import { useRoutePlanner } from './useRoutePlanner'

const repository: RouteRepository = { search: async () => routes }

afterEach(cleanup)

describe('경로와 안내 화면의 수명', () => {
  beforeEach(() => history.replaceState(null, '', '#home'))

  const renderLoadedPlanner = async (guidanceApi?: GuidanceRepository) => {
    const rendered = renderHook(() => useRoutePlanner(repository, guidanceApi))
    act(() => rendered.result.current.findRoutes(places[1]))
    await waitFor(() => expect(rendered.result.current.trip.status).toBe('success'))
    return rendered
  }

  it('안내 중 뒤로 갔다가 다시 돌아와도 단계와 열차 선택을 유지한다', async () => {
    const { result } = await renderLoadedPlanner()
    act(() => result.current.startGuide())
    act(() => {
      result.current.guidance.next()
      result.current.guidance.setTrain('09:42')
    })

    act(() => history.back())
    await waitFor(() => expect(result.current.screen).toBe('results'))
    expect(result.current.guidance).toMatchObject({ step: 1, train: '09:42', route: routes[0] })

    act(() => history.forward())
    await waitFor(() => expect(result.current.screen).toBe('guide'))
    expect(result.current.guidance).toMatchObject({ step: 1, train: '09:42', route: routes[0] })
  })

  it('새 검색과 필터 및 경로 선택과 출발지 변경은 활성 안내 세션을 끝내지 않는다', async () => {
    const { result } = await renderLoadedPlanner()
    act(() => result.current.startGuide())
    act(() => result.current.guidance.next())

    act(() => result.current.findRoutes(places[2]))
    await waitFor(() => expect(result.current.trip.status).toBe('success'))
    act(() => result.current.applyFilter(['walk', 'subway']))
    await waitFor(() => expect(result.current.trip.status).toBe('success'))
    act(() => result.current.selectRoute(routes[1].id))

    expect(result.current.trip.selected).toBe(routes[1])
    expect(result.current.guidance).toMatchObject({ route: routes[0], step: 1 })
    expect(result.current.guidance.destination).toBe(places[1])

    act(() => result.current.openSearch('origin'))
    act(() => result.current.choosePlace(places[3]))
    await waitFor(() => expect(result.current.trip.status).toBe('success'))
    act(() => result.current.applyFilter(['bike']))
    await waitFor(() => expect(result.current.trip.status).toBe('success'))
    expect(result.current.trip).toMatchObject({
      status: 'success',
      origin: places[3],
      destination: places[2],
      selected: null,
    })
    expect(result.current.guidance).toMatchObject({ route: routes[0], step: 1 })

    act(() => result.current.resumeGuide())
    expect(result.current.screen).toBe('guide')
    expect(result.current.guidance).toMatchObject({ route: routes[0], step: 1 })
  })

  it('같은 여행의 같은 경로 시작은 진행 상태를 유지한 채 안내로 복귀한다', async () => {
    const { result } = await renderLoadedPlanner()
    act(() => result.current.startGuide())
    act(() => {
      result.current.guidance.next()
      result.current.guidance.setTrain('09:42')
      result.current.go('detail')
    })

    act(() => result.current.startGuide())

    expect(result.current.screen).toBe('guide')
    expect(result.current.modal).toBeNull()
    expect(result.current.guidance).toMatchObject({ step: 1, train: '09:42', route: routes[0] })
  })

  it('다른 경로 시작은 확인 전까지 기존 안내를 보존하고 확인 후 교체한다', async () => {
    const { result } = await renderLoadedPlanner()
    act(() => result.current.startGuide())
    act(() => result.current.guidance.next())
    act(() => {
      result.current.go('results')
      result.current.selectRoute(routes[1].id)
    })

    act(() => result.current.startGuide())
    expect(result.current.modal).toBe('replace-guide')
    expect(result.current.guidance).toMatchObject({ route: routes[0], step: 1 })

    act(() => result.current.confirmReplacement())
    expect(result.current.screen).toBe('guide')
    expect(result.current.modal).toBeNull()
    expect(result.current.guidance).toMatchObject({
      route: routes[1],
      step: 0,
      train: null,
      destination: places[1],
    })
  })

  it('명시적으로 종료한 안내는 과거 안내 URL에서도 되살아나지 않는다', async () => {
    const { result } = await renderLoadedPlanner()
    act(() => result.current.startGuide())
    act(() => result.current.exitGuide())

    expect(result.current.guidance.route).toBeNull()
    act(() => {
      history.replaceState(null, '', '#guide')
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    await waitFor(() => expect(result.current.screen).toBe('detail'))
    expect(location.hash).toBe('#detail')
  })

  it('검색 목적지가 바뀐 뒤 도착해도 시작 당시 목적지 스냅샷을 표시한다', async () => {
    const { result } = await renderLoadedPlanner()
    act(() => result.current.startGuide())
    act(() => result.current.findRoutes(places[2]))
    await waitFor(() => expect(result.current.trip.destination).toBe(places[2]))
    act(() => result.current.resumeGuide())

    for (let step = 0; step < routes[0].legs.length; step += 1) {
      act(() => result.current.advance())
    }

    expect(result.current.screen).toBe('arrival')
    expect(result.current.guidance.completed).toBe(true)
    expect(result.current.destinationName).toBe(places[1].name)
    expect(result.current.guidance.destination).toBe(places[1])
  })

  it('출발지 변경 뒤 현재 탐색의 과거 상세 URL은 결과로 보정한다', async () => {
    const { result } = await renderLoadedPlanner()
    act(() => result.current.openSearch('origin'))
    act(() => result.current.choosePlace(places[2]))
    expect(result.current.trip.selected).toBeNull()

    act(() => {
      history.replaceState(null, '', '#detail')
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    await waitFor(() => expect(result.current.screen).toBe('results'))
    expect(location.hash).toBe('#results')
  })

  it('결과 화면에서 검색을 취소하면 기존 결과 화면과 경로를 보존한다', async () => {
    const { result } = await renderLoadedPlanner()

    act(() => result.current.openSearch('destination'))
    expect(result.current.screen).toBe('search')
    act(() => result.current.cancelSearch())

    expect(result.current.screen).toBe('results')
    expect(result.current.trip.status).toBe('success')
    expect(result.current.trip.destination).toBe(places[1])
    expect(result.current.trip.selected).toBe(routes[0])
    expect(result.current.trip.visible.length).toBeGreaterThan(0)
  })

  it('결과 화면에서 경로 입력으로 돌아가면 위치와 입력 패널을 유지한다', async () => {
    const { result } = await renderLoadedPlanner()
    const origin = result.current.trip.origin
    const destination = result.current.trip.destination

    act(() => result.current.returnToRouteInput())

    expect(result.current.screen).toBe('home')
    expect(result.current.routePanelOpen).toBe(true)
    expect(result.current.trip.origin).toBe(origin)
    expect(result.current.trip.destination).toBe(destination)
  })

  it('홈에서 검색을 취소하면 홈으로 돌아간다', async () => {
    const { result } = await renderLoadedPlanner()

    act(() => result.current.go('home'))
    act(() => result.current.openSearch('destination'))
    act(() => result.current.cancelSearch())

    expect(result.current.screen).toBe('home')
  })

  it('장소 탐색을 나갔다 돌아와도 기존 여행 상태를 보존한다', async () => {
    const { result } = await renderLoadedPlanner()
    const destination = result.current.trip.destination

    act(() => result.current.openBrowse())
    expect(result.current.screen).toBe('browse')
    act(() => result.current.go('home'))

    expect(result.current.trip.destination).toBe(destination)
    expect(result.current.trip.status).toBe('success')
  })

  it('결과 화면에서 교환하면 새 좌표로 재조회하고 안내 세션은 유지한다', async () => {
    const search = vi.fn(
      async (_request: Parameters<RouteRepository['search']>[0], _signal: AbortSignal) => routes,
    )
    const { result } = renderHook(() => useRoutePlanner({ search }))
    act(() => result.current.findRoutes(places[1]))
    await waitFor(() => expect(result.current.trip.status).toBe('success'))
    act(() => result.current.startGuide())
    act(() => result.current.guidance.next())
    act(() => result.current.go('results'))

    act(() => result.current.swapPlaces())
    expect(result.current.trip).toMatchObject({
      origin: places[1],
      destination: places[0],
      status: 'loading',
      selected: null,
    })
    await waitFor(() => expect(result.current.trip.status).toBe('success'))

    expect(search.mock.calls.at(-1)?.[0]).toEqual({
      origin: places[1],
      destination: places[0],
      modes: ['walk', 'bike', 'bus', 'subway'],
      priority: 'fast',
      departedAt: expect.any(String),
    })
    expect(result.current.guidance).toMatchObject({ route: routes[0], step: 1 })
  })

  it.each([
    ['NO_INFO', 'no-info'],
    ['OUTSIDE_WINDOW', 'outside-window'],
    ['STALE', 'stale'],
  ] as const)('도착 응답의 %s 상태를 안내 상태로 보존한다', async (status, expected) => {
    const transitRoute = {
      ...routes[0],
      legs: [
        {
          ...routes[0].legs[1],
          routeId: '1002',
          from: { id: '221', name: '역삼역' },
          to: { id: '220', name: '선릉역' },
        },
      ],
    }
    const guidanceApi: GuidanceRepository = {
      arrivals: async () => ({ status, trains: [], updatedAt: null }),
      replan: async () => [],
    }
    const { result } = renderHook(() =>
      useRoutePlanner({ search: async () => [transitRoute] }, guidanceApi),
    )
    act(() => result.current.findRoutes({ ...places[1], stationId: 'dogok' }))
    await waitFor(() => expect(result.current.trip.status).toBe('success'))
    act(() => result.current.startGuide())
    act(() => result.current.openTrain())

    await waitFor(() => expect(result.current.arrivalStatus).toBe(expected))
    expect(result.current.arrivals).toEqual([])
  })

  it('버스 구간에서는 지하철 도착 API를 호출하지 않는다', async () => {
    const arrivals = vi.fn(async () => ({
      status: 'NO_INFO' as const,
      trains: [],
      updatedAt: null,
    }))
    const busRoute = {
      ...routes[0],
      legs: [
        {
          mode: 'bus' as const,
          title: '간선버스',
          note: '역삼역 → 도곡역',
          minutes: 10,
          routeId: '146',
          from: { id: 'station-1', name: '역삼역' },
          to: { id: 'station-2', name: '도곡역' },
        },
      ],
    }
    const { result } = renderHook(() =>
      useRoutePlanner({ search: async () => [busRoute] }, { arrivals, replan: async () => [] }),
    )
    act(() => result.current.findRoutes({ ...places[1], stationId: 'dogok' }))
    await waitFor(() => expect(result.current.trip.status).toBe('success'))
    act(() => result.current.startGuide())
    act(() => result.current.openTrain())

    expect(result.current.arrivalStatus).toBe('unsupported')
    expect(arrivals).not.toHaveBeenCalled()
  })

  it('재탐색 모달을 닫은 뒤 늦게 온 후보는 반영하지 않는다', async () => {
    let resolveReplan!: (proposals: ReplanProposal[]) => void
    const guidanceApi: GuidanceRepository = {
      arrivals: async () => ({ status: 'NO_INFO', trains: [], updatedAt: null }),
      replan: () => new Promise((resolve) => (resolveReplan = resolve)),
    }
    const { result } = await renderLoadedPlanner(guidanceApi)
    act(() => result.current.startGuide())
    act(() => result.current.openReplan())
    act(() => result.current.requestReplan())
    expect(result.current.replan.status).toBe('loading')

    act(() => result.current.closeGuidanceDialog())
    await act(async () => {
      resolveReplan([
        {
          route: routes[1],
          reason: '늦은 응답',
          source: 'MOCK',
        },
      ])
      await Promise.resolve()
    })
    expect(result.current.replan).toMatchObject({ status: 'idle', proposals: [] })
  })

  it('재탐색 조건은 안내 시작 시점 스냅샷을 사용한다', async () => {
    const replan = vi.fn(async () => [])
    const guidanceApi: GuidanceRepository = {
      arrivals: async () => ({ status: 'NO_INFO', trains: [], updatedAt: null }),
      replan,
    }
    const { result } = await renderLoadedPlanner(guidanceApi)
    const modesAtStart = [...result.current.trip.enabled]
    act(() => result.current.startGuide())
    act(() => result.current.trip.setPriority('calm'))
    act(() => result.current.openReplan())
    act(() => result.current.requestReplan())
    await waitFor(() => expect(result.current.replan.status).toBe('empty'))
    expect(replan).toHaveBeenCalledWith(
      expect.objectContaining({
        conditions: expect.objectContaining({ modes: modesAtStart, priority: 'fast' }),
      }),
      expect.any(AbortSignal),
    )
  })
})
