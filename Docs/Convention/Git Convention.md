# Git 브랜치 전략 및 협업 컨벤션

이 문서는 브랜치·커밋·MR·리뷰·병합 규칙의 원본이다. 이슈 구조·기능 ID·상태·완료 기준은 Jira 컨벤션을 따른다. 프로젝트 키는 `S15P21A104`이다.

## 1. 개요

본 문서는 팀의 Git 사용 규칙을 정의합니다. 목표는 다음과 같습니다.

- 브랜치 관리 기준을 통일해 충돌과 혼란을 줄인다
- 코드 리뷰를 통해 품질을 보장하고 지식을 공유한다
- 배포 가능한 상태의 코드를 항상 유지한다

---

## 2. 브랜치 전략 — 파트별 통합 브랜치

`main`은 배포 가능한 상태를 유지하고, `develop-FE`, `develop-BE`, `develop-AI`에서 파트별 작업을 통합한다. 이 문서의 `develop-*`는 이 세 브랜치 중 해당 파트를 뜻한다.

| 브랜치 | 기준 키·분기점 | 병합 대상 |
| --- | --- | --- |
| `main` | 운영 브랜치, 영구 유지 | 배포 MR을 통해 반영 |
| `develop-*` | 파트별 통합 브랜치, 영구 유지 | 릴리즈 시 main |
| `feat/{Epic prefix}-{내용}` | 관련 Story가 속한 기능 Epic의 prefix, 해당 develop-* | 해당 develop-* |
| `feat/{업무 분류}-{내용}` | 관련 Story가 없는 작업의 업무 분류, 해당 develop-* | 해당 develop-* |
| `fix/{Epic prefix}-{내용}` | 관련 Story가 속한 기능 Epic의 prefix, 해당 develop-* | 해당 develop-* |
| `hotfix/{Epic prefix}-{내용}` | 관련 Story가 속한 기능 Epic의 prefix, main | main 및 관련 develop-* |

### 브랜치 흐름

> 다이어그램: GIT BRANCH STRATEGY COMPARISON.png (원본 문서 참고)

```
main     ──────────●─────────────────────●───────────────●──▶
                   \                   / \             /
                    \                 /   (hotfix 반영)
develop(BE, FE, AI)  ──●───●───●───●───●───●─┴─────●───●───●──▶
                        \       \       /         /
feat/*                   ●───●───┘       ●───●───┘
```

- 기능·일반 버그는 해당 파트 `develop-*`에서 분기하고 같은 브랜치로 병합한다.
- 운영 긴급 수정은 `main`에서 분기하고 `main`과 관련 `develop-*`에 모두 반영한다.
- 위 기존 도식은 통합 흐름을 설명하며, 브랜치 종류·명명·병합 대상의 정확한 기준은 표와 아래 규칙을 따른다.

### Epic prefix와 Jira 이슈 연결

- 이슈 구조와 종료 정책은 Jira 컨벤션을 따른다.
- Epic prefix는 관련 Story가 속한 기능 Epic의 제목 맨 앞 대괄호 안에 작성된 도메인 코드다.
    - 예: Epic `[ROUTE] 경로 추천`에 속한 Story `[ROUTE-001] 경로 입력 구현`의 Epic prefix는 `ROUTE`이다.
- 브랜치에는 Jira 이슈 키가 아니라 Epic prefix를 사용하며 대괄호는 포함하지 않는다.
    - 예: `feat/ROUTE-route-search-api`
- Story·Task·Bug는 같은 Epic 아래의 독립 이슈다. '관련 Story'는 부모 이슈라는 뜻이 아니다.
- 커밋과 MR의 관련 이슈에는 실제 Task 또는 Bug의 Jira 키를 사용한다.
- Story 코드(`ROUTE-001` 등)는 기능 구분과 Story·Task 연결에 사용하며, Epic prefix(`ROUTE`) 및 Jira 키(`S15P21A104-숫자`)와 구분한다.

### 브랜치 네이밍 규칙

```
feat/{Epic prefix}-{내용}
feat/{업무 분류}-{내용}       # 관련 Story가 없는 기획·인프라 등 예외 작업
fix/{Epic prefix}-{내용}
hotfix/{Epic prefix}-{내용}
```

