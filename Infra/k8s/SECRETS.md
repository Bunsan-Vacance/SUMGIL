# Secret 등록 가이드 (각 파트 담당자용)

> 원칙: **키는 쓰는 쪽이 등록한다.** 인프라 담당자는 파이프라인·렌더 경로까지만 깔아뒀다.
> 값은 절대 커밋·채팅·문서에 남기지 않는다.

## 등록 대상 (7건)

| 변수 | 발급처 | 소유 | 사용처 |
|---|---|---|---|
| `DB_PASSWORD` | 별도 채널 (기존 값 유지) | Infra | `data-secret` → PG·BE |
| `SEOUL_SUBWAY_KEY` | 열린데이터광장 | BE | `be-secret` → 수집기 |
| `SEOUL_API_KEY` | 열린데이터광장 | BE | `be-secret` → 수집기 |
| `SEOUL_BIKE_KEY` | 열린데이터광장 | BE | `be-secret` → 수집기 |
| `KMA_API_KEY` | 기상청 API허브 | BE | `be-secret` → 수집기 |
| `VITE_API_BASE_URL` | 고정값 (`https://j15a104.p.ssafy.io`) | FE | `fe-image` 빌드 인자 |
| `VITE_KAKAO_MAP_APP_KEY` | 카카오 개발자 콘솔 (JS 키) | FE | `fe-image` 빌드 인자 |

키 추가 시 `*.env.example`에 키 이름만 먼저 커밋 — 등록 스크립트가 자동 추종한다.

## 등록 방법

```bash
# 값 있는 셸에서 1회 실행 (없으면 생성, 있으면 값 갱신)
export DB_PASSWORD=... SEOUL_SUBWAY_KEY=... SEOUL_API_KEY=... SEOUL_BIKE_KEY=... \
  KMA_API_KEY=... VITE_API_BASE_URL=... VITE_KAKAO_MAP_APP_KEY=...
bash Infra/k8s/scripts/register-gitlab-vars.sh

# 등록 여부만 확인 (값 미출력)
bash Infra/k8s/scripts/register-gitlab-vars.sh --check
```

전제: `glab` 인증 + project Maintainer 이상. 값은 masked+protected+main 스코프.
UI에서 직접 넣어도 된다 (Settings → CI/CD → Variables, masked+protected 체크).

## 등록 후 흐름 (자동)

```
GitLab 변수 → main 파이프라인 → deploy-prod가 Secret 렌더 → apply → rollout
```

로테이션 때도 같은 명령으로 값만 갱신하면 된다. 노드에 scp할 필요 없음.

## 주의

- `set -x` 디버그 출력 금지 (값이 로그에 샌다).
- `VITE_*`는 빌드타임 — 값 바뀌면 FE 이미지 재빌드 필요.
- `KAKAO_REST_API_KEY`는 아직 Secret에 없음. 키 나오면 `be-secret.env.example`에 행 추가 후 이 절차로 등록.
