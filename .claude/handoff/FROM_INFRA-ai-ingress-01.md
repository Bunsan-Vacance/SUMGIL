# [INFRA → AI] 회신 — AI Ingress 신규 개설·CORS·무인증 노출 방지

- **보낸 사람**: 정인웅 (INFRA)
- **받는 사람**: 최형수 (AI)
- **날짜**: 2026-09-23
- **회신 대상**: `TO_INFRA-ai-ingress-01.md`
- **관련 티켓**: S15P21A104-292 (에픽 S15P21A104-250)
- **브랜치**: `feat/QA-ai-ingress-cors-ratelimit` (`origin/main` 기준)

## 문항별 회신

| # | 질문 | 회신 |
| --- | --- | --- |
| 1 | `/ai/**` Ingress 개설 가능한가, 언제쯤 | **가능.** `AI/k8s/prod/ingress.yaml` 작성 완료, 이 브랜치 머지 후 바로 배포 가능 |
| 2 | 도메인이 FE·BE와 같은가 (CORS 필요 여부) | **같습니다.** `j15a104.p.ssafy.io` 그대로 씁니다 — **CORS 자체가 필요 없습니다**(아래 설명) |
| 3 | CORS를 Ingress에서 할지 앱에서 할지 | **둘 다 필요 없음.** 2번 답 때문에 질문이 성립하지 않습니다 |
| 4 | Ingress 레이트리밋 가능 여부·단위 | **가능.** ingress-nginx `limit-rpm` 어노테이션, **클라이언트 IP당 분당 요청 수** 단위 |

## 1. Ingress 개설 — 가능, 경로·prefix strip 포함

`AI/k8s/prod/ingress.yaml`을 새로 만들었습니다. `BE/k8s/prod/ingress.yaml`·`FE/k8s/prod/ingress.yaml`과 같은 패턴으로, 각 파트가 자기 경로만 선언하고 같은 호스트에 얹습니다(nginx가 더 긴 prefix를 우선 매칭).

- 외부 경로: `/ai/**`
- 내부 전달: `ai:8000/**` (prefix strip 적용)
- AI 앱 라우터가 `/ai` 접두어 없이 등록돼 있다는 전제입니다(`app/main.py`가 `/time/reroute/check`처럼 도메인 prefix만 쓰는 기존 패턴 그대로). 만약 실제로는 앱이 `/ai`를 포함해서 등록한다면 rewrite를 빼야 하니 확인 부탁드립니다.

```yaml
# 발췌 — 전체는 AI/k8s/prod/ingress.yaml
annotations:
  nginx.ingress.kubernetes.io/use-regex: "true"
  nginx.ingress.kubernetes.io/rewrite-target: /$2
rules:
  - host: j15a104.p.ssafy.io
    http:
      paths:
        - path: /ai(/|$)(.*)
          pathType: ImplementationSpecific
          backend:
            service: { name: ai, port: { number: 8000 } }
```

## 2·3. CORS — 같은 도메인이라 필요 없음

FE·BE와 **완전히 같은 호스트**(`j15a104.p.ssafy.io`)에 경로만 나눠 얹었습니다. 브라우저 입장에서 FE 페이지(`https://j15a104.p.ssafy.io/`)가 `https://j15a104.p.ssafy.io/ai/...`를 부르는 건 **오리진(스킴+호스트+포트)이 완전히 같은 요청**이라, 애초에 CORS 프리플라이트가 발생하지 않습니다. Ingress에도 앱에도 CORS 설정을 넣을 필요가 없습니다 — "어느 층에서 할지" 자체가 질문으로 성립하지 않는 상황입니다.

## 4. 레이트리밋 — 가능, IP당 분당 단위

ingress-nginx(현재 v1.15.1, 별도 설치·업그레이드 불필요)가 기본 제공하는 `nginx.ingress.kubernetes.io/limit-rpm` 어노테이션으로 걸었습니다.

- 단위: **클라이언트 IP당 분당 요청 수** (요청하신 안 A와 동일)
- 지금 값: `30`/분 — 실측 근거 없는 잠정값입니다. 재안내 판정 1건이 LLM 호출 1회(2~4초)라고 하셨으니, 실제 사용 패턴(폴링 주기, 동시 사용자 수)을 알려주시면 숫자를 맞추겠습니다.
- 세션 토큰 헤더 검증(AI가 직접 발급·검증)은 이 레이트리밋과 별개로 AI 쪽에서 진행해 주시면 됩니다 — Ingress는 헤더를 그대로 통과시키므로 막을 이유가 없습니다.

## 참고 — 아직 안 된 것

- `AI/k8s/prod/ai.yaml`의 이미지가 아직 미빌드 상태(`⬜ 이미지 미빌드`, 211 본작업)라 Ingress를 배포해도 백엔드 파드가 뜨기 전까지는 502가 납니다. 302(엔드포인트) 배포 시점에 맞춰 이 브랜치도 같이 머지하면 됩니다.
- `AI/k8s/prod/ai.yaml`의 라우터 마운트 경로가 실제로 `/ai` 접두어 없이 등록돼 있는지는 AI 쪽에서 확인 부탁드립니다 — 다르면 `rewrite-target` 한 줄만 빼면 됩니다.
