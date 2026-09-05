# 따릉이 파일형 데이터 수동 다운로드 안내

서울 열린데이터광장의 아래 3종은 "파일형"으로 제공돼 API 키로 자동 다운로드가 안 됩니다.
브라우저로 직접 받아서 지정된 경로에 넣어주세요.

공통 절차: [data.seoul.go.kr](https://data.seoul.go.kr) 접속 → 검색창에 데이터셋 번호
(`OA-15182` 등)를 입력 → 검색 결과에서 해당 데이터셋 클릭 → 파일 다운로드.

## 1. 대여소별 이용정보 — 월별 (OA-15182)

- 월별 CSV, UTF-8-SIG 인코딩. **건별 이력이 아니라 자치구·대여소·월 단위 집계**입니다
  (컬럼: 자치구/대여소명/기준년월/대여건수/반납건수) — 시간 해상도가 없어서
  **날씨-수요 상관분석엔 못 쓰고**, 정류소·자치구 단위 월간 총량 비교용으로만 씁니다.
- 저장 위치: `AI/data/raw/bike/rental_history/` — 파일명은 원본 그대로 둬도 됩니다.
- 파싱: `cd AI && python -m DATA_ENGINE.eda.parsers rental_history data/raw/bike/rental_history/<파일명>.csv`

## 2. 대여소별 5분단위 이용현황 — O-D (OA-21229)

- 월별 ZIP(안에 일자별 CSV), CP949 인코딩. **날씨 영향 분석의 실제 소스**입니다 —
  기준_날짜+기준_시간대(0~2355, 5분단위 HMM코드)로 시간 단위까지 집계 가능하고,
  집계_기준(출발시간/도착시간)이 따로 있어 파서가 dt_5min(datetime)을 만들어줍니다.
- 저장 위치: `AI/data/raw/bike/station_5min/`
- 파싱: `cd AI && python -m DATA_ENGINE.eda.parsers station_5min data/raw/bike/station_5min/<파일명>.zip`

## 3. 따릉이 대여소 마스터 (OA-21235)

- 대여소 좌표. CP949 인코딩. **거치대수는 없고 대여소_ID/주소1/주소2/위도/경도만** 있습니다 —
  재고 비율(거치대수 대비 잔여대수) 계산엔 못 쓰고, 공간분석(4번 섹션)의 좌표 조인용입니다.
- 저장 위치: `AI/data/raw/bike/station_master/`
- 파싱: `cd AI && python -m DATA_ENGINE.eda.parsers station_master data/raw/bike/station_master/<파일명>.csv`

## 주의

- 위 스키마는 2026-09-06, 2026년 1~7월치 실물 파일로 확인한 것입니다(`AI/DATA_ENGINE/conf/column_map.yaml`
  참고). 다음 배포분에서 컬럼이 바뀔 수 있으니, 새로 받을 때마다 헤더를 한 번 대조해보세요.
  파서 실행 시 매핑에 없는 컬럼이 있으면 경고 로그로 알려줍니다.
- 다운로드한 원본·파싱 결과물은 모두 `.gitignore`(`AI/data/**`, `*.parquet`) 대상이라
  커밋되지 않습니다. 안심하고 받아서 넣으세요.
