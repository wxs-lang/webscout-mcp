    def test_extract_default_on_missing(self):
        extractor = DataExtractor(Config(), None)
        rules = [ExtractionRule(name="missing", selector=".nonexistent", default="N/A")]
        result = extractor.extract_from_html(self.SAMPLE_HTML, rules)
        assert result["missing"] == "N/A"


# --- MCP Server (import test) ---

class TestServer:
    def test_create_server(self):
        """Verify the server can be created without errors."""
        pytest.importorskip("mcp")
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(cache_dir=Path(tmpdir))
            from webscout_mcp.server import create_server
            server = create_server(cfg)
            assert server is not None
