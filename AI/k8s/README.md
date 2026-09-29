# AI/k8s — 서빙 매니페스트 (호스트 프로세스 연결, S15P21A104-211 이미지 전까지)

> 상태: **호스트 systemd 프로세스를 클러스터에 물린 임시 구성**. AI 이미지는 아직 없다.
> AI 에이전트용 안내: 이미지 전환 전에 아래 ⬜를 위에서부터 닫으세요. 추측으로 채우지 마세요.

## 현재 연결 방식

- AI FastAPI는 파드가 아니라 **J15A104A 호스트의 systemd `ai-api.service`**(uvicorn, Tailscale `100.64.193.109:8000`)로 돈다.
  호스트 쪽 반영 절차는 [`AI/README.md`](../README.md) "운영 반영 (J15A104A)" 절.
- 클러스터에는 **selector 없는 Service `ai`(8000) + EndpointSlice `ai-host`(100.64.193.109:8000) + Ingress `ai`**가 있다.
  파드가 없어 selector를 두지 않고 EndpointSlice로 호스트 IP를 직접 지정한다.
- 대상 IP가 Tailscale인 이유: ingress-nginx 파드(control-plane)에서 `100.64.193.109:8000/health` 200이 확인돼
  호스트 bind·ufw 변경이 필요 없다.
- 외부 경로: `https://j15a104.p.ssafy.io/ai/**` → `/ai` prefix를 떼고 호스트로 (`limit-rpm: 30`).

## 파일

| 파일 | 내용 | 상태 |
|---|---|---|
| `prod/ai.yaml` | Service `ai`(selector 없음) + EndpointSlice `ai-host` | ✅ 임시 (이미지 전환 시 Deployment로 교체) |
| `prod/ingress.yaml` | Ingress `ai` (경로 `/ai` prefix → Service `ai`:8000, TLS `sumgil-tls`) | ✅ |
| `prod/kustomization.yaml` | ns prod, resources 2건 (이미지·CM·Secret 생성은 뺌) | ✅ |
| `prod/ai-config.env` | 비민감 설정 (현재 `ENVIRONMENT=prod` 1건) — **현재 미참조** | ⬜ 이미지 전환 시 복원 |
| `prod/ai-secret.env.example` | 비밀 키 목록 (`CROWD_LLM_API_KEY`) — **현재 미참조** | ⬜ 이미지 전환 시 복원 |
| `prod/ai-secret.env` | 실값 (노드 only, gitignore) | — |

호스트 프로세스의 설정·비밀은 서버 `AI/.env`(EnvironmentFile)가 갖는다.

## 전제 (코드 기준, 확정)

- 진입점: `uvicorn app.main:app` (`AI/app/main.py`). 라우터 prefix `/bike`·`/crowd`·`/route`·`/time` + `/health`.
- 서빙 설정 원본: `AI/app/core/config.py` (`Settings`, `.env` 지원).
- 소유 경계: 매니페스트는 AI 저장소 `AI/k8s/`에 둔다 (BE·FE와 동일, `Infra/k8s/CONTRACT.md` 1절).

## ⬜ 미결 (이미지 전환 시, 위에서부터)

1. **Dockerfile** — 이미지 빌드 정의 없음. `sumgil-ai` 이름만 예약. 멀티스테이지 + `uvicorn[standard]` 포함할 것.
   무거운 의존성(torch·pyspark)은 서빙에 필요 — 슬림화는 별도 과제.
2. **데이터·모델 프로비저닝** — `AI/data/`·`AI/models/`는 git 추적 제외(Drive 미러). 호스트 방식은 서버 디스크를 그대로 써서 당장은 해당 없음.
   이미지 전환 시 선택지: (a) initContainer로 Drive/오브젝트에서 받기 (b) PVC에 미리 배치 (c) 이미지 bake.
3. **리소스 값** — 파드 전환 시 BE 복사치(requests 250m/384Mi)부터. 모델 로딩 메모리 실측 후 조정.
4. **Secret 운용** — 파드 전환 시 `CROWD_LLM_API_KEY` 외 키 추가는 `render-secrets.sh` 등록
   (현재 BE·Infra 2종만. AI 로테이션 시점에).
5. **전환 시 되돌릴 것** — `ai.yaml`을 Deployment+Service(selector `app: ai`)로 교체, EndpointSlice `ai-host` 삭제,
   `kustomization.yaml`에 images·configMapGenerator·secretGenerator 복원. Service 이름 `ai`·포트 8000은 Ingress가 참조하니 유지.

해소됨: 외부 공개 경로(Ingress `/ai/**`) — 호스트 프로세스 연결로 열렸다.

## 절차

```bash
# 렌더 검증 (CI manifests-validate가 매번 수행)
kubectl kustomize AI/k8s/prod > /dev/null

# 적용 (control-plane, 저장소 체크아웃에서)
sudo k3s kubectl apply -k AI/k8s/prod        # 또는 -f AI/k8s/prod/ai.yaml -f AI/k8s/prod/ingress.yaml (-n prod)

# 확인
curl https://j15a104.p.ssafy.io/ai/time/meta

# 롤백 (연결만 제거 — 호스트 프로세스는 그대로)
sudo k3s kubectl delete -k AI/k8s/prod
```

## 검증 기준 (211 AC2)

`AI 이미지 빌드 + /health prod 확인`. 이미지는 미해결(⬜ 1) — 현재는 호스트 프로세스의 `/time/meta`로 대신 확인한다.
