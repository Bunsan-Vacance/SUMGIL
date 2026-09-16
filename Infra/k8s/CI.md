# CI 규약 (S15P21A104-210)

> 파이프라인 구조·원칙의 단일 정본. job 추가·트리거 변경 시 이 문서부터 고친다.

## 구조

```
.gitlab-ci.yml            workflow + stages + AI 잡
.gitlab/ci/be.yml         be-test · be-image
.gitlab/ci/fe.yml         fe-test · fe-image
.gitlab/ci/manifests.yml  manifests-validate
.gitlab/ci/deploy.yml     deploy-prod
```

네이밍: `파트-동작`. stages: `lint → test → build → deploy`.

## 브랜치별 동작

| 소스 | 파이프라인 | 배포 |
|---|---|---|
| 개발 push (`develop-*`, `feat/*`) | lint/test만 | 없음 |
| MR | 변경 파트만 | 없음 |
| main push | lint/test + 변경 파트 image | `deploy-prod` 자동 |

`build`·`deploy` job은 main 한정 rules라 개발 파이프라인에 나타나지 않는다.

## 원칙

1. **파일 1개 = 파트 1개.** 트리거 경로는 그 파트 소스 + 자기 CI 파일. 매니페스트 변경은 `manifests-validate`가 맡고 소스 job은 모른다.
2. **트리거는 anchor로 한 곳에.** 경로 추가 시 anchor 1곳만 고친다 (복제 금지 — `fe.yml` 이중 rules가 전례).
3. **검증은 가볍게, 빌드는 main에서만.** 개발 push에 빌드를 태우지 않는다 (시간·레지스트리 오염).
4. **배포는 자동, 롤백은 SHA.** main 통과 = 배포 가능. 이전 SHA 재apply가 롤백 (별도 정책은 백로그).
5. **Secret은 변수에서만.** 값 커밋·로그 출력 금지. 키 목록 원본은 `*.env.example`.
6. **AI는 AI가.** 루트의 AI 잡·트리거는 AI 파트 소유. 건드리기 전 AI 담당자와 협의.

## 트레이드오프

- **자동 배포 vs 수동 승인**: 자동 선택. SHA 불변이라 검증 통과물이 곧 배포물. 실패 시 롤백이 수동과 동일 절차. 단, Secret·VITE 변수 미등록이면 deploy 실패 — 변수 등록이 선행 조건.
- **브랜치별 파일 복제 vs rules 분기**: 분기 선택. 복제는 드리프트 확정 (경로 추가 시 N곳 수정).
- **러너 직통 kubectl vs ssh 경유**: 직통 가정 (러너=a104 호스트). kubeconfig·insecure-registry 미확인 시 첫 main 파이프라인에서 실패 — 그때 ssh 경유로 전환 (⬜).
- **FE 값 주입**: 빌드타임 (`--build-arg`). 런타임 변경 시 이미지 재빌드 필요 — 구조적 제약으로 수용.

## 미확인 (⬜)

- 러너 kubeconfig·docker insecure-registry (첫 main 파이프라인에서 확인).
- GitLab 변수 7건: `DB_PASSWORD`·`SEOUL_*`·`KMA_*`·`VITE_API_BASE_URL`·`VITE_KAKAO_MAP_APP_KEY` (현재 0건).
