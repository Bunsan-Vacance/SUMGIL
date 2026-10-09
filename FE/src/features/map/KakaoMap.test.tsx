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

const mocks = vi.hoisted(() => ({
  loadKakaoMaps: vi.fn(),
  stock: vi.fn(),
  nearby: vi.fn(),
}))
vi.mock('../../lib/kakao/sdk', () => ({ loadKakaoMaps: mocks.loadKakaoMaps }))
vi.mock('../../api/repositories', () => ({
  bikeStationRepository: { nearby: mocks.nearby },
  bikeStockRepository: { stock: mocks.stock },
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
const position = {
  coords: { latitude: 37.5, longitude: 127.03 },
} as GeolocationPosition
let originalGeolocation: PropertyDescriptor | undefined

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
  static boundsApplied = false

  constructor() {
    FakeMap.instances.push(this)
  }

  getCenter = vi.fn(() => new FakeLatLng(37.5, 127) as never)
  getLevel = vi.fn(() => 5)
  getProjection = vi.fn(() => ({
    pointFromCoords: (point: FakeLatLng) =>
      FakeMap.boundsApplied
        ? {
            x: Math.round((point.getLng() - 127) * 1000 + 220),
            y: Math.round((point.getLat() - 37.5) * 1000 + 110),
          }
        : {
            x: -4,
            y: -37,
          },
    containerPointFromCoords: () => ({
      x: 0,
      y: 0,
    }),
  }))
  setCenter = vi.fn()
  setLevel = vi.fn()
  setBounds = vi.fn(() => {
    FakeMap.boundsApplied = true
  })
  panTo = vi.fn()
  relayout = vi.fn()
  getBounds = vi.fn(() => new FakeBounds())
  dragStart: (() => void) | null = null
}

class FakeBounds {
  static containsAll = false

  extend = vi.fn()
  contain = vi.fn(() => FakeBounds.containsAll)
}

class FakeMarker {
  setMap = vi.fn()
  setImage = vi.fn()
  setZIndex = vi.fn()
  setPosition = vi.fn()

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
          if (target instanceof FakeMap && type === 'dragstart')
            target.dragStart = handler as unknown as () => void
        },
      ) as unknown as KakaoMaps['event']['addListener'],
      removeListener: removeListener as unknown as KakaoMaps['event']['removeListener'],
    },
  }
}