```
feat/ROUTE-route-search-api
feat/ROUTE-route-result-ui
feat/INFRA-ci-pipeline
fix/ROUTE-duplicate-rerouting
hotfix/ROUTE-route-search-failure
```

- Epic prefix와 업무 분류는 영문 대문자로 작성한다.
- 내용은 영문 소문자와 하이픈으로 작성한다.
- 관련 Story가 없는 작업은 Jira 컨벤션의 공식 업무 분류(`PLAN`, `UX`, `DESIGN`, `TECH`, `INFRA`, `DOCS`, `QA`, `PT`)를 prefix로 사용한다.
- 일반 버그와 운영 긴급 버그도 관련 Story가 있다면 해당 Epic prefix를 사용한다. 관련 Story가 없다면 가장 가까운 공식 업무 분류를 사용한다.
- Epic의 Jira 키나 Task·Bug의 Jira 키를 브랜치 prefix로 사용하지 않는다.
- `main`, `develop-*`에 직접 커밋·push하지 않는다. 작업 브랜치에 push한 뒤 MR로 반영한다.
- MR 병합 후 작업 브랜치는 삭제한다. 관련 Story에 후속 Task가 남았다면 최신 `develop-*`에서 같은 명명 규칙으로 다시 생성한다.

---

## 3. MR(Merge Request) 및 코드 리뷰 규칙

### 3.1 기본 원칙

- `feat/*`, `fix/*`는 해당 파트 `develop-*`을 대상으로 MR을 생성한다.
- MR은 Task 또는 Bug 단위로 생성한다. 작고 서로 관련된 작업 2개까지는 하나로 묶을 수 있다.
- 일반 MR은 작성자 외 리뷰어 1인 이상, 핫픽스 MR은 2인 이상 승인 후 병합한다.
- 미해결 논의가 있으면 병합하지 않는다. 테스트·CI·완료 기준은 Jira 컨벤션을 따른다.

### 3.2 이슈와 브랜치 생성 순서

- Jira에 실제 이슈를 먼저 등록한 뒤 2절의 규칙으로 브랜치를 생성한다.
- Jira의 브랜치 생성 기능을 사용할 때도 분기점·브랜치 이름·저장소를 확인한다.
- 자동 생성된 브랜치명에 Jira 키가 포함되었다면 팀 규칙에 맞게 Epic prefix 기반 이름으로 수정한다.

### 3.3 MR 템플릿

#### 타이틀

```
[Epic prefix 또는 업무 분류] 작업 제목

[ROUTE] 경로 탐색 API 구현
[INFRA] AI 개발 환경 구축
[DEPLOY] develop-BE → main
[SYNC] main → develop-AI
```

```markdown
## 작업 내용
- 변경 목적과 결과

## 관련 에픽
- [ROUTE] 경로 추천: S15P21A104-39

## 관련 스토리
- [ROUTE-001] 경로 입력 구현: S15P21A104-54
- 관련 스토리가 없는 작업이면 해당 없음

## 관련 이슈
- S15P21A104-{Task 또는 Bug 번호}: 해당 Jira 이슈 URL

## 변경 사항
- 주요 변경점

## 테스트
- 수행한 검증과 결과
```

- 관련 Epic과 Story에는 제목·Jira 키를 기입하고, 관련 이슈에는 포함한 Task·Bug 키와 Jira 링크를 모두 기입한다. Story 키를 종료 대상으로 넣지 않는다.
- `Closes` 문구만으로 Jira 완료가 보장된다고 가정하지 않는다. 연동·자동화 설정과 Jira 완료 기준을 확인하고 상태를 처리한다.

### 3.4 리뷰 가이드

- 같은 역할의 팀원이 24시간 이내 1차 리뷰하는 것을 원칙으로 한다.
- 응답이 어렵다면 다른 리뷰어에게 요청한다. 시간 경과만으로 승인 요건을 생략하지 않는다.
- 요구사항·이슈 범위·컨벤션 준수 여부와 검증 결과를 확인한다.

### 3.5 병합 방식

