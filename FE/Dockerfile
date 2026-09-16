FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL
ARG VITE_KAKAO_MAP_APP_KEY
RUN node -e "for (const name of ['VITE_API_BASE_URL', 'VITE_KAKAO_MAP_APP_KEY']) { if (!process.env[name]?.trim()) throw new Error(name + ' is required'); }" \
    && npm run build

FROM nginx:stable-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
