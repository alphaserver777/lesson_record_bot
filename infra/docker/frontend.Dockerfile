FROM node:20-alpine AS build

WORKDIR /frontend
COPY miniapp/package.json ./
RUN npm install
COPY miniapp/ ./
ENV VITE_API_BASE=/cabinet
ENV VITE_BASE_PATH=/cabinet/
ENV VITE_TELEGRAM_BOT_URL=https://t.me/proffessorit_bot
RUN npm run build

FROM nginx:1.27-alpine
COPY infra/docker/frontend-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /frontend/dist/ /usr/share/nginx/html/
HEALTHCHECK --interval=20s --timeout=5s --retries=5 \
  CMD wget -q --spider http://127.0.0.1/ || exit 1
