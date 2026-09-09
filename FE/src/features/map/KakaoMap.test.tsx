// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  KakaoMapClickEvent,
  KakaoMapInstance,
  KakaoMaps,
  MapOverlay,
} from '../../lib/kakao/sdk'
import type { Place } from '../route/types'
import KakaoMap from './KakaoMap'

const mocks = vi.hoisted(() => ({ loadKakaoMaps: vi.fn() }))
vi.mock('../../lib/kakao/sdk', () => ({ loadKakaoMaps: mocks.loadKakaoMaps }))

const origin = {
  id: 'origin',
  name: '강남역',
  address: '서울 강남구 강남대로',
  kind: '지하철역',
  lat: 37.498,
  lng: 127.028,
}

class FakeResizeObserver {
  observe = vi.fn()
  disconnect = vi.fn()
}

class FakeLatLng {
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

class FakeMap {
  static instances: FakeMap[] = []

  constructor() {
    FakeMap.instances.push(this)
  }

  getCenter = vi.fn(() => new FakeLatLng(37.5, 127) as never)
  getLevel = vi.fn(() => 5)
  getProjection = vi.fn(() => ({ containerPointFromCoords: () => ({ x: 0, y: 0 }) }))
  setCenter = vi.fn()
  setLevel = vi.fn()
  setBounds = vi.fn()
  panTo = vi.fn()
  relayout = vi.fn()
  getBounds = vi.fn(() => new FakeBounds())
}

class FakeBounds {
  extend = vi.fn()
  contain = vi.fn(() => false)
}

class FakeMarker {
  setMap = vi.fn()
  setImage = vi.fn()
  setZIndex = vi.fn()

  constructor(readonly options: { title?: string }) {}
}

class FakeCustomOverlay {
  setMap = vi.fn()

