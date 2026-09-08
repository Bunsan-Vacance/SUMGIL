# 외부 데이터 소스 조사 — 인증·쿼터·응답 스키마·수집 주기

> Jira `S15P21A104-66`(인증키 발급·호출 검증) · `S15P21A104-68`(쿼터·스키마 조사·수집 주기 확정)의 산출물.
> 표의 "확인" 열이 `발급 후`인 항목은 아직 실측하지 않은 값이다. 추정치를 사실처럼 적지 않는다.
> Notion 표는 이 문서를 그대로 옮긴다. 정본은 이 파일이다.

## 1. 호출 방법

인증키는 `BE/.env`(Git 제외)에 둔다. 키 이름은 `BE/.env.example`에 있다.

```bash
# 저장소 루트에서
node BE/scripts/external/probe.mjs subway                               # 전체 역 일괄 첫 페이지 (0~1000)
node BE/scripts/external/probe.mjs subway --start 1000 --end 2000       # 두 번째 페이지 (전체는 3회)
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
| 지하철 실시간 도착 **일괄** (OA-15799) | `swopenapi.seoul.go.kr/api/subway/{KEY}/json/realtimeStationArrival/{start}/{end}/ALL` | 열린데이터광장 **실시간 지하철 전용 키** (일반키와 별도) | **최대 1,000행** (`end-start` > 1000 이면 `ERROR-336`) | 페이지에 명시 없음. 발급 후 마이페이지 확인 | `recptnDt` (도착정보 생성시각) | **3회** (0–1000, 1000–2000, 2000–3000). 전체 약 2,960~2,980행 | 60초 → 4,320회/일 · 120초 → 2,160회/일 | 실측 완료 (2026-09-08): 1,000행 · 585 KB · 100~207 ms. 인덱스 없는 `/ALL` 은 `ERROR-340`(별도 승인 서비스)이라 쓰지 않는다 |
| 따릉이 실시간 대여정보 `bikeList` (OA-15493) | `openapi.seoul.go.kr:8088/{KEY}/json/bikeList/{start}/{end}/` | 열린데이터광장 일반키 (전용키 있으면 우선) | **최대 1,000건** | 페이지에 명시 없음. 제약 해제는 활용사례 갤러리 등록 | **없음** → 수신시각(`collected_at`)을 신선도 기준으로 씀 | **3회** (1–1000, 1001–2000, 2001–3000). 전체 **2,732개소** (2026-09-08, 3페이지 732행) | 60초 → 4,320회/일 · 120초 → 2,160회/일 | 실측 완료 (2026-09-08, 핫스팟): 1,000행 · 194 KB · 1,154 ms · 필드 7개 · 생성시각 없음 확인. **실습실 망에서는 호출 불가** (3절) |
| 버스 도착정보 `getLowArrInfoByStId` (공공데이터포털 15000314) | `ws.bus.go.kr/api/rest/arrive/getLowArrInfoByStId?serviceKey=&stId=&resultType=json` | 공공데이터포털 serviceKey (**디코딩 키**를 `.env`에) | 정류소 1개 | 개발계정 **1,000회/일**, 운영계정 전환(활용사례 등록) 시 증가 | `mkTm` (제공시각, 실측 확인) | 정류소별 | 데모 권역 정류소 N개 × 주기. 전체 폴링 불가 | 실측 완료 (2026-09-08): 정류소 111000012 → HTTP 200 · 748 ms · 21 KB · 14행 · 필드 89개. 키는 발급 직후 바로 활성 |

### 지하철 실시간 도착 API 응답 스키마 (서울역 역명 조회 · 2026-09-08 실측, 샘플키 2회 + 전용키 1회)

- 결과: HTTP 200 · 55~72 ms · 약 3.6 KB · `errorMessage.code = INFO-000` · 요청 5행 / `total` 22~24 (3회 호출, 시점마다 다름)
- 오류 응답은 `errorMessage` 없이 최상위에 `code`/`message`/`status`가 온다 (예: `INFO-200` 데이터 없음).
- **일괄 조회는 `/{start}/{end}/ALL` 형식**이다 (2026-09-08 실측). `0/1000/ALL` → 1,000행 · 585 KB · 207 ms · `total` 2,978. `1000/1999/ALL` → 1,000행 · 100 ms. 행은 역 × 방향 × 열차 단위라 1,000행에 역 약 680개가 들어 있고, 전체는 3회로 받는다.
- `0/3000/ALL` → `ERROR-336` "데이터요청은 한번에 최대 1000건을 넘을 수 없습니다. 요청종료위치에서 요청시작위치를 뺀 값이 1000을 넘지 않도록 수정하세요." → 1회 1,000행 제한은 서버가 강제한다.
- 인덱스 없는 `/ALL` 은 두 키 모두 `ERROR-340` "해당 인증키로는 실시간 도착정보(일괄)서비스를 사용할 수 없습니다" (HTTP 200, 181 bytes). 별도 승인이 필요한 서비스로 보이며, 인덱스 형식으로 같은 데이터가 나오므로 신청하지 않는다.
- 필드 31개: `arvlCd, arvlMsg2, arvlMsg3, barvlDt, beginRow, bstatnId, bstatnNm, btrainNo, btrainSttus, curPage, endRow, lstcarAt, ordkey, pageRow, recptnDt, rowNum, selectedCount, statnFid, statnId, statnList, statnNm, statnTid, subwayHeading, subwayId, subwayList, subwayNm, totalCount, trainCo, trainLineNm, trnsitCo, updnLine`
- 시각 후보: `recptnDt="2026-09-08 10:53:55"` (생성시각, 신선도 기준), `barvlDt="32"` (도착까지 남은 초. 시각이 아니다)
- 역 식별: `statnId`(역 ID) · `subwayId`(노선 ID) · `statnNm`(역명). 정적 적재(69)의 `station.station_id`와 같은 체계인지 확인해야 한다.
- 샘플: `samples/subway-station.json`

### 따릉이 bikeList 응답 스키마 (2026-09-08 실측, 핫스팟 망)

- 결과: `1/1000` → HTTP 200 · 1,154 ms · 193,820 bytes · `rentBikeStatus.RESULT.CODE = INFO-000` · 1,000행. `2001/3000` → 621 ms · 143 KB · **732행** → 전체 2,732개소, 3회면 끝난다. 주기당 약 530 KB
- 필드 7개: `stationId, stationName, rackTotCnt, parkingBikeTotCnt, shared, stationLatitude, stationLongitude`. `develop-AI`의 `AI/DATA_ENGINE/collect/bike_realtime.py`가 쓰는 것과 같다. 숫자 필드가 문자열로 온다.
- **생성시각 필드가 없다** (probe 시각 후보 0개). 어댑터 규칙(생성시각 없으면 `UNKNOWN`)에 그대로 걸리므로, 수집기가 붙이는 수신시각을 신선도 기준으로 쓴다고 명시한다.
- `list_total_count`는 **전체 대여소 수가 아니라 요청 페이지의 건수**를 돌려준다 (1/1000 요청에 1000). 지하철 일괄의 `total`과 다르다. 전체 끝은 마지막 페이지의 행 수가 1,000 미만인 것으로 판단한다.
- 오류 응답은 최상위 `RESULT.CODE`로 온다.
- 샘플: `samples/bike.json`

### 버스 도착정보 응답 스키마 (정류소 111000012 · 2026-09-08 실측)

- 결과: HTTP 200 · 748 ms · 21,074 bytes · `msgHeader.headerCd = "0"` · 14행 (정류소를 지나는 노선 1건 = 1행)
- `msgHeader.itemCount`는 **0으로 왔는데 행은 14개**였다. 행 수는 `itemList` 길이로 센다. 1건이면 배열이 아니라 객체 하나로 올 수 있다.
- 필드 89개. 노선별로 첫째·둘째 도착 버스가 접미사 1·2로 나뉜다: `stId, stNm, arsId, busRouteId, busRouteAbrv, rtNm, routeType, dir, staOrd, term, nextBus, mkTm, firstTm, lastTm, arrmsg1/2, exps1/2, kals1/2, neus1/2, traTime1/2, traSpd1/2, sectOrd1/2, stationNm1/2, plainNo1/2, vehId1/2, busType1/2, isArrive1/2, isLast1/2, full1/2, goal1/2, deTourAt, avgCf1/2, expCf1/2, kalCf1/2, neuCf1/2, nstnId1/2, nstnOrd1/2, nstnSec1/2, nstnSpd1/2, nmainOrd1/2, nmainSec1/2, nmainStnid1/2, nmain2Ord1/2, nmain2Stnid1/2, namin2Sec1/2, nmain3Ord1/2, nmain3Sec1/2, nmain3Stnid1/2, brdrde_Num1/2, brerde_Div1/2, rerdie_Div1/2, reride_Num1/2, repTm1/2`
- 시각 후보: `mkTm="2026-09-08 11:10:10.0"` (제공시각, 신선도 기준). `firstTm`·`lastTm`은 첫차·막차 시각이라 생성시각이 아니다.
- 정류소 1개 응답이 21 KB라 정류소 N개 폴링은 N × 21 KB × 주기. 대상 정류소 수를 작게 잡아야 한다.
- 샘플: `samples/bus-111000012.json`

## 3. 함정

| 함정 | 영향 | 대응 |
| --- | --- | --- |
| **실습실 네트워크에서 `openapi.seoul.go.kr`(115.84.165.45)에 닿지 않는다** (2026-09-08 실측: 8088뿐 아니라 80·443도 TCP 타임아웃. 같은 대역의 `data.seoul.go.kr` 115.84.165.40과 `swopenapi.seoul.go.kr`은 정상) | 따릉이 bikeList는 실습실 PC에서 어떤 포트로도 호출 불가. 포트 우회 없음. 72(대여소 마스터), 2주차 수집기 모두 영향 | 수집기는 EC2에서 돌린다. 로컬 검증은 핫스팟 등 다른 망에서 1회. 대여소 마스터는 파일형(OA-21235 등)으로 우선 적재 |
| **지하철 일괄은 인덱스 없는 `/ALL` 이 아니라 `/{start}/{end}/ALL` 이다** (`/ALL` 은 `ERROR-340`, 2026-09-08 실측) | 문서만 보고 `/ALL` 을 쓰면 키가 정상이어도 "인증키 문제"로 오해한다 | probe·수집기는 인덱스 형식만 쓴다. 1회 1,000행(`ERROR-336`)이라 3분할 |
| 지하철 샘플키는 서울역만 조회된다 (일괄 `0/1000/ALL` 도 `ERROR-336`) | 승인 전 전체 일괄 검증 불가 | 승인 전엔 `--station 서울`로 코드만 검증 |
| 공공데이터포털 신규 키는 활성화까지 지연이 있을 수 있다 | 발급 직후 등록 오류 | 잠시 뒤 재시도. 이번 발급 건은 즉시 활성이었다 |
| 공공데이터포털 키는 인코딩·디코딩 두 형태다 | 인코딩 키를 넣으면 이중 인코딩으로 인증 실패 | `.env`에는 디코딩 키. probe가 URL 조립 시 인코딩한다 |
| 일 트래픽 한도가 페이지에 없다 | 60초 폴링 가능 여부를 지금 못 정한다 | 발급 후 마이페이지에서 확인해 4절 결정 |
| bikeList 1,000건 제한 | 3회 분할 호출로 호출량 3배 | 주기 결정에 반영 |
| 버스는 정류소 단위 호출 | 전체 정류소 폴링은 비현실적 | 데모 권역 정류소만. 권역 확정(팀 안건) 전엔 대상 미정 |
| 서비스 권역 미확정 | 정적 적재 범위·버스 대상 정류소를 못 정한다 | 적재 스크립트는 권역 파라미터로 받게 설계 |

## 4. 수집 주기 결정

계산 기준: 하루 1,440분.

| 소스 | 60초 | 120초 | 비고 |
| --- | --- | --- | --- |
| 지하철 일괄 (3분할) | 4,320회/일 | 2,160회/일 | 역별 호출이었다면 약 300역 × 1,440 = 432,000회/일. **일괄 3분할로 1/100**. 주기당 약 1.75 MB |
| 따릉이 (3분할) | 4,320회/일 | 2,160회/일 | 일 한도가 1,000회면 어느 쪽도 불가 → 갤러리 등록 필요 |
| 버스 (정류소 N개) | N × 1,440 | N × 720 | 개발계정 1,000회/일이면 N=1도 60초 불가 |

**결정 후보**: 지하철 60초, 따릉이 120초. 지하철도 3분할이라 60초면 하루 4,320회로 따릉이와 같은 쿼터 문제를 안는다. 실제 한도가 1,000회/일로 확인되면 승인 전까지 데모 시간대에만 폴링하고, 활용사례 갤러리 등록·운영계정 전환 신청을 병행한다. 신선도 기준(교통·재고 120초, 혼잡도 300초)은 이 주기와 맞아야 하므로 따릉이 120초는 기준선과 같다.

발급 후 한도를 확인하면 이 절을 결정으로 바꾼다.

## 5. 남은 일

- [x] 열린데이터광장 일반키 · 실시간 지하철 전용키 발급 → 역명 조회 `INFO-000` 검증 (2026-09-08)
- [x] 지하철 일괄은 `/{start}/{end}/ALL` 형식으로 검증 (1,000행 × 3회, `ERROR-336` 확인) → `samples/subway.json` (2026-09-08)
- [x] 일반키로 핫스팟 망에서 `bike` 호출 → `samples/bike.json` (2026-09-08). 실습실 망에서는 불가 확인
- [x] 공공데이터포털 버스도착정보 활용신청 → `bus --st-id 111000012` 실측, `samples/bus-111000012.json` (2026-09-08)
- [ ] 소스별 일 트래픽 한도 확인 (열린데이터광장 마이페이지, 공공데이터포털 마이페이지) → 4절 결정
- [ ] 최형수에게 bikeList 하루 4,320회 호출 시 차단 경험·갤러리 등록 여부 확인
