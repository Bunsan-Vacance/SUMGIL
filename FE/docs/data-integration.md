# 데이터 접근과 API 연결

## 현재 연결 상태

| 영역                              | 실제 구현                                                                                                                                                                                                                                           | 연결 위치                                                                          |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| 지도 타일·장소 마커               | 카카오 JavaScript SDK + 장소 검색                                                                                                                                                                                                                   | `lib/kakao/sdk.ts`, `features/map/useKakaoMap.ts`                                  |
| 현재 위치                         | 브라우저 Geolocation, 홈 지도 준비 시 자동 1회 또는 홈 길찾기·출발 검색에서 사용자 버튼 클릭 시 1회. 자동 조회 성공 시 빈 출발지에 현재 위치를 반영                                                                                                 | `features/map/useCurrentLocation.ts`                                               |
| 지도 위치 선택                    | 카카오 지도 클릭 + 좌표 역지오코딩                                                                                                                                                                                                                  | `features/map/MapPlacePicker.tsx`                                                  |
| 검색 화면의 장소 후보             | 카카오 JavaScript SDK 장소·주소 검색                                                                                                                                                                                                                | `lib/kakao/sdk.ts`, `api/repositories.ts`                                          |
| 실제 경로 입력의 장소·역 후보     | 백엔드 역 검색과 카카오 장소·주소 검색 결과                                                                                                                                                                                                         | `api/repositories.ts`, `features/route/usePlaceSearch.ts`                          |
| 추천 경로                         | `VITE_API_BASE_URL` 설정 시 실제 API, 미설정 시 preview 샘플. `VITE_ROUTE_SEARCH_MOCK=true`면 경로만 API 형식 mock                                                                                                                                  | `api/repositories.ts`, `api/mock`                                                  |
| 정렬·이동수단 필터                | 요청 modes·priority는 서버에 전달한다. API 후보는 서버 응답 순서를 시작점으로 사용하고, 화면의 TIME은 시간순, COMFORT는 유효한 `congestionPrediction`만 혼잡도순으로 정렬하며 값이 없는 후보는 뒤에 둔다. preview fixture도 같은 화면 규칙을 따른다 | `api/repositories.ts`, `features/route`                                            |
| 경로선·실제 길찾기                | 응답 leg geometry를 연결하며 geometry가 없으면 직선으로 대체하지 않음                                                                                                                                                                               | `api/repositories.ts`, `features/map`                                              |
| 혼잡도·예측                       | `Route.congestionPrediction`의 퍼센트·서버 등급·데이터 상태·예측 근거를 mapper에서 검증·보존. `comfort.*`와 근거 없는 경로 전체 혼잡도는 사용하지 않음                                                                                              | `features/route/types.ts`, `api/routeMapper.ts`                                    |
| 구간 전환·대여소 ID               | 선택 `transitionType`과 명시 `rentalId`를 보존하고 기존 TRANSFER 응답과 호환                                                                                                                                                                        | `features/route/types.ts`, `api/routeMapper.ts`, `features/map/routeMapMarkers.ts` |
| 따릉이 대여소 데이터·지도 마커    | 백엔드 nearby 응답 또는 정적 JSON, CustomOverlay                                                                                                                                                                                                    | `api/repositories.ts`, `features/map/bikeStations.ts`                              |
| 실시간 열차 도착·잔여 경로 재탐색 | `VITE_GUIDANCE_MOCK=true` 또는 API 주소 미설정 시 mock, 그 외 백엔드 API                                                                                                                                                                            | `api/guidance.ts`, `features/guidance`, `app/useRoutePlanner.ts`                   |

### 따릉이 대여소 정적 데이터

