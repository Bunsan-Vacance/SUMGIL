import { describe, expect, it } from 'vitest'
import { bikeProposal, places, routes } from '../../api/mock/fixtures'
import { guidanceReducer, initialGuidance } from './guidanceReducer'

describe('길안내 진행 상태', () => {
  it('다른 안내를 시작하면 진행 상태를 초기화하고 경로와 출도착지를 고정한다', () => {
    const previous = {
      step: 3,
      train: '09:42',
      route: bikeProposal,
      origin: places[0],
      destination: places[1],
      completed: false,
      locationStatus: 'idle' as const,
    }
    expect(
      guidanceReducer(previous, {
        type: 'start',
        route: routes[0],
        origin: places[2],
        destination: places[3],
      }),
    ).toEqual({
      ...initialGuidance,
      route: routes[0],
      origin: places[2],
      destination: places[3],
    })
  })
  it('같은 경로 객체와 출도착지로 활성 안내를 다시 시작하면 진행 상태를 보존한다', () => {
    const active = {
      step: 2,
      train: '09:42',
      route: routes[0],
      origin: places[0],
      destination: places[1],
      completed: false,
      locationStatus: 'idle' as const,
    }
    expect(
      guidanceReducer(active, {
        type: 'start',
        route: routes[0],
        origin: { ...places[0] },
        destination: { ...places[1] },
      }),
    ).toBe(active)
  })
  it('마지막 구간에서는 단계를 넘기지 않고 완료 상태로 전환한다', () => {
    const beforeLast = { ...initialGuidance, route: routes[0], step: routes[0].legs.length - 2 }
    const last = guidanceReducer(beforeLast, { type: 'next' })
    expect(last).toMatchObject({ step: routes[0].legs.length - 1, completed: false })
    expect(guidanceReducer(last, { type: 'next' })).toMatchObject({
      step: routes[0].legs.length - 1,
      completed: true,
    })
  })
  it('안내를 종료하면 과거 경로와 완료 상태를 제거한다', () => {
    const completed = {
      step: 2,
      train: '09:42',
      route: routes[0],
      origin: places[0],
      destination: places[1],
      completed: true,
      locationStatus: 'idle' as const,
    }
    expect(guidanceReducer(completed, { type: 'stop' })).toEqual(initialGuidance)
  })

  it('이전 단계로 돌아가면 탑승 선택을 지우고 재탐색은 완료 구간을 보존한다', () => {
    const active = {
      ...initialGuidance,
      route: routes[0],
      origin: places[0],
      destination: places[1],
      step: 2,
      train: '09:42',
    }
    expect(guidanceReducer(active, { type: 'previous' })).toMatchObject({
      step: 1,
      train: null,
    })
    const remaining = {
      ...routes[1],
      id: 'remaining',
      legs: routes[1].legs.slice(2),
      minutes: 5,
    }
    const replanned = guidanceReducer(active, { type: 'replan', route: remaining })
    expect(replanned.route?.legs).toEqual([...routes[0].legs.slice(0, 2), ...remaining.legs])
    expect(replanned.step).toBe(2)
    expect(replanned.destination).toBe(places[1])
    expect(replanned.train).toBeNull()
  })

  it('도보와 자전거는 연속된 정확한 도착 위치 두 번으로 진행한다', () => {
    const active = { ...initialGuidance, route: routes[0], step: 0 }
    const endpoint = routes[0].legs[0].to!
    const candidate = guidanceReducer(active, {
      type: 'location',
      latitude: endpoint.lat!,
      longitude: endpoint.lng!,
      accuracy: 5,
    })
    expect(candidate.step).toBe(0)
    const progressed = guidanceReducer(candidate, {
      type: 'location',
      latitude: endpoint.lat!,
      longitude: endpoint.lng!,
      accuracy: 5,
    })
    expect(progressed.step).toBe(1)
    const nextEndpoint = routes[0].legs[1].to!
    expect(
      guidanceReducer(progressed, {
        type: 'location',
        latitude: nextEndpoint.lat!,
        longitude: nextEndpoint.lng!,
        accuracy: 5,
      }).step,
    ).toBe(1)
    expect(
      guidanceReducer(candidate, {
        type: 'location',
        latitude: endpoint.lat! + 0.0003,
        longitude: endpoint.lng!,
        accuracy: 10,
      }).locationCandidateCount,
    ).toBe(0)
    expect(
      guidanceReducer(active, {
        type: 'location',
        latitude: endpoint.lat!,
        longitude: endpoint.lng!,
        accuracy: 26,
      }),
    ).toMatchObject({ step: 0, locationCandidateCount: 0 })

    const finalRoute = { ...routes[0], legs: [routes[0].legs[0]] }
    const final = { ...initialGuidance, route: finalRoute }
    const finalCandidate = guidanceReducer(final, {
      type: 'location',
      latitude: finalRoute.legs[0].to!.lat!,
      longitude: finalRoute.legs[0].to!.lng!,
      accuracy: 5,
    })
    expect(
      guidanceReducer(finalCandidate, {
        type: 'location',
        latitude: finalRoute.legs[0].to!.lat!,
        longitude: finalRoute.legs[0].to!.lng!,
        accuracy: 5,
      }),
    ).toMatchObject({ completed: true, step: 0 })
  })

  it('자전거 구간도 도착점 좌표를 두 번 확인하면 자동 진행한다', () => {
    const endpoint = { lat: 37.5, lng: 127.0 }
    const bikeRoute = {
      ...bikeProposal,
      legs: bikeProposal.legs.map((leg, index) => (index === 1 ? { ...leg, to: endpoint } : leg)),
    }
    const active = { ...initialGuidance, route: bikeRoute, step: 1 }
    const atEndpoint = {
      type: 'location' as const,
      latitude: endpoint.lat,
      longitude: endpoint.lng,
      accuracy: 10,
    }
    expect(guidanceReducer(active, atEndpoint)).toMatchObject({ step: 1, completed: false })
    expect(guidanceReducer(guidanceReducer(active, atEndpoint), atEndpoint)).toMatchObject({
      step: 2,
      completed: false,
    })
  })

  it('대중교통은 목적지에서 멀어진 위치를 확인한 뒤에만 자동으로 하차 처리한다', () => {
    const endpoint = { lat: 37.5, lng: 127.0 }
    const transitRoute = {
      ...routes[0],
      legs: [{ ...routes[0].legs[0], mode: 'subway' as const, to: endpoint }],
    }
    const active = { ...initialGuidance, route: transitRoute }
    const atDestination = {
      type: 'location' as const,
      latitude: endpoint.lat,
      longitude: endpoint.lng,
      accuracy: 5,
    }
    expect(guidanceReducer(active, atDestination)).toMatchObject({ step: 0, completed: false })
    const away = guidanceReducer(active, {
      type: 'location',
      latitude: endpoint.lat + 0.002,
      longitude: endpoint.lng,
      accuracy: 5,
    })
    const nearOnce = guidanceReducer(away, atDestination)
    expect(nearOnce.completed).toBe(false)
    expect(guidanceReducer(nearOnce, atDestination)).toMatchObject({ completed: true, step: 0 })
  })

  it('버스는 정류장 밖 이동을 확인한 뒤 도착점 근처에서 두 번 확인해야 진행한다', () => {
    const endpoint = { lat: 37.5, lng: 127.0 }
    const busRoute = {
      ...routes[3],
      legs: routes[3].legs.map((leg, index) => (index === 1 ? { ...leg, to: endpoint } : leg)),
    }
    const active = { ...initialGuidance, route: busRoute, step: 1 }
    const away = {
      type: 'location' as const,
      latitude: endpoint.lat + 0.002,
      longitude: endpoint.lng,
      accuracy: 5,
    }
    const near = {
      type: 'location' as const,
      latitude: endpoint.lat,
      longitude: endpoint.lng,
      accuracy: 5,
    }
    const armed = guidanceReducer(active, away)
    expect(guidanceReducer(armed, near).step).toBe(1)
    expect(guidanceReducer(guidanceReducer(armed, near), near).step).toBe(2)
  })

  it('수동 단계 변경 뒤에는 이전 위치 후보를 이어 쓰지 않는다', () => {
    const endpoint = routes[0].legs[0].to!
    const active = { ...initialGuidance, route: routes[0] }
    const candidate = guidanceReducer(active, {
      type: 'location',
      latitude: endpoint.lat!,
      longitude: endpoint.lng!,
      accuracy: 5,
    })
    const manuallyChanged = guidanceReducer(candidate, { type: 'set-step', step: 0 })
    expect(manuallyChanged.locationCandidateCount).toBe(0)
    expect(
      guidanceReducer(manuallyChanged, {
        type: 'location',
        latitude: endpoint.lat!,
        longitude: endpoint.lng!,
        accuracy: 5,
      }).step,
    ).toBe(0)
  })

  it('무효 GPS를 거부하고 재탐색은 위치 확인 후보를 초기화한다', () => {
    const endpoint = { lat: 37.5, lng: 127.0 }
    const route = {
      ...routes[0],
      legs: routes[0].legs.map((leg, index) => (index === 0 ? { ...leg, to: endpoint } : leg)),
    }
    const active = { ...initialGuidance, route }
    const candidate = guidanceReducer(active, {
      type: 'location',
      latitude: endpoint.lat,
      longitude: endpoint.lng,
      accuracy: 5,
    })
    expect(
      guidanceReducer(candidate, {
        type: 'location',
        latitude: 91,
        longitude: endpoint.lng,
        accuracy: 5,
      }),
    ).toMatchObject({ step: 0, locationCandidateCount: 0 })

    const pending = guidanceReducer(candidate, { type: 'location-status', status: 'no-position' })
    expect(pending.locationCandidateCount).toBe(0)
    const replanned = guidanceReducer(candidate, { type: 'replan', route: routes[1] })
    expect(replanned).toMatchObject({
      step: 0,
      locationCandidateCount: 0,
      locationCandidateStep: null,
      transitAwayStep: null,
    })
  })

  it('위치 없이 현재 단계를 직접 수정한다', () => {
    const active = { ...initialGuidance, route: routes[0], step: 0 }
    expect(guidanceReducer(active, { type: 'set-step', step: 3 })).toMatchObject({
      step: 3,
      train: null,
    })
    expect(guidanceReducer(active, { type: 'set-step', step: 99 })).toBe(active)
  })
})
