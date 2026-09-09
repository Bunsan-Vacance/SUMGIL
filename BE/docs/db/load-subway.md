# 지하철 정적 적재 (S15P21A104-69 · 70)

> `line` · `station` · `transfer_meta` · `edge_time`(SUBWAY) 을 공공데이터 파일에서 채우는 로더.
> 69 에서 골격(`load` 프로파일 · CsvTable · 그래프 빌더 · 검증 · JdbcTemplate upsert)을 만들고, 70 에서 **열차운행시각표를 1~9호선 엣지의 정본**으로 바꿨다 —
> 방향 있는 구간 + 요일×30분 슬롯별 `wait_sec`. 코드는 `com.ssafy.s15p21a104.load`, 원천과 설정은 `src/main/resources/data/subway/` (출처·열·규칙은 그 폴더 README).

## 실행

```bash
# 1) DB 기동 (저장소 루트)
docker compose -f Infra/docker/docker-compose.yml up -d postgres

# 2) 적재 (BE 폴더). local 프로파일이 없으면 DB_URL·DB_USERNAME·DB_PASSWORD 환경변수로 대신한다
cd BE
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.sources=subway --load.dry-run=true'   # 파싱·검증·건수·prune 예정만
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.sources=subway'                        # 실제 적재 + prune
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun                                                        # 지하철·버스·따릉이 전부
```

| 옵션 | 기본 | 뜻 |
| --- | --- | --- |
| `--load.dry-run` | false | DB 에 쓰지 않고 그래프 건수·검증 결과·prune 예정 엣지만 출력 |
| `--load.write-mode` | BATCH | `edge_time` 쓰기 방식. ROW 는 성능 비교용 baseline |
| `--load.prune` | true | 시각표가 덮는 노선(1001~1009)에서 이번 실행에 없는 `edge_time` 행과, 어느 엣지·환승에도 안 쓰이는 역을 지운다 |
| `--load.region` | (전부) | 포함할 line_id. 예 `--load.region=1002,1005`. 서비스 권역 확정 시 사용 |
| `--load.avg-speed-mps` | 9.2 | 시각표 밖 노선(경의중앙·수인분당) 거리 구간의 추정 표정속도 |

- 프로파일은 **`local,load` 두 개**를 함께 준다. `logback-spring.xml` 이 `local`·`default`·`prod` 에만 콘솔 출력을 붙여 두어 `load` 만 주면 로그가 나오지 않는다.
- 몇 번 실행해도 결과가 같다 (자연키 `ON CONFLICT DO UPDATE` + prune, `updated_at` 은 실행 시각). 두 번째 실행의 prune 은 0건이다.
- 검증 오류가 하나라도 있으면 아무것도 쓰지 않고 예외로 끝난다. 경고는 로그로만 남긴다.
- 시각표 42만 행은 gzip 을 스트리밍으로 읽어(`CsvTable.forEachRow`) 행을 메모리에 쌓지 않는다. 파싱 약 7초.

## 2026-09-09 적재 결과 (로컬 postgres:16)

| 테이블 | 행 | 비고 |
| --- | --- | --- |
| `line` | 17 | 1~9호선 + 경의중앙(1063)·수인분당(1075) + 환승 상대 노선(1065, 1067, 1077, 1092, 1093, 1094) |
| `station` | 416 | **좌표 있음 416, 없음 0** (2026-09-09 국가철도공단 역위치 11파일 + KTDB 보완 이후). 출처: 서울교통공사 232 · 국가철도공단 170 · KTDB 14. 69 대비 +76 |
| `transfer_meta` | 199 | 1~8호선 환승역 74개, 양방향, `source=extract` (변화 없음) |
| `edge_time` | 137,376 | 엣지 954 × 144. `timetable` 131,616 (방향 구간 914, 1~9호선) + `avg` 5,760 (코레일 거리 구간 40, 1063·1075) |

시각표 파싱: 424,264행 · 완행 열차 11,342대(급행 1,273대 제외) · 이상치 27건 제외 · 7.1초.
처리량(BATCH 1회): `edge_time` 137,376행 8.5초 ≈ 16,000 행/초. 69 의 12회 측정(약 40배, `BE/docs/perf/2026-09-08-edge-time-load.md`)은 107,136행 기준이며 재측정은 후속.

첫 실행의 prune: 엣지 14개(2,016행)와 고아 역 2개를 지웠다.

| 지운 것 | 이유 |
| --- | --- |
| 6호선 응암→구산→연신내→독바위→불광→역촌→응암 의 **역방향 6개** | 응암순환은 실제 단방향. 69 는 거리 구간을 양방향으로 만들었다 |
| 1호선 금정↔산본 2개 | 4호선(과천안산선) 구간이 코레일 파일에서 1호선으로 잡혀 있었다 |
| 4호선 상계↔당고개 2개, 역 당고개 | 2024년 개명 **당고개 → 불암산**. 시각표 이름으로 대체 |
| 1호선 서정리↔지제·지제↔평택 4개, 역 지제 | 개명 **지제 → 평택지제** |

