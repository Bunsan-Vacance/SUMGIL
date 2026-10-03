# 실제 FE 이미지 배포

`Dockerfile`은 Node 24에서 React 앱을 빌드하고 Nginx에서 `dist`를 제공한다.
컨테이너 포트는 80, 헬스 체크는 `/healthz`다. 기존 FE Deployment·Service·Ingress 계약을 유지한다.

## 빌드

FE 디렉터리에서 실행한다. 아래 두 환경변수를 배포 셸에 먼저 설정한다.
카카오 키는 JavaScript 키만 사용하고 키 값은 커밋하거나 빌드 로그에 출력하지 않는다.

- `VITE_API_BASE_URL`: 배포 사이트의 HTTPS origin. 현재는 `https://j15a104.p.ssafy.io`.
- `VITE_KAKAO_MAP_APP_KEY`: 카카오 JavaScript 키. SDK 허용 도메인에 배포 origin을 등록한다.
- `VITE_GRAFANA_BASE_URL`(선택): 운영자 뷰의 Grafana 보드 링크 베이스. 운영은 `https://j15a104.p.ssafy.io/grafana`. 비우면 링크가 비활성으로 빌드된다.

```sh
docker build --build-arg VITE_API_BASE_URL --build-arg VITE_KAKAO_MAP_APP_KEY -t sumgil-fe:latest .
```

두 인수가 비어 있으면 빌드를 중단한다. 로컬 `.env*`는 Docker 컨텍스트에서 제외하므로 개발 서버 주소를 실수로 배포하지 않는다.
`VITE_*`는 빌드 시 정적 JS에 포함되며 컨테이너 실행 이후 ConfigMap 변경으로 바뀌지 않는다.
API base에 `/api`를 붙이면 endpoint의 `/api`와 중복된다. `/` 또는 빈 값은 현재 FE에서 mock 모드로 처리되므로 사용하지 않는다.

## 서버 반영

플랫폼 배포 계약은 `Infra/k8s/CONTRACT.md`를 따른다. 이미지 저장소 주소는 기존 인프라 설정에서 읽는다.
기존 `build-push.sh`는 build-arg 전달이 없으므로 이 Dockerfile에는 위 명령으로 빌드한 이미지를 사용한다.

1. `npm test`와 실제 환경변수로 `npm run build`를 확인한다.
2. 이미지를 빌드하고 컨테이너에서 Nginx 설정, `/`, `/healthz`, JS/CSS 자산 응답을 확인한다.
3. 기존 FE 이미지 digest를 기록해 롤백할 수 있게 한다.
4. 빌드한 이미지를 기존 `sumgil-fe:latest` 저장소에 push한다.
5. 현재 Deployment의 imagePullPolicy가 Always인 것을 확인한 후 플랫폼 담당자가 FE만 rollout restart한다. 같은 latest 태그에 push만 하면 기존 파드는 교체되지 않는다.
6. FE replica 준비 상태와 공개 사이트의 실제 React HTML·자산·API·지도를 확인한다.

전체 `apply.sh`는 데이터 계층과 BE도 적용하므로 FE 이미지 교체만 할 때는 필요하지 않다.
원격 배포 디렉터리는 최신 FE 소스로 별도 준비하고, 기존 서버 FE/k8s 파일을 덮어쓰지 않는다.
MR은 develop-FE를 대상으로 만들며 실제 Jira 작업 키를 연결한다.

## 확인 범위

React 화면 배포와 BE 데이터 준비는 별개다. 역 검색이 빈 배열이면 BE 적재 상태를 확인한다.
카카오 도메인 미등록·HTTPS 인증서 문제는 이미지 빌드 성공만으로 해결되지 않는다.
