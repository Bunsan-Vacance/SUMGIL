# FE 배포 (컨테이너 계약)

> `FE/k8s/**`는 플랫폼(리드) 소유다. 개발자는 수정하지 않고 `FE/Dockerfile`과 계약값만 유지한다.
> 전체 경계는 [Infra/k8s/CONTRACT.md](../../Infra/k8s/CONTRACT.md).

## 계약값

| 항목 | 값 |
|---|---|
| 이미지 | `sumgil-fe:latest` |
| Dockerfile | `FE/Dockerfile` (빌드 컨텍스트 `FE/`) |
| 리슨 포트 | `80` |
| 헬스 경로 | `/healthz` |
| 라우팅 경로 | `/` (호스트 `j15a104.p.ssafy.io`) |
| 네임스페이스 | `prod` |

## 이미지 만들기

```bash
cd FE
docker build -t sumgil-fe:latest .
```

- 현재 Dockerfile은 정적 placeholder다. Vite 스캐폴딩 후 정적 빌드 + nginx multi-stage로 교체한다.
- 레지스트리 push와 배포는 플랫폼이 한다.

## 배포 가능하게 유지하려면

1. Dockerfile이 정적 산출물을 nginx로 서빙하고 `80`으로 리슨한다.
2. `/healthz`가 `200`을 반환한다.
3. 백엔드 호출은 같은 호스트의 `/api/` 경로를 쓴다 (API 주소 하드코딩 금지).

## 이 디렉토리

- `k8s/prod/` — FE 워크로드 매니페스트(플랫폼 템플릿).
- `k8s/argocd-application.yaml` — GitOps 전환용(설치 후순위).