새로 들어온 것: 1호선 서울~남영~용산~노량진~영등포~신도림~구로(69 코레일 파일에 없던 한복판)와 인천·신창·연천 방면, 3호선 일산선, 4호선 진접선, 5호선 하남, 7호선 부천·석남, 8호선 별내, 9호선 전체 — 엣지 224개·역 79개.

검증 경고 (오류 아님): 수인분당선(1075) 3조각(코레일 파일 부분 데이터), 김포골드라인 코드 없음(김포공항 환승 1건). 69 에 있던 "1호선 10조각 · 4호선 3조각" 경고는 시각표로, "좌표 없음 148" 경고는 국가철도공단 역위치 파일로 사라졌다.

### 좌표 원천과 교차 검증

원천 3종을 우선순위로 잇는다: ① 서울교통공사 역사 좌표 → ② 국가철도공단 노선별 역위치(`data/subway/kric/`, 11파일) → ③ KTDB 철도망 노드(`data/railgeometry/`, 수도권 범위·이름별 평균). ②를 ③과 대조해 **5 km 넘게 어긋나면 파일 오기로 보고 ③을 쓴다**, 500 m~5 km 는 유지하고 검토 목록으로 남긴다. 규칙과 파일별 결함은 `data/subway/README.md` "좌표 원천" 절.

| 처리 | 역 |
| --- | --- |
| 역위치 파일 무효(0,0 · 소수점 누락) → KTDB | 7호선 까치울·부천종합운동장·춘의·신중동·부천시청·상동·삼산체육관·굴포천·부평구청·산곡·석남, 3호선 원흥 |
| 역위치 파일 오기(5 km 초과) → KTDB 로 대체 | 청산(28.6 km), 별내별가람(7.8 km) |
| 500 m~5 km 차이 — 유지, 검토 필요 | 산본(1.1 km) |

②↔③ 차이는 대부분 작다(양쪽 있는 역 기준 중앙값 33 m, 95% 183 m). 6호선 역위치 파일은 좌표가 한 행씩 밀려 있지만 6호선은 전부 ①이 있어 쓰이지 않는다.

표본 — 강남→역삼(2호선) 평일 `wait_sec`:

| 슬롯 | 02:00 | 06:00 | 07:00 | 08:00 | 08:30 | 12:00 | 23:30 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 초 | 12,570 (첫차까지) | 193 | 152 | 82 | 78 | 176 | 249 |

## 데이터 흐름

```
seoul-train-timetable.csv.gz ─(스트리밍)─▶ TrainTimetableParser ─▶ DirectedSegment(914, travel 중앙값) ─┐
                                              └─▶ SlotWaits ("line|from|to" → 3×48 기대 대기) ─────────┤
korail-segments (거리, 시각표 밖 노선 1063·1075 만) ──▶ KorailSegmentParser ─▶ Segment(20, 양방향) ────┼─▶ SubwayGraphBuilder ─▶ LoadValidator ─▶ EdgeTimeExpander(waits) ─▶ UpsertWriter ─▶ pruneSubway
seoulmetro-transfer ──────────────▶ TransferRecord ────────────────────────────────────────────────┤        (station_id 결정)      (오류면 중단)
seoulmetro-station-coords, kric-line9 ─▶ StationCoord ────────────────────────────────────────────┘
conf/station-aliases ─▶ StationNameNormalizer (모든 역명에 적용)
```

## 식별자·값 규칙

