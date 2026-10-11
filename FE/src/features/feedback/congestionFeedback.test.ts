import { describe, expect, it } from 'vitest'
import { routes } from '../../api/mock/fixtures'
import type { Leg, Route } from '../route/types'
import { buildFeedbackRequest, feedbackTarget, isFeedbackGrade } from './congestionFeedback'

const leg = (overrides: Partial<Leg>): Leg => ({
  mode: 'subway',
  title: '2호선',
  note: '',
  minutes: 10,
  ...overrides,
})
const route = (legs: Leg[], departedAt?: string): Route => ({
  ...routes[0],
  legs,
  departedAt,
})

describe('혼잡 체감 피드백 대상 구간', () => {
  it('가장 오래 타는 지하철 구간을 고른다', () => {
    const target = feedbackTarget(
      route([
        leg({ mode: 'walk', minutes: 30 }),
        leg({ title: 'A', minutes: 8 }),
        leg({ title: 'B', minutes: 15 }),
        leg({ mode: 'bus', minutes: 40 }),
      ]),
    )
    expect(target?.leg.title).toBe('B')
    expect(target?.index).toBe(2)
  })

  it('지하철이 없으면 가장 긴 버스 구간을 고른다', () => {
    const target = feedbackTarget(
      route([
        leg({ mode: 'bus', title: '짧은', minutes: 5 }),
        leg({ mode: 'bus', title: '긴', minutes: 9 }),
      ]),
    )
    expect(target?.leg.title).toBe('긴')
  })

  it('환승·승하차 전이 구간은 제외한다', () => {
    expect(
      feedbackTarget(
        route([
          leg({ transfer: true, minutes: 20 }),
          leg({ transitionType: 'BOARDING', minutes: 20 }),
          leg({ title: '본선', minutes: 3 }),
        ]),
      )?.leg.title,
    ).toBe('본선')
  })

  it('도보·따릉이뿐이면 대상이 없다', () => {
    expect(feedbackTarget(route([leg({ mode: 'walk' }), leg({ mode: 'bike' })]))).toBeNull()
    expect(feedbackTarget(null)).toBeNull()
  })

  it('탑승 시각은 앞 구간 이동·대기와 이 구간 대기를 더해 추정한다', () => {
    const target = feedbackTarget(
      route(
        [
          leg({ mode: 'walk', minutes: 4 }),
          leg({ mode: 'bus', minutes: 6, waitMinutes: 2 }),
          leg({ minutes: 12, waitMinutes: 3 }),
        ],
        '2026-09-17T09:00:00.000Z',
      ),
    )
    // 4 + (6 + 2) + 3 = 15분 뒤
    expect(target?.boardedAt).toBe('2026-09-17T09:15:00.000Z')
  })

  it('출발 시각이 없으면 탑승 시각도 없다', () => {
    expect(feedbackTarget(route([leg({})]))?.boardedAt).toBeUndefined()
  })
})

describe('혼잡 체감 피드백 요청', () => {
  it('구간 정보와 예측 등급을 요청에 담는다', () => {
    const target = feedbackTarget(
      route(
        [
          leg({
            routeId: '1002',
            from: { id: 's1', name: '강남' },
            to: { id: 's2', name: '당산' },
            segmentCongestionLevel: 75,
          }),
        ],
        '2026-09-17T09:00:00.000Z',
      ),
    )!
    expect(buildFeedbackRequest(target, 'CONGESTED', 'fb-1')).toEqual({
      feedbackId: 'fb-1',
      mode: 'subway',
      routeId: '1002',
      fromStationId: 's1',
      fromName: '강남',
      toStationId: 's2',
      toName: '당산',
      boardedAt: '2026-09-17T09:00:00.000Z',
      reportedGrade: 'CONGESTED',
      predictedGrade: 'CONGESTED',
    })
  })

  it('버스 구간은 bus로, id를 생략하면 새로 만든다', () => {
    const target = feedbackTarget(route([leg({ mode: 'bus' })]))!
    const request = buildFeedbackRequest(target, 'RELAXED')
    expect(request.mode).toBe('bus')
    expect(request.feedbackId).toBeTruthy()
    expect(request.predictedGrade).toBeUndefined()
  })

  it('세 등급만 유효하다', () => {
    expect(isFeedbackGrade('NORMAL')).toBe(true)
    expect(isFeedbackGrade('SATURATED')).toBe(false)
    expect(isFeedbackGrade(null)).toBe(false)
  })
})
