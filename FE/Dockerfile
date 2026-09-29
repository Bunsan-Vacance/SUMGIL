FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL
ARG VITE_KAKAO_MAP_APP_KEY
# AI(TIME) 재안내 서버 베이스 URL. 선택 — 비우면 재안내 폴링이 꺼진 채 빌드된다(운영은 Ingress /ai).
ARG VITE_AI_BASE_URL
RUN node -e "for (const name of ['VITE_API_BASE_URL', 'VITE_KAKAO_MAP_APP_KEY']) { if (!process.env[name]?.trim()) throw new Error(name + ' is required'); }" \
    && npm run build

FROM nginx:stable-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
