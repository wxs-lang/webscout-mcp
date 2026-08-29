"""Competitor analysis module for webscout-mcp.

Compare multiple websites across SEO, performance, content quality, and more.
Generate detailed comparison reports with scores and recommendations.

Features:
- Multi-site SEO comparison
- Performance benchmarking
- Content quality comparison
- Backlink profile comparison (basic)
- Social media presence comparison
- Feature comparison matrix
- Overall ranking and scoring
- Actionable recommendations
- Exportable comparison reports
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..logging_config import get_logger

log = get_logger(__name__)


@dataclass
class SiteMetrics:
    """Metrics for a single site."""

    url: str = ""
    name: str = ""
    # SEO metrics
    seo_score: float = 0.0
    title_length: int = 0
    meta_description_length: int = 0
    heading_count: int = 0
    h1_count: int = 0
    image_count: int = 0
    images_with_alt: int = 0
    internal_links: int = 0
    external_links: int = 0
    has_schema: bool = False
    has_og_tags: bool = False
    has_twitter_cards: bool = False
    canonical_url: str = ""
    # Performance metrics
    performance_score: float = 0.0
    html_size_kb: float = 0.0
    dom_node_count: int = 0
    request_count: int = 0
    css_count: int = 0
    js_count: int = 0
    has_gzip: bool = False
    has_brotli: bool = False
    has_cache_headers: bool = False
    has_lazy_loading: bool = False
    render_blocking_resources: int = 0
    # Content metrics
    content_score: float = 0.0
    word_count: int = 0
    content_length: int = 0
    readability_score: float = 0.0
    keyword_density: dict = field(default_factory=dict)
    # Broken links
    broken_link_count: int = 0
    total_link_count: int = 0
    # Overall
    overall_score: float = 0.0
    rank: int = 0

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "name": self.name,
            "seo_score": self.seo_score,
            "performance_score": self.performance_score,
            "content_score": self.content_score,
            "overall_score": self.overall_score,
            "rank": self.rank,
            "title_length": self.title_length,
            "heading_count": self.heading_count,
            "image_count": self.image_count,
            "images_with_alt": self.images_with_alt,
            "internal_links": self.internal_links,
            "external_links": self.external_links,
            "has_schema": self.has_schema,
            "html_size_kb": self.html_size_kb,
            "dom_node_count": self.dom_node_count,
            "request_count": self.request_count,
            "word_count": self.word_count,
            "broken_link_count": self.broken_link_count,
            "total_link_count": self.total_link_count,
        }


@dataclass
class ComparisonResult:
    """Result of competitor comparison."""

    sites: list[SiteMetrics] = field(default_factory=list)
    comparison_matrix: dict[str, list] = field(default_factory=dict)
    winner: str | None = None
    recommendations: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "sites": [s.to_dict() for s in self.sites],
            "winner": self.winner,
            "recommendations": self.recommendations,
            "summary": self.summary,
            "num_sites": len(self.sites),
        }


class CompetitorAnalyzer:
    """Analyze and compare multiple competitor websites.

    Features:
    - Multi-metric comparison
    - Automatic ranking
    - Feature comparison matrix
    - Gap analysis
    - Actionable recommendations
    """

    def __init__(
        self,
        seo_weight: float = 0.35,
        performance_weight: float = 0.30,
        content_weight: float = 0.25,
        broken_link_weight: float = 0.10,
    ) -> None:
        self.seo_weight = seo_weight
        self.performance_weight = performance_weight
        self.content_weight = content_weight
        self.broken_link_weight = broken_link_weight

    def add_site(
        self,
        url: str,
        name: str = "",
        seo_metrics: dict | None = None,
        performance_metrics: dict | None = None,
        content_metrics: dict | None = None,
        link_metrics: dict | None = None,
    ) -> SiteMetrics:
        """Add a site to compare.

        Args:
            url: Site URL.
            name: Site name (defaults to URL).
            seo_metrics: SEO metrics dict.
            performance_metrics: Performance metrics dict.
            content_metrics: Content metrics dict.
            link_metrics: Link metrics dict.

        Returns:
            SiteMetrics with all metrics.
        """
        site = SiteMetrics(url=url, name=name or url)

        if seo_metrics:
            self._apply_seo_metrics(site, seo_metrics)
        if performance_metrics:
            self._apply_performance_metrics(site, performance_metrics)
        if content_metrics:
            self._apply_content_metrics(site, content_metrics)
        if link_metrics:
            self._apply_link_metrics(site, link_metrics)

        # Calculate scores
        self._calculate_scores(site)

        return site

    def _apply_seo_metrics(self, site: SiteMetrics, metrics: dict) -> None:
        """Apply SEO metrics to site."""
        site.title_length = metrics.get("title_length", 0)
        site.meta_description_length = metrics.get("meta_description_length", 0)
        site.heading_count = metrics.get("heading_count", 0)
        site.h1_count = metrics.get("h1_count", 0)
        site.image_count = metrics.get("image_count", 0)
        site.images_with_alt = metrics.get("images_with_alt", 0)
        site.internal_links = metrics.get("internal_links", 0)
        site.external_links = metrics.get("external_links", 0)
        site.has_schema = metrics.get("has_schema", False)
        site.has_og_tags = metrics.get("has_og_tags", False)
        site.has_twitter_cards = metrics.get("has_twitter_cards", False)
        site.canonical_url = metrics.get("canonical_url", "")

    def _apply_performance_metrics(self, site: SiteMetrics, metrics: dict) -> None:
        """Apply performance metrics to site."""
        site.html_size_kb = metrics.get("html_size_kb", 0)
        site.dom_node_count = metrics.get("dom_node_count", 0)
        site.request_count = metrics.get("request_count", 0)
        site.css_count = metrics.get("css_count", 0)
        site.js_count = metrics.get("js_count", 0)
        site.has_gzip = metrics.get("has_gzip", False)
        site.has_brotli = metrics.get("has_brotli", False)
        site.has_cache_headers = metrics.get("has_cache_headers", False)
        site.has_lazy_loading = metrics.get("has_lazy_loading", False)
        site.render_blocking_resources = metrics.get("render_blocking_resources", 0)

    def _apply_content_metrics(self, site: SiteMetrics, metrics: dict) -> None:
        """Apply content metrics to site."""
        site.word_count = metrics.get("word_count", 0)
        site.content_length = metrics.get("content_length", 0)
        site.readability_score = metrics.get("readability_score", 0)
        site.keyword_density = metrics.get("keyword_density", {})

    def _apply_link_metrics(self, site: SiteMetrics, metrics: dict) -> None:
        """Apply link metrics to site."""
        site.broken_link_count = metrics.get("broken_link_count", 0)
        site.total_link_count = metrics.get("total_link_count", 0)

    def _calculate_scores(self, site: SiteMetrics) -> None:
        """Calculate individual and overall scores for a site."""
        # SEO Score (0-100)
        seo_score = 50  # Base
        if 30 <= site.title_length <= 60:
            seo_score += 15
        if 70 <= site.meta_description_length <= 160:
            seo_score += 10
        if site.h1_count == 1:
            seo_score += 10
        if site.image_count > 0 and site.images_with_alt == site.image_count:
            seo_score += 10
        if site.has_schema:
            seo_score += 5
        if site.has_og_tags:
            seo_score += 5
        if site.has_twitter_cards:
            seo_score += 5
        if site.canonical_url:
            seo_score += 5
        site.seo_score = min(100, seo_score)

        # Performance Score (0-100)
        perf_score = 50  # Base
        if site.html_size_kb <= 50:
            perf_score += 15
        elif site.html_size_kb <= 100:
            perf_score += 10
        if site.dom_node_count <= 500:
            perf_score += 15
        elif site.dom_node_count <= 1500:
            perf_score += 10
        if site.request_count <= 10:
            perf_score += 10
        elif site.request_count <= 20:
            perf_score += 5
        if site.has_gzip or site.has_brotli:
            perf_score += 5
        if site.has_cache_headers:
            perf_score += 5
        if site.has_lazy_loading:
            perf_score += 5
        if site.render_blocking_resources == 0:
            perf_score += 5
        site.performance_score = min(100, perf_score)

        # Content Score (0-100)
        content_score = 30  # Base
        if site.word_count >= 300:
            content_score += 20
        if site.word_count >= 1000:
            content_score += 15
        if site.readability_score >= 60:
            content_score += 20
        if site.readability_score >= 80:
            content_score += 15
        site.content_score = min(100, content_score)

        # Broken Link Score (0-100, higher is better)
        if site.total_link_count > 0:
            broken_ratio = site.broken_link_count / site.total_link_count
            link_score = max(0, 100 - broken_ratio * 200)
        else:
            link_score = 100  # No links = perfect score

        # Overall Score (weighted average)
        site.overall_score = round(
            site.seo_score * self.seo_weight
            + site.performance_score * self.performance_weight
            + site.content_score * self.content_weight
            + link_score * self.broken_link_weight,
            2,
        )

    def compare(self, sites: list[SiteMetrics]) -> ComparisonResult:
        """Compare multiple sites and generate report.

        Args:
            sites: List of SiteMetrics to compare.

        Returns:
            ComparisonResult with comparison data.
        """
        result = ComparisonResult(sites=sites)

        if not sites:
            return result

        # Rank sites by overall score
        ranked = sorted(sites, key=lambda s: s.overall_score, reverse=True)
        for i, site in enumerate(ranked):
            site.rank = i + 1

        result.winner = ranked[0].name if ranked else None

        # Build comparison matrix
        metrics_to_compare = [
            "overall_score",
            "seo_score",
            "performance_score",
            "content_score",
            "title_length",
            "heading_count",
            "image_count",
            "images_with_alt",
            "internal_links",
            "external_links",
            "html_size_kb",
            "dom_node_count",
            "request_count",
            "word_count",
            "broken_link_count",
        ]

        for metric in metrics_to_compare:
            values = []
            for site in sites:
                value = getattr(site, metric, None)
                values.append(value)
            result.comparison_matrix[metric] = values

        # Generate recommendations
        result.recommendations = self._generate_recommendations(sites)

        # Generate summary
        result.summary = self._generate_summary(sites)

        return result

    def _generate_recommendations(self, sites: list[SiteMetrics]) -> list[str]:
        """Generate actionable recommendations based on comparison."""
        recommendations = []

        if len(sites) < 2:
            return ["Add more sites for meaningful comparison."]

        # Find best and worst in each category
        best_seo = max(sites, key=lambda s: s.seo_score)
        worst_seo = min(sites, key=lambda s: s.seo_score)
        best_perf = max(sites, key=lambda s: s.performance_score)
        worst_perf = min(sites, key=lambda s: s.performance_score)
        best_content = max(sites, key=lambda s: s.content_score)
        worst_content = min(sites, key=lambda s: s.content_score)

        if best_seo.name != worst_seo.name:
            recommendations.append(
                f"SEO: {worst_seo.name} can learn from {best_seo.name} "
                f"(score gap: {best_seo.seo_score - worst_seo.seo_score:.1f})"
            )

        if best_perf.name != worst_perf.name:
            recommendations.append(
                f"Performance: {worst_perf.name} should optimize page speed "
                f"(gap: {best_perf.performance_score - worst_perf.performance_score:.1f})"
            )

        if best_content.name != worst_content.name:
            recommendations.append(
                f"Content: {worst_content.name} should improve content quality "
                f"(gap: {best_content.content_score - worst_content.content_score:.1f})"
            )

        # Specific recommendations
        for site in sites:
            if site.image_count > 0 and site.images_with_alt < site.image_count:
                missing = site.image_count - site.images_with_alt
                recommendations.append(f"{site.name}: Add alt text to {missing} image(s)")

            if not site.has_schema:
                recommendations.append(f"{site.name}: Add Schema.org structured data")

            if not site.has_gzip and not site.has_brotli:
                recommendations.append(f"{site.name}: Enable gzip/brotli compression")

            if not site.has_cache_headers:
                recommendations.append(f"{site.name}: Add cache-control headers")

            if site.broken_link_count > 0:
                recommendations.append(f"{site.name}: Fix {site.broken_link_count} broken link(s)")

        return recommendations

    def _generate_summary(self, sites: list[SiteMetrics]) -> str:
        """Generate a human-readable summary."""
        if not sites:
            return "No sites to compare."

        ranked = sorted(sites, key=lambda s: s.overall_score, reverse=True)
        lines = [f"Comparison of {len(sites)} websites:", ""]

        for i, site in enumerate(ranked):
            lines.append(
                f"{i + 1}. {site.name} - Overall: {site.overall_score:.1f} "
                f"(SEO: {site.seo_score:.0f}, Perf: {site.performance_score:.0f}, "
                f"Content: {site.content_score:.0f})"
            )

        lines.append("")
        lines.append(f"Winner: {ranked[0].name} with score {ranked[0].overall_score:.1f}")

        return "\n".join(lines)

    def export_comparison_table(self, result: ComparisonResult) -> str:
        """Export comparison as Markdown table.

        Args:
            result: Comparison result.

        Returns:
            Markdown formatted table.
        """
        if not result.sites:
            return "No data to export."

        site_names = [s.name for s in result.sites]
        lines = ["| Metric | " + " | ".join(site_names) + " |"]
        lines.append("|" + "---|" * (len(site_names) + 1))

        display_metrics = [
            ("Overall Score", "overall_score"),
            ("SEO Score", "seo_score"),
            ("Performance Score", "performance_score"),
            ("Content Score", "content_score"),
            ("Title Length", "title_length"),
            ("Headings", "heading_count"),
            ("Images", "image_count"),
            ("Images with Alt", "images_with_alt"),
            ("Internal Links", "internal_links"),
            ("External Links", "external_links"),
            ("HTML Size (KB)", "html_size_kb"),
            ("DOM Nodes", "dom_node_count"),
            ("Requests", "request_count"),
            ("Word Count", "word_count"),
            ("Broken Links", "broken_link_count"),
        ]

        for label, metric in display_metrics:
            values = []
            for site in result.sites:
                value = getattr(site, metric, "-")
                if isinstance(value, float):
                    values.append(f"{value:.1f}")
                else:
                    values.append(str(value))
            lines.append(f"| {label} | " + " | ".join(values) + " |")

        return "\n".join(lines)


def compare_sites(sites_data: list[dict]) -> ComparisonResult:
    """Convenience function to compare sites.

    Args:
        sites_data: List of dicts with url, name, and metrics.

    Returns:
        ComparisonResult with comparison data.
    """
    analyzer = CompetitorAnalyzer()
    sites = []
    for data in sites_data:
        site = analyzer.add_site(
            url=data.get("url", ""),
            name=data.get("name", ""),
            seo_metrics=data.get("seo", {}),
            performance_metrics=data.get("performance", {}),
            content_metrics=data.get("content", {}),
            link_metrics=data.get("links", {}),
        )
        sites.append(site)
    return analyzer.compare(sites)
