# Frontend

**스택** React · TypeScript · TailwindCSS · Vite

지도 기반 시각화와 분석 대시보드를 담당한다.

---

## 사전 요구사항

| 항목 | 버전 | 상태 |
| --- | --- | --- |
| Node.js | 20 이상 | ✅ 설치됨 (v24.19.0) |
| npm | 10 이상 | ✅ 설치됨 (11.17.0) |

## 초기화

**아직 프로젝트가 생성되지 않았다.** 폴더만 잡아둔 상태이며, 아래 명령으로 스캐폴딩한다.

```bash
cd FE

# Vite + React + TypeScript
npm create vite@latest . -- --template react-ts
npm install

# TailwindCSS v4
npm install tailwindcss @tailwindcss/vite
```

`vite.config.ts`에 플러그인을 등록한다.

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
})
```

`src/index.css` 최상단에 한 줄을 추가한다.

```css
@import "tailwindcss";
```

> 스캐폴딩 도구가 디렉터리 구조를 직접 만들기 때문에, 충돌을 피하려고 하위 폴더를 미리 만들어두지 않았다. 초기화 후 아래 구조를 얹는다.

## 목표 디렉터리 구조

```
FE/
├─ public/
├─ src/
│  ├─ api/         API 클라이언트, 요청·응답 타입
│  ├─ assets/      이미지·폰트
│  ├─ components/  재사용 UI 컴포넌트
│  ├─ features/    도메인 단위 묶음 (컴포넌트 + 훅 + 상태)
│  ├─ hooks/       공용 커스텀 훅
│  ├─ pages/       라우트 단위 화면
│  ├─ stores/      전역 상태
│  ├─ types/       공용 타입 정의
│  └─ utils/       순수 유틸 함수
├─ index.html
├─ vite.config.ts
└─ tsconfig.json
```

## 실행

```bash
npm run dev      # 개발 서버 (http://localhost:5173)
npm run build    # 프로덕션 빌드
npm run preview  # 빌드 결과 미리보기
npm run lint     # 린트
```

## 작업 규칙

- **API 주소는 하드코딩하지 않는다.** `.env`의 `VITE_API_BASE_URL`을 사용하고, `.env.example`에 키 이름만 남긴다.
- 컴포넌트는 `features/` 우선으로 배치하고, 두 곳 이상에서 쓰일 때 `components/`로 올린다.
- 타입은 `any`를 두지 않는다. 서버 응답 타입은 `api/`에 모아 백엔드 명세와 1:1로 맞춘다.