지도 대여소 마커와 기존 장소 선택 흐름은 `src/data/bike-stations.json`을 사용한다. 원본은 작업공간의
`서울시 공공자전거 따릉이 대여소 마스터 정보.json`이며, `DATA` 3,430건 중 위도·경도가
모두 0인 77건을 제외한 3,353건을 생성 시점에 추출했다. 원본에는 알려진 갱신일이 없어
최신성은 보장하지 않으며, 실시간 대여 가능 자전거 수량은 포함하지 않는다. 대여소명은
`addr2`를 사용하고 비어 있으면 화면에는 `따릉이 대여소`를 표시한다. 주소는 `addr1`과
`addr2`를 합친 값이며, 내부 대여소 ID는 선택 장소 식별에만 사용하고 화면에는 노출하지 않는다.
지도를 축소하면 화면 기준으로 가까운 대여소를 숫자 그룹으로 묶고, 그룹 버튼을 누르면 해당 지역을 확대한다. `VITE_API_BASE_URL` 설정 시 지도 대여소는 nearby API를 사용하며, 요청 실패 시 정적 데이터로 대체하지 않는다.

백엔드 nearby 응답의 `dockCount`와 `distanceMeters`는 `Place`까지 보존해 선택 카드에
표시한다. 거치대 수는 실시간 자전거 재고가 아닌 전체 거치대 수이며, 거리는 해당 응답을
조회한 지도 중심 기준이다. 값이 없으면 해당 항목을 숨기고 주소가 없어도 대여소 이름과
메타데이터 카드를 표시한다.

일반 장소 검색은 카카오 JavaScript SDK의 키워드 검색을 사용하며 결과가 없으면 지오코더 주소 검색으로 재시도한다. 실제 경로 입력 검색은 백엔드 역 검색과 카카오 장소·주소 검색을 함께 제공한다. 역 ID가 출발지와 도착지 모두에 있으면 기존 역간 GET을 사용하고, 그 외에는 좌표와 장소명을 담은 coordinate POST를 사용한다. 일반 장소를 임의의 역으로 매핑하지 않으며, 화면 장소로 변환할 때 이름·주소·좌표를 검증하고 유효한 좌표가 없는 카카오 결과는 제외한다. 백엔드 역 결과는 좌표가 없어도 역 ID로 선택할 수 있다. 선택한 장소는 검색 화면의 최근 목록에 최대 10개까지 저장하며 현재 위치는 저장하지 않는다. 지도 선택은 `coord2Address(lng, lat)`으로 도로명·지번 주소를 표시하고, 주소를 찾지 못해도 좌표를 선택할 수 있다. SDK 콜백은 `AbortSignal`을 확인해 취소된 요청의 늦은 응답을 반영하지 않는다. 경로 조회는 `VITE_API_BASE_URL` 설정 시 백엔드, 미설정 시 기존 preview 샘플 저장소를 사용한다. `VITE_ROUTE_SEARCH_MOCK=true`를 명시하면 API base가 있어도 경로 검색만 최종 `ApiResult<List<RouteSearchResponse>>` fixture를 공용 mapper로 변환한다. 이 모드의 fixture 출처는 `MOCK`이며 서버가 준 후보 배열 순서와 중복 `ALTERNATIVE`를 그대로 유지한다. 역·장소·대여소 API는 API base 설정에 따라 계속 실제 연결을 사용한다.

## 프론트엔드 인터페이스

`api/contracts.ts`는 화면이 데이터를 받는 방식을 정의한다. **백엔드의 확정 API 명세가 아니다.**

