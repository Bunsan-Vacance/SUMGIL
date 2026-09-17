# 개발과 검증 기준

## 기능을 추가할 때

1. [구조](architecture.md)에서 수정할 책임을 찾는다. 기능 전용 UI는 `features`, 화면 배치는 `pages`, 여러 기능의 흐름 연결은 `app`에 둔다.
2. 두 기능 이상에서 실제로 같은 규칙을 쓰면 `components`로 올린다. 이름만 비슷한 요소를 무리하게 공통화하지 않는다.
3. 상태는 가장 가까운 소유자에 둔다. 계산 가능한 값은 파생하고, 서로 함께 바뀌는 업무 상태는 reducer에서 처리한다.
4. DOM·SDK·타이머·이벤트·네트워크 사용은 훅/어댑터로 모으고 정리 함수를 작성한다. React StrictMode에서 중복 마운트돼도 오래된 응답이 상태를 갱신하지 않도록 한다.
5. 사용자에게 구현 방식을 설명하는 상시 문구를 추가하지 않는다. 실제로 기다리거나 판단할 상황의 안내만 표시한다.

타입은 `any`로 우회하지 않는다. 서버에서 받은 값은 화면에서 바로 해석하지 않고 데이터 접근 계층에서 검증·변환한다. props는 각 화면이 필요한 값과 동작을 명시하며 전체 앱 상태 객체를 넘기지 않는다.

## 도구

```sh
npm run build         # TypeScript 검증 + 배포 빌드
npm test              # 경로/안내 상태, 계산, 요청 취소 테스트
npm run format        # 코드와 문서 포맷
npm run format:check  # 형식 확인
```

Prettier는 코드와 문서 형식만 검사한다. ESLint나 React 전용 린트를 수행한다고 간주하지 않는다. 현재 별도 ESLint 설정은 없다.

## 변경별 검증

- 계산/상태 규칙 변경: 해당 단위 테스트와 빌드.
- API/비동기 변경: 성공·실패·취소·늦은 응답을 확인.
- 경로 응답 계약 변경: `routeMapper`의 `congestionPrediction`, TIME/COMFORT 정렬, 구간 전환·지도 marker focused test와 빌드.
- 화면/레이아웃 변경: 관련 흐름을 모바일 크기에서 브라우저로 확인. 확대된 시트의 내부 스크롤과 고정 버튼을 함께 본다.
- 지도 변경: `localhost:5173`에서 타일, 출발/도착 마커, 시트 크기 변경, 화면 전환을 확인. 승인 없이 위치 권한을 자동 요청하지 않는다.
- 낮은 영향의 단순 문구/스타일 변경에 구현을 그대로 따라 쓰는 테스트를 추가하지 않는다.

현재 경로 계약 focused 검증은 FE 디렉터리에서 다음으로 실행한다.

```powershell
node node_modules/vitest/vitest.mjs run src/api/routeMapper.test.ts src/features/route/LegList.test.tsx src/features/map/routeMapMarkers.test.ts src/features/map/KakaoMap.test.tsx src/api/mock/repositories.test.ts
```

## 수동 회귀 확인

홈 → 도착지 검색 → 결과 → 다른 경로 선택 → 상세 → 안내 → 도착. 필터 취소/적용, 결과 없음, 브라우저 뒤로 가기, 시트 클릭/드래그/키보드도 관련 변경 시 확인한다. 안내의 단계/탑승/제안은 제품 화면 밖의 미리보기 도구로 조작한다.

## 문서 갱신

| 변경                         | 함께 갱신할 문서                  |
| ---------------------------- | --------------------------------- |
| 파일 책임·의존 방향          | `architecture.md`                 |
| 상태 소유·초기화·화면 전환   | `state.md`                        |
| API 계약·샘플/실제 연결 상태 | `data-integration.md`             |
| 명령·환경 변수·실행 요건     | `setup.md`, FE README             |
| 팀이 결정한 구조 방향        | 문서 README의 현재 결정/변경 기록 |

파일마다 설명 문서를 만들거나 코드 내용을 문서에 복제하지 않는다. 책임·이유·연결 지점·한계를 중심으로 유지한다. 완료한 작업만 구현 완료로 표시한다.

브랜치·커밋·MR은 저장소의 Git 컨벤션을 따른다. 이 문서는 Jira 키 생성이나 원격 푸시를 승인하지 않는다.