  constructor(readonly options: unknown) {}
}

function fakeMaps(
  markerClickHandlers: Array<() => void>,
  removeListener: ReturnType<typeof vi.fn>,
  markers: FakeMarker[],
): KakaoMaps {
  return {
    load: vi.fn((callback: () => void) => callback()),
    LatLng: FakeLatLng as unknown as KakaoMaps['LatLng'],
    LatLngBounds: FakeBounds as unknown as KakaoMaps['LatLngBounds'],
    MarkerImage: class {
      constructor(
        readonly src: string,
        readonly size: unknown,
        readonly options?: unknown,
      ) {}
    } as unknown as KakaoMaps['MarkerImage'],
    Size: class {
      constructor(
        readonly width: number,
        readonly height: number,
      ) {}
    } as unknown as KakaoMaps['Size'],
    Point: class {
      constructor(
        readonly x: number,
        readonly y: number,
      ) {}
    } as unknown as KakaoMaps['Point'],
    Map: class extends FakeMap {
      constructor(..._args: ConstructorParameters<KakaoMaps['Map']>) {
        super()
      }
    } as unknown as KakaoMaps['Map'],
    Marker: class extends FakeMarker {
      constructor(options: ConstructorParameters<KakaoMaps['Marker']>[0]) {
        super(options)
        markers.push(this)
      }
    } as unknown as KakaoMaps['Marker'],
    CustomOverlay: FakeCustomOverlay as unknown as KakaoMaps['CustomOverlay'],
    Polyline: class {} as unknown as KakaoMaps['Polyline'],
    services: {
      Places: class {
        keywordSearch = vi.fn()
      } as unknown as KakaoMaps['services']['Places'],
      Geocoder: class {} as KakaoMaps['services']['Geocoder'],
      Status: { OK: 'OK', ZERO_RESULT: 'ZERO_RESULT', ERROR: 'ERROR' },
    },
    event: {
      addListener: vi.fn(
        (
          target: KakaoMapInstance | MapOverlay,
          type: string,
          handler: (event: KakaoMapClickEvent) => void,
        ) => {
          if (target instanceof FakeMarker && type === 'click')
            markerClickHandlers.push(handler as unknown as () => void)
        },
      ) as unknown as KakaoMaps['event']['addListener'],
      removeListener: removeListener as unknown as KakaoMaps['event']['removeListener'],
    },
  }
}

function renderMap(options: { places?: Place[] } = {}) {
  const markerClickHandlers: Array<() => void> = []
  const markers: FakeMarker[] = []
  const removeListener = vi.fn()
  const maps = fakeMaps(markerClickHandlers, removeListener, markers)
  mocks.loadKakaoMaps.mockResolvedValue(maps)
  const rendered = render(
    <KakaoMap origin={origin} destination={null} places={options.places} onMessage={vi.fn()} />,
  )
  return { ...rendered, markerClickHandlers, markers, maps, removeListener }
}

beforeEach(() => {
  FakeMap.instances = []
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('일반 지도 장소 마커', () => {
  it('마커 선택 정보를 표시하고 버튼과 Escape로 닫는다', async () => {
    const { markerClickHandlers } = renderMap()
    await waitFor(() => expect(markerClickHandlers).toHaveLength(1))

    act(() => markerClickHandlers[0]())
    expect(screen.getByRole('region', { name: '선택한 장소 정보' }).textContent).toContain('강남역')
    expect(screen.getByRole('region', { name: '선택한 장소 정보' }).textContent).toContain(
      '서울 강남구 강남대로',
    )
    const locateButton = screen.getByRole('button', { name: '현재 위치' })
    const infoCard = screen.getByRole('region', { name: '선택한 장소 정보' })
    expect(
      locateButton.compareDocumentPosition(infoCard) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '장소 정보 닫기' }))
    expect(screen.queryByRole('region', { name: '선택한 장소 정보' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '출발 장소 정보' }))
    expect(screen.queryByRole('region', { name: '선택한 장소 정보' })).not.toBeNull()

    act(() => markerClickHandlers[0]())
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('region', { name: '선택한 장소 정보' })).toBeNull()
  })

  it('장소가 바뀌면 이전 선택을 지우고 이전 marker callback도 무시한다', async () => {
    const { rerender, markerClickHandlers } = renderMap()
    await waitFor(() => expect(markerClickHandlers).toHaveLength(1))
    act(() => markerClickHandlers[0]())
    expect(screen.queryByRole('region', { name: '선택한 장소 정보' })).not.toBeNull()

    const oldHandler = markerClickHandlers[0]
    const nextOrigin = { ...origin, id: 'next', name: '선릉역' }
    rerender(<KakaoMap origin={nextOrigin} destination={null} onMessage={vi.fn()} />)
    expect(screen.queryByRole('region', { name: '선택한 장소 정보' })).toBeNull()
    act(() => oldHandler())
    expect(screen.queryByRole('region', { name: '선택한 장소 정보' })).toBeNull()
  })

  it('언마운트 시 marker click listener와 marker를 정리한다', async () => {
    const { unmount, markerClickHandlers, markers, maps, removeListener } = renderMap()
    await waitFor(() => expect(markerClickHandlers).toHaveLength(1))

    const marker = markers[0]
    unmount()

    expect(removeListener).toHaveBeenCalledWith(marker, 'click', markerClickHandlers[0])
    expect(marker.setMap).toHaveBeenCalledWith(null)
    expect(maps.event.removeListener).toBe(removeListener)
  })

  it('탐색 결과마다 marker를 만들고 모두 정리한다', async () => {
    const nextPlace = { ...origin, id: 'next', name: '선릉역' }
    const { unmount, markerClickHandlers, markers, removeListener } = renderMap({
      places: [origin, nextPlace],
    })
    await waitFor(() => expect(markerClickHandlers).toHaveLength(2))

    expect(markers).toHaveLength(2)
    unmount()
    expect(removeListener).toHaveBeenCalledTimes(3)
    markers.forEach((marker) => expect(marker.setMap).toHaveBeenCalledWith(null))
  })

  it('장소를 focus하면 지도를 재생성하지 않고 해당 좌표로 이동한다', async () => {
    const nextPlace = { ...origin, id: 'next', name: '선릉역', lat: 37.5045, lng: 127.0489 }
    const places = [origin, nextPlace]
    const rendered = renderMap({ places })
    vi.stubGlobal('kakao', { maps: rendered.maps })
    await waitFor(() => expect(rendered.markerClickHandlers).toHaveLength(2))

    rendered.rerender(
      <KakaoMap
        origin={origin}
        destination={null}
        places={places}
        focusedPlace={nextPlace}
        onMessage={vi.fn()}
      />,
    )

    expect(FakeMap.instances).toHaveLength(1)
    expect(FakeMap.instances[0].setLevel).toHaveBeenCalledWith(3)
    expect(FakeMap.instances[0].panTo).toHaveBeenCalled()
  })

  it('탐색 장소 선택 시 선택 marker만 강조하고 해제하면 원상복구한다', async () => {
    const nextPlace = { ...origin, id: 'next', name: '선릉역', lat: 37.5045, lng: 127.0489 }
    const places = [origin, nextPlace]
    const rendered = renderMap({ places })
    await waitFor(() => expect(rendered.markerClickHandlers).toHaveLength(2))

    rendered.rerender(
      <KakaoMap
        origin={origin}
        destination={null}
        places={places}
        focusedPlace={nextPlace}
        onMessage={vi.fn()}
      />,
    )
    expect(rendered.markers[1].setZIndex).toHaveBeenLastCalledWith(3)
    expect(rendered.markers[1].setImage).toHaveBeenCalled()
    expect(rendered.markers[0].setZIndex).toHaveBeenLastCalledWith(1)
    const selectedImage = rendered.markers[1].setImage.mock.calls.at(-1)?.[0]

    rendered.rerender(
      <KakaoMap
        origin={origin}
        destination={null}
        places={places}
        focusedPlace={null}
        onMessage={vi.fn()}
      />,
    )
    expect(rendered.markers[1].setImage.mock.calls.at(-1)?.[0]).not.toBe(selectedImage)
    expect(rendered.markers[1].setZIndex).toHaveBeenLastCalledWith(1)
  })
})
