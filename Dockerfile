# Dockerfile for webscout-mcp
# https://github.com/wxs-lang/webscout-mcp

FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md LICENSE ./
COPY webscout_mcp/ ./webscout_mcp/

# Build the package
RUN pip install --no-cache-dir --upgrade pip build wheel \
    && python -m build --wheel --outdir /dist

# Runtime stage
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="webscout-mcp" \
      org.opencontainers.image.description="A smart web search & fetch MCP server with built-in caching, rate-limiting, and content extraction" \
      org.opencontainers.image.url="https://github.com/wxs-lang/webscout-mcp" \
      org.opencontainers.image.documentation="https://github.com/wxs-lang/webscout-mcp#readme" \
      org.opencontainers.image.source="https://github.com/wxs-lang/webscout-mcp" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="0.4.0"

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy built wheel from builder stage
COPY --from=builder /dist/*.whl /tmp/

# Install the package
RUN pip install --no-cache-dir /tmp/*.whl \
    && rm -rf /tmp/*.whl

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /home/appuser/.cache/webscout \
    && chown -R appuser:appuser /home/appuser

USER appuser

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEBSCOUT_CACHE_DIR=/home/appuser/.cache/webscout

# Expose SSE port (if using SSE transport)
EXPOSE 8000

# Default command: run as MCP server (stdio transport)
ENTRYPOINT ["webscout-mcp"]
CMD ["serve", "--transport", "stdio"]