- `PlaceRepository.search(query, signal): Promise<Place[]>`
- `RouteRepository.search({ origin, destination, modes?, priority?, departedAt? }, signal): Promise<Route[]>`
- `useTrip`은 검색 시 `modes`, 현재 `priority`, 검색 시각 또는 사용자가 선택한 오늘(Asia/Seoul)의 출발 시각 `departedAt`을 전달하며 WALK를 항상 포함한다. 필터 변경과 전체 수단 복원은 이미 목적지가 있고 검색된 상태에서만 같은 조건으로 재요청하고, priority 변경도 직전 출발 시각을 유지해 TIME/COMFORT로 재요청한다. 진행 중 요청은 취소하고 늦은 응답은 무시한다.
- `Route.departedAt`가 있으면 해당 시각을 기준으로 도착 예정 시각을 계산하고, 없으면 샘플의 `09:41` 기준을 유지한다. 백엔드 요청의 `departureTime`은 같은 순간을 Asia/Seoul 기준 timezone 없는 `LocalDateTime`으로 변환한다.
- `Route.congestionPrediction`·`source`·`walk`·`line`은 화면 모델의 선택 필드다. 예측 퍼센트는 0도 유효하고 100 초과도 보존한다. 카드·상세는 지하철 `worstSegment.congestionPercent`를 지도·구간과 같은 40/70/100 경계로 표시하며, 버스 최악 구간은 위치가 일치하는 leg의 서버 등급을 사용한다. 해당 정보가 없으면 서버 `congestionGrade`를 표시한다. 예측값이 없으면 `예측 정보 없음`을 표시하고 혼잡도 정렬·추천에서 제외한다. 모든 표시값은 서울 기준 D+0~D+3 예상값이며 `predictionBasis`는 `최근 7일 데이터 기반`·`일부 기간 데이터 기반`·`요일 평균 기준` 중 하나로 표시한다. 혼잡 사유 설명과 폐기된 구계약 필드는 사용하지 않는다. `walk`는 일반 비환승 WALK 구간의 `distanceMeters`가 있을 때만 합산하고, `line`과 구간 표시명은 `routeName`을 우선한다. 샘플·모델·UI가 지원하는 것과 BE 응답 매핑 여부를 구분한다.
- 역 ID가 있는 기존 GET `/api/routes/search`는 여러 경로 후보를 배열로 반환하며, 좌표 기반 POST `/api/routes/search/coordinate`도 같은 후보 변환 규칙을 사용한다. 요청 `modes`에는 `WALK`가 항상 포함되고 응답 구간에는 `WALK`·`TRANSFER`가 포함될 수 있다. 서버는 속도·혼잡 후보를 최대 6개까지 만들 수 있고, 저장소는 응답 후보와 중복 `ALTERNATIVE`를 보존한다. 화면은 TIME에서 시간순, COMFORT에서 유효한 `congestionPrediction`만 혼잡도순으로 정렬하고 예측값이 없는 후보를 뒤에 둔다. `LOW_CONGESTION`은 서버 분류를 근거로 하며, 혼잡 후보가 비어도 빠른 후보를 유지하고 mock·0%·임의 순위를 만들지 않는다. `SHORTEST`는 `빠른 경로`, `ALTERNATIVE`는 `다른 경로`, `SHORTEST_WITH_BIKE`는 `따릉이 포함 경로`로 표시한다. 요청한 이동수단으로 필터한 결과가 비어도 조회 성공으로 처리해 `해당 수단으로는 경로가 없어요`를 표시한다. 2026-09-22 확인한 `develop-BE` (`9815f8f`)는 `congestionPrediction`을 제공하는 계약이며, 실제 응답에 값이 없으면 예측 정보 없음으로 표시한다. `/api/congestion` 통계 응답을 신규 예측으로 변환하지 않는다.
- 지하철·버스 구간 혼잡도는 `legs[].congestionLevel` 선택 숫자 필드와 `legs[].congestionGrade` 선택 등급 필드(`RELAXED`/`NORMAL`/`CONGESTED`/`SATURATED`/`null`)로 받는다. 등급이 있으면 FE가 숫자로 다시 계산한 등급보다 우선하고, 숫자만 있으면 기존 퍼센트·등급 변환을 유지한다. 누락·null이면 표시하지 않으며 WALK·BIKE 구간에는 적용하지 않는다.
- 경로 구간 표시명은 서버 `routeName`을 우선하며, 없으면 `routeId`의 노선 매핑을 적용한다. `BIKE`는 `자전거`, `WALK`는 `도보`로 표시하고 원본 ID는 보존한다.
- BUS 구간의 `routeOptions`는 `{ routeId, routeName, headwayMin }` 목록으로 검증해 구간에 보존한다. `routeName`과 `headwayMin`은 null일 수 있으며, 상세 화면은 각 버스 번호와 확인 가능한 배차간격을 표시한다. 여러 노선이면 기본으로 접어 두고 펼치면 노선별 배차간격을 표시한다. 이 목록은 표시 전용이므로 별도 경로 후보를 만들거나 탐색·집계에 사용하지 않는다. `routeOptions: null`인 기존 응답은 종전의 다중 경로 그룹화 방식과 호환하고, 빈 배열은 해당 구간의 공통 운행 노선 정보가 없다는 뜻으로 표시한다.

