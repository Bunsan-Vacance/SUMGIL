# Infra

**스택** AWS EC2 · Nginx · Docker

배포 환경 구성과 컨테이너 오케스트레이션을 담당한다.

---

## 현재 상태

**골격만 잡아둔 단계다.** 각 파트의 Dockerfile이 아직 없어 `docker compose up`으로 전체 스택이 뜨지는 않는다. 다만 BE 로컬 개발에 필요한 `postgres`·`redis`는 실제로 뜬다.

| 파일 | 상태 |
| --- | --- |
| `docker/docker-compose.yml` | `postgres`·`redis`·`kafka`는 실행 가능 (BE 로컬 개발용, [BE/README.md](../BE/README.md) 참고). `fe`·`be`는 각 파트 Dockerfile이 생기기 전까지 주석 처리 |
| `nginx/nginx.conf` | 리버스 프록시 골격 (`server_name` 미지정) |

## 디렉터리 구조

```
Infra/
├─ docker/
│  └─ docker-compose.yml   로컬 통합 실행 (postgres · redis · kafka)
└─ nginx/
   └─ nginx.conf           리버스 프록시 설정
```

## 로컬 기동

```bash
docker compose -f Infra/docker/docker-compose.yml up -d postgres redis      # BE 개발
docker compose -f Infra/docker/docker-compose.yml up -d --wait kafka        # 수집기·스트림
```

Kafka 구성·검증 절차·함정은 [BE/docs/infra/kafka.md](../BE/docs/infra/kafka.md)에 있다.

## 진행 순서

1. **파트별 Dockerfile 작성** — `FE/Dockerfile`, `BE/Dockerfile`
2. **compose 주석 해제** — `docker-compose.yml`의 `fe`, `be`, `db` 블록
3. **환경 변수 분리** — `Infra/docker/.env` 생성 (Git 제외), `.env.example`에 키 이름만 커밋
4. **로컬 검증** — `docker compose -f Infra/docker/docker-compose.yml up --build`
5. **EC2 배포** — 인스턴스 생성 → Docker 설치 → 저장소 클론 → compose 실행 → 도메인·HTTPS 설정

## 라우팅 설계

Nginx가 80 포트를 받아 경로로 갈라 보낸다.

| 경로 | 대상 |
| --- | --- |
| `/` | 프론트엔드 (`fe:5173`) |
| `/api/` | 백엔드 (`be:8080`) |

## 작업 규칙

- **`.env`, `*.pem`, `*.key`는 절대 커밋하지 않는다.** 루트 `.gitignore`에 등록돼 있으나 `git add -f`로 우회하지 않도록 주의한다.
- **EC2에서는 데이터 포트를 `ports:`로 공개하지 않는다.** 현재 `5432`·`6379`·`9092`가 열려 있는 건 로컬 개발 편의다. Docker가 UFW를 우회하므로 그대로 배포하면 인터넷에 노출된다. 배포 시 세 포트를 함께 내부 네트워크로 돌린다.
- EC2 키페어와 DB 접속 정보는 팀 내 별도 채널로 공유한다.
- `nginx.conf` 수정 후에는 `nginx -t`로 문법을 검증한 뒤 reload 한다.

## 참고

현재 개발 환경에 Docker 29.6.1이 설치돼 있어 로컬 검증은 바로 가능하다.
