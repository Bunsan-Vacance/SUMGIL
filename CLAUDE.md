# CLAUDE.md

Claude Code가 이 저장소에서 작업할 때 참고하는 가이드.

## 프로젝트

SSAFY 15기 2학기 특화 프로젝트 — **빅데이터 분산처리**. 서울시 공공데이터를 Hadoop/Spark/Kafka로 분산 처리해 도시 혼잡도를 분석하고 지도 기반 서비스로 제공한다.

JIRA 프로젝트 키는 `S15P21A104`, 원격은 GitLab(`lab.ssafy.com/s15-bigdata-dist-sub1/S15P21A104`)이다.

## 저장소 구조

```
AI/       분석 파이프라인 · 모델 (Python, PyTorch, PySpark)
BE/       API 서버 (Java 21, Spring Boot 4.x, Gradle)
FE/       웹 클라이언트 (React, TypeScript, TailwindCSS, Vite)
Infra/    배포 구성 (EC2, k3s, Kustomize)
Docs/
  Convention/      팀 규칙
  Service Design/  기획 · 데이터 검토 문서
```

파트별 셋업·실행 방법은 각 폴더의 README에 있다. 작업 전 해당 README를 먼저 읽는다.

## 현재 상태

- **BE는 초기화·구현 진행 중** — Java 21 · Spring Boot 4.1.1 · Gradle Wrapper. `domain/`(station·bike·bus·congestion·route)·`global/`·`load/` 구조, Flyway 마이그레이션, `GET /api/stations/search`·`GET /api/routes/search`·`GET /api/bike-stations/nearby`가 있다.
- **FE는 아직 초기화되지 않았다.** 폴더와 README만 있으며, 스캐폴딩 도구(`npm create vite`)가 구조를 만든다. 충돌을 피하려 하위 폴더를 미리 만들지 않는다. (1차 배포용 `FE/docker/placeholder/`는 예외)
- **1차 인프라는 EC2 2대 k3s에 배포 완료 (2026-09-11).** 자세한 구성은 [Infra/README.md](./Infra/README.md).
- **개발 환경에 Python이 설치돼 있지 않다.** AI 파트 작업 전 확인이 필요하다.
- 설치 확인된 도구: Node 24.19, npm 11.17, JDK 21, Docker 29.6, kubectl/Kustomize. Gradle은 Wrapper를 쓴다.

## 커밋·브랜치 규칙

**커밋·브랜치를 만들기 전에 항상 [Docs/Convention/Git Convention.md](./Docs/Convention/Git%20Convention.md) 원문을 먼저 읽는다.** 아래는 자주 놓치는 지점만 짚어둔 요약이지 전체 규칙이 아니다 — 이 요약과 원문이 어긋나면 원문이 맞다.

- 커밋: `[<JIRA-KEY>] <type>: <subject>` — `type`은 `feat`/`fix`/`docs`/`style`/`refactor`/`test`/`chore`. 기능·문서 작업은 예외 없이 실제 JIRA 이슈(작업/Task) 키를 붙인다. **티켓이 존재할 수 없는 순수 저장소 설정 작업**(예: 이 문서 자체 정비, 최초 리포 골격 구성)만 키 없이 `chore:`로 쓴다 — 이 예외는 `Docs/Convention/Git Convention.md`에는 없지만 `a898c32`가 실제 선례다. 애매하면 사용자에게 티켓 유무를 먼저 확인한다.
- 커밋 단위는 작업(Task) 단위로 나눈다. 한 커밋에 여러 티켓을 섞으면 JIRA 개발 탭 연결이 뭉개진다. 여러 티켓을 한 MR에서 닫을 때는 MR 본문에 `Closes S15P21A104-##`를 줄 단위로 적는다(커밋 본문 아님, [Git Convention.md](./Docs/Convention/Git%20Convention.md) 3.3 MR 템플릿 참고).
- 브랜치는 **작업이 속한 스토리** 키를 쓴다 (`feat/{스토리 키}-{작업 내용}`, 예: `feat/S15P21A104-3-planning-docs`). **스토리 없이 에픽에 바로 달린 예외 작업**은 스토리 키 대신 에픽 prefix를 쓴다(예: `feat/INFRA-ai-fastapi-scaffold`) — 이때도 커밋 메시지의 JIRA 키는 그 작업(Task) 이슈의 실제 키를 그대로 쓴다.
- `main`, `develop-*`에는 직접 커밋하지 않고 MR로 반영한다.

## 작업 시 주의

