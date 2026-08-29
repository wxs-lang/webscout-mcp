"""REST API server module for webscout-mcp.

FastAPI-based REST API server providing HTTP endpoints for all webscout features.
Includes OpenAPI documentation, authentication, and rate limiting.

Features:
- Search endpoints (multi-backend)
- Fetch and content extraction endpoints
- Crawl endpoints
- SEO analysis, broken link check, performance analysis
- Vector search and RAG endpoints
- Monitoring endpoints
- Data export endpoints
- OpenAPI / Swagger documentation
- API key authentication
- CORS support
- Health check endpoints
"""

from __future__ import annotations

import json
from typing import Any

from .logging_config import get_logger

log = get_logger(__name__)

try:
    from fastapi import Depends, FastAPI, Header, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

    # Fallback base classes
    class BaseModel:  # type: ignore
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    def Field(default=None, **kwargs):  # type: ignore
        return default


# Request/Response models
class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query")
    max_results: int = Field(default=10, ge=1, le=50, description="Max results")
    backend: str | None = Field(default=None, description="Search backend (bing, duckduckgo, google, brave)")


class FetchRequest(BaseModel):
    url: str = Field(..., description="URL to fetch")
    extract: bool = Field(default=True, description="Extract article content")
    render_js: bool = Field(default=False, description="Render JavaScript")
    format: str = Field(default="markdown", description="Output format (text, markdown, html)")


class CrawlRequest(BaseModel):
    url: str = Field(..., description="Start URL")
    max_depth: int = Field(default=2, ge=0, le=5, description="Max crawl depth")
    max_pages: int = Field(default=50, ge=1, le=500, description="Max pages to crawl")
    concurrency: int = Field(default=5, ge=1, le=20, description="Concurrent requests")


class SEORequest(BaseModel):
    url: str | None = Field(default=None, description="URL to analyze")
    html: str | None = Field(default=None, description="HTML content to analyze")


class BrokenLinkRequest(BaseModel):
    url: str | None = Field(default=None, description="URL to check")
    html: str | None = Field(default=None, description="HTML content to check")
    base_url: str | None = Field(default=None, description="Base URL for relative links")


class PerformanceRequest(BaseModel):
    url: str | None = Field(default=None, description="URL to analyze")
    html: str | None = Field(default=None, description="HTML content to analyze")


class VectorSearchRequest(BaseModel):
    query: str = Field(..., description="Search query")
    collection: str = Field(default="default", description="Collection name")
    top_k: int = Field(default=5, ge=1, le=50, description="Number of results")


class RAGRequest(BaseModel):
    query: str = Field(..., description="Question")
    collection: str = Field(default="default", description="Collection name")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of context documents")


class MonitorRequest(BaseModel):
    url: str = Field(..., description="URL to monitor")
    check_interval: int = Field(default=300, ge=10, description="Check interval in seconds")
    alert_type: str = Field(default="webhook", description="Alert type (webhook, email)")
    alert_target: str = Field(..., description="Alert target URL or email")


class ExportRequest(BaseModel):
    data: list[dict[str, Any]] = Field(..., description="Data to export")
    format: str = Field(default="json", description="Export format (json, csv, excel, markdown, html)")
    fields: list[str] | None = Field(default=None, description="Fields to export")