function renderMap(
  options: {
    origin?: Place | null
    destination?: Place | null
    places?: Place[]
    route?: Route | null
    onPlaceSelect?: (place: Place) => void
    autoLocate?: boolean
    onCurrentLocation?: (position: GeolocationPosition) => void
    livePosition?: { latitude: number; longitude: number; accuracy: number } | null
  } = {},
) {
  const markerClickHandlers: Array<() => void> = []
  const markers: FakeMarker[] = []
  const removeListener = vi.fn()
  const maps = fakeMaps(markerClickHandlers, removeListener, markers)
  mocks.loadKakaoMaps.mockResolvedValue(maps)
  const rendered = render(
    <KakaoMap
      origin={options.origin === undefined ? origin : options.origin}
      destination={options.destination === undefined ? null : options.destination}
      places={options.places}
      route={options.route}
      onPlaceSelect={options.onPlaceSelect}
      autoLocate={options.autoLocate}
      onCurrentLocation={options.onCurrentLocation}
      livePosition={options.livePosition}
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

function clickBikeMarker(rendered: ReturnType<typeof renderMap>, index = 0) {
  const content = (rendered.customOverlays[index].options as { content: HTMLButtonElement }).content
  fireEvent.click(content)
}

beforeEach(() => {
  originalGeolocation = Object.getOwnPropertyDescriptor(navigator, 'geolocation')
  mocks.stock.mockReset().mockResolvedValue({
    rentalId: 'ST-1',
    status: 'UNAVAILABLE',
    availableBikes: null,
    stockUpdatedAt: null,
  })
  mocks.nearby.mockReset().mockResolvedValue([])
  FakeBounds.containsAll = false
  FakeMap.instances = []
  FakeMap.boundsApplied = false
  FakeCustomOverlay.instances = []
  FakeAbstractOverlay.instances = []
  FakeResizeObserver.callbacks = []
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
})

afterEach(() => {
  cleanup()
  if (originalGeolocation) Object.defineProperty(navigator, 'geolocation', originalGeolocation)
  else Reflect.deleteProperty(navigator, 'geolocation')
  history.replaceState(null, '', '#home')
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('일반 지도 장소 마커', () => {
  it('livePosition은 단일 위치 마커를 갱신하고 드래그 후 현재 위치 버튼으로 추적을 재개한다', async () => {
    const first = { latitude: 37.5, longitude: 127.03, accuracy: 8 }
    const rendered = renderMap({ livePosition: first })
    await waitFor(() => expect(rendered.markers).toHaveLength(2))
    const liveMarker = rendered.markers[1]
    const map = FakeMap.instances[0]
    expect(map.panTo).toHaveBeenCalledTimes(1)

    rendered.rerender(
      <KakaoMap
        origin={origin}
        destination={null}
        livePosition={{ ...first, latitude: 37.51 }}
        onMessage={vi.fn()}
      />,
    )
    expect(liveMarker.setPosition).toHaveBeenCalledOnce()
    expect(map.panTo).toHaveBeenCalledTimes(2)

    act(() => map.dragStart?.())
    rendered.rerender(
      <KakaoMap
        origin={origin}
        destination={null}
        livePosition={{ ...first, latitude: 37.52 }}
        onMessage={vi.fn()}
      />,
    )
    expect(liveMarker.setPosition).toHaveBeenCalledTimes(2)
    expect(map.panTo).toHaveBeenCalledTimes(2)

    fireEvent.click(screen.getByRole('button', { name: '현재 위치' }))
    expect(map.panTo).toHaveBeenCalledTimes(3)
    expect(rendered.markers).toHaveLength(2)
  })

  it('안내 종료 시 live 마커를 제거하고 유효하지 않은 좌표는 표시하지 않는다', async () => {
    const rendered = renderMap({
      livePosition: { latitude: 37.5, longitude: 127.03, accuracy: 8 },
    })
    await waitFor(() => expect(rendered.markers).toHaveLength(2))
    const liveMarker = rendered.markers[1]
    rendered.rerender(
      <KakaoMap origin={origin} destination={null} livePosition={null} onMessage={vi.fn()} />,
    )
    expect(liveMarker.setMap).toHaveBeenCalledWith(null)
    rendered.rerender(
      <KakaoMap
        origin={origin}
        destination={null}
        livePosition={{ latitude: 91, longitude: 127.03, accuracy: 8 }}
        onMessage={vi.fn()}
      />,
    )
    expect(rendered.markers).toHaveLength(2)
  })

  it('홈 지도는 준비되면 현재 위치로 자동 이동한다', async () => {
    const getCurrentPosition = vi.fn()
    const onCurrentLocation = vi.fn()
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { getCurrentPosition },
    })
    const rendered = renderMap({ autoLocate: true, onCurrentLocation })
    vi.stubGlobal('kakao', { maps: rendered.maps })

    await waitFor(() => expect(getCurrentPosition).toHaveBeenCalledOnce())
    act(() => getCurrentPosition.mock.calls[0][0](position))

    const point = FakeMap.instances[0].panTo.mock.calls[0][0]
    expect(point).toBeInstanceOf(FakeLatLng)
    expect((point as FakeLatLng).getLat()).toBe(position.coords.latitude)
    expect((point as FakeLatLng).getLng()).toBe(position.coords.longitude)
    expect(onCurrentLocation).toHaveBeenCalledWith(position)
    expect(getCurrentPosition).toHaveBeenCalledOnce()
  })

  it('홈으로 재진입하면 지도 재생성 후 현재 위치를 다시 조회한다', async () => {
    const getCurrentPosition = vi.fn()
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { getCurrentPosition },
    })
    const rendered = renderMap({ autoLocate: true })
    vi.stubGlobal('kakao', { maps: rendered.maps })
    await waitFor(() => expect(getCurrentPosition).toHaveBeenCalledOnce())
    act(() => getCurrentPosition.mock.calls[0][0](position))

    rendered.rerender(
      <KakaoMap
        key="home-reentry"
        origin={origin}
        destination={null}
        autoLocate
        onMessage={vi.fn()}
      />,
    )
    await waitFor(() => expect(getCurrentPosition).toHaveBeenCalledTimes(2))
  })

  it('주소가 없어도 대여소 메타데이터를 정보 카드에 표시한다', async () => {
    const station: Place = {
      id: 'bike-station:ST-0',
      name: '대여소',
      address: '',
      kind: '따릉이 대여소',
      lat: 37.5,
      lng: 127,
      dockCount: 0,
      distanceMeters: 42.5,
    }
    mocks.nearby.mockResolvedValueOnce([
      {
        id: 'ST-0',
        name: '대여소',
        address: '',
        lat: 37.5,
        lng: 127,
        dockCount: 0,
        distanceMeters: 42.5,
      },
    ])
    FakeBounds.containsAll = true
    const rendered = renderMap({ origin: station })

    await waitFor(() => expect(rendered.customOverlays).toHaveLength(1))
    clickBikeMarker(rendered)

    const card = screen.getByRole('region', { name: '따릉이 실시간 재고' })
    expect(card.textContent).toContain('대여소')
    expect(card.textContent).toContain('거치대 총 0개')
    expect(card.textContent).toContain('지도 중심에서 43m')
  })

  it('onBikeStationSelect가 있으면 대여소 선택을 콜백으로만 전달한다', async () => {
    mocks.nearby.mockResolvedValueOnce([
      {
        id: 'ST-0',
        name: '대여소',
        address: '',
        lat: 37.5,
        lng: 127,
        availableBikes: 4,
        stockUpdatedAt: '2026-10-09T01:00:00+09:00',
      },
    ])
    FakeBounds.containsAll = true
    const onBikeStationSelect = vi.fn()
    const onPlaceSelect = vi.fn()
    const maps = fakeMaps([], vi.fn(), [])
    mocks.loadKakaoMaps.mockResolvedValue(maps)
    render(
      <KakaoMap
        origin={null}
        onMessage={vi.fn()}
        onPlaceSelect={onPlaceSelect}
        onBikeStationSelect={onBikeStationSelect}
        bikeStationsVisible
        bikeStockBadges
      />,
    )
    await waitFor(() => expect(FakeCustomOverlay.instances).toHaveLength(1))
    const content = (FakeCustomOverlay.instances[0].options as { content: HTMLButtonElement })
      .content
    expect(content.querySelector('.bike-stock-badge')?.textContent).toBe('4')
    fireEvent.click(content)
    expect(onBikeStationSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'bike-station:ST-0' }),
    )
    expect(onPlaceSelect).not.toHaveBeenCalled()
    expect(screen.queryByRole('region', { name: '따릉이 실시간 재고' })).toBeNull()
    expect(mocks.stock).not.toHaveBeenCalled()
  })

  it('stationMarkers를 주면 역 오버레이를 만들고 클릭 시 datum으로 알린다', async () => {
    const maps = fakeMaps([], vi.fn(), [])
    mocks.loadKakaoMaps.mockResolvedValue(maps)
    const datum = {
      stationId: '222',
      stationName: '강남',
      lat: 37.4979,
      lng: 127.0276,
      grade: 'NORMAL' as const,
    }
    const onStationSelect = vi.fn()
    const onViewportChange = vi.fn()
    const { rerender } = render(
      <KakaoMap
        origin={null}
        onMessage={vi.fn()}
        stationMarkers={[datum]}
        onStationSelect={onStationSelect}
        onViewportChange={onViewportChange}
      />,
    )
    await waitFor(() => expect(FakeCustomOverlay.instances).toHaveLength(1))
    const content = (FakeCustomOverlay.instances[0].options as { content: HTMLButtonElement })
      .content
    expect(content.classList.contains('station-marker')).toBe(true)
    expect(content.classList.contains('grade-normal')).toBe(true)
    expect(onViewportChange).toHaveBeenCalledWith({ lat: 37.5, lng: 127 })
    fireEvent.click(content)
    expect(onStationSelect).toHaveBeenCalledWith(datum)

    rerender(
      <KakaoMap
        origin={null}
        onMessage={vi.fn()}
        stationMarkers={[{ ...datum, grade: 'CONGESTED' }]}
        onStationSelect={onStationSelect}
        selectedStationId="222"
      />,
    )
    await waitFor(() => expect(content.classList.contains('grade-congested')).toBe(true))
    expect(content.classList.contains('selected')).toBe(true)
    expect(FakeCustomOverlay.instances).toHaveLength(1)
  })

  it('역 마커 목록에서 사라진 역의 오버레이는 정리한다', async () => {
    const maps = fakeMaps([], vi.fn(), [])
    mocks.loadKakaoMaps.mockResolvedValue(maps)
    const datum = {
      stationId: '222',
      stationName: '강남',
      lat: 37.4979,
      lng: 127.0276,
      grade: null,
    }
    const { rerender } = render(
      <KakaoMap origin={null} onMessage={vi.fn()} stationMarkers={[datum]} />,
    )
    await waitFor(() => expect(FakeCustomOverlay.instances).toHaveLength(1))
    const overlay = FakeCustomOverlay.instances[0]
    rerender(<KakaoMap origin={null} onMessage={vi.fn()} stationMarkers={[]} />)
    await waitFor(() => expect(overlay.setMap).toHaveBeenCalledWith(null))
  })

  it('대여소 메타데이터가 없으면 해당 항목을 숨긴다', async () => {
    const station: Place = {
      id: 'bike-station:ST-1',
      name: '정보 없는 대여소',
      address: '',
      kind: '따릉이 대여소',
      lat: 37.5,
      lng: 127,
    }
    mocks.nearby.mockResolvedValueOnce([
      {
        id: 'ST-1',
        name: '정보 없는 대여소',
        address: '',
        lat: 37.5,
        lng: 127,
      },
    ])
    FakeBounds.containsAll = true
    const rendered = renderMap({ origin: station })

    await waitFor(() => expect(rendered.customOverlays).toHaveLength(1))
    clickBikeMarker(rendered)

    const card = screen.getByRole('region', { name: '따릉이 실시간 재고' })
    expect(card.textContent).toContain('정보 없는 대여소')
    expect(card.textContent).not.toContain('거치대 총')
    expect(card.textContent).not.toContain('지도 중심에서')
  })

  it('마커 선택 정보를 표시하고 닫기 버튼과 Escape로 닫는다', async () => {
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

    act(() => markerClickHandlers[0]())
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

  it('출발지와 도착지 정보 바로가기 버튼을 표시하지 않는다', () => {
    renderMap({ destination: { ...origin, id: 'destination', name: '선릉역' } })

    expect(screen.queryByRole('button', { name: '출발 장소 정보' })).toBeNull()
    expect(screen.queryByRole('button', { name: '도착 장소 정보' })).toBeNull()
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
    expect(removeListener).toHaveBeenCalledTimes(4)
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
      legs: [
        {
          mode: 'subway',
          title: '2호선',
          note: '2호선',
          minutes: 10,
          routeId: '1002',
          from: { id: 'start', name: '승차역', lat: 37.5, lng: 127 },
          to: { id: 'end', name: '하차역', lat: 37.51, lng: 127.01 },
        },
      ],
      geometry,
    }
    const rendered = renderMap({ route })
    await waitFor(() =>
      expect(document.querySelectorAll('.route-svg-overlay polyline')).toHaveLength(4),
    )
    const firstSvg = document.querySelector('.route-svg-overlay') as SVGSVGElement
    expect(firstSvg.style.zIndex).toBe('5')
    expect(firstSvg.style.overflow).toBe('visible')
    expect(firstSvg.querySelectorAll('polyline')[0].getAttribute('points')).toBe('220,110 230,120')
    expect(firstSvg.querySelectorAll('polyline')[2].getAttribute('points')).toBe('320,210 330,220')

    const nextRoute: Route = {
      ...route,
      geometry: { ...geometry, coordinates: [geometry.coordinates[0]] },
    }
    rendered.rerender(
      <KakaoMap origin={origin} destination={null} route={nextRoute} onMessage={vi.fn()} />,
    )
    await waitFor(() =>
      expect(document.querySelectorAll('.route-svg-overlay polyline')).toHaveLength(2),
    )
    expect(FakeAbstractOverlay.instances[0].setMap).toHaveBeenCalledWith(null)
    expect(document.querySelectorAll('.route-svg-overlay')).toHaveLength(1)

    expect(rendered.customOverlays).toHaveLength(4)
    rendered.rerender(
      <KakaoMap origin={origin} destination={null} route={null} onMessage={vi.fn()} />,
    )
    await waitFor(() => expect(document.querySelectorAll('.route-svg-overlay')).toHaveLength(0))
    rendered.customOverlays.forEach((overlay) => expect(overlay.setMap).toHaveBeenCalledWith(null))

    rendered.unmount()
    expect(FakeAbstractOverlay.instances.at(-1)?.setMap).toHaveBeenCalledWith(null)
    expect(document.querySelectorAll('.route-svg-overlay')).toHaveLength(0)
  })

  it('leg geometry의 여러 선 조각을 하나의 polyline으로 이어 그린다', async () => {
    const route: Route = {
      id: 'route-leg-geometry',
      label: '도보 경로',
      minutes: 5,
      transfers: 0,
      modes: ['walk'],
      legs: [
        {
          mode: 'walk',
          title: '도보',
          note: '도보',
          minutes: 5,
          geometry: {
            type: 'MultiLineString',
            coordinates: [
              [
                [127, 37.5],
                [127.01, 37.51],
              ],
              [
                [127.02, 37.52],
                [127.03, 37.53],
              ],
            ],
          },
        },
      ],
    }
    const rendered = renderMap({ route })

    await waitFor(() => {
      const lines = document.querySelectorAll('.route-svg-overlay polyline')
      expect(lines).toHaveLength(2)
      expect(lines[0].getAttribute('points')).toBe('220,110 230,120 240,130 250,140')
    })

    for (const mode of ['subway', 'bus'] as const) {
      rendered.rerender(
        <KakaoMap
          origin={origin}
          destination={null}
          route={{
            ...route,
            id: `route-${mode}-geometry`,
            modes: [mode],
            legs: route.legs.map((leg) => ({ ...leg, mode })),
          }}
          onMessage={vi.fn()}
        />,
      )
      await waitFor(() =>
        expect(document.querySelectorAll('.route-svg-overlay polyline')).toHaveLength(4),
      )
    }
  })

  it('지하철·버스 geometry에 실제 혼잡 색상과 승차·환승·하차 marker를 관리한다', async () => {
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
          segmentCongestionLevel: 20,
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
          segmentCongestionLevel: 50,
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
      expect(document.querySelectorAll('.route-svg-overlay polyline')).toHaveLength(4),
    )
    const routeLines = document.querySelectorAll('.route-svg-overlay polyline')
    expect(routeLines[0].getAttribute('stroke')).toBe('#fff')
    expect(routeLines[0].getAttribute('stroke-width')).toBe('12')
    expect(routeLines[1].getAttribute('stroke')).toBe('#1d4ed8')
    expect(routeLines[1].getAttribute('stroke-width')).toBe('8')
    expect(routeLines[2].getAttribute('stroke')).toBe('#fff')
    expect(routeLines[2].getAttribute('stroke-width')).toBe('12')
    expect(routeLines[3].getAttribute('stroke')).toBe('#15803d')
    expect(routeLines[3].getAttribute('stroke-width')).toBe('8')
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

  it('백엔드 구간 혼잡도 숫자를 등급 색상으로 변환한다', async () => {
    const route: Route = {
      id: 'route-preview-congestion',
      label: '혼잡도 시안 경로',
      minutes: 14,
      transfers: 0,
      modes: ['subway'],
      legs: Array.from({ length: 4 }, (_, index) => ({
        mode: index % 2 === 0 ? ('subway' as const) : ('bus' as const),
        title: `구간 ${index + 1}`,
        note: '시안 구간',
        minutes: 3,
        segmentCongestionLevel: [20, 50, 80, 110][index],
        geometry: {
          type: 'MultiLineString' as const,
          coordinates: [
            [
              [127.03 + index * 0.01, 37.5 + index * 0.01],
              [127.04 + index * 0.01, 37.51 + index * 0.01],
            ],
          ],
        },
      })),
    }
    renderMap({ route })

    await waitFor(() => {
      const lines = document.querySelectorAll('.route-svg-overlay polyline')
      expect(lines).toHaveLength(8)
      expect(
        Array.from(lines)
          .filter((_, index) => index % 2 === 1)
          .map((line) => line.getAttribute('stroke')),
      ).toEqual(['#1d4ed8', '#15803d', '#b91c1c', '#7e22ce'])
    })
  })

  it('선택 경로에 구간 등급이 있으면 네 단계 범례를 표시한다', () => {
    renderMap({
      route: {
        id: 'route-congestion',
        label: '혼잡도 경로',
        minutes: 8,
        transfers: 0,
        modes: ['subway'],
        legs: [
          {
            mode: 'subway',
            title: '2호선',
            note: '2호선',
            minutes: 8,
            segmentCongestionLevel: 110,
          },
        ],
      },
    })

    const legend = screen.getByRole('group', { name: '구간 혼잡도 범례' })
    expect(legend.textContent).toBe('여유보통혼잡포화')
  })

  it('개발용 혼잡도 미리보기는 지도 연결 전에도 구간 색을 보여준다', async () => {
    history.replaceState(null, '', '?preview=congestion#detail')
    mocks.loadKakaoMaps.mockRejectedValueOnce(new Error('카카오 키 없음'))
    renderMap({
      route: {
        id: 'route-preview',
        label: '혼잡도 시안 경로',
        minutes: 8,
        transfers: 0,
        modes: ['subway'],
        legs: [
          {
            mode: 'subway',
            title: '2호선',
            note: '역삼역 → 선릉역',
            minutes: 8,
            segmentCongestionLevel: 80,
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
        ],
      },
    })

    const preview = screen.getByRole('img', { name: '혼잡도 경로 시안 지도' })
    expect(preview.querySelector('.congestion-preview-line')?.getAttribute('data-grade')).toBe(
      'CONGESTED',
    )
    expect(preview.querySelector('.congestion-preview-line')?.getAttribute('stroke')).toBe(
      '#b91c1c',
    )
    expect(screen.getByText('시안 지도 · 카카오 지도 연결 전')).toBeTruthy()
    await waitFor(() => expect(screen.getByText('지도를 불러오지 못했어요')).toBeTruthy())
  })

  it('자전거 경계 marker는 일반 대여소 아이콘으로 만들고 경로 해제 시 정리한다', async () => {
    const route: Route = {
      id: 'route-bike-markers',
      label: '따릉이 경로',
      minutes: 8,
      transfers: 0,
      modes: ['bike'],
      legs: [
        {
          mode: 'bike',
          title: '따릉이 이동',
          note: '대여소에서 반납소까지',
          minutes: 8,
          from: { id: 'bike-rental', name: '대여소', lat: 37.5, lng: 127.03 },
          to: { id: 'bike-return', name: '반납소', lat: 37.52, lng: 127.05 },
        },
      ],
    }
    const rendered = renderMap({ route })
    await waitFor(() => expect(rendered.customOverlays).toHaveLength(2))

    const contents = rendered.customOverlays.map(
      (overlay) => (overlay.options as { content: HTMLButtonElement }).content,
    )
    expect(contents.every((content) => content.className === 'bike-station-marker')).toBe(true)
    expect(contents.every((content) => !content.classList.contains('route-active'))).toBe(true)
    expect(
      rendered.customOverlays.every(
        (overlay) => (overlay.options as { zIndex?: number }).zIndex === 10,
      ),
    ).toBe(true)
    mocks.stock.mockReset()
    fireEvent.click(contents[0])
    expect(mocks.stock).not.toHaveBeenCalled()

    rendered.rerender(
      <KakaoMap origin={origin} destination={null} route={null} onMessage={vi.fn()} />,
    )
    await waitFor(() =>
      rendered.customOverlays.forEach((overlay) =>
        expect(overlay.setMap).toHaveBeenCalledWith(null),
      ),
    )
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
      expect(document.querySelectorAll('.route-svg-overlay polyline')).toHaveLength(2),
    )
    const map = FakeMap.instances[0]
    const setBoundsCalls = map.setBounds.mock.calls.length

    act(() => FakeResizeObserver.trigger())

    expect(map.setBounds.mock.calls.length).toBeGreaterThan(setBoundsCalls)
    expect(map.setCenter).toHaveBeenCalledTimes(1)
  })

  it('SDK 준비 후 경로 bounds보다 live 위치 추적이 우선하고 resize 시 사용자 드래그를 유지한다', async () => {
    const route: Route = {
      id: 'route-live-camera',
      label: '길안내 경로',
      minutes: 8,
      transfers: 0,
      modes: ['walk'],
      legs: [],
      geometry: {
        type: 'MultiLineString',
        coordinates: [
          [
            [127.01, 37.49],
            [127.04, 37.52],
          ],
        ],
      },
    }
    const rendered = renderMap({
      route,
      livePosition: { latitude: 37.5, longitude: 127.03, accuracy: 7 },
    })
    await waitFor(() => expect(document.querySelector('.route-svg-overlay')).not.toBeNull())
    const map = FakeMap.instances[0]
    expect(map.setBounds).toHaveBeenCalledOnce()
    expect(map.panTo).toHaveBeenCalledOnce()

    const boundsCalls = map.setBounds.mock.calls.length
    const panCalls = map.panTo.mock.calls.length
    act(() => FakeResizeObserver.trigger())
    expect(map.setBounds).toHaveBeenCalledTimes(boundsCalls)
    expect(map.panTo).toHaveBeenCalledTimes(panCalls + 1)

    act(() => map.dragStart?.())
    const preservedCenter = map.getCenter()
    const pausedPanCalls = map.panTo.mock.calls.length
    act(() => FakeResizeObserver.trigger())
    expect(map.setCenter).toHaveBeenLastCalledWith(preservedCenter)
    expect(map.panTo).toHaveBeenCalledTimes(pausedPanCalls)
    rendered.unmount()
  })
})

