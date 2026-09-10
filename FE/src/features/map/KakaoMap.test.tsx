// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  KakaoMapClickEvent,
  KakaoMapInstance,
  KakaoMaps,
  MapOverlay,
} from '../../lib/kakao/sdk'
import type { Place, Route } from '../route/types'
import KakaoMap from './KakaoMap'

const mocks = vi.hoisted(() => ({ loadKakaoMaps: vi.fn() }))
vi.mock('../../lib/kakao/sdk', () => ({ loadKakaoMaps: mocks.loadKakaoMaps }))
vi.mock('../../api/repositories', () => ({
  bikeStationRepository: null,
  isBackendConfigured: false,
}))

const origin = {
  id: 'origin',
  name: '강남역',
  address: '서울 강남구 강남대로',
  kind: '지하철역',
  lat: 37.498,
  lng: 127.028,
}

class FakeResizeObserver {
  static callbacks: Array<() => void> = []

  constructor(callback: ResizeObserverCallback) {
    FakeResizeObserver.callbacks.push(() => callback([], this as unknown as ResizeObserver))
  }

  observe = vi.fn()
  disconnect = vi.fn()

  static trigger() {
    FakeResizeObserver.callbacks.forEach((callback) => callback())
  }
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
  getProjection = vi.fn(() => ({
    pointFromCoords: (point: FakeLatLng) => ({
      x: point.getLng() * 100,
      y: point.getLat() * 100,
    }),
    containerPointFromCoords: () => ({ x: 0, y: 0 }),
  }))
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
  static instances: FakeCustomOverlay[] = []
  setMap = vi.fn()

  constructor(readonly options: unknown) {
    FakeCustomOverlay.instances.push(this)
  }
}

class FakeAbstractOverlay {
  static instances: FakeAbstractOverlay[] = []
  map: KakaoMapInstance | null = null

  constructor() {
    FakeAbstractOverlay.instances.push(this)
  }

  setMap = vi.fn((map: KakaoMapInstance | null) => {
    if (this.map && !map) (this as unknown as { onRemove?: () => void }).onRemove?.()
    this.map = map
    if (map) {
      const overlay = this as unknown as { onAdd?: () => void; draw?: () => void }
      overlay.onAdd?.()
      overlay.draw?.()
    }
  })

