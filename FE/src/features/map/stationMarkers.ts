import type { KakaoMapInstance, KakaoMaps } from '../../lib/kakao/sdk'
import { segmentCongestionPresentation } from '../route/segmentCongestion'
import type { SegmentCongestionGrade } from '../route/types'

export interface StationMarkerDatum {
  stationId: string
  stationName: string
  lat: number
  lng: number
  grade: SegmentCongestionGrade | null
}

export interface StationOverlay {
  element: HTMLButtonElement
  setGrade(grade: SegmentCongestionGrade | null): void
  setSelected(selected: boolean): void
  destroy(): void
}

const NO_INFO_LABEL = '정보 없음'

function gradeLabel(grade: SegmentCongestionGrade | null) {
  return (grade && segmentCongestionPresentation(grade)?.label) || NO_INFO_LABEL
}

export function stationMarkerLabel(name: string, grade: SegmentCongestionGrade | null): string {
  return grade ? `${name} · 지금 ${gradeLabel(grade)}` : `${name} · ${NO_INFO_LABEL}`
}

function gradeClass(grade: SegmentCongestionGrade | null) {
  return `grade-${grade ? grade.toLowerCase() : 'none'}`
}

/** 역 이름과 현재 혼잡 등급을 보여 주는 지도 핀. 좌표 위에 띄우므로 CSS transform으로 위치를 맞춘다. */
export function createStationOverlay(
  maps: KakaoMaps,
  map: KakaoMapInstance,
  datum: StationMarkerDatum,
  selected: boolean,
  onSelect: () => void,
  zIndex = 2,
): StationOverlay {
  const element = document.createElement('button')
  element.type = 'button'
  const dot = document.createElement('span')
  dot.className = 'station-marker-dot'
  const name = document.createElement('span')
  name.className = 'station-marker-name'
  name.textContent = datum.stationName
  const gradeElement = document.createElement('span')
  gradeElement.className = 'station-marker-grade'
  element.append(dot, name, gradeElement)

  const setGrade = (grade: SegmentCongestionGrade | null) => {
    element.className = `station-marker ${gradeClass(grade)}${
      element.classList.contains('selected') ? ' selected' : ''
    }`
    gradeElement.textContent = gradeLabel(grade)
    const label = stationMarkerLabel(datum.stationName, grade)
    element.setAttribute('aria-label', label)
    element.title = label
  }
  const setSelected = (value: boolean) => {
    element.classList.toggle('selected', value)
    element.setAttribute('aria-pressed', String(value))
  }
  setGrade(datum.grade)
  setSelected(selected)
  element.addEventListener('click', onSelect)
  const overlay = new maps.CustomOverlay({
    map,
    position: new maps.LatLng(datum.lat, datum.lng),
    content: element,
    clickable: true,
    zIndex,
  })
  return {
    element,
    setGrade,
    setSelected,
    destroy() {
      element.removeEventListener('click', onSelect)
      overlay.setMap(null)
    },
  }
}
