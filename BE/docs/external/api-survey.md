# 외부 데이터 소스 조사 — 인증·쿼터·응답 스키마·수집 주기

> Jira `S15P21A104-66`(인증키 발급·호출 검증) · `S15P21A104-68`(쿼터·스키마 조사·수집 주기 확정)의 산출물.
> 표의 "확인" 열이 `발급 후`인 항목은 아직 실측하지 않은 값이다. 추정치를 사실처럼 적지 않는다.
> Notion 표는 이 문서를 그대로 옮긴다. 정본은 이 파일이다.

## 1. 호출 방법

인증키는 `BE/.env`(Git 제외)에 둔다. 키 이름은 `BE/.env.example`에 있다.

```bash
# 저장소 루트에서
node BE/scripts/external/probe.mjs subway                               # 전체 역 일괄
node BE/scripts/external/probe.mjs subway --key sample --station 서울   # 키 승인 전 검증 (샘플키는 서울역만)
node BE/scripts/external/probe.mjs bike --start 1 --end 1000 --save
node BE/scripts/external/probe.mjs bus --st-id <정류소ID> --save
node BE/scripts/external/probe.mjs subway --repeat 5 --jsonl .claude/perf/raw/probe.jsonl   # 응답 시간 분포
```

probe는 호출마다 HTTP 상태, 응답 시간, 크기, 결과 코드, 행 수, 필드 목록, 생성시각 후보를 출력한다.
같은 호출을 curl로 하려면 probe가 출력하는 `curl` 줄에서 `{KEY}`만 바꾸면 된다.
`--save`는 정상 응답의 앞 20행만 남겨 `BE/docs/external/samples/`에 저장한다. 목업 테스트는 이 샘플로 한다(쿼터 소진 방지).

## 2. 소스별 정리

| 소스 | 엔드포인트 | 인증 | 1회 건수 | 일 트래픽 | 생성시각 필드 | 분할 호출 | 수집 주기(안) | 확인 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 지하철 실시간 도착 **일괄** (OA-15799) | `swopenapi.seoul.go.kr/api/subway/{KEY}/json/realtimeStationArrival/ALL` | 열린데이터광장 **실시간 지하철 전용 키** (일반키와 별도) | 전체 역 1회 | 페이지에 명시 없음. 발급 후 마이페이지 확인 | `recptnDt` (도착정보 생성시각) | 불필요 | 60초 → 1,440회/일 | 샘플키로 역명 조회 검증 완료 (2026-09-08) |
| 따릉이 실시간 대여정보 `bikeList` (OA-15493) | `openapi.seoul.go.kr:8088/{KEY}/json/bikeList/{start}/{end}/` | 열린데이터광장 일반키 (전용키 있으면 우선) | **최대 1,000건** | 페이지에 명시 없음. 제약 해제는 활용사례 갤러리 등록 | **없음** → 수신시각(`collected_at`)을 신선도 기준으로 씀 | **3회** (1–1000, 1001–2000, 2001–3000, 대여소 약 2,700개소) | 60초 → 4,320회/일 · 120초 → 2,160회/일 | 발급 후. **실습실 네트워크에서 8088 포트 차단** (3절) |
| 버스 도착정보 `getLowArrInfoByStId` (공공데이터포털 15000314) | `ws.bus.go.kr/api/rest/arrive/getLowArrInfoByStId?serviceKey=&stId=&resultType=json` | 공공데이터포털 serviceKey (**디코딩 키**를 `.env`에) | 정류소 1개 | 개발계정 **1,000회/일**, 운영계정 전환(활용사례 등록) 시 증가 | `mkTm` (제공시각) — 발급 후 실측 | 정류소별 | 데모 권역 정류소 N개 × 주기. 전체 폴링 불가 | 발급 후 |

### 지하철 일괄 API 응답 스키마 (샘플키 · 서울역 · 2026-09-08 실측)

- 결과: HTTP 200 · 56~72 ms · 약 3.6 KB · `errorMessage.code = INFO-000` · 요청 5행 / `total` 22~24 (2회 호출, 시점마다 다름)
- 오류 응답은 `errorMessage` 없이 최상위에 `code`/`message`/`status`가 온다 (예: `INFO-200` 데이터 없음).
- 필드 31개: `arvlCd, arvlMsg2, arvlMsg3, barvlDt, beginRow, bstatnId, bstatnNm, btrainNo, btrainSttus, curPage, endRow, lstcarAt, ordkey, pageRow, recptnDt, rowNum, selectedCount, statnFid, statnId, statnList, statnNm, statnTid, subwayHeading, subwayId, subwayList, subwayNm, totalCount, trainCo, trainLineNm, trnsitCo, updnLine`
- 시각 후보: `recptnDt="2026-09-08 10:53:55"` (생성시각, 신선도 기준), `barvlDt="32"` (도착까지 남은 초. 시각이 아니다)
- 역 식별: `statnId`(역 ID) · `subwayId`(노선 ID) · `statnNm`(역명). 정적 적재(69)의 `station.station_id`와 같은 체계인지 확인해야 한다.
- 샘플: `samples/subway-station.json`

