# CLAUDE.md

Claude Code가 이 저장소에서 작업할 때 참고하는 가이드.

## 프로젝트

SSAFY 15기 2학기 특화 프로젝트 — **빅데이터 분산처리**. 서울시 공공데이터를 Hadoop/Spark/Kafka로 분산 처리해 도시 혼잡도를 분석하고 지도 기반 서비스로 제공한다.

JIRA 프로젝트 키는 `S15P21A104`, 원격은 GitLab(`lab.ssafy.com/s15-bigdata-dist-sub1/S15P21A104`)이다.

## 저장소 구조

```
AI/       분석 파이프라인 · 모델 (Python, PyTorch, PySpark)
BE/       API 서버 (Java 21, Spring Boot 3.x, Gradle)
FE/       웹 클라이언트 (React, TypeScript, TailwindCSS, Vite)
Infra/    배포 구성 (Docker, Nginx, AWS EC2)
Docs/
  Convention/      팀 규칙
  Service Design/  기획 · 데이터 검토 문서
```

파트별 셋업·실행 방법은 각 폴더의 README에 있다. 작업 전 해당 README를 먼저 읽는다.

## 현재 상태

- **FE / BE는 프로젝트가 초기화되지 않았다.** 폴더와 README만 있으며, 스캐폴딩 도구(`npm create vite`, Spring Initializr)가 구조를 만들 예정이라 하위 폴더를 미리 만들지 않았다. 충돌을 피하려는 의도이므로 임의로 채우지 않는다.
- **개발 환경에 Python이 설치돼 있지 않다.** AI 파트 작업 전 확인이 필요하다.
- 설치 확인된 도구: Node 24.19, npm 11.17, JDK 21, Docker 29.6. Gradle은 Wrapper를 쓴다.

## 커밋 규칙

전체 규칙은 [Docs/Convention/Git Convention.md](./Docs/Convention/Git%20Convention.md)에 있다. 요약하면 다음과 같다.

```
[<JIRA-KEY>] <type>: <subject>

예) [S15P21A104-3] docs: 주제 선정 및 데이터 검토 리포트 작성
```

- `type`은 `feat` / `fix` / `docs` / `style` / `refactor` / `test` / `chore`
- JIRA 키를 대괄호로 감싸 맨 앞에 둔다 — JIRA 연동이 이 패턴을 인식한다
- 대응 티켓이 없는 저장소 설정성 작업은 키 없이 `chore:`로 쓴다
- 여러 티켓을 닫을 때는 본문에 `Closes S15P21A104-##`를 줄 단위로 적는다
- **커밋 단위는 티켓 단위로 나눈다.** 한 커밋에 여러 티켓 내용을 섞으면 JIRA 개발 탭 연결이 뭉개진다

## 브랜치

```
feat/{스토리 키}-{작업 내용}   예) feat/S15P21A104-3-planning-docs
hotfix/{이슈번호}-{작업 내용}
```

`main`, `develop-*`에는 직접 커밋하지 않고 MR로 반영한다. 브랜치는 작업(Task)이 아니라 **작업이 속한 스토리** 키를 쓴다.

> 현재 로컬 브랜치는 `main`이지만 원격은 `master`다. 이름이 어긋나 있어 푸시 전 확인이 필요하다.

## 작업 시 주의

**커밋·푸시는 요청받았을 때만 한다.** 파일 생성·수정 후에는 무엇을 바꿨는지 보고하고 커밋 여부는 사용자 판단에 맡긴다.

**시크릿을 커밋하지 않는다.** `.env`, `*.pem`, `*.key`는 `.gitignore`에 등록돼 있다. 공공데이터 API 키, DB 접속 정보, EC2 키페어가 여기 해당한다.

**데이터·모델 산출물을 커밋하지 않는다.** `AI/data/`, `AI/models/`는 추적 제외다. 용량이 크고 재생성이 가능하다.

**문서는 한국어로 쓴다.** 기존 문서가 전부 한국어이며, 코드 주석도 한국어를 쓴다.

**줄바꿈은 LF다.** `.gitattributes`에서 정규화하므로 편집 시 유지한다.

## 기획 배경

주제 확정까지의 검토 과정이 `Docs/Service Design/`에 문서화돼 있다. 데이터 관련 판단이 필요할 때 참조한다.

| 문서 | 쓸모 |
| --- | --- |
| 데이터-검증-리포트.md | **조사한 데이터·API 47건의 판정.** 어떤 데이터가 확보 가능한지, 규모·신뢰도·접근 제약이 무엇인지 |
| 데이터-기준-기획.md | 혼잡도 갈래별 후보 11건의 파이프라인 설계 |
| 주제-기준-기획.md | 초기 검토 후보 3건 (제조·스포츠·재난) |
| 기획-데이터-검토-리포트.md | 전체 흐름과 의사결정 로그 |

특히 검증 리포트의 **원칙 8가지**(표본 부족 구간에 값을 채우지 않는다, 추정 데이터는 변화율로 쓴다 등)는 데이터 처리 코드를 쓸 때 그대로 적용된다.
