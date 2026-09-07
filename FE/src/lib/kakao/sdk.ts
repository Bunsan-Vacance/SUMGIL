export interface MapPoint {
  getLat(): number
  getLng(): number
}
export interface KakaoPlaceSearchResult {
  id: string
  place_name: string
  category_name?: string
  category_group_code?: string
  category_group_name?: string
  phone?: string
  address_name?: string
  road_address_name?: string
  x: string
  y: string
  place_url?: string
  distance?: string
}
export interface KakaoAddressSearchResult {
  address_name: string
  address_type?: string
  x: string
  y: string
}
export interface MapBounds {
  extend(point: MapPoint): void
}
export interface KakaoMapInstance {
  relayout(): void
  getCenter(): MapPoint
  setCenter(point: MapPoint): void
  setBounds(bounds: MapBounds, top?: number, right?: number, bottom?: number, left?: number): void
  panTo(point: MapPoint): void
}
export interface MapOverlay {
  setMap(map: KakaoMapInstance | null): void
}
export interface KakaoMaps {
  load(callback: () => void): void
  LatLng: new (lat: number, lng: number) => MapPoint
  LatLngBounds: new () => MapBounds
  Map: new (
    container: HTMLElement,
    options: { center: MapPoint; level: number },
  ) => KakaoMapInstance
  Marker: new (options: { map: KakaoMapInstance; position: MapPoint; title?: string }) => MapOverlay
  Polyline: new (options: {
    map: KakaoMapInstance
    path: MapPoint[]
    strokeWeight: number
    strokeColor: string
    strokeOpacity: number
    strokeStyle: string
  }) => MapOverlay
  services: {
    Places: new () => {
      keywordSearch(
        query: string,
        callback: (results: KakaoPlaceSearchResult[], status: string) => void,
      ): void
    }
    Geocoder: new () => {
      addressSearch(
        query: string,
        callback: (results: KakaoAddressSearchResult[], status: string) => void,
      ): void
    }
    Status: { OK: string; ZERO_RESULT: string; ERROR: string }
  }
}
declare global {
  interface Window {
    kakao?: { maps: KakaoMaps }
  }
}

let pending: Promise<KakaoMaps> | null = null
export function loadKakaoMaps(): Promise<KakaoMaps> {
  if (pending) return pending
  const key = import.meta.env.VITE_KAKAO_MAP_APP_KEY?.trim()
  if (!key) return Promise.reject(new Error('missing-key'))
  pending = new Promise<KakaoMaps>((resolve, reject) => {
    const script = document.createElement('script')
    let settled = false
    const timeout = window.setTimeout(() => fail(), 15000)
    const fail = () => {
      if (settled) return
      settled = true
      clearTimeout(timeout)
      script.remove()
      pending = null
      reject(new Error('sdk-unavailable'))
    }
    script.async = true
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(key)}&autoload=false&libraries=services`
    script.onerror = fail
    script.onload = () => {
      if (settled) return
      if (!window.kakao?.maps?.load) {
        fail()
        return
      }
      window.kakao.maps.load(() => {
        if (settled) return
        settled = true
        clearTimeout(timeout)
        resolve(window.kakao!.maps)
      })
    }
    document.head.append(script)
  })
  return pending
}