  getPanels = vi.fn(() => ({ overlayLayer: document.body }))
  getProjection = vi.fn(() => FakeMap.instances[0].getProjection())
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
    AbstractOverlay: FakeAbstractOverlay as unknown as KakaoMaps['AbstractOverlay'],
    Polyline: class {
      setMap = vi.fn()
    } as unknown as KakaoMaps['Polyline'],
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

function renderMap(
  options: { places?: Place[]; route?: Route | null; onPlaceSelect?: (place: Place) => void } = {},
) {
  const markerClickHandlers: Array<() => void> = []
  const markers: FakeMarker[] = []
  const removeListener = vi.fn()
  const maps = fakeMaps(markerClickHandlers, removeListener, markers)
  mocks.loadKakaoMaps.mockResolvedValue(maps)
  const rendered = render(
    <KakaoMap
      origin={origin}
      destination={null}
      places={options.places}
      route={options.route}
      onPlaceSelect={options.onPlaceSelect}
      onMessage={vi.fn()}
    />,
  )
  return {
    ...rendered,
    markerClickHandlers,
    markers,
    maps,
    removeListener,
    customOverlays: FakeCustomOverlay.instances,
  }
}

beforeEach(() => {
  FakeMap.instances = []
  FakeCustomOverlay.instances = []
  FakeAbstractOverlay.instances = []
  FakeResizeObserver.callbacks = []
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

  it('MultiLineString의 각 선을 따로 그리고 경로 변경·해제 시 정리한다', async () => {
    const geometry: NonNullable<Route['geometry']> = {
      type: 'MultiLineString',
      coordinates: [
        [
          [127, 37.5],
          [127.01, 37.51],
        ],
        [
          [127.1, 37.6],
          [127.11, 37.61],
        ],
      ],
    }
    const route: Route = {
      id: 'route-1',
      label: '최단 경로',
      minutes: 10,
      transfers: 0,
      modes: ['subway'],
      legs: [],
      geometry,
    }
    const rendered = renderMap({ route })
    await waitFor(() =>
      expect(document.querySelectorAll('.route-svg-overlay polyline')).toHaveLength(2),
    )
    const firstSvg = document.querySelector('.route-svg-overlay') as SVGSVGElement
    expect(firstSvg.style.zIndex).toBe('5')
    expect(firstSvg.style.overflow).toBe('visible')
    expect(firstSvg.querySelectorAll('polyline')[0].getAttribute('points')).toContain('12700')
    expect(firstSvg.querySelectorAll('polyline')[1].getAttribute('points')).toContain('12710')

    const nextRoute: Route = {
      ...route,
      geometry: { ...geometry, coordinates: [geometry.coordinates[0]] },
    }
    rendered.rerender(
      <KakaoMap origin={origin} destination={null} route={nextRoute} onMessage={vi.fn()} />,
    )
    await waitFor(() =>
      expect(document.querySelectorAll('.route-svg-overlay polyline')).toHaveLength(1),
    )
    expect(FakeAbstractOverlay.instances[0].setMap).toHaveBeenCalledWith(null)
    expect(document.querySelectorAll('.route-svg-overlay')).toHaveLength(1)

    rendered.unmount()
    expect(FakeAbstractOverlay.instances.at(-1)?.setMap).toHaveBeenCalledWith(null)
    expect(document.querySelectorAll('.route-svg-overlay')).toHaveLength(0)
  })

  it('구간별 geometry 선 색상과 승차·환승·하차 marker를 관리한다', async () => {
    const onPlaceSelect = vi.fn()
    const transfer = { id: 'transfer', name: '환승역', lat: 37.51, lng: 127.04 }
    const route: Route = {
      id: 'route-styled',
      label: '최단 경로',
      minutes: 10,
      transfers: 1,
      modes: ['subway', 'bus'],
      legs: [
        {
          mode: 'subway',
          title: '2호선',
          note: '2호선',
          minutes: 5,
          routeId: '1002',
          from: { id: 'start', name: '승차역', lat: 37.5, lng: 127.03 },
          to: transfer,
          geometry: {
            type: 'MultiLineString',
            coordinates: [
              [
                [127.03, 37.5],
                [127.04, 37.51],
              ],
            ],
          },
        },
        {
          mode: 'bus',
          title: '버스',
          note: '버스',
          minutes: 5,
          routeId: 'bus-1',
          from: transfer,
          to: { id: 'end', name: '하차역', lat: 37.52, lng: 127.05 },
          geometry: {
            type: 'MultiLineString',
            coordinates: [
              [
                [127.04, 37.51],
                [127.05, 37.52],
              ],
            ],
          },
        },
      ],
    }
    const rendered = renderMap({ route, onPlaceSelect })
    await waitFor(() =>
      expect(document.querySelectorAll('.route-svg-overlay polyline')).toHaveLength(2),
    )
    const routeLines = document.querySelectorAll('.route-svg-overlay polyline')
    expect(routeLines[0].getAttribute('stroke')).toBe('#6379bd')
    expect(routeLines[1].getAttribute('stroke')).toBe('#2f80c0')
    await waitFor(() => expect(rendered.customOverlays).toHaveLength(3))
    expect(
      rendered.customOverlays.every(
        (overlay) => (overlay.options as { zIndex?: number }).zIndex === 10,
      ),
    ).toBe(true)
    const contents = rendered.customOverlays.map(
      (overlay) => (overlay.options as { content: HTMLButtonElement }).content,
    )
    expect(contents.map((content) => content.textContent)).toEqual(['승차', '하차', '환승'])
    expect(contents[0].getAttribute('aria-label')).toContain('승차역')
    expect(contents[0].getAttribute('aria-label')).not.toContain('start')
    fireEvent.click(contents[0])
    expect(onPlaceSelect).toHaveBeenCalledWith(expect.objectContaining({ kind: '승차' }))

    rendered.unmount()
    rendered.customOverlays.forEach((overlay) => expect(overlay.setMap).toHaveBeenCalledWith(null))
  })

  it('지도 크기가 바뀌면 저장한 경로 bounds를 다시 적용한다', async () => {
    const geometry: NonNullable<Route['geometry']> = {
      type: 'MultiLineString',
      coordinates: [
        [
          [127, 37.5],
          [127.01, 37.51],
        ],
      ],
    }
    const route: Route = {
      id: 'route-resize',
      label: '최단 경로',
      minutes: 10,
      transfers: 0,
      modes: ['subway'],
      legs: [],
      geometry,
    }
    renderMap({ route })
    await waitFor(() =>
      expect(document.querySelectorAll('.route-svg-overlay polyline')).toHaveLength(1),
    )
    const map = FakeMap.instances[0]
    const setBoundsCalls = map.setBounds.mock.calls.length

    act(() => FakeResizeObserver.trigger())

    expect(map.setBounds.mock.calls.length).toBeGreaterThan(setBoundsCalls)
    expect(map.setCenter).toHaveBeenCalledTimes(1)
  })
})
