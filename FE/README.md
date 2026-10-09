# 숨길 프론트엔드

React · TypeScript · Vite · TailwindCSS 기반 모바일 웹앱.

## 시작하기

```sh
npm ci
npm run dev
```

[http://localhost:5173](http://localhost:5173)에서 확인한다. 실제 카카오 지도를 쓰려면 `.env.local`의 JavaScript 키와 카카오 앱의 SDK 도메인 등록이 필요하다. 키는 저장소에 포함하지 않는다.

## 휴대폰에서 앱으로 사용하기

배포된 HTTPS 주소를 휴대폰 브라우저로 연 뒤 홈 화면에 추가하면 앱처럼 사용할 수 있다.

- Android: 브라우저 메뉴에서 `앱 설치` 또는 `홈 화면에 추가`를 선택한다.
- iPhone: Safari의 공유 메뉴에서 `홈 화면에 추가`를 선택한다.

이 앱은 카카오 지도와 경로 API를 사용하므로 인터넷 연결이 필요하다. 오프라인 사용은 지원하지 않는다.

## 문서

**[프론트엔드 문서 시작점](docs/README.md)**

- [설치·환경 설정·미리보기](docs/setup.md)
- [폴더 구조와 책임](docs/architecture.md)
- [상태 소유와 화면 흐름](docs/state.md)
- [데이터 접근과 API 연결](docs/data-integration.md)
- [개발·검증·문서 갱신 기준](docs/development.md)
- [실제 FE 이미지 배포](docs/deployment.md)

AI 작업 지침은 [AGENTS.md](AGENTS.md)를 참고한다. 과거 기획은 [초기 기록](docs/history/initial-frontend-plan.md)에 보관했다.

## 현재 구현

홈(상단 검색창·집/회사 칩·최근 경로 시트)·장소 검색·최근 검색·연속 경로 목록·이동수단 필터·상세·길안내·도착 화면. 출발·도착 교환, 현재 위치 출발, 지도에서 위치 선택을 연결했고 바텀시트 드래그/클릭/키보드 조작과 실제 카카오 지도·장소 마커를 지원한다.

`VITE_API_BASE_URL`을 설정하면 백엔드 경로·대여소·실시간 열차 도착·잔여 경로 재탐색 API를 사용하고, 설정하지 않으면 preview용 샘플 저장소로 실행한다. 백엔드 주소를 유지한 채 최종 경로 응답을 확인하려면 `.env.local`에서 `VITE_ROUTE_SEARCH_MOCK=true`를 명시한다. 이때 경로 검색만 `ApiResult` 형식의 `MOCK` 응답을 사용하고 다른 API는 계속 백엔드에 연결한다. 장소명·도로명 주소 검색은 카카오 JavaScript SDK에 연결했다.

## 검증

```sh
npm run build
npm test
npm run format:check
```

브랜치·커밋·MR은 [팀 Git 컨벤션](../Docs/Convention/Git%20Convention.md)을 따른다.
