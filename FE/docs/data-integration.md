# 데이터 접근과 API 연결

## 현재 연결 상태

| 영역                           | 실제 구현                                                                            | 연결 위치                                                 |
| ------------------------------ | ------------------------------------------------------------------------------------ | --------------------------------------------------------- |
| 지도 타일·장소 마커            | 카카오 JavaScript SDK + 장소 검색                                                    | `lib/kakao/sdk.ts`, `features/map/useKakaoMap.ts`         |
| 현재 위치                      | 브라우저 Geolocation, 출발 검색에서 버튼 클릭 시 1회                                 | `features/map/useCurrentLocation.ts`                      |
| 지도 위치 선택                 | 카카오 지도 클릭 + 좌표 역지오코딩                                                   | `features/map/MapPlacePicker.tsx`                         |
| 검색 화면의 장소 후보          | 카카오 JavaScript SDK 장소·주소 검색                                                 | `lib/kakao/sdk.ts`, `api/repositories.ts`                 |
| 실제 경로 입력의 장소·역 후보  | 백엔드 역 검색과 카카오 장소·주소 검색 결과                                          | `api/repositories.ts`, `features/route/usePlaceSearch.ts` |
| 추천 경로                      | `VITE_API_BASE_URL` 설정 시 실제 API, 미설정 시 샘플                                 | `api/repositories.ts`                                     |
| 정렬·이동수단 필터             | 요청 modes는 서버에 전달하고 결과에도 같은 필터를 적용, 우선순위 정렬은 클라이언트   | `api/repositories.ts`, `features/route`                   |
| 경로선·실제 길찾기             | 응답 leg geometry를 연결하며 geometry가 없으면 직선으로 대체하지 않음                | `api/repositories.ts`, `features/map`                     |
| 혼잡도                         | 화면 모델·샘플은 지원하지만 현재 backend route mapper가 서버 혼잡도 필드를 읽지 않음 | `features/route/types.ts`, `api/repositories.ts`          |
| 따릉이 대여소 데이터·지도 마커 | 백엔드 nearby 응답 또는 정적 JSON, CustomOverlay                                     | `api/repositories.ts`, `features/map/bikeStations.ts`     |

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

일반 장소 검색은 카카오 JavaScript SDK의 키워드 검색을 사용하며 결과가 없으면 지오코더 주소 검색으로 재시도한다. 실제 경로 입력 검색은 백엔드 역 검색과 카카오 장소·주소 검색을 함께 제공한다. 역 ID가 출발지와 도착지 모두에 있으면 기존 역간 GET을 사용하고, 그 외에는 좌표와 장소명을 담은 coordinate POST를 사용한다. 일반 장소를 임의의 역으로 매핑하지 않으며, 화면 장소로 변환할 때 이름·주소·좌표를 검증하고 유효한 좌표가 없는 카카오 결과는 제외한다. 백엔드 역 결과는 좌표가 없어도 역 ID로 선택할 수 있다. 선택한 장소는 검색 화면의 최근 목록에 최대 10개까지 저장하며 현재 위치는 저장하지 않는다. 지도 선택은 `coord2Address(lng, lat)`으로 도로명·지번 주소를 표시하고, 주소를 찾지 못해도 좌표를 선택할 수 있다. SDK 콜백은 `AbortSignal`을 확인해 취소된 요청의 늦은 응답을 반영하지 않는다. 경로 조회는 `VITE_API_BASE_URL` 설정 시 백엔드, 미설정 시 샘플 저장소를 사용한다.

## 프론트엔드 인터페이스

`api/contracts.ts`는 화면이 데이터를 받는 방식을 정의한다. **백엔드의 확정 API 명세가 아니다.**