- **일반 Merge를 사용하고 squash는 사용하지 않는다.** 기존 커밋 이력을 유지한다.
- 병합 후 원격 `feat/*`, `fix/*`는 삭제한다. `hotfix/*`는 main과 관련 develop-* 반영 후 삭제한다.
- 후속 Task의 브랜치 재생성은 2절을 따른다.

---

## 4. 커밋 메시지 컨벤션 (Task·Bug 단위)

커밋 메시지 맨 앞에 실제 작업(Task) 또는 버그(Bug)의 **Jira 이슈 키**를 붙인다. 관련 Story나 Epic 키로 대체하지 않는다.

```
[<JIRA-KEY>] <type>: <subject>
```

**type 종류**

| type | 의미 |
| --- | --- |
| `feat` | 새로운 기능 추가 |
| `fix` | 버그 수정 |
| `docs` | 문서 수정 |
| `style` | 코드 포맷팅, 세미콜론 등 (로직 변경 없음) |
| `refactor` | 리팩토링 (기능 변화 없음) |
| `test` | 테스트 코드 추가/수정 |
| `chore` | 빌드, 설정, 패키지 매니저 등 |

**예시**

```
[S15P21A104-{Task 번호}] feat: 경로 탐색 API 연동
[S15P21A104-{Bug 번호}] fix: 경로 이탈 후 중복 재탐색 수정
[S15P21A104-{Task 번호}] docs: 실행 방법 추가
```

중괄호 부분은 실제 이슈 번호로 치환한다.

- subject는 한글 기준 50자 이내, 명령형/서술형 통일 (팀 내 택1)
- 이슈 키는 대괄호 `[ ]`로 감싸서 맨 앞에 위치 — JIRA가 이슈 키를 인식하는 표준 패턴이라 가장 안전함

---

## 5. Jira-GitLab 연동

- 저장소 연결과 이슈 상태 자동화는 별도로 확인한다.
- 브랜치에는 Epic prefix를 사용하고, 커밋과 MR에는 실제 Task·Bug의 Jira 키를 사용한다.
- Jira 개발 정보에서 커밋과 MR이 실제 이슈에 연결되는지 확인한다.
- MR 텍스트나 Smart Commit 명령만으로 상태가 바뀐다고 가정하지 않는다. 실제 연동 앱·자동화 설정에 따라 검증한다.
- 이슈 완료 판단은 Jira 컨벤션을 따른다. Story·Epic은 Task 완료에 따라 자동 종료하지 않는다.

---

## 6. 핫픽스 프로세스

1. 운영 긴급 버그를 Jira에 등록한다.
2. `main`에서 `hotfix/{Epic prefix}-{내용}` 브랜치를 생성한다. 관련 Story가 없다면 공식 업무 분류를 사용한다.
3. 수정·재현 테스트·회귀 테스트·CI를 확인하고, 작성자 외 리뷰어 2인 이상 승인을 받는다.
4. MR로 `main`에 병합하고 운영 반영을 확인한다.
5. 관련 `develop-FE`, `develop-BE`, `develop-AI`에도 MR로 수정 내용을 반영한다.
6. 양쪽 반영을 확인한 뒤 hotfix 브랜치를 삭제하고 Jira 완료 기준에 따라 Bug를 완료 처리한다.

---

## 7. 체크리스트 요약

- [ ]  main과 develop-*에 직접 커밋·push하지 않았는가?
- [ ]  브랜치에 Jira 키가 아닌 관련 Epic prefix를 사용했는가?
- [ ]  관련 Story가 없는 작업은 공식 업무 분류를 prefix로 사용했는가?
- [ ]  feat/fix MR의 대상이 해당 파트 develop-*인가?
- [ ]  커밋과 MR에 실제 Task·Bug 키를 기입했는가?
- [ ]  일반 MR 1인 이상, 핫픽스 2인 이상 승인을 받았는가?
- [ ]  미해결 논의가 없고 필요한 테스트와 CI를 통과했는가?
- [ ]  일반 Merge이며 squash가 꺼져 있는가?
- [ ]  핫픽스가 main과 관련 develop-* 모두에 반영됐는가?
- [ ]  병합 후 작업 브랜치를 삭제했는가?
- [ ]  Jira 컨벤션의 완료 기준을 확인했는가?