화면의 `getRoutes`도 API 후보의 routeType을 확인해 허용 수단만 필터링하고 서버 배열 순서를 유지한다. 샘플 후보만 우선순위에 따라 로컬 정렬한다.

`api/repositories.ts`에서 사용할 구현을 선택한다. 페이지에서는 `fixtures`를 import하지 않는다. `app/preview.ts`는 초기 후보를 만들지 않고 미리보기 시나리오의 제안 경로만 주입한다.

조회 훅은 이전 요청을 `AbortController`로 취소하고 취소 후 도착한 결과를 무시한다. 구현을 교체할 때 `signal`을 실제 `fetch`에도 전달한다. 실패를 빈 성공 응답으로 바꾸지 않는다.

## 안내 API 계약 (2026-09-17)

지하철 구간의 실시간 도착 조회는 `GET /api/transit/arrivals?stationId=&routeId=`를 사용한다. 응답의 `status`는 `LIVE`, `NO_INFO`, `OUTSIDE_WINDOW`, `STALE`를 구분하며 `LIVE`일 때만 `trains`에 열차 후보가 있다. 화면은 세 빈 상태를 하나로 합치지 않고 각각 운행 정보 없음, 운행 시간 외, 정보 지연으로 안내한다.

잔여 경로 재탐색은 `POST /api/routes/replan`에 `step`, `boundaryId`, `destStationId`, `destLat`, `destLng`, `modes`, `priority`, `requestedAt`을 평면 JSON으로 보낸다. 응답 후보는 현재 단계 경계에서 목적지까지 이어지는지 검증한 뒤 안내 세션에만 반영한다. 안내 요청은 닫기·교체 시 취소하며 늦게 도착한 응답은 반영하지 않는다.

## 백엔드 연결 순서

1. 팀과 요청·응답·오류 형식을 합의한다. 임의 endpoint나 HTTP 응답 타입을 먼저 확정하지 않는다.
2. 서버 DTO와 화면용 `Place`/`Route` 타입의 차이를 확인한다. 서버 응답 검증과 변환은 데이터 접근 계층에 둔다.
3. `api`에 실제 저장소 구현을 추가하고 `api/repositories.ts`의 연결을 바꾼다. 기본 URL은 `VITE_API_BASE_URL` 환경 변수로 받는다.
4. 역 ID가 둘 다 있는 경로 검색은 요청한 `modes`, `priority`, `departureTime`을 기존 GET 쿼리로 전달한다. 좌표 장소가 포함되면 같은 값을 JSON body에 담아 `/api/routes/search/coordinate`로 POST한다. `departureTime`은 Asia/Seoul 현지 `LocalDateTime`으로 보낸다. API 응답 순서와 FE 화면 정렬은 별도이며, 혼잡 후보가 비어도 성공한 빈 혼잡 후보로 처리한다. 좌표 API의 `INVALID_COORDINATE`(400), `ACCESS_CANDIDATE_NOT_FOUND`(404), `ROUTE_DATA_NOT_READY`(503)는 코드별 안내와 재시도를 제공한다. 최신 `develop-BE`는 좌표 검색을 구현했으며, 조건에 따라 성공한 빈 배열을 반환할 수 있다.
5. 경로 좌표가 제공되면 지도 훅에서 선택 경로의 선을 표시한다. `MultiLineString`은 원래 선분 배열을 유지하며 좌표가 없으면 직선으로 대체하지 않는다.
6. 미리보기 초기 상태는 빈 후보 목록이며, 직접 해시 접근은 현재 검색·선택·안내 상태를 검증하는 화면 접근 규칙을 따른다.

## 합의해야 할 항목

