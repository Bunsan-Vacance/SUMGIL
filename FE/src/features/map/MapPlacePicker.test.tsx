// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  KakaoCoord2AddressResult,
  KakaoMapClickEvent,
  KakaoMapInstance,
  KakaoMaps,
} from '../../lib/kakao/sdk'
import MapPlacePicker from './MapPlacePicker'

const mocks = vi.hoisted(() => ({ loadKakaoMaps: vi.fn() }))
vi.mock('../../lib/kakao/sdk', () => ({ loadKakaoMaps: mocks.loadKakaoMaps }))
vi.mock('../../api/repositories', () => ({
  bikeStationRepository: null,
  isBackendConfigured: false,
}))

const callbacks: Array<(results: KakaoCoord2AddressResult[], status: string) => void> = []
const clickHandlers: Array<(event: KakaoMapClickEvent) => void> = []

class TestResizeObserver {
  observe() {}
  disconnect() {}
}

function fakeMaps(): KakaoMaps {
  class LatLng {
    constructor(
      private readonly lat: number,
      private readonly lng: number,
    ) {}
    getLat() {
      return this.lat
    }
    getLng() {
      return this.lng
    }
  }
  class Map {
    relayout() {}
    getLevel() {
      return 5
    }
    getProjection() {
      return { containerPointFromCoords: () => ({ x: 0, y: 0 }) }
    }
    getBounds() {
      return { contain: () => false }
    }
  }
  class Marker {
    setMap() {}
  }
  class CustomOverlay {
    constructor(_options: unknown) {}
    setMap() {}
  }
  class Geocoder {
    coord2Address(
      _lng: number,
      _lat: number,
      callback: (results: KakaoCoord2AddressResult[], status: string) => void,
    ) {
      callbacks.push(callback)
    }
  }
  return {
    LatLng,
    Map,
    Marker,
    CustomOverlay,
    services: { Geocoder, Status: { OK: 'OK', ZERO_RESULT: 'ZERO_RESULT', ERROR: 'ERROR' } },
    event: {
      addListener: (
        _target: KakaoMapInstance,
        type: string,
        handler: (event: KakaoMapClickEvent) => void,
      ) => {
        if (type === 'click') clickHandlers.push(handler)
      },
      removeListener: () => undefined,
    },
  } as unknown as KakaoMaps
}

beforeEach(() => {
  callbacks.length = 0
  clickHandlers.length = 0
  mocks.loadKakaoMaps.mockResolvedValue(fakeMaps())
  vi.stubGlobal('ResizeObserver', TestResizeObserver)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

describe('지도 위치 선택', () => {
  it('연속 클릭의 늦은 주소 응답을 무시한다', async () => {
    const onSelect = vi.fn()
    render(<MapPlacePicker target="destination" onCancel={vi.fn()} onSelect={onSelect} />)
    await waitFor(() => expect(clickHandlers).toHaveLength(1))

    act(() => {
      clickHandlers[0]({ latLng: { getLat: () => 37.5, getLng: () => 127.03 } })
      clickHandlers[0]({ latLng: { getLat: () => 37.51, getLng: () => 127.04 } })
      callbacks[1]([{ road_address: { address_name: '새 주소' } }], 'OK')
      callbacks[0]([{ address: { address_name: '오래된 주소' } }], 'OK')
    })

    expect(screen.getByText('새 주소')).toBeTruthy()
    expect(screen.queryByText('오래된 주소')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '이 위치를 도착지로 설정' }))
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ lat: 37.51, lng: 127.04, address: '새 주소' }),
    )
  })

  it('취소하면 위치 확정을 호출하지 않는다', async () => {
    const onSelect = vi.fn()
    const onCancel = vi.fn()
    render(<MapPlacePicker target="origin" onCancel={onCancel} onSelect={onSelect} />)
    await waitFor(() => expect(clickHandlers).toHaveLength(1))

    act(() => {
      clickHandlers[0]({ latLng: { getLat: () => 37.5, getLng: () => 127.03 } })
    })
    fireEvent.click(screen.getByRole('button', { name: '검색으로 돌아가기' }))
    expect(onCancel).toHaveBeenCalledOnce()
    expect(onSelect).not.toHaveBeenCalled()
  })
})