**커밋·푸시는 요청받았을 때만 한다.** 파일 생성·수정 후에는 무엇을 바꿨는지 보고하고 커밋 여부는 사용자 판단에 맡긴다.

**시크릿을 커밋하지 않는다.** `.env`, `*.pem`, `*.key`는 `.gitignore`에 등록돼 있다. 공공데이터 API 키, DB 접속 정보, EC2 키페어가 여기 해당한다.

**데이터·모델 산출물을 커밋하지 않는다.** `AI/data/`, `AI/models/`는 추적 제외다. 용량이 크고 재생성이 가능하다.
실제 데이터 파일은 대신 팀 공유 Google Drive([SUMGIL](https://drive.google.com/drive/folders/1C_x37kCT3wfeLqqw1aApt_ODWNks8THw))의
`data/` 폴더에 올린다 — `AI/data/`는 도메인(JIRA 에픽 prefix) 우선 구조다: `CROWD/`, `BIKE/`처럼 도메인마다
`raw/`(원본) → `interim/`(중간 산출물) → `processed/`(분석·모델링용 최종본) 3단계를 갖고, 여러 도메인이 공유하는
외부 요인(날씨 등)은 `EXTERNAL/`에 같은 3단계로 둔다. Drive에도 이 구조를 그대로 미러링하고,
새 도메인·서브폴더를 로컬에 추가하면 Drive에도 동일한 경로로 폴더를 만든다.

**문서는 한국어로 쓴다.** 기존 문서가 전부 한국어이며, 코드 주석도 한국어를 쓴다.

**줄바꿈은 LF다.** `.gitattributes`에서 정규화하므로 편집 시 유지한다.

**호출 한도·과금이 있는 외부 API는 대량·반복 실행 전 사용자에게 확인한다.** 서울 열린데이터광장·공공데이터포털 API 키는 발급 정책·호출 한도가 있고(`AI/README.md` 4절), `bikeList`처럼 호출당 건수 제한이 있는 것도 있다. 대여이력 몇 개월치 다운로드처럼 호출 횟수가 크거나 반복 실행되는 스크립트는 작성은 하되, 실행 범위(기간·건수)를 사용자와 먼저 맞추고 실행한다. 스키마 확인 수준의 1회성 호출은 예외.

**커밋 전 해당 파트의 lint·테스트를 로컬에서 통과시킨다.** AI는 `ruff check .` / `black --check .` / `pytest -q`(`AI/CLAUDE.md` 참고), BE/FE는 초기화 후 각 파트 README의 검증 명령을 따른다.

**파트 간 협의는 `.claude/handoff/`에 기록한다.** 보낸 요청은 `TO_<파트>-<주제>-<NN>.md`, 받은 회신은 같은 슬러그·번호의 `FROM_<파트>-<주제>-<NN>.md`로 짝을 맞춘다. 처리가 끝나면 **요청·회신을 함께** `done/`으로 옮긴다 — 루트에 남은 파일이 미결 목록이다. `TO_` 문서에는 회신 형식·채널을 반드시 적는다. 규약 원문은 [.claude/handoff/README.md](./.claude/handoff/README.md). 이 폴더는 `.gitignore` 대상이라 내 쪽 기록일 뿐이고, 실제 전달은 Notion·Discord·JIRA 코멘트로 한다 — 상대가 봐야 하는 계약 본문은 해당 파트 폴더에 커밋한다(`AI/app/CROWD/SERVING_CONTRACT.md`처럼).

**`AI/` 안에서 작업할 때는 `AI/CLAUDE.md`(실행·CI·모듈 규약)를 추가로 참고한다.**

## 기획 배경

주제 확정까지의 검토 과정이 `Docs/Service Design/`에 문서화돼 있다. 데이터 관련 판단이 필요할 때 참조한다.

| 문서 | 쓸모 |
| --- | --- |
| 데이터-검증-리포트.md | **조사한 데이터·API 47건의 판정.** 어떤 데이터가 확보 가능한지, 규모·신뢰도·접근 제약이 무엇인지 |
| 데이터-기준-기획.md | 혼잡도 갈래별 후보 11건의 파이프라인 설계 |
| 주제-기준-기획.md | 초기 검토 후보 3건 (제조·스포츠·재난) |
| 기획-데이터-검토-리포트.md | 전체 흐름과 의사결정 로그 |

특히 검증 리포트의 **원칙 8가지**(표본 부족 구간에 값을 채우지 않는다, 추정 데이터는 변화율로 쓴다 등)는 데이터 처리 코드를 쓸 때 그대로 적용된다.
