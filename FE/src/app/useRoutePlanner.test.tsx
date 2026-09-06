// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { RouteRepository } from '../api/contracts'
import { places, routes } from '../api/mock/fixtures'
import { useRoutePlanner } from './useRoutePlanner'

const repository: RouteRepository = { search: async () => routes }

afterEach(cleanup)

describe('경로와 안내 화면의 수명', () => {
  beforeEach(() => history.replaceState(null, '', '#home'))

  const renderLoadedPlanner = async () => {
    const rendered = renderHook(() => useRoutePlanner(repository))
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
    act(() => result.current.selectRoute(routes[1].id))

    expect(result.current.trip.selected).toBe(routes[1])
    expect(result.current.guidance).toMatchObject({ route: routes[0], step: 1 })
    expect(result.current.guidance.destination).toBe(places[1])

    act(() => result.current.openSearch('origin'))
    act(() => result.current.choosePlace(places[3]))
    act(() => result.current.applyFilter(['bike']))
    expect(result.current.trip).toMatchObject({ status: 'idle', selected: null })
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

  it('출발지 변경 뒤 현재 탐색의 과거 상세 URL은 홈으로 보정한다', async () => {
    const { result } = await renderLoadedPlanner()
    act(() => result.current.openSearch('origin'))
    act(() => result.current.choosePlace(places[2]))
    expect(result.current.trip.selected).toBeNull()

    act(() => {
      history.replaceState(null, '', '#detail')
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    await waitFor(() => expect(result.current.screen).toBe('home'))
    expect(location.hash).toBe('#home')
  })
})
