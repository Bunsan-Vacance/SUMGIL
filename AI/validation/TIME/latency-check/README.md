# TIME 재안내 성능 측정 — `POST /time/reroute/check`

JIRA S15P21A104-323 하위 323-4. `AI/validation/README.md`의 PoC·스파이크 관례를 따른다 —
`app/`(프로덕션)이 아니고, `app/`은 이 폴더를 import하지 않는다.

## 목적

FE는 이동 중 이 엔드포인트를 120초마다 폴링한다. 폴링 대부분은 평소 상태(`no_trigger`)로 끝나지만,
재고가 고갈될 것 같으면 대안을 골라 안내하는 `proposal` 경로가 돈다 — 이 경로에는 LLM 게이트웨이
(GMS) 호출이 섞여 있어 `no_trigger`보다 훨씬 느리다. 동시 접속 세션이 늘어날 때 두 경로의 응답
시간이 FE 타임아웃(6초) 안에 들어오는지, 그리고 `proposal` 경로의 지연 중 얼마가 LLM 자체이고
얼마가 나머지 처리(트리거 판정·주변 대여소 탐색·경로 연결)인지를 잰다.

## 구성

- `src/run_local.py` — **가짜 BE·가짜 LLM(고정 지연)·가짜 색인**을 붙인 로컬 측정. 실제 GMS·BE를
  전혀 부르지 않는다. `no_trigger`·`proposal` 두 경로를 세션 N개가 동시에 두드리는 상황을
  스레드풀로 흉내낸다. **실행 가능** — 반복 실행해도 외부 자원을 쓰지 않는다.
- `src/run_dev.py` — 실제 배포된 AI 서버에 HTTP로 요청을 보낸다. `no_trigger` 경로만 기본으로
  돌고, LLM(`proposal`) 경로는 `--with-proposal`을 명시해야 켜진다. **이 세션에서는 작성만 하고
  실행하지 않았다** — 배포 서버에 반복 호출을 보내는 스크립트라 실행 범위(호출 수·시각)를 먼저
  사람과 맞춘다(`AI/CLAUDE.md` 하드 룰).

## 실행

```bash
cd AI
# 로컬(가짜 BE·LLM·색인) — 스모크
python validation/TIME/latency-check/src/run_local.py --sessions 10 --rounds 1

# 로컬 — 본 측정(세션 수를 바꿔가며 여러 번 실행)
python validation/TIME/latency-check/src/run_local.py --sessions 10 --rounds 3
python validation/TIME/latency-check/src/run_local.py --sessions 50 --rounds 3
python validation/TIME/latency-check/src/run_local.py --sessions 100 --rounds 3

# 배포 서버(작성만 함 — 실행 전 --base-url·--rental-id·--dest-station-id를 실제 값으로 맞출 것)
python validation/TIME/latency-check/src/run_dev.py \
    --base-url https://<배포 주소> --rental-id <실제 대여소 ID> \
    --dest-station-id <실제 목적지 역 ID> --count 20
```

결과는 각 스크립트 옆 `out/`(기본, `.gitignore` 대상 아님 — 필요하면 커밋 여부는 별도 판단)에
`.md`·`.json`으로 쌓인다. 실행 조건(세션 수·라운드·LLM 지연)은 파일명과 JSON 본문에 같이 남는다.

## 지표 정의

- **p50/p95** — 응답 시간(초 단위로 측정해 ms로 환산) 분포의 50·95 백분위수. 선형 보간
  (numpy 기본 방식과 동일)으로 계산해 표본이 적어도(스모크 n=10) 값이 튄다.
- **no_trigger 경로** — 트리거가 서지 않는 평소 상태. `run_local.py`는 재고가 임계 미달인
  가짜 대여소로 강제한다. BE(가짜) 조회 1회 외에 다른 I/O가 없어 대부분 수 ms 안에 끝난다.
- **proposal 경로** — `debugForceTrigger`로 트리거를 강제하고, 후보 2곳 중 하나를 LLM
  (`AgentStrategy`)이 고른다. 가짜 BE(재고 조회·경로 연결) + 가짜 LLM(고정 지연) 순서로 돈다.
- **LLM 지연 분해(전체 − LLM)** — `run_local.py`의 가짜 LLM은 `--llm-delay-sec`(기본 1.2초 —
  2026-09-23 GMS 실호출 1회 실측 근사, `app/TIME/llm.py` 모듈 docstring 참고)만큼 `time.sleep`
  하고 곧바로 응답한다. 지연이 **상수**이므로 `proposal` 표본 각각에서 이 값을 그대로 빼면
  "LLM을 뺀 나머지 처리 시간"이 정확히 나온다(근사가 아니다) — 트리거 판정·후보 탐색·프리페치·
  경로 연결·도보 합성을 합친 오버헤드다. `run_dev.py`는 실제 GMS 지연이 상수가 아니므로 이
  분해를 하지 않는다(스크립트 docstring 참고).
- **동시성** — `run_local.py`는 세션마다 매 라운드 새 `sessionId`를 써서 쿨다운
  (`time_trigger_cooldown_sec`, 기본 600초)이 결과를 왜곡하지 않게 한다. 라운드 사이에 실제
  120초를 기다리지 않는다 — "그 순간 동시에 몰리면"을 재는 부하 측정이지 실시간 흐름 재현이
  아니다.

## 계약 기준

**FE 타임아웃 6초.** `no_trigger`·`proposal` 두 경로 모두 p95가 이 안에 들어와야 폴링 하나가
타임아웃으로 끊기지 않는다. `proposal` 경로는 LLM 고정 지연(기본 1.2초)이 이미 그 안에 포함돼
있으므로, "오버헤드"(LLM을 뺀 나머지)가 `6초 − LLM 지연` 안에 들어오는지로 읽는다.

## 재사용한 가짜 객체

`AI/test/TIME/test_time_router.py`의 패턴을 그대로 따른다 — `FakeAdapter`(BE 대역, `call(name,
args)`가 `GET_ETA_STOCK`/`REPLAN_ROUTE`를 고정 응답으로 처리), `app.TIME.station_index.
InMemoryStationIndex`(색인), `app.TIME.strategy.RuleStrategy`/`AgentStrategy`(전략), `router.py`
모듈 레벨 팩토리(`_station_index`·`_adapter`·`_strategy`·`_now`·`get_settings`)를 monkeypatch로
갈아끼우는 방식. LLM만 이 폴더에 새로 추가했다(`FakeLlmClient` — `app/test/` 어디에도 아직 없다).
`AI/app/TIME`·`AI/test/TIME`은 다른 작업이 동시에 고치고 있어 이 검증 코드는 그 두 폴더를
**읽기만** 했고 수정하지 않았다.

## 알려진 단순화(다음에 다듬을 것)

- `run_local.py`의 라운드는 실시간 120초 간격을 두지 않는다 — 필요하면 `measure_path`에
  라운드 사이 `time.sleep`을 추가한다.
- LLM 지연은 고정값이다. 실제 GMS는 지연에 분산이 있을 것이므로, 더 사실적인 측정이 필요하면
  `FakeLlmClient`에 지연 분포(예: 정규분포 근사)를 추가한다.
- `run_dev.py`는 이 세션에서 실행하지 않아 실제 배포 서버 수치가 없다.
