# 코드 구조와 책임

## 구조

```text
src/
  main.tsx                  React 진입점, 전역 CSS
  App.tsx                   지도·페이지·모달을 조립하는 앱 셸
  app/
    useNavigation.ts        해시 URL과 브라우저 뒤로 가기
    useRoutePlanner.ts      검색 → 상세 → 안내 흐름 연결
    preview.ts              미리보기 초기 상태와 제안 경로
    PreviewToolbar.tsx      제품 화면 밖의 시나리오 조작
    opsAccess.ts            운영자 뷰 노출 조건(DEV 또는 VITE_OPS_VIEW)
  pages/                    Home, Browse, Search, Results, Detail, Arrival
                            HomePage는 상단 검색창·칩·레이어 토글·최근 경로 시트
                            OpsPage.tsx 운영자 뷰(개발 전용 진입점)
  components/
    Modal.tsx               네이티브 dialog, 공통 닫기 동작
    BottomSheet.tsx         손잡이·본문·고정 푸터 배치
    useBottomSheet.ts       드래그, 높이 상태, 키보드 조작
    useToast.ts             일시적인 안내 문구
  features/
    route/                  경로 타입·계산·카드·구간 목록·필터·검색/선택 상태·즐겨찾기·최근 검색 저장
    guidance/               독립된 안내 세션, 안내 복귀 바, 안내 관련 모달
    ops/                    운영자 뷰: 지도 훅·재고 레이어·히트맵·데이터 상태
  map/                    지도 컴포넌트, 지도 위치 선택, 대여소 마커, SDK 수명 관리, 현재 위치 훅, 홈 레이어 토글(homeLayers·HomeLayerToggle), 재고 배지(bikeStockBadge)·홈 레이어 상태(useHomeMapLayers)·대여소 카드(BikeStationCard)·재고/예측 훅(useBikeStationOutlook), 역 마커(stationMarkers)·주변 역 조회(useNearbyStationCongestion)·역 카드(StationCard)·도착/시간대 훅(useStationArrivals·useStationHourlyCongestion·congestionAdvice)
  api/
    contracts.ts            데이터 접근 인터페이스
    repositories.ts         실제로 사용할 구현 선택
    ops.ts                  운영자 뷰 BE 저장소와 응답 검증
    mock/                   샘플 장소·경로와 비동기 구현, 운영자 뷰 샘플(opsFixtures·opsRepositories)
  lib/kakao/sdk.ts           SDK 타입, 스크립트 1회 로드와 재시도
  styles.css                공통 토큰과 화면 스타일
```

## 의존 방향

`App → pages / 기능 컴포넌트`로 화면을 구성한다. `app/useRoutePlanner → useTrip / useGuidance / useNavigation`으로 여러 기능이 만나는 흐름만 연결한다. 결과 화면은 지도와 바텀시트를 사용하지 않고 `ResultsPage`가 전체 세로 스크롤 목록을 소유한다.

