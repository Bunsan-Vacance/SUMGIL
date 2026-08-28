# S15P21A104

SSAFY 15기 2학기 특화 프로젝트 — **빅데이터 분산처리**

서울시 공공데이터를 분산 처리해 도시 혼잡도를 분석하고, 그 결과를 지도 기반 서비스로 제공한다.

---

## 저장소 구조

```
S15P21A104/
├─ AI/       분석 파이프라인 · 피처 엔지니어링 · 모델 (Python)
├─ BE/       API 서버 (Java · Spring Boot)
├─ FE/       웹 클라이언트 (React · TypeScript)
├─ Infra/    배포 구성 (Docker · Nginx)
└─ Docs/
   ├─ Convention/     팀 규칙 (Git · JIRA)
   └─ Service Design/ 기획 · 데이터 검토 문서
```

각 파트의 셋업과 실행 방법은 해당 폴더의 README를 참조한다.

| 파트 | 스택 | 문서 |
| --- | --- | --- |
| AI & Data | Python, PyTorch, PySpark | [AI/README.md](./AI/README.md) |
| Backend | Java, Spring Boot | [BE/README.md](./BE/README.md) |
| Frontend | React, TypeScript, TailwindCSS | [FE/README.md](./FE/README.md) |
| Infra | AWS EC2, Nginx, Docker | [Infra/README.md](./Infra/README.md) |

## 진행 상황

| 항목 | 상태 |
| --- | --- |
| 주제 검토 및 데이터 검증 | ✅ 완료 — [문서](#기획-문서) |
| 팀 컨벤션 수립 | ✅ 완료 |
| 저장소 구조화 | ✅ 완료 |
| FE / BE 프로젝트 초기화 | ⬜ 대기 — 각 README의 초기화 절차 참조 |
| Python 환경 구축 | ⬜ 대기 — 개발 환경에 Python 미설치 |

## 기획 문서

주제 확정까지의 검토 과정과 데이터 검증 결과를 문서로 남겼다.

| 문서 | 내용 |
| --- | --- |
| [주제 선정 및 데이터 검토 리포트](./Docs/Service%20Design/기획-데이터-검토-리포트.md) | 전체 흐름 · 선정 기준의 진화 · 의사결정 로그 |
| [주제 기준 기획](./Docs/Service%20Design/주제-기준-기획.md) | 주제를 먼저 정하고 데이터를 찾은 후보 3건 |
| [데이터 기준 기획](./Docs/Service%20Design/데이터-기준-기획.md) | 혼잡도 데이터에 주제를 붙인 후보 11건 |
| [데이터 검증 리포트](./Docs/Service%20Design/데이터-검증-리포트.md) | 데이터·API 47건의 6축 검증과 판정 |

## 개발 규칙

브랜치 전략, 커밋 메시지 형식, MR·코드리뷰 규칙은 [Git Convention](./Docs/Convention/Git%20Convention.md)을 따른다.

```
브랜치   feat/{스토리 키}-{작업 내용}     예) feat/S15P21A104-3-planning-docs
커밋     [{JIRA 키}] {type}: {subject}   예) [S15P21A104-3] docs: 기획 문서 추가
```

- `main`, `develop-*`은 직접 커밋 금지 — MR을 통해서만 반영한다
- MR은 리뷰어 1인 이상의 승인을 받아야 병합한다

## 링크

- [JIRA](https://ssafy.atlassian.net/jira/software/c/projects/S15P21A104/boards/15001)
- [GitLab](https://lab.ssafy.com/s15-bigdata-dist-sub1/S15P21A104)