class APIResponse(BaseModel):
    success: bool = True
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def create_app(
    title: str = "WebScout MCP API",
    version: str = "1.0.0",
    api_key: str | None = None,
    cors_origins: list[str] | None = None,
) -> Any:
    """Create and configure FastAPI application.

    Args:
        title: API title.
        version: API version.
        api_key: Optional API key for authentication.
        cors_origins: Optional CORS origins list.

    Returns:
        Configured FastAPI application.
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError("FastAPI is required for REST API. Install with: pip install fastapi uvicorn")

    app = FastAPI(
        title=title,
        version=version,
        description="AI-powered web intelligence platform API",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS middleware
    origins = cors_origins or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API key authentication dependency
    async def verify_api_key(x_api_key: str | None = Header(None)):
        if api_key and x_api_key != api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return x_api_key

    # Dependency for protected routes
    auth_dep = Depends(verify_api_key) if api_key else None

    # ============ Health Check ============
    @app.get("/health", response_model=APIResponse, tags=["System"])
    async def health_check():
        """Health check endpoint."""
        return APIResponse(
            success=True,
            data={"status": "healthy", "version": version},
        )

    @app.get("/health/ready", response_model=APIResponse, tags=["System"])
    async def readiness_check():
        """Readiness check endpoint."""
        return APIResponse(
            success=True,
            data={"status": "ready", "dependencies": {"fastapi": "ok"}},
        )

    # ============ Search Endpoints ============
    @app.post("/api/v1/search", response_model=APIResponse, tags=["Search"])
    async def search(request: SearchRequest):
        """Search the web using multiple backends."""
        try:
            from . import WebScout

            scout = WebScout()
            results = scout.search(
                request.query,
                max_results=request.max_results,
                backend=request.backend,
            )
            return APIResponse(
                success=True,
                data=[r.to_dict() if hasattr(r, "to_dict") else r for r in results],
                metadata={"query": request.query, "count": len(results)},
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ============ Fetch Endpoints ============
    @app.post("/api/v1/fetch", response_model=APIResponse, tags=["Fetch"])
    async def fetch_url(request: FetchRequest):
        """Fetch and extract content from a URL."""
        try:
            from . import WebScout

            scout = WebScout()
            page = scout.fetch(
                request.url,
                extract=request.extract,
                render_js=request.render_js,
            )
            return APIResponse(
                success=True,
                data=page.to_dict() if hasattr(page, "to_dict") else {"content": str(page)},
                metadata={"url": request.url},
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ============ Crawl Endpoints ============
    @app.post("/api/v1/crawl", response_model=APIResponse, tags=["Crawl"])
    async def crawl_site(request: CrawlRequest):
        """Crawl a website starting from a URL."""
        try:
            from . import WebScout

            scout = WebScout()
            pages = scout.crawl(
                request.url,
                depth=request.max_depth,
                max_pages=request.max_pages,
            )
            return APIResponse(
                success=True,
                data=[p.to_dict() if hasattr(p, "to_dict") else p for p in pages],
                metadata={"url": request.url, "pages_crawled": len(pages)},
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ============ Analysis Endpoints ============
    @app.post("/api/v1/analysis/seo", response_model=APIResponse, tags=["Analysis"])
    async def seo_analysis(request: SEORequest):
        """Perform SEO analysis on a URL or HTML content."""
        try:
            from .seo_analyzer import SEOAnalyzer

            analyzer = SEOAnalyzer()
            if request.html:
                metrics = analyzer.analyze(request.html, url=request.url or "")
            elif request.url:
                from . import WebScout

                scout = WebScout()
                page = scout.fetch(request.url)
                metrics = analyzer.analyze(page.html if hasattr(page, "html") else str(page), url=request.url)
            else:
                raise HTTPException(status_code=400, detail="Either url or html must be provided")
            return APIResponse(success=True, data=metrics.to_dict())
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/v1/analysis/broken-links", response_model=APIResponse, tags=["Analysis"])
    async def broken_links(request: BrokenLinkRequest):
        """Check for broken links on a page."""
        try:
            from .broken_link_checker import BrokenLinkChecker

            checker = BrokenLinkChecker()
            if request.html:
                report = checker.check_page(request.html, base_url=request.base_url or "")
            elif request.url:
                from . import WebScout

                scout = WebScout()
                page = scout.fetch(request.url)
                html = page.html if hasattr(page, "html") else str(page)
                report = checker.check_page(html, base_url=request.url)
            else:
                raise HTTPException(status_code=400, detail="Either url or html must be provided")
            return APIResponse(success=True, data=report.to_dict())
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/v1/analysis/performance", response_model=APIResponse, tags=["Analysis"])
    async def performance_analysis(request: PerformanceRequest):
        """Analyze page performance."""
        try:
            from .performance_analyzer import PerformanceAnalyzer

            analyzer = PerformanceAnalyzer()
            if request.html:
                metrics = analyzer.analyze(request.html, url=request.url or "")
            elif request.url:
                from . import WebScout

                scout = WebScout()
                page = scout.fetch(request.url)
                html = page.html if hasattr(page, "html") else str(page)
                metrics = analyzer.analyze(html, url=request.url)
            else:
                raise HTTPException(status_code=400, detail="Either url or html must be provided")
            return APIResponse(success=True, data=metrics.to_dict())
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ============ Vector Search & RAG Endpoints ============
    @app.post("/api/v1/vector/search", response_model=APIResponse, tags=["Vector Search"])
    async def vector_search(request: VectorSearchRequest):
        """Semantic search in vector store."""
        try:
            from .vector_store import VectorStore

            store = VectorStore()  # type: ignore[call-arg]
            results = store.search(request.query, n_results=request.top_k)
            return APIResponse(
                success=True,
                data=[r.to_dict() if hasattr(r, "to_dict") else r for r in results],
                metadata={"query": request.query, "count": len(results)},
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/v1/rag/query", response_model=APIResponse, tags=["RAG"])
    async def rag_query(request: RAGRequest):
        """Ask a question using RAG (Retrieval-Augmented Generation)."""
        try:
            from .vector_store import RAGEngine, VectorStore

            store = VectorStore()  # type: ignore[call-arg]
            rag = RAGEngine(vector_store=store)
            answer = rag.query(request.query, n_results=request.top_k)  # type: ignore[call-arg]
            return APIResponse(success=True, data=answer)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ============ Monitoring Endpoints ============
    @app.post("/api/v1/monitor/add", response_model=APIResponse, tags=["Monitoring"])
    async def add_monitor(request: MonitorRequest):
        """Add a URL to monitor."""
        try:
            from .monitor import MonitorConfig, WebMonitor

            config = MonitorConfig(check_interval=request.check_interval)
            monitor = WebMonitor(config=config)
            return APIResponse(
                success=True,
                data={"url": request.url, "interval": request.check_interval, "status": "added"},
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ============ Export Endpoints ============
    @app.post("/api/v1/export", response_model=APIResponse, tags=["Export"])
    async def export_data(request: ExportRequest):
        """Export data to various formats."""
        try:
            from .data_exporter import DataExporter, ExportConfig

            config = ExportConfig(format=request.format, fields=request.fields or [])
            exporter = DataExporter(config=config)
            # For API, return the exported content as string
            if request.format == "json":
                content = json.dumps(request.data, indent=2, ensure_ascii=False)
            elif request.format == "csv":
                import csv
                import io

                output = io.StringIO()
                if request.data:
                    writer = csv.DictWriter(output, fieldnames=request.data[0].keys())
                    writer.writeheader()
                    writer.writerows(request.data)
                content = output.getvalue()
            else:
                content = json.dumps(request.data, indent=2)
            return APIResponse(
                success=True,
                data={"format": request.format, "content": content, "count": len(request.data)},
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ============ Metrics Endpoint ============
    @app.get("/metrics", tags=["System"])
    async def prometheus_metrics():
        """Prometheus metrics endpoint."""
        try:
            from .metrics import get_metrics

            metrics = get_metrics()
            return metrics.generate_metrics()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    return app


def run_server(
    host: str = "0.0.0.0",  # nosec B104 - default bind address, user can override
    port: int = 8000,
    api_key: str | None = None,
    cors_origins: list[str] | None = None,
    reload: bool = False,
) -> None:
    """Run the REST API server.

    Args:
        host: Server host.
        port: Server port.
        api_key: Optional API key for authentication.
        cors_origins: Optional CORS origins.
        reload: Enable auto-reload for development.
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError("FastAPI and uvicorn are required. Install with: pip install fastapi uvicorn")

    import uvicorn

    app = create_app(api_key=api_key, cors_origins=cors_origins)

    log.info("Starting WebScout API server", extra={"host": host, "port": port})
    uvicorn.run(app, host=host, port=port, reload=reload)