- `PlaceRepository.search(query, signal): Promise<Place[]>`
- `RouteRepository.search({ origin, destination, modes?, priority?, departedAt? }, signal): Promise<Route[]>`
- `useTrip`은 검색 시 `modes`, 현재 `priority`, 검색 시각 또는 사용자가 선택한 오늘(Asia/Seoul)의 출발 시각 `departedAt`을 전달하며 WALK를 항상 포함한다. 필터 변경과 전체 수단 복원은 이미 목적지가 있고 검색된 상태에서만 같은 조건으로 재요청하고, priority 변경도 직전 출발 시각을 유지해 TIME/COMFORT로 재요청한다. 진행 중 요청은 취소하고 늦은 응답은 무시한다.
- `Route.departedAt`가 있으면 해당 시각을 기준으로 도착 예정 시각을 계산하고, 없으면 샘플의 `09:41` 기준을 유지한다. 백엔드 요청의 `departureTime`은 같은 순간을 Asia/Seoul 기준 timezone 없는 `LocalDateTime`으로 변환한다.
- `Route.congestionPercent`·`walk`·`line`은 화면 모델의 선택 필드다. `walk`는 모든 비환승 WALK 구간의 `distanceMeters`가 있을 때만 합산한다. `line`과 구간 표시명은 `routeName`을 우선하고 기존 `routeId` 매핑을 대체값으로 사용한다. 경로 전체 혼잡도는 별도 합산하지 않는다. 샘플·모델·UI가 지원하는 것과 BE 응답 매핑 여부를 구분한다.
- 역 ID가 있는 기존 GET `/api/routes/search`는 여러 경로 후보를 배열로 반환하며, 좌표 기반 POST `/api/routes/search/coordinate`도 같은 후보 변환 규칙을 사용한다. 요청 `modes`에는 `WALK`가 항상 포함되고 응답 구간에는 `WALK`·`TRANSFER`가 포함될 수 있다. 저장소 변환 단계는 응답 순서와 중복 `ALTERNATIVE` 후보를 보존한다. `LOW_CONGESTION`은 `덜 붐비는 경로`, `SHORTEST`는 `빠른 경로`, `ALTERNATIVE`는 이동수단 포함 여부와 관계없이 `다른 경로`로 표시하며, `SHORTEST_WITH_BIKE`만 `따릉이 포함 경로`로 표시한다. 요청한 이동수단으로 필터한 결과가 비어도 조회 성공으로 처리해 `해당 수단으로는 경로가 없어요`를 표시한다. 현재 BE 응답에는 경로 전체 혼잡도 수치가 없어 백분율을 생성하거나 표시하지 않는다. LOW_CONGESTION 표시는 서버 분류를 근거로 한다. live 화면은 전체 혼잡도 수치가 없어도 쾌적 기준을 선택할 수 있다. FE 모델·샘플·UI에 값이 있더라도 근거 없는 혼잡도나 덜 붐빔을 주장하지 않는다.
- 경로 구간 표시명은 서버 `routeName`을 우선하며, 없으면 `routeId`의 노선 매핑을 적용한다. `BIKE`는 `자전거`, `WALK`는 `도보`로 표시하고 원본 ID는 보존한다.

화면의 `getRoutes`도 API 후보의 routeType을 확인해 허용 수단만 필터링하고 서버 배열 순서를 유지한다. 샘플 후보만 우선순위에 따라 로컬 정렬한다.

`api/repositories.ts`에서 사용할 구현을 선택한다. 페이지에서는 `fixtures`를 import하지 않는다. `app/preview.ts`는 초기 후보를 만들지 않고 미리보기 시나리오의 제안 경로만 주입한다.

조회 훅은 이전 요청을 `AbortController`로 취소하고 취소 후 도착한 결과를 무시한다. 구현을 교체할 때 `signal`을 실제 `fetch`에도 전달한다. 실패를 빈 성공 응답으로 바꾸지 않는다.

## 백엔드 연결 순서

