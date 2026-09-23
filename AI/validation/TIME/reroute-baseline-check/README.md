# 재안내 규칙·에이전트 기준선 비교 하네스

JIRA S15P21A104-331. `AI/validation/README.md`의 PoC·스파이크 관례를 따른다 — `app/`(프로덕션)이
아니고, `app/`은 이 폴더를 import하지 않는다. `AI/app/TIME`·`AI/test/TIME`은 **읽기만** 했다.

## 목적

같은 `AgentContext` 표본 집합에 `RuleStrategy`(규칙 기준선)와 `AgentStrategy`(LLM 에이전트)를
그대로 태워 선택 일치율·가드 탈락 사유·안내 문장 길이·토큰·지연을 나란히 잰다. 여기서 나온
수치가 토큰 최적화(후보 요약 압축·후보 상한·max_tokens 상한 등, `plans/TIME-331-harness-plan.md`
3단계)의 **채택 판정 기준선**이다. `AI/CLAUDE.md`의 "모델 비교는 동등 조건에서만 한다" 하드
룰을 그대로 지킨다 — 두 전략이 완전히 같은 표본·같은 `ScoreWeights`·같은 `LlmBudget` 상한을
보게 한다.

## 구성

- `src/samples_io.py` — `AgentContext` ↔ JSON 왕복(`to_json`/`from_json`). 표본 파일 포맷의
  단일 진실 원천이다.
- `src/build_samples.py` — 합성 표본 N건(기본 8, `--n`)을 `samples/samples.json`에 만든다.
  `AI/test/TIME/test_time_strategy.py`의 `station`·`reading`·`candidate`·`fired_ctx` 팩토리
  **패턴을 재현**한다(직접 import는 하지 않는다 — `test/`는 pytest 전용 구조라 외부에서 끌어다
  쓰는 자리가 아니다, `AI/CLAUDE.md` `test/` 규약). `--from-parquet <latest_stock.parquet>`을
  주면 실제 스냅샷의 고갈 임박 대여소로 표본을 만든다(파일이 없으면 값을 지어내지 않고 오류
  메시지만 내고 종료).
- `src/compare.py` — `--llm fake|real`로 두 전략을 표본마다 태우고 `out/compare_<llm>.{json,md}`·
  `figures/compare_<llm>.png`를 만든다.
- `samples/samples.json` — 커밋 대상(작다, 재생성 가능하지만 리뷰 시 바로 보이게 둔다).
- `out/`·`figures/` — 실행 산출물. `out/`은 저장소 전역 `.gitignore`(45행 `out/`)에 이미 걸려
  있다(`git check-ignore`로 확인함). `figures/`는 이 저장소의 다른 `out/` 밖 그림
  (`DATA_ENGINE/reports/figures/`)과 달리 gitignore 대상이 아니다 — 커밋 여부는 이 세션에서
  결정하지 않았다(요청받았을 때만 커밋한다, 루트 `CLAUDE.md`).

## 실행

```bash
cd AI
# 1) 표본 생성 — 합성 표본 8건(기본)
%USERPROFILE%\miniforge3\envs\SUMGIL\python.exe validation/TIME/reroute-baseline-check/src/build_samples.py --n 8

# 2) 비교 — fake(네트워크 없음, 반복 실행 안전)
%USERPROFILE%\miniforge3\envs\SUMGIL\python.exe validation/TIME/reroute-baseline-check/src/compare.py --llm fake

# (참고, 이 세션에서는 실행하지 않았다) 실제 GMS 게이트웨이 1회 호출 — 표본 수만큼 호출한다
%USERPROFILE%\miniforge3\envs\SUMGIL\python.exe validation/TIME/reroute-baseline-check/src/compare.py --llm real
```

PowerShell에서는 `$env:PYTHONIOENCODING = "utf-8"`을 먼저 실행한다(한글 출력 깨짐 방지).

**`--llm real`은 표본 수만큼 실제 LLM 게이트웨이(GMS)를 호출한다.** 표본 8건이면 8회 호출이고,
`--n`을 올리면 그만큼 늘어난다 — 무료 API는 아니고 세션당 상한(`Settings.
time_llm_max_calls_per_session` 등)과도 무관하게 스크립트가 표본마다 새 예산을 만들어 매번
호출하므로, 실행 전 호출 횟수를 사용자와 맞춘다(`AI/CLAUDE.md` 하드 룰). 이 세션은 **fake만
실행했고 real은 실행하지 않았다.**

### 다른 표본 수·지연으로

```bash
%USERPROFILE%\miniforge3\envs\SUMGIL\python.exe validation/TIME/reroute-baseline-check/src/build_samples.py --n 20 --out validation/TIME/reroute-baseline-check/samples/samples_n20.json
%USERPROFILE%\miniforge3\envs\SUMGIL\python.exe validation/TIME/reroute-baseline-check/src/compare.py --llm fake --samples validation/TIME/reroute-baseline-check/samples/samples_n20.json --fake-delay-ms 50
```

## 표본 다양성(기본 8건)

`build_samples.py` 모듈 docstring에 전체 목록이 있다. 요약:

