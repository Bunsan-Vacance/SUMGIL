// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import GuidanceDialogs from './GuidanceDialogs'
import type { RerouteCheckResponse } from '../../api/reroute'
import type { Leg } from '../route/types'

afterEach(cleanup)

beforeAll(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value() {
      this.setAttribute('open', '')
    },
  })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {
    configurable: true,
    value() {
      this.removeAttribute('open')
    },
  })
})

afterAll(() => {
  vi.restoreAllMocks()
})

const leg: Leg = { mode: 'subway', title: '지하철 이동', note: '', minutes: 5 }

const proposal: RerouteCheckResponse = {
  status: 'proposal',
  recommendationId: 'reco-1',
  validUntil: '2999-01-01T00:00:00+09:00',
  recommendedBy: 'AGENT',
  reason: '역삼 대여소는 도착 시점에 자전거가 없을 가능성이 높아요.',
  target: { rentalId: 'ST-TARGET', name: '역삼', currentBikes: 0, predictedStock: 0.3 },
  alternative: {
    rentalId: 'ST-ALT',
    name: '교대',
    lat: 37.5,
    lng: 127.0,
    distanceMeters: 180,
    currentBikes: 6,
  },
  boundary: { legIndex: 1, nodeId: 'ND-1', lat: 37.5, lng: 127.0 },
  walkLeg: {
    mode: 'WALK',
    fromLat: 37.5,
    fromLng: 127.0,
    toLat: 37.501,
    toLng: 127.001,
    minutes: 3,
    geometryStatus: 'estimated',
    estimated: true,
  },
  route: { legs: [{ mode: 'BIKE', minutes: 8 }] },
}

function renderDialog(
  overrides: Partial<Parameters<typeof GuidanceDialogs>[0]> = {},
  onAcceptReroute = vi.fn(),
  onDismissReroute = vi.fn(),
) {
  const onClose = vi.fn()
  render(
    <GuidanceDialogs
      dialog="reroute"
      leg={leg}
      arrivals={[]}
      arrivalStatus="idle"
      proposals={[]}
      currentRemaining={0}
      replanStatus="idle"
      rerouteProposal={proposal}
      onClose={onClose}
      onExit={vi.fn()}
      onTrain={vi.fn()}
      onLoadArrivals={vi.fn()}
      onLoadReplan={vi.fn()}
      onAcceptReplan={vi.fn()}
      onAcceptReroute={onAcceptReroute}
      onDismissReroute={onDismissReroute}
      {...overrides}
    />,
  )
  return { onClose, onAcceptReroute, onDismissReroute }
}

describe('재안내(따릉이 고갈) 팝업', () => {
  it('대상·대안 대여소 정보와 도보 추정·AI 추천 표시를 보여준다', () => {
    renderDialog()

    expect(screen.getByText('대여소를 바꿔볼까요?')).toBeTruthy()
    expect(screen.getByText(proposal.reason!)).toBeTruthy()
    expect(screen.getByText('역삼')).toBeTruthy()
    expect(screen.getByText(/현재 0대/)).toBeTruthy()
    expect(screen.getByText(/예상 재고 0\.3대/)).toBeTruthy()
    expect(screen.getByText('교대')).toBeTruthy()
    expect(screen.getByText(/180m/)).toBeTruthy()
    expect(screen.getByText('도보 추정')).toBeTruthy()
    expect(screen.getByText('AI 추천')).toBeTruthy()
  })

  it('수락·거절 버튼이 각각의 콜백을 호출한다', () => {
    const onAcceptReroute = vi.fn()
    const onDismissReroute = vi.fn()
    renderDialog({}, onAcceptReroute, onDismissReroute)

    fireEvent.click(screen.getByRole('button', { name: '이 대여소로 변경' }))
    expect(onAcceptReroute).toHaveBeenCalledOnce()

    fireEvent.click(screen.getByRole('button', { name: '기존 경로 유지' }))
    expect(onDismissReroute).toHaveBeenCalledOnce()
  })

  it('제안 정보가 없으면 안내 문구만 보여준다', () => {
    renderDialog({ rerouteProposal: null })
    expect(screen.getByText('재안내 정보를 불러오지 못했어요.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '이 대여소로 변경' })).toBeNull()
  })
})