### 따릉이 bikeList 응답 스키마 (AI 파트 수집기 기준, 본인 미실측)

`develop-AI`의 `AI/DATA_ENGINE/collect/bike_realtime.py`가 쓰는 필드: `stationId, stationName, rackTotCnt, parkingBikeTotCnt, shared, stationLatitude, stationLongitude`.
정상 응답은 `rentBikeStatus.RESULT.CODE = INFO-000`, 오류 응답은 최상위 `RESULT.CODE`. 숫자 필드가 문자열로 온다.
**생성시각 필드가 없다.** 어댑터 규칙(생성시각 없으면 `UNKNOWN`)에 그대로 걸리므로, 수집기가 붙이는 수신시각을 신선도 기준으로 쓴다고 명시한다.

### 버스 도착정보 응답 스키마

`msgHeader.headerCd = "0"`이 정상, `msgBody.itemList`가 행. 1건이면 배열이 아니라 객체 하나로 올 수 있다.
`msgHeader.itemCount`가 실제 행 수와 다를 수 있어 행 수는 `itemList` 길이로 센다. 필드는 발급 후 실측해 채운다.

## 3. 함정

| 함정 | 영향 | 대응 |
| --- | --- | --- |
| **실습실 네트워크가 `openapi.seoul.go.kr:8088`을 막는다** (2026-09-08 TCP 연결 타임아웃, 같은 호스트 443은 정상) | 따릉이 bikeList는 실습실 PC에서 호출 불가. 72(대여소 마스터), 2주차 수집기 모두 영향 | 수집기는 EC2에서 돌린다. 로컬 검증은 핫스팟 등 다른 망에서 1회. 대여소 마스터는 파일형(OA-21235 등)으로 우선 적재 |
| 지하철 샘플키는 서울역만 조회된다 | 승인 전 전체 일괄(ALL) 검증 불가 | 승인 전엔 `--station 서울`로 코드만 검증 |
| 공공데이터포털 신규 키는 활성화까지 지연이 있을 수 있다 | 발급 직후 등록 오류 | 잠시 뒤 재시도 |
| 공공데이터포털 키는 인코딩·디코딩 두 형태다 | 인코딩 키를 넣으면 이중 인코딩으로 인증 실패 | `.env`에는 디코딩 키. probe가 URL 조립 시 인코딩한다 |
| 일 트래픽 한도가 페이지에 없다 | 60초 폴링 가능 여부를 지금 못 정한다 | 발급 후 마이페이지에서 확인해 4절 결정 |
| bikeList 1,000건 제한 | 3회 분할 호출로 호출량 3배 | 주기 결정에 반영 |
| 버스는 정류소 단위 호출 | 전체 정류소 폴링은 비현실적 | 데모 권역 정류소만. 권역 확정(팀 안건) 전엔 대상 미정 |
| 서비스 권역 미확정 | 정적 적재 범위·버스 대상 정류소를 못 정한다 | 적재 스크립트는 권역 파라미터로 받게 설계 |

## 4. 수집 주기 결정

계산 기준: 하루 1,440분.

| 소스 | 60초 | 120초 | 비고 |
| --- | --- | --- | --- |
| 지하철 일괄 | 1,440회/일 | 720회/일 | 역별 호출이었다면 약 300역 × 1,440 = 432,000회/일. **일괄 엔드포인트 선택으로 1/300** |
| 따릉이 (3분할) | 4,320회/일 | 2,160회/일 | 일 한도가 1,000회면 어느 쪽도 불가 → 갤러리 등록 필요 |
| 버스 (정류소 N개) | N × 1,440 | N × 720 | 개발계정 1,000회/일이면 N=1도 60초 불가 |

**결정 후보**: 지하철 60초, 따릉이 120초. 단 실제 한도가 1,000회/일로 확인되면 승인 전까지 데모 시간대에만 폴링하고, 활용사례 갤러리 등록·운영계정 전환 신청을 병행한다. 신선도 기준(교통·재고 120초, 혼잡도 300초)은 이 주기와 맞아야 하므로 따릉이 120초는 기준선과 같다.

발급 후 한도를 확인하면 이 절을 결정으로 바꾼다.

## 5. 남은 일

- [ ] 열린데이터광장 일반키 · 실시간 지하철 키 발급 → `subway` 일괄 호출 → `samples/subway.json`
- [ ] 따릉이 키로 다른 망(또는 EC2)에서 `bike` 1회 호출 → `samples/bike.json`
- [ ] 공공데이터포털 버스도착정보 활용신청 → `bus --st-id` 1회 호출 → `samples/bus-<stId>.json`, 필드 실측
- [ ] 소스별 일 트래픽 한도 확인 → 4절 결정
- [ ] 최형수에게 bikeList 하루 4,320회 호출 시 차단 경험·갤러리 등록 여부 확인