- 페이지는 전달받은 값과 이벤트로 화면을 그린다. 샘플 파일이나 SDK를 직접 읽지 않는다.
- `DetailPage`는 경로 상세와 활성 길안내를 같은 지도·바텀시트에서 렌더링한다. `RouteTimeline`이 실제 구간 인덱스를 보존한 승차·하차·환승 목록을 표시하고, `BikePrediction`의 현재 재고와 도착 예측도 두 상태에서 유지한다. 화면 스타일은 `DetailPage.css`, 타임라인 스타일은 `RouteTimeline.css`에 둔다.
- 타임라인은 교통수단 아이콘과 세로 노선선으로 승하차를 연결한다. 노선명·방면·구간 혼잡도를 노선선 옆에 표시하며 출발·도착 이름과 완전히 같은 endpoint pair만 중복 제거한다. 환승 등 실제 leg는 합치거나 생략하지 않는다. 상세 시트의 기본 높이는 내용에 맞추되 최대 76%로 제한하며, 사용자가 펼치면 기존 94% 높이를 유지한다.
- 검색 결과 카드와 상세·안내 요약의 이동 시간 막대는 `RouteModeStrip`을 공유한다. 구간은 이동 시간 비율로 폭을 배정하고 짧은 구간은 44px까지 보장한다. 구간이 많아지면 44px 최소 폭을 컨테이너 폭을 구간 수로 나눈 값까지 낮춰 flex로 함께 줄어든다. 구간 축약·폭 비율·노선 색상·환승 아이콘과 좁은 폭의 표시 규칙을 동일하게 유지한다. 검색 결과 카드는 막대 위 혼잡도 라벨을 숨기고 각 승차역 행의 노선명 왼쪽에 구간 등급을 표시한다. 상세·안내 요약은 기존 막대 위 라벨을 유지한다.
- `SearchPage`의 검색어는 페이지 내부 상태이며 `usePlaceSearch`가 데이터 조회를 맡는다. 최근 검색·즐겨찾기 저장은 `recentPlaces`·`favoritePlaces` 모듈이 맡는다.
- `HomePage`는 `BottomSheet`를 항상 렌더링한다. 지도 훅이 마운트 때 `.home-panel`·`.bottom-sheet` 높이를 한 번 찾아 관찰하므로 시트를 조건부로 렌더링하지 않는다. `.home-topbar`는 지도 위에 겹치는 오버레이라 관찰·차감하지 않는다. 홈은 길찾기 입력 패널이 열린 채 시작하며(`routePanelOpen` 초기 true), 집·회사·즐겨찾기 칩 행(`FavoriteChips`)은 패널 안과 상단 바 두 곳에서 같은 컴포넌트로 그린다.
- `useRoutePlanner.findRoutesFrom`은 저장된 출발·도착으로 바로 검색한다(최근 경로 탭). 출발지 상태 반영과 검색을 같은 틱에서 하기 위해 `trip.search(destination, origin)`을 직접 호출한다.
- 홈에서는 `KakaoMap`이 대여소 선택만 `onBikeStationSelect`로 알리고 지도 안 재고 시트·대여소 토글을 열지 않는다. 카드는 `HomePage`가 홈 시트 안에 그린다. 상세·탐색 화면의 지도 안 `BikeStockSheet`와 토글은 그대로다.
- `useKakaoMap`은 `bikeStationsVisible`·`bikeStockBadges`가 바뀌면 다음 idle을 기다리지 않고 마커를 다시 맞춘다. nearby 재조회 결과는 기존 마커의 `setBadge`로 반영한다.
- 역 데이터는 App의 `useNearbyStationCongestion`이 가져오고 `KakaoMap`은 `stationMarkers` prop을 오버레이로만 동기화한다(지도 훅이 idle 때 `onViewportChange`로 중심을 알린다). 따릉이 nearby는 지도 훅 안에 남아 있다(과거 결정).
- 역 카드의 도착·시간대별 조회 훅은 카드 컴포넌트가 소유한다(카드가 열릴 때만 요청, `key`로 리셋). 대여소 카드가 App에서 훅을 받는 것과 다르다.
- 혼잡도 등급·색은 `features/route/segmentCongestion`을 재사용한다. 마커·막대·요약·범례가 같은 임계값을 쓴다.
- 기능 훅은 `api/repositories`를 통해 데이터를 받는다. `api/contracts`는 화면용 타입을 참조하는 프론트엔드 인터페이스다.
- `selectors`와 reducer는 React·DOM·네트워크 없이 동작하는 함수다.
- `components`는 특정 경로 데이터나 화면 이름을 알지 않는다.
- 카카오 SDK 사용은 `features/map`과 `lib/kakao` 안으로 제한한다. 일반 지도와 장소 탐색 지도는 `useKakaoMap`, 지도 위치 선택은 `MapPlacePicker`, 현재 위치 조회는 `useCurrentLocation`이 맡는다. `KakaoMap`은 경로 장소 또는 탐색 결과 배열을 받아 마커를 관리한다.
- 길안내의 지속 위치 추적은 `useGuidance`가 소유하며 `locationProgress`에서 도착 지점과 거리·직접 확인 행동을 판정한다. `App`은 유효한 위치를 지도에 전달할 뿐 별도 위치 watch를 만들지 않는다. 지도는 기존 현재 위치 마커를 갱신하고 드래그 시 추종을 중단한다. 위치 갱신 때문에 지도나 경로 오버레이를 재생성하지 않는다.
- 따릉이 정적 데이터 변환과 선택용 `Place` 변환은 `features/map/bikeStations`, viewport 내 자전거 아이콘 오버레이는 `features/map/bikeStationMarkers`가 맡는다. 선택 결과는 기존 장소 선택 흐름으로 전달한다.
- 미리보기 시나리오용 제안 경로는 `app/preview`에서 주입한다. 초기 후보·선택 경로를 기능 훅 내부에 숨겨 넣지 않는다.
- 운영자 뷰 진입은 `app/opsAccess`가 개발 빌드이거나 `VITE_OPS_VIEW=true`일 때만 연다. `useNavigation`과 `resolveScreen`이 같은 검사를 쓴다. 노출 범위 제한이지 접근 제어가 아니다.
- `OpsPage`는 앱 셸·`useKakaoMap`·`PreviewToolbar` 없이 렌더링한다. `App`이 `screen === 'ops'`일 때 페이지만 반환한다.
- `features/ops/useOpsMap`은 별도 지도 훅이며 `lib/kakao` 로더와 `features/map/bikeStationMarkers`만 가져온다. `useKakaoMap`은 바텀시트 높이 관찰과 경로·장소 마커에 묶여 있어 재사용하지 않는다.
- `features/ops/useOpsData`가 조회 상태를 소유한다. 탭이 보일 때만 주기적으로 다시 조회하고, 지도 bbox가 바뀌면 재조회한다. 요청은 `AbortController`로 취소한다. 이전 data가 있으면 재조회 중에도 data를 유지하고 `refreshing`만 켜며, 재조회 실패 시에도 data를 유지한 채 `error`를 함께 둔다(data가 없을 때만 전체 로딩·오류 화면).
- 운영자 뷰 mock은 `VITE_OPS_MOCK=true`일 때만 쓴다. 실제 API 실패를 mock으로 대체하지 않으며, mock 데이터에는 화면에 "샘플" 배지를 표시한다.

