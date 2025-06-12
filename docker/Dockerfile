# Dockerfile

FROM python:3.10-slim-bookworm AS builder

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libxrender1 libxtst6 ca-certificates fonts-liberation libasound2 libpangocairo-1.0-0 libpango-1.0-0 libu2f-udev \
    supervisor curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Poetry
ENV POETRY_HOME="/opt/poetry"
ENV POETRY_VERSION=1.8.3
RUN curl -sSL https://install.python-poetry.org | python3 - --version ${POETRY_VERSION} 
ENV PATH="${POETRY_HOME}/bin:${PATH}"

WORKDIR /app_builder

RUN pip install uv

# Copy Poetry project files
COPY pyproject.toml poetry.lock ./

RUN poetry export -f requirements.txt --output requirements.txt --only main --without-hashes && \
    uv pip install --system --no-cache -r requirements.txt


FROM python:3.10-slim-bookworm

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libxrender1 libxtst6 ca-certificates fonts-liberation libasound2 libpangocairo-1.0-0 libpango-1.0-0 libu2f-udev \
    supervisor curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appgroup && useradd -r -g appgroup -s /bin/bash -d /app appuser

WORKDIR /app

# Copy installed packages and executables from builder stage
COPY --from=builder /usr/local/lib/python3.10/site-packages/ /usr/local/lib/python3.10/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /opt/poetry/bin/poetry /usr/local/bin/poetry

# Copy application code
COPY . .

# Install Playwright browsers and dependencies, and fetch camoufox
# Note: poetry is now available in the final image if needed for any build scripts,
# but dependencies should already be installed.
RUN camoufox fetch && \
    python -m playwright install firefox && \
    python -m playwright install-deps firefox

RUN mkdir -p /app/logs && \
    mkdir -p /app/auth_profiles/active && \
    mkdir -p /app/auth_profiles/saved && \
    mkdir -p /app/certs && \
    mkdir -p /app/browser_utils/custom_scripts && \
    mkdir -p /home/appuser/.cache/ms-playwright && \
    mkdir -p /home/appuser/.mozilla && \
    chown -R appuser:appgroup /app && \
    chown -R appuser:appgroup /home/appuser

COPY supervisord.conf /etc/supervisor/conf.d/app.conf

#新增解决 ❌ 错误 (--internal-launch-mode): 执行 camoufox.server.launch_server 时发生异常: Version information not found at /app/.cache/camoufox/version.json. Please run `camoufox fetch` to install.
RUN mkdir -p /var/cache/camoufox && \
    # 2. 从 builder 阶段复制 camoufox 的缓存文件到最终镜像的 /var/cache/camoufox
    # 这是最关键的一步，确保文件内容存在
    cp -a /root/.cache/camoufox/* /var/cache/camoufox/ && \
    # 3. 创建 appuser 期望的缓存路径
    mkdir -p /app/.cache && \
    # 4. 创建软链接，将 /app/.cache/camoufox 指向实际文件所在位置
    ln -s /var/cache/camoufox /app/.cache/camoufox 
#新增结束

RUN python update_browserforge_data.py

EXPOSE 2048
EXPOSE 3120

USER appuser
ENV HOME=/app
ENV PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright

ENV PYTHONUNBUFFERED=1

# Default environment variables (can be overridden by .env or runtime)
ENV PORT=8000
ENV DEFAULT_FASTAPI_PORT=2048
ENV DEFAULT_CAMOUFOX_PORT=9222
ENV STREAM_PORT=3120
ENV SERVER_LOG_LEVEL=INFO
ENV DEBUG_LOGS_ENABLED=false
ENV AUTO_CONFIRM_LOGIN=true

# Backward compatibility
ENV SERVER_PORT=2048
ENV INTERNAL_CAMOUFOX_PROXY=""

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/app.conf"]