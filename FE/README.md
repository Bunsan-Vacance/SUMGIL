# 숨길 프론트엔드

React · TypeScript · Vite · TailwindCSS 기반 모바일 웹앱.

## 시작하기

```sh
npm ci
npm run dev
```

[http://localhost:5173](http://localhost:5173)에서 확인한다. 실제 카카오 지도를 쓰려면 `.env.local`의 JavaScript 키와 카카오 앱의 SDK 도메인 등록이 필요하다. 키는 저장소에 포함하지 않는다.

## 문서

**[프론트엔드 문서 시작점](docs/README.md)**

- [설치·환경 설정·미리보기](docs/setup.md)
- [폴더 구조와 책임](docs/architecture.md)
- [상태 소유와 화면 흐름](docs/state.md)
- [데이터 접근과 API 연결](docs/data-integration.md)
- [개발·검증·문서 갱신 기준](docs/development.md)

AI 작업 지침은 [AGENTS.md](AGENTS.md)를 참고한다. 과거 기획은 [초기 기록](docs/history/initial-frontend-plan.md)에 보관했다.

## 현재 구현

홈·장소 검색·최근 검색·연속 경로 목록·이동수단 필터·상세·길안내·도착 화면. 출발·도착 교환, 현재 위치 출발, 지도에서 위치 선택을 연결했고 바텀시트 드래그/클릭/키보드 조작과 실제 카카오 지도·장소 마커를 지원한다.

경로 계산·소요시간·혼잡도는 아직 샘플이다. 장소명·도로명 주소 검색은 카카오 JavaScript SDK에 연결했고, 실제 경로선·자동 안내·백엔드 경로 API와 실시간 열차 정보는 미연결이다.

## 검증

```sh
npm run build
npm test
npm run format:check
```

브랜치·커밋·MR은 [팀 Git 컨벤션](../Docs/Convention/Git%20Convention.md)을 따른다.