타입을 참조하는 의존성은 `import type`으로 명시한다. 페이지의 `Navigate` 타입 참조는 화면 이동 계약이며, 페이지에서 앱 상태를 직접 조회하는 것은 아니다.

## 수정 위치 안내

| 변경                                   | 시작할 파일                                                                                                                                |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| 카드 디자인                            | `features/route/RouteCard.tsx`, `styles.css`                                                                                               |
| 결과 화면 배치                         | `pages/ResultsPage.tsx`                                                                                                                    |
| 드래그 높이·키보드 동작                | `components/useBottomSheet.ts`                                                                                                             |
| 필터 취소·적용                         | `features/route/FilterDialog.tsx`, `tripReducer.ts`                                                                                        |
| 경로 정렬                              | `features/route/selectors.ts`                                                                                                              |
| 서버 경로 연결                         | `api/contracts.ts`, `api/repositories.ts`, `features/route/useTrip.ts`                                                                     |
| 길안내 단계                            | `features/guidance/guidanceReducer.ts`, `pages/DetailPage.tsx`                                                                             |
| 지도 수명·마커·크기                    | `features/map/useKakaoMap.ts`                                                                                                              |
| 홈 레이아웃(검색창·칩·시트)            | `pages/HomePage.tsx`, `styles.css`(`.home-*`)                                                                                              |
| 홈 시트 스냅·접힘 높이                 | `pages/HomePage.tsx`(`HOME_SHEET_COLLAPSED_HEIGHT`), `components/useBottomSheet.ts`, `styles.css`                                          |
| 지도 하단 컨트롤 배치                  | `features/map/KakaoMap.tsx`, `App.tsx`, `styles.css`                                                                                       |
| 홈 레이어 토글·가용 레이어             | `features/map/homeLayers.ts`, `features/map/HomeLayerToggle.tsx`                                                                           |
| 최근 경로 저장·표시 규칙               | `features/route/recentRoutes.ts`, `pages/HomePage.tsx`                                                                                     |
| 역 마커 모양·등급 색                   | `features/map/stationMarkers.ts`, `styles.css`(`.station-marker`)                                                                          |
| 주변 역 조회 반경·디바운스·재조회 기준 | `features/map/useNearbyStationCongestion.ts`                                                                                               |
| 역 카드 문구·요약 규칙                 | `features/map/StationCard.tsx`, `features/map/congestionAdvice.ts`                                                                         |
| 혼잡도 레이어 노출 조건                | `features/map/homeLayers.ts`                                                                                                               |
| 대여소 배지 등급·색                    | `features/map/bikeStockBadge.ts`, `styles.css`(`.bike-stock-badge`)                                                                        |
| 대여소 카드 문구·시점 규칙             | `features/map/BikeStationCard.tsx`(`describeOutlookSlot`)                                                                                  |
| 홈 레이어·선택 대여소 상태             | `features/map/useHomeMapLayers.ts`, `App.tsx`                                                                                              |
| 즐겨찾기 저장 규칙·칩                  | `features/route/favoritePlaces.ts`, `pages/HomePage.tsx`, `pages/SearchPage.tsx`                                                           |
| 일반 장소 탐색 화면                    | `pages/BrowsePage.tsx`, `features/route/usePlaceSearch.ts`                                                                                 |
| 지도에서 위치 선택                     | `features/map/MapPlacePicker.tsx`                                                                                                          |
| 위치 권한·오류                         | `features/map/useCurrentLocation.ts`                                                                                                       |
| 운영자 뷰 진입·노출 조건               | `app/opsAccess.ts`, `app/useNavigation.ts`                                                                                                 |
| 운영자 뷰 레이아웃                     | `pages/OpsPage.tsx`, `styles.css`(`.ops-*`)                                                                                                |
| 대여소 재고 마커 색·라벨               | `features/ops/bikeStockLayer.ts`, `features/ops/useOpsData.ts`(`stockLevel`)                                                               |
| 히트맵 색 구간·셀 상세                 | `features/ops/CongestionHeatmap.tsx`, `features/ops/useOpsData.ts`(`heatmapCellTone`), `features/route/segmentCongestion.ts`(등급 색·경계) |
| 운영자 뷰 BE 연결·응답 검증            | `api/ops.ts`, `api/contracts.ts`                                                                                                           |

