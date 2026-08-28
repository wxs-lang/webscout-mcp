# Deployment Guide

This guide covers various deployment options for WebScout MCP Server.

## Table of Contents

- [Docker](#docker)
- [Docker Compose](#docker-compose)
- [systemd Service](#systemd-service)
- [Kubernetes](#kubernetes)
- [Configuration](#configuration)

## Docker

### Build the Image

```bash
docker build -t webscout-mcp:latest .
```

### Run with stdio Transport (for MCP Clients)

```bash
docker run -it --rm \
  --name webscout-mcp \
  -e WEBSCOUT_LOG_LEVEL=INFO \
  -v webscout-cache:/home/appuser/.cache/webscout \
  webscout-mcp:latest
```

### Run with SSE Transport

```bash
docker run -d --rm \
  --name webscout-mcp \
  -p 8000:8000 \
  -e WEBSCOUT_LOG_LEVEL=INFO \
  -v webscout-cache:/home/appuser/.cache/webscout \
  webscout-mcp:latest \
  serve --transport sse --host 0.0.0.0 --port 8000
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `WEBSCOUT_LOG_LEVEL` | Log level (DEBUG, INFO, WARNING, ERROR) | WARNING |
| `WEBSCOUT_CACHE_DIR` | Cache directory path | ~/.cache/webscout |
| `WEBSCOUT_CACHE_TTL` | Cache TTL in seconds | 7200 |
| `WEBSCOUT_CACHE_MAX_SIZE_MB` | Max cache size in MB | 512 |
| `WEBSCOUT_REQUEST_TIMEOUT` | Request timeout in seconds | 15.0 |
| `WEBSCOUT_MAX_RETRIES` | Max retries per request | 3 |
| `WEBSCOUT_RATE_LIMIT_PER_SECOND` | Rate limit per domain | 2.0 |
| `WEBSCOUT_SEARCH_BACKENDS` | Search backends (comma-separated) | bing,duckduckgo |
| `WEBSCOUT_SEARCH_MERGE_BACKENDS` | Merge results from all backends | false |
| `WEBSCOUT_CRAWLER_CONCURRENCY` | Crawler concurrency | 5 |
| `WEBSCOUT_RESPECT_ROBOTS` | Respect robots.txt | true |

## Docker Compose

### Quick Start

```bash
# Start the service
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the service
docker-compose down
```

### Configuration

Edit `docker-compose.yml` to customize environment variables, ports, and volumes.

### Persistent Cache

The cache volume `webscout-cache` persists cached data across container restarts.

## systemd Service

### Installation

1. Copy the service file:

```bash
sudo cp deploy/webscout-mcp.service /etc/systemd/system/
```

2. Create the user and directory:

```bash
sudo useradd -r -s /sbin/nologin webscout
sudo mkdir -p /opt/webscout-mcp /var/cache/webscout
sudo chown -R webscout:webscout /opt/webscout-mcp /var/cache/webscout
```

3. Install the package:

```bash
cd /opt/webscout-mcp
sudo -u webscout pip install webscout-mcp
```

4. Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable webscout-mcp
sudo systemctl start webscout-mcp
```

### Management

```bash
# Check status
sudo systemctl status webscout-mcp

# View logs
sudo journalctl -u webscout-mcp -f

# Restart
sudo systemctl restart webscout-mcp

# Stop
sudo systemctl stop webscout-mcp
```

### Security Hardening

The systemd service includes security hardening:
- `NoNewPrivileges=true`
- `PrivateTmp=true`
- `ProtectSystem=strict`
- `ProtectHome=true`
- `RestrictNamespaces=true`
- `MemoryDenyWriteExecute=true`
- `ProtectControlGroups=true`
- `ProtectKernelModules=true`
- `ProtectKernelTunables=true`

## Kubernetes

### Basic Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webscout-mcp
  labels:
    app: webscout-mcp
spec:
  replicas: 1
  selector:
    matchLabels:
      app: webscout-mcp
  template:
    metadata:
      labels:
        app: webscout-mcp
    spec:
      containers:
      - name: webscout-mcp
        image: wxslang/webscout-mcp:latest
        ports:
        - containerPort: 8000
        env:
        - name: WEBSCOUT_LOG_LEVEL
          value: "INFO"
        - name: WEBSCOUT_CACHE_DIR
          value: "/data/cache"
        volumeMounts:
        - name: cache
          mountPath: /data/cache
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
      volumes:
      - name: cache
        persistentVolumeClaim:
          claimName: webscout-cache
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: webscout-cache
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
---
apiVersion: v1
kind: Service
metadata:
  name: webscout-mcp
spec:
  selector:
    app: webscout-mcp
  ports:
  - port: 8000
    targetPort: 8000
  type: ClusterIP
```

### Apply the Deployment

```bash
kubectl apply -f k8s/deployment.yaml
```

## Configuration

### Config File

Create a TOML config file at `~/.config/webscout/config.toml`:

```toml
[cache]
dir = "~/.cache/webscout"
ttl = 7200
max_size_mb = 512

[fetch]
timeout = 15.0
max_retries = 3
retry_backoff = 0.5

[search]
max_results = 10
safe_search = true
backends = ["bing", "duckduckgo"]
merge_backends = false

[crawler]
max_depth = 2
max_pages = 20
same_domain_only = true
concurrency = 5
respect_robots = true

[logging]
level = "WARNING"
json = false
```

### Hot Reload

Configuration can be hot-reloaded at runtime using the `reload()` method:

```python
from webscout_mcp.config import Config

config = Config.from_env()
# ... later ...
config.reload()  # Reload from file and environment
```

## Troubleshooting

### Container won't start

Check logs:
```bash
docker logs webscout-mcp
```

### Permission denied for cache directory

Ensure the cache directory is writable:
```bash
docker run -v $(pwd)/cache:/home/appuser/.cache/webscout ...
```

### SSE endpoint not accessible

Check port mapping and firewall settings:
```bash
docker run -p 8000:8000 ...
```

## Support

For issues and questions, please open an issue on [GitHub](https://github.com/wxs-lang/webscout-mcp/issues).