| id | 후보 수 | 대표하는 축 |
| --- | --- | --- |
| `large_score_gap` | 2 | 점수 차 큼(가깝고 안전 vs 멀고 위험) |
| `small_score_gap` | 2 | 점수 차 작음(거의 동점) |
| `single_candidate` | 1 | 후보 1개 — LLM을 아예 안 부르는 지름길 경로 |
| `near_risky_far_safe` | 2 | 가깝지만 재고 불안 vs 멀지만 안정적 |
| `many_candidates` | 4 | 점수 분포가 넓다 |
| `proxy_predicted_stock` | 2 | `p_empty` 없이 `predicted_stock` 근사만으로 판단 |
| `low_confidence_facts` | 2 | `facts`가 다른 값(ETA 상한 근접·`p_full`>0·`horizon`=30) |
| `three_candidates_close` | 3 | 인접 점수가 촘촘해 순위가 민감하다 |

`--n`이 8과 다르면 이 시나리오를 순환하며 채운다.

## 지표 정의

- **일치율(`match_rate`)** — 전체 표본 중 `rule_index == agent_index`인 비율. **주의**:
  `AgentStrategy`는 가드에 하나라도 걸리면 `fallback`(=`RuleStrategy`, 같은 가중치)을 그대로
  돌려주므로, 가드 탈락·후보 1개 표본은 정의상 항상 일치한다. 그래서 이 값은 "LLM이 규칙에
  동의하는 비율"이 아니라 "두 전략의 최종 출력이 같은 비율"이다. 실제 판단이 갈릴 수 있었던
  표본만 보려면 `recommended_by == AGENT`(LLM 응답이 가드를 통과해 실제로 채택된 표본)만
  따로 골라 그 안에서의 일치율(`n_llm_accepted_and_match / n_llm_accepted`)을 본다 —
  `compare.py`가 둘 다 출력한다.
- **가드 탈락 사유 분포** — `AgentStrategy.rejections`를 표본별로 센 것(`strategy.RejectReason`
  8종 중 표본당 최대 1개, 표본이 가드를 하나라도 통과 못 하면 그 사유 하나로 폴백한다).
- **reason 글자수·문장수** — `len(reason)`과 `strategy._sentence_count(reason)`(TOO_LONG 판정과
  같은 정규식 — 소수점(`0.62`)의 마침표를 문장 끝으로 세지 않는다).
- **입력/출력 토큰** — `LlmResult.input_tokens`/`output_tokens`. **`fake` 모드는 항상
  `None`이다** — 실제로 세지 않은 값을 0으로 채우면 "안 세었다"와 "0개 썼다"가 섞인다
  (`app/TIME/llm.py` 모듈 docstring과 같은 원칙). `real`에서만 게이트웨이 응답의 실제 값이 들어간다.
- **LLM 지연(ms)** — `LlmResult.latency_ms`. LLM이 실제로 호출된 표본에서만 값이 있다(후보 1개·
  가드가 호출 전에 막은 표본은 `None`).
- **전략 전체 지연(ms)** — `RuleStrategy.decide()`/`AgentStrategy.decide()` 벽시계 시간
  (`time.perf_counter()`). `fake` 모드는 지연이 사실상 0에 가깝고(고정 지연 `--fake-delay-ms`,
  기본 0), `real`은 LLM 게이트웨이 왕복 시간이 대부분을 차지한다.
- **p50/p95** — 선형 보간(`validation/TIME/latency-check`와 같은 방식)으로 계산한 백분위수.

## fake 클라이언트

`LlmClient` Protocol을 만족하는 가짜 게이트웨이(`compare.py`의 `FakeLlmClient`)로, 네트워크를
전혀 쓰지 않는다. 표본의 `RuleStrategy` 선택을 그대로 따라 하고(`chosen_index`), `reason`은 그
후보의 `describe_candidate()` 요약에서 번호만 뗀 문장을 그대로 인용한다 — 둘 다 프롬프트에 실제로
보여준 값이라 `AgentStrategy`의 환각 검사(허용 숫자·이름 검사·문장 수)를 항상 통과한다. 그래서
fake 모드의 일치율이 100%에 가까운 것은 **정상이고 기대한 결과다** — "LLM이 규칙에 동의한다"는
증거가 아니라 파싱·가드·집계 배관이 실제 게이트웨이 없이도 끝까지 도는지 확인하는 스모크
테스트다. 고정 지연은 `--fake-delay-ms`(기본 0ms)로 흉내낼 수 있다.

## 알려진 단순화

- `--from-parquet` 경로는 이 폴더에 학습된 예측 모델이 없어 `predicted_stock`·`p_empty`·
  `model_horizon_min`을 문서화된 근사치로 채운다(`build_samples.py` 모듈 docstring
  `--from-parquet` 절 참고) — 실제 LightGBM 산출과 절대 안 섞이게 `source="parquet_naive_proxy"`로
  구분해뒀다. 이 세션에서는 스냅샷 파일이 없어 오류 종료 경로만 확인했다(값 지어내기 없음).
- 8개 시나리오의 거리·재고·확률 값은 잠정 설계값이다(`strategy.ScoreWeights`의 잠정 가중치와
  같은 처지) — 실제 트래픽 분포를 보면 다시 조정한다.
- `--llm real`은 이 세션에서 실행하지 않았다. `RESULTS.md`의 real 절은 미측정이다.
