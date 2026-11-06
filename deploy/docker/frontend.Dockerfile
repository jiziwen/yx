# 构建用户端或管理端，二者拥有独立产物及 Nginx 配置。
FROM node:20.19-bookworm-slim AS build
RUN corepack enable && corepack prepare pnpm@11.25.0 --activate
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY apps/ ./apps/
COPY packages/ ./packages/
RUN pnpm install --frozen-lockfile
ARG APP_NAME=web
RUN pnpm --filter @yingxu/${APP_NAME} build && cp -r apps/${APP_NAME}/dist /frontend-dist
FROM nginx:1.28-alpine
ARG APP_NAME=web
COPY --from=build /frontend-dist/ /usr/share/nginx/html/
COPY deploy/nginx/${APP_NAME}.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
