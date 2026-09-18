# BE 배포 (컨테이너 계약)

> `BE/k8s/**`는 플랫폼(리드) 소유다. 개발자는 수정하지 않고 `BE/Dockerfile`과 계약값만 유지한다.
> 전체 경계는 [Infra/k8s/CONTRACT.md](../../Infra/k8s/CONTRACT.md).

## 계약값

| 항목 | 값 |
|---|---|
| 이미지 | `sumgil-be:latest` |
| Dockerfile | `BE/Dockerfile` (빌드 컨텍스트 `BE/`) |
| 리슨 포트 | `8080` |
| 헬스 경로 | `/actuator/health` |
| 라우팅 경로 | `/api/` (호스트 `j15a104.p.ssafy.io`) |
| 네임스페이스 | `prod` |

## 환경변수

플랫폼이 주입한다. BE는 이름으로만 참조한다.

| 구분 | 파일 | 주입 | 키 |
|---|---|---|---|
| 비민감 | `k8s/prod/be-config.env` (커밋) | ConfigMap `be-config` | `DB_URL` `DB_USERNAME` `REDIS_HOST` `REDIS_PORT` `APP_CORS_ALLOWED_ORIGINS` |
| 비밀(데이터) | 데이터 계층 소유(`Infra/k8s/prod/data-secret.env`) | Secret `data-secret` | `DB_PASSWORD` |
| 비밀(앱) | `k8s/prod/be-secret.env` (gitignore) | Secret `be-secret` | 수집기·BE 공용 API 키 |

- `DB_PASSWORD`는 데이터 계층(Infra)이 소유한다. BE는 `data-secret`을 소비만 한다. 배포용 환경변수는 로컬용 `BE/.env`와 별개 파일이다.
- 파일명 규칙(210): `<용도>.env` / `<용도>-secret.env` / `<용도>.env.example`.

## 이미지 만들기

```bash
cd BE
docker build -t sumgil-be:latest .
```

- 로컬 빌드·실행은 [BE/README.md](../README.md) 8절을 따른다.
- 레지스트리 push와 배포는 플랫폼이 한다.

## 배포 가능하게 유지하려면

1. Dockerfile이 이미지를 만들고 컨테이너가 `8080`으로 리슨한다.
2. `/actuator/health`가 `200`을 반환한다.
3. 환경변수를 이름으로만 참조한다 (값 하드코딩 금지).
4. 무상태를 유지한다.

## 이 디렉토리

- `k8s/prod/` — BE 워크로드 매니페스트(Deployment·Service·Ingress·config·secret).
- 데이터 계층(Postgres·Redis·Kafka)은 BE가 아니라 Infra 소유다(`Infra/k8s/prod/`).
