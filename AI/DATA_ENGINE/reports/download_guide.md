# 따릉이 파일형 데이터 수동 다운로드 안내

서울 열린데이터광장의 아래 3종은 "파일형"으로 제공돼 API 키로 자동 다운로드가 안 됩니다.
브라우저로 직접 받아서 지정된 경로에 넣어주세요.

공통 절차: [data.seoul.go.kr](https://data.seoul.go.kr) 접속 → 검색창에 데이터셋 번호
(`OA-15182` 등)를 입력 → 검색 결과에서 해당 데이터셋 클릭 → 파일 다운로드.

## 1. 따릉이 대여이력 (OA-15182)

- 월별 CSV. cp949 인코딩 가능성이 높습니다 (`DATA_ENGINE/eda/parsers.py`가 자동 감지·처리).
- 저장 위치: `AI/data/raw/bike/rental_history/` — 파일명은 원본 그대로 둬도 됩니다.
- 파싱: `cd AI && python -m DATA_ENGINE.eda.parsers rental_history data/raw/bike/rental_history/<파일명>.csv`

## 2. 대여소별 대여/반납 5분단위 (OA-21229)

- 일별 또는 월별 ZIP.
- 저장 위치: `AI/data/raw/bike/station_5min/`
- 파싱: `cd AI && python -m DATA_ENGINE.eda.parsers station_5min data/raw/bike/station_5min/<파일명>.zip`

## 3. 따릉이 대여소 마스터 (OA-21235, OA-13252)

- 대여소 좌표·거치대수. CSV 또는 엑셀(xlsx)로 제공될 수 있습니다.
- 저장 위치: `AI/data/raw/bike/station_master/`
- 파싱: `cd AI && python -m DATA_ENGINE.eda.parsers station_master data/raw/bike/station_master/<파일명>.csv`

## 주의

- 위 세 데이터셋 모두 **원본 헤더가 실제로 어떤지 확인 후** `AI/conf/column_map.yaml`을
  대조해보세요. 연도별로 컬럼명이 바뀐 이력이 있어, 지금 매핑표는 최선 추정치입니다.
  파서 실행 시 매핑에 없는 컬럼이 있으면 경고 로그로 알려줍니다.
- 다운로드한 원본·파싱 결과물은 모두 `.gitignore`(`AI/data/**`, `*.parquet`) 대상이라
  커밋되지 않습니다. 안심하고 받아서 넣으세요.
