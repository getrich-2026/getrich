FROM python:3.12-slim

# 安装系统依赖（uv + postgres client for psycopg build）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 先复制依赖文件以利用 layer cache
COPY pyproject.toml uv.lock ./

# 安装依赖到 system Python（容器内无需 venv 隔离）
RUN uv pip install --system --no-cache .

# 复制源码
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY migrations/clickhouse/ ./migrations/clickhouse/
COPY scripts/ ./scripts/

# 默认命令（可被 docker-compose 覆盖）
CMD ["uv", "run", "uvicorn", "getrich.apps.web.main:app", "--host", "0.0.0.0", "--port", "8000"]
