FROM python:3.12-slim-trixie

LABEL io.modelcontextprotocol.server.name="io.github.D4Vinci/Scrapling"
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy dependency file first for better layer caching
COPY pyproject.toml ./
COPY requirements.txt ./

# Install dependencies only
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --all-extras --compile-bytecode

# Copy source code
COPY . .

# Install browsers and project in one optimized layer
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/var/cache/apt \
    --mount=type=cache,target=/var/lib/apt \
    apt-get update && \
    uv run playwright install-deps chromium && \
    uv run playwright install chromium && \
    uv sync --all-extras --compile-bytecode && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Expose port for HTTP server
EXPOSE 8000

# Ensure required Python packages are available at build time
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

# Default command: run as web service with Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]