- 출발/도착의 장소 ID 및 위도·경도, 좌표 순서와 좌표계.
- 출발 시각과 시간대, 시간·거리의 단위(현재 화면 모델은 분·m).
- 전체 경로와 구간별 ID, 이동수단, 환승, 구간 안내, 경로선 좌표 배열.
- 대표 경로 분류(빠름/혼잡), `Route.congestionPrediction`의 0 이상 퍼센트·서버 등급·dataStatus·predictionBasis, D+0~D+3 기준과 세 가지 근거 문구.
- 결과 없음·조회 실패·지원하지 않는 구간·데이터 지연 처리.
- 안내 중 제안 경로가 전체 경로인지 현재 위치 이후의 잔여 경로인지.

## 지도 설정과 정리

JavaScript 키는 `.env.local`에 넣고 Git에 올리지 않는다. 브라우저에서 쓰는 JavaScript 키는 클라이언트 번들에 포함되므로 서버 비밀키로 취급하지 않고 카카오 도메인 제한으로 사용 범위를 관리한다. Admin/REST 비밀키를 `VITE_*`에 넣지 않는다.

SDK 로더는 진행 중인 Promise를 공유하고 실패하면 다시 시도할 수 있게 초기화한다. 컴포넌트가 사라진 뒤 도착한 SDK·장소 검색 응답은 무시한다. 위치 조회는 독립 훅에서 요청 순서를 검사한다.

## 추가 경로 응답 필드 (2026-09-15)

- totalDistanceMeters와 구간 distanceMeters는 유효한 비음수 숫자일 때만 표시한다. null/누락을 0이나 직선거리로 대체하지 않는다.
- `transferCount`가 유효하면 0을 포함해 서버 값을 그대로 우선 사용한다. 값이 null/누락일 때만 실제 탑승(BIKE·BUS·SUBWAY) 경계를 보완 계산한다. 첫 탑승은 세지 않으며, 도보·BOARDING·ALIGHTING·BIKE 대여/반납 구간은 자체 환승으로 세지 않는다. BIKE와 대중교통 전환, 대중교통 수단 변경, 다른 지하철 노선 변경을 세고 같은 지하철 노선 분할과 연속 자전거 조각은 세지 않는다. BUS는 구간 `routeOptions`의 누적 공통 노선이 있으면 유지하고 없으면 환승 후 현재 집합으로 재설정한다. 명시 `TRANSFER`는 다음 실제 탑승 경계에서 한 번만 반영하며 차량 변경과 중복하지 않는다.

## 혼잡 예측과 구간 전환 (2026-09-17)

경로 검색 후보의 `congestionPrediction`은 `congestionPercent`, 서버 결정 `congestionGrade`, `dataStatus`, `predictionBasis`, `worstSegment`를 가진다. `predictionBasis`는 세 가지 근거 문구로 표시하고, 예측값이 없으면 `예측 정보 없음`을 표시한다. 모든 값은 서울 기준 D+0~D+3 예상값이며 혼잡 사유 설명은 제공하지 않는다. 2026-09-22 확인한 `develop-BE` (`9815f8f`)에는 이 필드가 구현돼 있다. 운영 응답의 데이터 제공 여부는 별도 확인이 필요하다. 카드·상세는 지하철 최악 구간에 지도·구간과 같은 40/70/100 경계와 색을 사용하고, 버스는 해당 leg에 내려온 서버 4단계 등급을 사용한다. 최악 구간 응답이 없는 구버전은 서버 3단계 등급으로 표시한다. 상세 계약은 [FE-BE-통합-API-계약](../../../FE-BE-통합-API-계약.md)을 따른다.

`Leg.transitionType`은 `BOARDING`, `ALIGHTING`, `TRANSFER`, `BIKE_RENTAL`, `BIKE_RETURN` 중 하나이며 기존 `mode: TRANSFER` 구간에 선택적으로 제공한다. 누락 응답은 기존 표시와 호환하고, `transferCount: 0`은 그대로 보존한다. `fromRentalId`·`toRentalId`는 `RouteEndpoint.rentalId`로 전달하며 노드 ID나 좌표로 대여소 ID를 추측하지 않는다. 자세한 확정 계약은 [FE-02-구간전환-API-계약](../../../FE-02-구간전환-API-계약.md)을 따른다.