describe('지도 영역 크기 계산', () => {
  afterEach(() => vi.restoreAllMocks())

  // jsdom은 레이아웃이 없어 클래스별 높이를 프로토타입 getter로 지정한다.
  function renderInShell(heights: Record<string, number>) {
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function (
      this: HTMLElement,
    ) {
      return heights[this.className] ?? 0
    })
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.className === 'test-shell' ? 800 : 0
    })
    mocks.loadKakaoMaps.mockResolvedValue(fakeMaps([], vi.fn(), []))
    const { container } = render(
      <div className="test-shell">
        {Object.keys(heights).map((className) => (
          <div key={className} className={className} />
        ))}
        <KakaoMap origin={null} onMessage={vi.fn()} />
      </div>,
    )
    return container.querySelector<HTMLElement>('.kakao-map-wrap')!
  }

  it('.home-topbar가 셸 안에 있어도 지도 top은 0이고 높이는 셸에서 바텀시트만 뺀다', () => {
    const wrapper = renderInShell({ 'home-topbar': 200, 'bottom-sheet': 300 })
    expect(wrapper.style.top).toBe('0px')
    expect(wrapper.style.height).toBe('500px')
  })

  it('.home-panel이 보이면 그 높이만큼 지도 top이 내려가고 높이가 줄어든다', () => {
    const wrapper = renderInShell({ 'home-topbar': 200, 'home-panel': 120, 'bottom-sheet': 300 })
    expect(wrapper.style.top).toBe('120px')
    expect(wrapper.style.height).toBe('380px')
  })
})