1. 팀과 요청·응답·오류 형식을 합의한다. 임의 endpoint나 HTTP 응답 타입을 먼저 확정하지 않는다.
2. 서버 DTO와 화면용 `Place`/`Route` 타입의 차이를 확인한다. 서버 응답 검증과 변환은 데이터 접근 계층에 둔다.
3. `api`에 실제 저장소 구현을 추가하고 `api/repositories.ts`의 연결을 바꾼다. 기본 URL은 `VITE_API_BASE_URL` 환경 변수로 받는다.
4. 역 ID가 둘 다 있는 경로 검색은 요청한 `modes`, `priority`, `departureTime`을 기존 GET 쿼리로 전달한다. 좌표 장소가 포함되면 같은 값을 JSON body에 담아 `/api/routes/search/coordinate`로 POST한다. `departureTime`은 Asia/Seoul 현지 `LocalDateTime`으로 보내며, 서버는 `priority`와 `departureTime`을 LINE 혼잡도 기반 추천 계산에 사용하며 화면은 서버 추천 순서를 유지한다. 좌표 API의 `ACCESS_CANDIDATE_NOT_READY`(501)는 준비 중 안내로 표시하며 `ROUTE_DATA_NOT_READY`(503)는 경로 데이터 준비 중 안내와 재시도를 제공한다. 최신 `develop-BE`는 좌표 검색을 구현했고 접근 후보가 없으면 ACCESS_CANDIDATE_NOT_FOUND(404)를 반환한다. 해당 오류의 전용 FE 안내는 별도 작업이며, 역간 검색은 그래프 미적재 상태이면 503을 반환한다.
5. 경로 좌표가 제공되면 지도 훅에서 선택 경로의 선을 표시한다. `MultiLineString`은 원래 선분 배열을 유지하며 좌표가 없으면 직선으로 대체하지 않는다.
6. 미리보기 초기 상태는 빈 후보 목록이며, 직접 해시 접근은 현재 검색·선택·안내 상태를 검증하는 화면 접근 규칙을 따른다.

## 합의해야 할 항목

- 출발/도착의 장소 ID 및 위도·경도, 좌표 순서와 좌표계.
- 출발 시각과 시간대, 시간·거리의 단위(현재 화면 모델은 분·m).
- 전체 경로와 구간별 ID, 이동수단, 환승, 구간 안내, 경로선 좌표 배열.
- 대표 경로 분류(빠름/쾌적), `Route.congestionPercent`의 0~100 혼잡도 의미와 기준 시각, 설명 근거.
- 결과 없음·조회 실패·지원하지 않는 구간·데이터 지연 처리.
- 안내 중 제안 경로가 전체 경로인지 현재 위치 이후의 잔여 경로인지.

## 지도 설정과 정리

JavaScript 키는 `.env.local`에 넣고 Git에 올리지 않는다. 브라우저에서 쓰는 JavaScript 키는 클라이언트 번들에 포함되므로 서버 비밀키로 취급하지 않고 카카오 도메인 제한으로 사용 범위를 관리한다. Admin/REST 비밀키를 `VITE_*`에 넣지 않는다.

SDK 로더는 진행 중인 Promise를 공유하고 실패하면 다시 시도할 수 있게 초기화한다. 컴포넌트가 사라진 뒤 도착한 SDK·장소 검색 응답은 무시한다. 위치 조회는 독립 훅에서 요청 순서를 검사한다.

## 추가 경로 응답 필드 (2026-09-15)

- totalDistanceMeters와 구간 distanceMeters는 유효한 비음수 숫자일 때만 표시한다. null/누락을 0이나 직선거리로 대체하지 않는다.
- transferCount가 있으면 0도 보존해 우선 사용한다. 누락 시 기존 TRANSFER 구간 수와 노선 전환 계산을 사용한다. 현재 서버 정의에는 자전거 대여·반납 경계도 포함된다.

- 상세·안내의 지하철 구간은 /api/congestion의 STATION 대상에 원본 출발역 ID와 검색 출발 시각을 전달한다. 출발역의 통계 혼잡도로 표시하며 경로 전체 혼잡도로 합산하지 않는다. 성공 응답의 data 누락/null은 미제공이며 준비 중으로 표시한다. 이 조회는 COMFORT 경로 추천을 활성화하지 않는다.

## 따릉이 실시간 재고 (2026-09-17)

대여소 아이콘을 선택하면 nearby의 rentalId로 `/api/bike-stations/{rentalId}/stock`을 조회하고 바텀시트에 표시한다. AVAILABLE은 0대를 포함한 유효한 재고, STALE은 수집 시각과 함께 마지막 확인 값, UNAVAILABLE은 재고 확인 불가로 표시한다. 실패 시 재시도하며 선택 변경·닫기 시 이전 요청을 취소하고 늦은 응답을 무시한다. 수집기가 없는 로컬 환경에서는 UNAVAILABLE이 정상이다.

대여소 표시 토글은 기본 켜짐이며 지도 영역 오른쪽 위에 둔다. 표시 상태는 지도 컴포넌트가 관리하고 경로선은 숨기지 않는다. 재고 응답 검증과 오류 변환은 API 저장소에서 처리한다.