- `/api/congestion`은 기존 통계 조회로만 사용하며 신규 `congestionPrediction`으로 변환하지 않는다. 통계 data가 없으면 예측 정보 없음으로 표시하고 0%·LOW·혼잡 순위를 만들지 않는다.

## 따릉이 실시간 재고 (2026-09-24)

대여소 아이콘을 선택하면 nearby의 rentalId로 `/api/bike-stations/{rentalId}/stock`을 조회하고 바텀시트에 표시한다. AVAILABLE은 0대를 포함한 유효한 재고, STALE은 수집 시각과 함께 마지막 확인 값, UNAVAILABLE은 재고 확인 불가로 표시한다. 실패 시 재시도하며 선택 변경·닫기 시 이전 요청을 취소하고 늦은 응답을 무시한다. 수집기가 없는 로컬 환경에서는 UNAVAILABLE이 정상이다.

경로 결과의 BIKE 후보는 경로 소요 시간과 `congestionPrediction`을 기준으로 즉시 표시·추천한다. 결과 화면은 출발 대여소 재고·도착 예측이나 반납 대여소 stock을 조회하지 않으며, 해당 값으로 후보를 숨기거나 추천에서 제외하지 않는다. 선택한 경로의 상세 화면에서만 출발 대여소의 현재 stock과 도착 시 prediction을 별도로 조회해 표시한다.

`GET /api/bike-stations/{rentalId}/stock`은 경로 변수 `rentalId`를 요청하고 `{ rentalId, availableBikes, stockUpdatedAt, status, rackCount? }`를 `success: true`의 `data`로 반환한다. `BikeStock.rackCount`는 총 거치대 수를 뜻하는 optional `number | null` 필드다. 숫자는 0 이상의 정수이며, `null` 또는 필드 누락은 거치대 수 미제공으로 보존한다. 기존 응답(`rentalId`, `availableBikes`, `stockUpdatedAt`, `status`)은 그대로 유효하다. 성공 응답은 `AVAILABLE`/`STALE` 상태와 수집 시각을 포함하며, 값이 없으면 null/누락으로 보존한다. API 오류와 형식 오류는 빈 성공 응답으로 바꾸지 않고 상세 화면에서 재시도 또는 정보 없음으로 표시한다.

대여소 표시 토글은 기본 켜짐이며 지도 영역 오른쪽 위에 둔다. 표시 상태는 지도 컴포넌트가 관리하고 경로선은 숨기지 않는다. 재고 응답 검증과 오류 변환은 API 저장소에서 처리한다.

## 검색 예외 복구 (2026-09-17)

경로 검색의 `ACCESS_CANDIDATE_NOT_FOUND`, `OUT_OF_SERVICE_AREA`, `SERVICE_ENDED` 오류 코드는 `RepositoryError.code`에 보존한다. 결과 화면은 원인에 맞는 입력 수정·출발 시간 변경·이동수단 변경 액션을 제공하며, 오류를 빈 성공 결과로 바꾸지 않는다. 자세한 BE 전달 계약은 [FE-03-검색예외-API-계약](../../../FE-03-검색예외-API-계약.md)을 따른다.

## 도착 시 따릉이 예측 (2026-09-17)

BIKE 구간의 명시적 `from.rentalId`와 `departedAt + 이전 구간 minutes 합`을 사용해 `/api/bike-stations/{rentalId}/prediction?arrivalTime=<offset ISO>`를 조회한다. `VITE_BIKE_PREDICTION_MOCK=true`일 때만 mock을 사용하며, 라이브 요청 실패를 mock으로 대체하지 않는다. `predictedBikes=0`과 `null`을 구분하고 현재 재고와 도착 시 예측을 하나의 상세 카드 안에서 독립된 상태로 표시한다. 현재 재고는 `/api/bike-stations/{rentalId}/stock`을 별도로 조회하며, `AVAILABLE`은 현재 수량, `STALE`은 마지막 확인 시각과 수량, `UNAVAILABLE`은 정보 없음으로 구분한다. 자세한 계약은 [FE-06-따릉이예측-API-계약](../../../FE-06-따릉이예측-API-계약.md)을 따른다.
