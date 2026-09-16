# 배포 계약 — 앱과 플랫폼의 경계

> 기준은 컨테이너 이미지다. 앱은 이미지를 만들고, 플랫폼은 그 이미지를 실행한다.

## 1. 소유

| 대상 | 소유 | 위치 |
|---|---|---|
| `Dockerfile`, `.dockerignore` | 앱(개발자) | `BE/` · `FE/` |
| 앱 워크로드 `k8s/**` (Deployment·Service·Ingress·config·secret) | 플랫폼(리드) | `BE/k8s/` · `FE/k8s/` |
| 데이터 계층 (Postgres·Redis·Kafka) | 플랫폼(리드) | `Infra/k8s/prod/` |
| 플랫폼 서비스 (Registry·Ingress 컨트롤러·Namespace) | 플랫폼(리드) | `Infra/k8s/` |

- 개발자는 볼륨·네트워크·StatefulSet 같은 클러스터 자원을 함부로 수정하지 않는다.
  Deployment·Service 같은 파트 매니페스트는 문서 갱신을 전제로 각 파트가 작성할 수 있다.
  계약값 변경은 플랫폼에 요청한다.
- 매니페스트 커밋은 플랫폼(리드)이 한다.
- 매니페스트는 앱 저장소 `k8s/`에 둔다. 배포는 수동 apply (GitOps 미도입).
- **데이터 계층은 어떤 앱에도 의존하지 않는다.** 의존 방향은 `앱 → 데이터`. 데이터 계층은 자기 자격증명·스토리지를 소유하고 앱의 Secret·설정을 읽지 않는다.

## 2. 앱 계약값

앱이 지키는 값. 플랫폼이 이 값을 기준으로 배포한다.

| 계약값 | BE | FE |
|---|---|---|
| Dockerfile | `BE/Dockerfile` (컨텍스트 `BE/`) | `FE/Dockerfile` (컨텍스트 `FE/`) |
| 이미지 이름 | `sumgil-be` | `sumgil-fe` |
| 이미지 태그 | `latest` | `latest` |
| 리슨 포트 | `8080` | `80` |
| 헬스 경로 | `/actuator/health` | `/healthz` |
| 라우팅 경로 | `/api/` | `/` |
| 상태 | 무상태 (Postgres·Redis 저장) | 정적 파일 |

앱이 지킬 것:

1. Dockerfile이 이미지를 만들고 컨테이너가 위 포트로 리슨한다.
2. 위 헬스 경로가 `200`을 반환한다.
3. 환경변수는 이름으로만 참조한다 (값 하드코딩 금지).
4. 배포용 환경변수와 로컬용(`BE/.env`)은 별개 파일이다.

## 3. 플랫폼 제공

| 제공 | 내용 | 위치 |
|---|---|---|
| 클러스터 | k3s 1 control-plane + 1 worker | `Infra/k8s/` |
| 네임스페이스 | `prod` | `Infra/k8s/namespaces/prod.yaml` |
| 데이터 계층 | Postgres·Redis·Kafka (Infra 소유, 앱 비의존) | `Infra/k8s/prod/` |
| 레지스트리 | 클러스터 내장 `registry:2` (NodePort 30500) | `Infra/k8s/prod/registry.yaml` |
| Ingress 컨트롤러 | ingress-nginx | `Infra/k8s/ingress-nginx/` |
| 라우팅 | `/api/`→BE, `/`→FE (호스트 `j15a104.p.ssafy.io`) | `BE/k8s/prod/ingress.yaml` · `FE/k8s/prod/ingress.yaml` |
| 환경변수 주입 | ConfigMap(비민감) + Secret(비밀) | 각 앱 `kustomization.yaml` |
| 스토리지 | local-path PVC | `Infra/k8s/prod/*.yaml` (데이터) · `BE/k8s/prod/*.yaml` |

## 4. 환경변수

| 구분 | 파일 | 주입 | 키 |
|---|---|---|---|
| 비민감(앱) | `BE/k8s/prod/be-config.env` (커밋) | ConfigMap `be-config` | `DB_URL` `DB_USERNAME` `REDIS_HOST` `REDIS_PORT` `APP_CORS_ALLOWED_ORIGINS` |
| 비밀(데이터) | 데이터 계층 소유 `Infra/k8s/prod/data-secret.env` (gitignore) | Secret `data-secret` | `DB_PASSWORD` |
| 비밀(앱) | `BE/k8s/prod/be-secret.env` (gitignore) | Secret `be-secret` | 앱 고유 비밀 (수집기·BE 공용) |

- 파일명 규칙(210): `<용도>.env` (커밋: `be-config.env` — 수집기·컨슈머 키 포함 단일 파일),
  비밀은 `<용도>-secret.env` (`be-secret.env`·`data-secret.env`, gitignore `*-secret.env` 적용).
  빈 템플릿은 `<용도>.env.example` (`be-secret.env.example`·`data-secret.env.example`).
- `DB_PASSWORD`는 **데이터 계층이 소유**한다(`data-secret`). Postgres와 앱이 각자 이 Secret을 소비한다 — 앱이 데이터에 의존하는 방향을 지킨다.
- 앱은 데이터 접속 포인터(`DB_URL`·`REDIS_HOST`)를 자기 `be-config.env`에서 유지한다.

- FE는 배포 런타임 환경변수가 없다 (`VITE_*`는 빌드 타임).
- 배포용과 로컬용(`BE/.env`)은 별개다.

## 5. 배포 흐름

```
Dockerfile → (build-push) → 이미지 → 레지스트리
   → kustomization images.newName → Deployment·Service·Ingress → apply → rollout
```

## 6. 규칙

- 포트·헬스·라우팅 경로는 양쪽이 공유하는 계약값이다. 한쪽만 바꾸면 롤아웃 실패·404.
- 환경변수 키 변경은 플랫폼(리드)이 한다.
- 새 서비스를 붙일 때: 개발자는 Dockerfile + 계약값을 준비하고 플랫폼에 요청한다. 플랫폼이 이미지 참조·네임스페이스·Ingress 경로·Secret 주입을 배선한다.