describe('따릉이 재고 조회', () => {
  const bike = { ...origin, id: 'bike-station:ST-1', name: '시험 대여소', kind: '따릉이 대여소' }
  const bikeRoute: Route = {
    id: 'bike-stock-route',
    label: '따릉이 경로',
    minutes: 8,
    transfers: 0,
    modes: ['bike'],
    legs: [
      {
        mode: 'bike',
        title: '따릉이 이동',
        note: '대여소에서 반납소까지',
        minutes: 8,
        from: {
          id: 'bike-rental',
          name: '시험 대여소',
          lat: 37.498,
          lng: 127.028,
          rentalId: 'ST-1',
        },
        to: {
          id: 'bike-return',
          name: '두 번째',
          lat: 37.52,
          lng: 127.05,
          rentalId: 'ST-2',
        },
      },
    ],
  }
  it.each([
    ['AVAILABLE', 0, '대여 가능한 자전거가 없어요.'],
    ['AVAILABLE', 7, '현재 대여할 수 있어요.'],
    ['STALE', 7, '마지막 확인 재고예요. 최신 정보가 아닐 수 있어요.'],
    ['UNAVAILABLE', null, '현재 실시간 재고를 확인할 수 없어요.'],
  ])('%s 재고 %s를 구분한다', async (status, count, label) => {
    mocks.stock.mockResolvedValue({
      rentalId: 'ST-1',
      status,
      availableBikes: count,
      stockUpdatedAt: count === null ? null : '2026-09-17T10:00:00+09:00',
    })
    const rendered = renderMap({ origin: bike, route: bikeRoute })
    await waitFor(() => expect(rendered.customOverlays).toHaveLength(2))
    clickBikeMarker(rendered)
    expect(await screen.findByText(label as string)).toBeTruthy()
    expect(mocks.stock).toHaveBeenCalledWith('ST-1', expect.any(AbortSignal))
  })
  it('실패 후 재시도하며 닫은 뒤 늦은 응답을 반영하지 않는다', async () => {
    let resolveStock!: (value: unknown) => void
    mocks.stock.mockRejectedValueOnce(new Error('network')).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveStock = resolve
        }),
    )
    const rendered = renderMap({ origin: bike, route: bikeRoute })
    await waitFor(() => expect(rendered.customOverlays).toHaveLength(2))
    clickBikeMarker(rendered)
    expect(
      screen.getByRole('region', { name: '따릉이 실시간 재고' }).querySelector('.sheet-grip'),
    ).toBeNull()
    fireEvent.click(await screen.findByRole('button', { name: '다시 시도' }))
    const signal = mocks.stock.mock.calls[1][1] as AbortSignal
    fireEvent.click(screen.getByRole('button', { name: '재고 정보 닫기' }))
    expect(signal.aborted).toBe(true)
    await act(async () =>
      resolveStock({
        rentalId: 'ST-1',
        status: 'AVAILABLE',
        availableBikes: 9,
        stockUpdatedAt: '2026-09-17T10:00:00+09:00',
      }),
    )
    expect(screen.queryByRole('region', { name: '따릉이 실시간 재고' })).toBeNull()
  })
  it('새 선택의 재고를 이전 요청의 늦은 응답으로 덮어쓰지 않는다', async () => {
    let resolveFirst!: (value: unknown) => void
    mocks.stock
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve
          }),
      )
      .mockResolvedValueOnce({
        rentalId: 'ST-2',
        status: 'AVAILABLE',
        availableBikes: 2,
        stockUpdatedAt: '2026-09-17T10:00:00+09:00',
      })
    const rendered = renderMap({ origin: bike, route: bikeRoute })
    await waitFor(() => expect(rendered.customOverlays).toHaveLength(2))
    clickBikeMarker(rendered)
    const signal = mocks.stock.mock.calls[0][1] as AbortSignal
    clickBikeMarker(rendered, 1)
    expect(await screen.findByText('2대')).toBeTruthy()
    expect(signal.aborted).toBe(true)
    await act(async () =>
      resolveFirst({
        rentalId: 'ST-1',
        status: 'AVAILABLE',
        availableBikes: 9,
        stockUpdatedAt: '2026-09-17T10:00:00+09:00',
      }),
    )
    expect(screen.queryByText('9대')).toBeNull()
  })
  it('대여소 표시 토글은 기본 켜짐이며 껐다가 켤 수 있다', () => {
    renderMap()
    fireEvent.click(screen.getByRole('button', { name: '따릉이 대여소 숨기기' }))
    expect(
      screen.getByRole('button', { name: '따릉이 대여소 보이기' }).getAttribute('aria-pressed'),
    ).toBe('false')
    fireEvent.click(screen.getByRole('button', { name: '따릉이 대여소 보이기' }))
    expect(
      screen.getByRole('button', { name: '따릉이 대여소 숨기기' }).getAttribute('aria-pressed'),
    ).toBe('true')
    expect(mocks.stock).not.toHaveBeenCalled()
  })
})
