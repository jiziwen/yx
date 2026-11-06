# 一个镜像运行 API/媒体/维护/调度进程，命令由部署单元明确覆盖。
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.4 /uv /uvx /bin/
WORKDIR /app
COPY services/backend/pyproject.toml services/backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY services/backend/ ./
ENV PYTHONUTF8=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home --uid 10001 yingxu && mkdir -p /app/.data/objects && chown -R yingxu:yingxu /app
USER yingxu
EXPOSE 8100
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8100"]
