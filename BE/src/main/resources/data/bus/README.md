# 버스 정적 적재 원천 데이터

> `load` 프로파일의 로더(`com.ssafy.s15p21a104.load.bus`)가 읽는 파일이다. 전부 무료 공공데이터 원본이며,
> 열린데이터광장 최신 배포분이 **xlsx 로만 제공**되어 `BE/scripts/data/xlsx-to-csv.mjs` 로 CSV(UTF-8, LF)로 바꿨다.
> 값은 건드리지 않았다 — 열 이름·순서·셀 값 모두 원본 그대로다. 파일명 뒤 날짜는 제공처의 배포 기준일이다.

## 원천 2종

| 파일 | 제공처 · 데이터셋 | 배포일 | 행 | 채우는 것 |
| --- | --- | --- | --- | --- |
| `seoul-bus-stops_20260902.csv` | 서울 열린데이터광장 [OA-15067 서울시 버스정류소 위치정보](https://data.seoul.go.kr/dataList/OA-15067/S/1/datasetView.do) (원본 `서울시버스정류소위치정보(20260902).xlsx`) | 2026-09-02 | 11,236 | 서울 시내 정류소 → `bus_stop` (정본). `NODE_ID` → `stop_id`, `X좌표` → `lng`, `Y좌표` → `lat` |
| `seoul-bus-route-stops_20260902.csv` | 서울 열린데이터광장 [OA-1095 서울시 버스 노선 정보 조회](https://data.seoul.go.kr/dataList/OA-1095/F/1/datasetView.do) (원본 `서울시버스노선별정류소정보(20260902).xlsx`) | 2026-09-02 | 41,688 | 노선 × 경유 정류소. `ROUTE_ID` distinct 718 → `bus_route`. 위치정보 파일에 없는 경유 정류소 1,863개(서울 밖 경기 구간) → `bus_stop` 좌표 보충 |

## 열

- 위치정보: `NODE_ID · ARS_ID · 정류소명 · X좌표 · Y좌표 · 정류소타입`
  - `NODE_ID`(9자리)는 버스 도착정보 API(`getLowArrInfoByStId`)의 `stId` 와 같은 체계다. `ARS_ID`(5자리, 정류소 안내판 번호)는 V1 스키마에 컬럼이 없어 적재하지 않는다.
  - 좌표는 WGS84 도(度) 단위다. 제공처 설명의 "EPSG-5179" 표기와 달리 실제 값은 경도 126.80~127.18, 위도 37.43~37.69 다.
  - `정류소타입`: 일반차로 6,251 · 마을버스 4,175 · 중앙차로 405 · 가로변시간 256 · 가로변전일 141 · 한강선착장 8. 컬럼이 없어 적재하지 않는다.
- 노선별: `ROUTE_ID · 노선명 · 순번 · NODE_ID · ARS_ID · 정류소명 · X좌표 · Y좌표`
  - `ROUTE_ID`(9자리)는 도착정보 API 의 `busRouteId` 와 같은 체계다. 노선명은 최대 11자, 같은 이름의 다른 ID 는 없다.
  - `순번`(경유 순서)은 V1 에 테이블이 없어 적재하지 않는다. 후속 BUS 엣지 작업이 이 파일을 다시 읽는다.

## 다시 받는 법

```bash
# 1) 열린데이터광장 데이터셋 페이지에서 최신 xlsx 를 내려받는다 (다운로드 버튼은 nio_download.do POST: infId · seq · infSeq)
# 2) 변환 — 원본 머리글이 그대로 출력되므로 열 구조가 바뀌면 여기서 드러난다
node BE/scripts/data/xlsx-to-csv.mjs 서울시버스정류소위치정보\(YYYYMMDD\).xlsx   BE/src/main/resources/data/bus/seoul-bus-stops_YYYYMMDD.csv
node BE/scripts/data/xlsx-to-csv.mjs 서울시버스노선별정류소정보\(YYYYMMDD\).xlsx BE/src/main/resources/data/bus/seoul-bus-route-stops_YYYYMMDD.csv
# 3) StaticLoadRunner 의 BUS_STOPS_FILE · BUS_ROUTE_STOPS_FILE 과 이 표를 갱신한다
```

## 빈 곳 (채우지 않은 것)

- 경기 구간 정류소 1,863개는 `정류소타입` 이 없다(원천에 없음). 좌표는 노선별 파일 값이다.
- 서비스 권역이 확정되지 않아 전체를 적재한다. `--load.region` 은 지하철 노선 기준이라 버스에는 적용되지 않는다.
