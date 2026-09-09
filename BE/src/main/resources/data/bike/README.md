# 따릉이 정적 적재 원천 데이터

> `load` 프로파일의 로더(`com.ssafy.s15p21a104.load.bike`)가 읽는 파일이다. 값은 원천 그대로고 형식(xlsx → CSV, JSON → CSV)만 바꿨다.

## 원천 2종 — 스냅샷이 정본, 파일은 대조용

| 파일 | 제공처 · 데이터셋 | 기준 | 행 | 채우는 것 |
| --- | --- | --- | --- | --- |
| `seoul-bike-stations-live_20260909.csv` | 서울 열린데이터광장 [OA-15493 서울시 공공자전거 실시간 대여정보(bikeList)](https://data.seoul.go.kr/dataList/OA-15493/A/1/datasetView.do) 를 `BE/scripts/data/bike-snapshot.mjs` 로 3페이지(1~3000) 호출해 합친 스냅샷 | 2026-09-09 호출 시각은 `BE/docs/db/load-bus-bike.md` | (적재 문서 참고) | **`bike_station` 정본.** `stationId` → `rental_id`, `stationName` 의 번호 접두어를 뗀 것 → `name`, `stationLatitude/Longitude` → `lat/lng`, `rackTotCnt` → `dock_count` |
| `seoul-bike-stations_202606.csv` | 서울 열린데이터광장 [OA-13252 서울시 공공자전거 따릉이 대여소 정보](https://data.seoul.go.kr/dataList/OA-13252/F/1/datasetView.do) (원본 `공공자전거 대여소 정보(26.6월 기준).xlsx`, 머리글 4행 병합) | 2026-06 (반기 갱신) | 2,789 | 적재하지 않는다. 대여소번호로 스냅샷과 대조해 누락·거치대수(LCD+QR) 차이를 경고로 남긴다 |

## 왜 스냅샷이 정본인가

- API 명세(`BE/docs/api/api-spec.md`)의 `rentalId` 예시와 Redis 키 규약(`bike:stock:{rentalId}`, `BE/docs/cache/strategy.md`)이 모두 `ST-1577` 형태다. 이 값은 bikeList 의 `stationId` 이고, 파일형 대여소 정보에는 없다.
- 2주차 수집기도 bikeList 를 읽으므로, 마스터와 실시간 재고의 키가 변환 없이 같아진다.
- bikeList 의 `stationName` 은 `"102. 망원역 1번출구 앞"` 처럼 파일의 `대여소번호`(102)를 접두어로 갖는다. 로더는 이 번호로 두 원천을 대조한다.

## 열

- 스냅샷: `stationId · stationName · stationLatitude · stationLongitude · rackTotCnt · parkingBikeTotCnt · shared` (API 필드명 그대로). `parkingBikeTotCnt`(현재 대여 가능 대수)·`shared`(거치율)는 호출 시점 값이라 마스터에 쓰지 않는다.
- 파일: `대여소번호 · 보관소명 · 자치구 · 상세주소 · 위도 · 경도 · 설치시기 · LCD거치대수 · QR거치대수 · 운영방식`. 열 이름은 병합 머리글(`대여소\n번호`, `소재지(위치)` 4열 병합, `설치형태` 아래 `LCD`/`QR` + `거치대수`)을 `--header` 로 정리한 것이다. `보관소명` 앞 공백과 `설치시기`(Excel 일련 날짜)는 원본 그대로다.

## 다시 받는 법

```bash
# 스냅샷 — 실습실 망에서는 openapi.seoul.go.kr:8088 이 막혀 있어 핫스팟·EC2 에서 실행한다 (호출 3회)
node BE/scripts/data/bike-snapshot.mjs            # → data/bike/seoul-bike-stations-live_<YYYYMMDD>.csv
# 파일 — 데이터셋 페이지에서 최신 xlsx 를 받은 뒤 (머리글 4행)
node BE/scripts/data/xlsx-to-csv.mjs "공공자전거 대여소 정보(YY.M월 기준).xlsx" BE/src/main/resources/data/bike/seoul-bike-stations_YYYYMM.csv \
  --header-rows 4 --header 대여소번호,보관소명,자치구,상세주소,위도,경도,설치시기,LCD거치대수,QR거치대수,운영방식
# StaticLoadRunner 의 BIKE_SNAPSHOT_FILE · BIKE_FILE 과 이 표를 갱신한다
```

## 빈 곳 (채우지 않은 것)

- 스냅샷에만 있는 대여소(파일 배포 뒤 신설)와 파일에만 있는 대여소(폐쇄·휴점)는 경고로만 남기고 스냅샷 기준으로 적재한다.
- `자치구`·`상세주소`·`운영방식` 은 V1 에 컬럼이 없어 적재하지 않는다.