- **`station.station_id` = 서울교통공사 역번호** (2026-09-09 회의 결정, S15P21A104-103). `conf/station-ids.csv` 가 정본: 노선별 역사코드 최솟값에서 앞 0 을 뗀 값(서울 `150`, 시청 `151`, 강남 `222`, 김포공항 `2513`), 코드가 없는 코레일 전용 역 12개는 `9001`~`9012`. 물리 역 1행. `station.name` 은 정규화 역명(표시용). 개명은 name 만 바뀌고 ID 는 유지된다. 표에 없는 역이 나오면 적재가 멈춘다 — ID 가 몰래 생기지 않게. 69~70 의 "정규화 역명 = ID" 규칙은 이 시점에 폐기됐고 첫 적재의 prune 이 옛 ID 행(엣지 954·환승 199·역 416)을 지웠다.
- `line.line_id` = 실시간 지하철 API `subwayId`. 수집기가 변환 없이 route_id 로 쓴다.
- **엣지는 방향이 있다.** 시각표 구간은 그 방향 열차가 있을 때만 생긴다(2호선 순환·6호선 응암순환). 코레일 거리 구간만 양방향이다.
- `edge_time.travel_sec`: 시각표 구간은 열차별 소요의 중앙값(`source=timetable`, 편차 60초 초과 엣지 23개뿐), 코레일 구간은 거리 ÷ 9.2 m/s(`source=avg`, 최소 30초).
- **`edge_time.wait_sec` = 슬롯 안 임의 시각 도착 시 다음 열차 출발까지의 기대 대기(초).** 배차가 고르면 배차간격 ÷ 2 와 같고, 열차가 없는 슬롯은 첫차까지의 대기가 된다. 막차 뒤는 같은 요일 유형의 첫차 + 24시간으로 잇는다. 하루 운행이 없는 (엣지, 요일)은 **86,400** 표식(1.3%). 코레일 `avg` 구간은 0(원천 없음).
- 요일: 시각표 DAY/SAT/END = `dow_type` 0/1/2. 자정 넘는 24:xx 표기는 24시간으로 접어 0~2번 슬롯에 들어간다.
- 급행(1호선·9호선 1,273대)은 제외한다. 도착 ≤ 출발인 이상치 27건은 표본에서 뺀다.
- `transfer_meta.walk_sec` 는 서울교통공사 환승거리 ÷ 1.2 m/s 값 그대로. 9호선·코레일 환승은 원천 없어 없다.
- 원천에 없는 값(코레일 역 좌표, 9호선 환승, 급행)은 **채워 넣지 않는다.**

## 읽는 쪽에 미치는 영향 (경로 탐색)

- **역 ID 형식이 바뀌었다**: `originStationId`·`destStationId`·`edge_time.from_node/to_node`·`transfer_meta.station_id`·Redis `reversal:{origin}:{dest}:…` 키에 들어가는 값이 한글 역명(`강남`)에서 역번호(`222`)가 됐다. 앞 0 은 없다(`0222` 아님). 역 이름은 `station.name`(`RouteNameMapper`)에서 읽는다. 표: `data/subway/conf/station-ids.csv`.
- `RouteEdgeTimeRepository.findSubwayEdgesForDefaultSlot()` 은 대표 슬롯 (dow 0, slot 0) 하나만 읽는다. 이제 슬롯마다 `wait_sec` 이 다르고 0번 슬롯(00:00~00:30)은 배차가 길다. **요청 시각의 (dow_type, time_slot) 로 조회해야 한다.** 행은 지우지 않으므로 "행 없음"으로 깨지지는 않는다.
- 역 ID 변경: 당고개 → 불암산, 지제 → 평택지제. 1호선 서울~구로 등 엣지 224개·역 79개 추가. 6호선 응암순환은 단방향.
- `wait_sec = 86400` 은 그 요일에 운행이 없다는 뜻이다. 비용으로 그대로 더하면 자연히 피해 간다.

## 스키마 변경

- 없음. V2(`source` VARCHAR(16), 69)까지가 최신이다.

## 테스트

```bash
cd BE
./gradlew test --tests 'com.ssafy.s15p21a104.load.*'    # 단위 94 + 통합 7 (postgres 필요) = 99 (지하철·버스·따릉이 로더 전체)
```

- `TrainTimetableParserTest`(10): 시각순 정렬 → 인접 구간, 방향은 열차에서만, 중앙값, 급행 제외, 이상치 제외+경고, 별칭, DAY/SAT/END, 24:xx, 모르는 표기 건너뜀, 통계
- `SlotWaitsTest`(8): 10분 간격 → 300초, 빈 슬롯 → 첫차까지, 막차 뒤 wrap, 슬롯 경계 적분, 24:xx 접기, 운행 없음 86,400, 3×48 표, 범위 검사
- `SubwayGraphBuilderDirectedTest`(6) · `EdgeTimeExpanderWaitsTest`(2) · `CsvTableStreamTest`(2) · `TransferParserTest.parsesMmSs`
- `UpsertWriterIT`: prune 이 옛 엣지·고아 역만 지우고 환승 역은 남김, dry-run 은 세기만 (`IT_` 접두어 격리)

## 남은 일 (후속 티켓)

- 급행(1호선 경인·경부, 9호선) 구간을 별도 route 로 적재. 시각표에 있다.
- 좌표 검토: 산본(원천 간 1.1 km)과 KTDB 로 채운 14개 역을 열린데이터광장 역사마스터 API(`subwayStationMaster`, 8088 — EC2/핫스팟)로 제3 원천 대조. `station.coord_source` 컬럼 추가 여부.
- 9호선·코레일 환승 도보 초 원천 조사.
- 수인분당선 3조각·경의중앙선: 코레일 시각표(별도 데이터셋) 확보 시 같은 방식으로 대체.
- `edge_time` 137k행 처리량 12회 재측정(perf 규약).
- 실시간 `statnId` ↔ `station_id` 매핑 표 (수집기 티켓).
