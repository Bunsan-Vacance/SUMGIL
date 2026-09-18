# AI/k8s — 서빙 매니페스트 (뼈대, S15P21A104-211)

> 상태: **뼈대만**. `kubectl kustomize` 렌더 검증까지만 된다. 클러스터 적용 금지.
> AI 에이전트용 안내: 값을 채우기 전에 아래 ⬜를 위에서부터 닫으세요. 추측으로 채우지 마세요.

## 파일

| 파일 | 내용 | 상태 |
|---|---|---|
| `prod/ai.yaml` | Deployment(`ai`, :8000, `/health` 프로브) + Service | ⬜ 이미지 없음 |
| `prod/kustomization.yaml` | ns prod, 이미지 매핑, CM/Secret 생성 | ✅ |
| `prod/ai-config.env` | 비민감 설정 (현재 `ENVIRONMENT=prod` 1건) | ⬜ 노브 미확정 |
| `prod/ai-secret.env.example` | 비밀 키 목록 (`CROWD_LLM_API_KEY`) | ⬜ 키 추가 가능 |
| `prod/ai-secret.env` | 실값 (노드 only, gitignore) | — |

## 전제 (코드 기준, 확정)

- 진입점: `uvicorn app.main:app` (`AI/app/main.py`). 라우터 prefix `/bike`·`/crowd`·`/route` + `/health`.
- 서빙 설정 원본: `AI/app/core/config.py` (`Settings`, `.env` 지원). k8s 값과 어긋나면 코드가 아니라 **이 디렉토리**를 고친다.
- 소유 경계: 매니페스트는 AI 저장소 `AI/k8s/`에 둔다 (BE·FE와 동일, `Infra/k8s/CONTRACT.md` 1절).
- Ingress 없음. 외부 공개는 BE 경유(테이블 조립)가 1차 — AI 직호출 공개는 별도 결정 후.

## ⬜ 미결 (위에서부터)

1. **Dockerfile** — 이미지 빌드 정의 없음. `sumgil-ai` 이름만 예약. 멀티스테이지 + `uvicorn[standard]` 포함할 것.
   무거운 의존성(torch·pyspark)은 서빙에 필요 — 슬림화는 별도 과제.
2. **데이터·모델 프로비저닝** — `AI/data/`·`AI/models/`는 git 추적 제외(Drive 미러).
   선택지: (a) initContainer로 Drive/오브젝트에서 받기 (b) PVC에 미리 배치 (c) 이미지 bake.
   서빙은 `crowd_serving_dir`·`bike_serving_dir` parquet, 배치는 `models/`를 읽는다.
3. **리소스 값** — 현재 BE 복사치(requests 250m/384Mi). 모델 로딩 메모리 실측 후 조정.
4. **Secret 운용** — `CROWD_LLM_API_KEY` 외 키 추가 시 `render-secrets.sh` 등록
   (현재 BE·Infra 2종만. AI 로테이션 시점에).
5. **포트** — 8000 가정 (uvicorn 기본). 바꾸면 `ai.yaml` 3곳(port·targetPort·probe) + CONTRACT.

## 절차

```bash
# 렌더 검증 (값 없이 됨 — CI kustomize-validate가 매번 수행)
kubectl kustomize AI/k8s/prod > /dev/null   # ai-secret 더미 필요 (CI 패턴 참고)

# 적용 (⬜ 1~2 닫힌 뒤에만)
# kubectl apply -k AI/k8s/prod --server-side
# kubectl rollout status deployment/ai -n prod
```

## 검증 기준 (211 AC2)

`AI 이미지 빌드 + /health prod 확인`. `/crowd/meta`는 서빙 데이터(⬜ 2) 들어온 뒤.
