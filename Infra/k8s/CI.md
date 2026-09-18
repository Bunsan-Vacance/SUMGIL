# CI 규약 (S15P21A104-210)

> 파이프라인 구조·원칙의 단일 정본. job 추가·트리거 변경 시 이 문서부터 고친다.

## 구조

```
.gitlab-ci.yml            workflow + stages + AI 잡
.gitlab/ci/be.yml         be-test · be-image
.gitlab/ci/fe.yml         fe-test · fe-image
.gitlab/ci/manifests.yml  manifests-validate
.gitlab/ci/deploy.yml     deploy-infra · deploy-be · deploy-fe
```

네이밍: `파트-동작`. stages: `lint → test → build → deploy`.

## 브랜치별 동작

배포 트리거 = 소유자 브랜치 (`CONTRACT.md` §1 소유표를 CI에 옮긴 것). 환경은 하나(namespace `prod`).

| 소스 | 파이프라인 | 배포 |
|---|---|---|
| `feat/*` push | lint/test만 | 없음 |
| MR | 변경 파트 lint/test | 없음 |
| `develop-BE` push (BE 변경) | be-test → `be-image` | `deploy-be` 자동 (BE/k8s/prod) |
| `develop-FE` push (FE 변경) | fe-test → `fe-image` | `deploy-fe` 자동 (FE/k8s/prod) |
| `develop-AI` push | ai-lint/test | 없음 (뼈대. `deploy-ai`는 AI 이미지 생기면) |
| `main` push (Infra 변경) | manifests-validate | `deploy-infra` 자동 (Infra/k8s) |

`build`·`deploy` job은 소유자 브랜치 한정 rules라 `feat/*`·MR 파이프라인에 나타나지 않는다.
세 deploy job은 `resource_group: prod`로 직렬화된다. 한 파트가 깨져도 다른 파트·데이터 계층은 영향 없다.

이미지 태그: `*-image`가 `IMAGE_TAG`(short SHA)를 dotenv로 넘기고, `deploy-*`가 `kustomize edit set image` 후 apply 한다.
태그가 바뀌어야 롤아웃이 난다 — 매니페스트는 `IfNotPresent`라 `latest` 재apply로는 새 코드가 뜨지 않는다.
`IMAGE_TAG`가 없으면(k8s만 변경) 라이브 태그를 유지한다.

## 원칙

1. **파일 1개 = 파트 1개.** 트리거 경로는 그 파트 소스 + 자기 CI 파일. 매니페스트 변경은 `manifests-validate`가 맡고 소스 job은 모른다.
2. **트리거는 anchor로 한 곳에.** 경로 추가 시 anchor 1곳만 고친다 (복제 금지 — `fe.yml` 이중 rules가 전례).
3. **검증은 어디서나, 빌드·배포는 소유자 브랜치에서만.** `feat/*`·MR에 빌드를 태우지 않는다 (시간·레지스트리 오염). 앱은 자기 `develop-*`, 클러스터 계층은 `main`.
4. **배포는 자동, 롤백은 SHA.** 소유자 브랜치 통과 = 배포. 이전 SHA로 `kustomize edit set image` 후 apply가 롤백 (별도 정책은 백로그).
4-1. **클러스터 계층이 먼저.** 계약값(namespace·`data-secret`·레지스트리·ingressClass·`sumgil-tls`)이 바뀌면 `deploy-infra`(main)가 먼저 성공한 뒤 파트가 따라간다. 그 외엔 순서 무관.
5. **Secret은 변수에서만.** 값 커밋·로그 출력 금지. 키 목록 원본은 `*.env.example`.
6. **AI는 AI가.** 루트의 AI 잡·트리거는 AI 파트 소유. 건드리기 전 AI 담당자와 협의.

## 트레이드오프

- **일괄 배포(main 1 job) vs 파트별 배포(소유자 브랜치 3 job)**: 파트별 선택. 일괄은 기능 반영이 `feat → develop → main` 두 홉이고, 변수 하나 비면 전 파트 배포가 선다. 파트별은 한 홉, 자기 변수 없으면 자기 job만 선다. 대가: 안정 환경 없음(환경 하나가 곧 dev) — MVP 기간 감수.
- **자동 배포 vs 수동 승인**: 자동 선택. SHA 불변이라 검증 통과물이 곧 배포물. 실패 시 롤백이 수동과 동일 절차. 단, 자기 파트 Secret·VITE 변수 미등록이면 자기 deploy 실패 — 변수 등록이 선행 조건 (`SECRETS.md`).
- **브랜치별 파일 복제 vs rules 분기**: 분기 선택. 복제는 드리프트 확정 (경로 추가 시 N곳 수정). CI 정의 정본은 main. `develop-*`는 `include: project … ref: main` 스텁으로 끌어온다 (⬜ 첫 파이프라인에서 자기참조 동작 확인, 실패 시 `[SYNC]`로 사본 전파).
- **러너 직통 kubectl vs ssh 경유**: 직통 가정 (러너=a104 호스트). kubeconfig·insecure-registry 미확인 시 첫 배포 파이프라인에서 실패 — 그때 ssh 경유로 전환 (⬜).
- **FE 값 주입**: 빌드타임 (`--build-arg`). 런타임 변경 시 이미지 재빌드 필요 — 구조적 제약으로 수용.

## 미확인 (⬜)

- 러너 kubeconfig·docker insecure-registry (첫 배포 파이프라인에서 확인).
- alpine 3.20 `apk add kustomize` 가용 (실패 시 릴리즈 바이너리 curl로 대체).
- `develop-*` `.gitlab-ci.yml` include 스텁 자기참조 (`[SYNC]` MR에서).
- GitLab 변수 (파트별 등록, `SECRETS.md`): Infra `DB_PASSWORD` · BE `SEOUL_*`·`KMA_*` · FE `VITE_API_BASE_URL`·`VITE_KAKAO_MAP_APP_KEY`.
