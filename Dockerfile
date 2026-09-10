# Dockerfile for webscout-mcp
# https://github.com/wxs-lang/webscout-mcp
#
# IMPORTANT: Version is managed by setuptools-scm (Git tag as single source of truth).
# The wheel is pre-built in CI (with full .git metadata) and copied into this image.
# Do NOT build the wheel inside Docker - setuptools-scm cannot detect version without .git.

FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="webscout-mcp" \
      org.opencontainers.image.description="A smart web search & fetch MCP server with built-in caching, rate-limiting, and content extraction" \
      org.opencontainers.image.url="https://github.com/wxs-lang/webscout-mcp" \
      org.opencontainers.image.documentation="https://github.com/wxs-lang/webscout-mcp#readme" \
      org.opencontainers.image.source="https://github.com/wxs-lang/webscout-mcp" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libcurl4 \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built wheel (built in CI with full Git metadata for setuptools-scm)
# The wheel is expected to be in dist/ directory of the build context
COPY dist/*.whl /tmp/

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
