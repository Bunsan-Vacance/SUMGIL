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
})