## 유지한 단순함

- 공통 버튼의 클래스는 공유하지만, 모든 버튼을 새로운 래퍼 컴포넌트로 만들지는 않았다. 공통 로딩·비활성화·아이콘 규칙이 필요해지면 추출한다.
- 공통 스타일은 `styles.css`에 두고, 경로 상세와 타임라인 스타일만 각각의 CSS로 분리한다.
- 라우팅은 기존 해시 방식을 유지한다. 중첩 경로·라우트별 데이터 로딩 등이 필요하면 라우터 도입을 검토한다.
- `useRoutePlanner`는 업무 규칙의 저장소가 아니다. 계산과 상태 변경 규칙은 각 기능에 두고, 화면 이동과 기능 간 호출만 연결한다.

## 지도와 레이아웃 사이의 계약

지도 래퍼는 `z-index: 0`으로 별도 쌓임 맥락을 만든다. SDK 내부의 타일·마커가 앱의 길안내 헤더와 버튼을 덮지 않도록 이 경계를 유지한다. 지도 위치 선택기는 검색 화면의 전체 영역을 직접 관리하고, 일반 지도 훅의 시트 높이 계산을 재사용하지 않는다. 결과 화면에서는 지도 래퍼를 마운트하지 않아 경로 카드를 전체 높이로 스크롤한다.

앱 셸은 `.page-viewport`와 안내 복귀 바를 세로로 배치한다. 복귀 바는 화면 영역 밖에 높이를 확보해 시트의 버튼이나 지도 출처 표시를 덮지 않는다. 현재 지도 훅은 부모 `.page-viewport`와 그 안의 `.bottom-sheet` 또는 `.home-panel` 높이를 관찰해 실제 지도 영역을 맞춘다. 홈에서는 `.home-topbar`를 관찰하지도 지도 높이에서 빼지도 않고(오버레이), 열린 `.home-panel`과 홈 시트(`.home-sheet`)만 차감한다. 지도 하단 컨트롤은 `KakaoMap`의 `bottomControls` 슬롯이 맡는다. `start`는 좌측 하단(홈에서는 레이어 범례), `end`는 우측 하단의 현재 위치 버튼 아래(홈에서는 레이어 토글)에 놓이며, 지도 래퍼 안에 있어 시트 높이를 따라 움직인다. 슬롯 내용은 `App`이 넘기고 `HomePage`는 토글·범례를 렌더링하지 않는다. 상세와 안내는 지도 key를 `route`로 공유하고 같은 `DetailPage`를 유지하여 안내 시작 시 지도·시트 높이·스크롤이 초기화되지 않는다. 나머지 화면은 `key={screen}`으로 다시 마운트한다. 이 클래스나 DOM 배치를 바꾸면 지도 크기·마커·카카오 출처 표시를 함께 확인한다.

운영자 뷰 지도 래퍼(`.ops-map-wrap`)도 `position: relative; z-index: 0`을 유지해 SDK 내부 요소가 페이지의 다른 영역을 덮지 않게 한다. 이 지도는 바텀시트가 없으므로 시트·`.page-viewport` 높이 관찰 로직의 대상이 아니며, 지도 높이는 `.ops-map`의 CSS가 정한다.
