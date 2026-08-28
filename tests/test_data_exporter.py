"""Tests for enhanced data exporter module."""
import os
import json
import tempfile
import pytest
from webscout_mcp.data_exporter import ExportConfig, ExportResult, DataExporter, export_data


class TestExportConfig:
    """Test ExportConfig class."""

    def test_config_creation(self):
        config = ExportConfig()
        assert config.format == "json"
        assert config.pretty_json is True
        assert config.csv_delimiter == ","
        assert config.append is False

    def test_config_custom(self):
        config = ExportConfig(
            format="csv",
            output_path="/tmp/test.csv",
            fields=["name", "url"],
            pretty_json=False,
            append=True,
        )
        assert config.format == "csv"
        assert config.output_path == "/tmp/test.csv"
        assert config.fields == ["name", "url"]
        assert config.pretty_json is False
        assert config.append is True

    def test_config_from_env(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_EXPORT_FORMAT", "csv")
        monkeypatch.setenv("WEBSCOUT_EXPORT_PATH", "/tmp/env.csv")
        monkeypatch.setenv("WEBSCOUT_EXPORT_PRETTY", "false")
        monkeypatch.setenv("WEBSCOUT_EXPORT_APPEND", "true")

        config = ExportConfig.from_env()
        assert config.format == "csv"
        assert config.output_path == "/tmp/env.csv"
        assert config.pretty_json is False
        assert config.append is True


class TestExportResult:
    """Test ExportResult class."""

    def test_result_creation(self):
        result = ExportResult()
        assert result.success is False
        assert result.record_count == 0
        assert result.error_message == ""

    def test_result_to_dict(self):
        result = ExportResult(
            success=True,
            output_path="/tmp/test.json",
            format="json",
            record_count=10,
            file_size_bytes=1024,
            file_size_kb=1.0,
            fields_exported=["name", "url"],
        )
        data = result.to_dict()
        assert data["success"] is True
        assert data["output_path"] == "/tmp/test.json"
        assert data["format"] == "json"
        assert data["record_count"] == 10
        assert data["file_size_bytes"] == 1024
        assert data["fields_exported"] == ["name", "url"]


class TestDataExporter:
    """Test DataExporter class."""

    @pytest.fixture
    def sample_data(self):
        return [
            {"name": "Result 1", "url": "https://example.com/1", "score": 0.95},
            {"name": "Result 2", "url": "https://example.com/2", "score": 0.85},
            {"name": "Result 3", "url": "https://example.com/3", "score": 0.75},
        ]

    def test_exporter_creation(self):
        exporter = DataExporter()
        assert exporter.config.format == "json"

    def test_exporter_custom_config(self):
        config = ExportConfig(format="csv", output_path="/tmp/test.csv")
        exporter = DataExporter(config=config)
        assert exporter.config.format == "csv"

    def test_export_json(self, sample_data):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name

        try:
            exporter = DataExporter(ExportConfig(format="json", output_path=output_path))
            result = exporter.export(sample_data)
            assert result.success is True
            assert result.format == "json"
            assert result.record_count == 3
            assert result.file_size_bytes > 0

            # Verify file content
            with open(output_path, "r") as f:
                data = json.load(f)
            assert len(data) == 3
            assert data[0]["name"] == "Result 1"
        finally:
            os.unlink(output_path)

    def test_export_csv(self, sample_data):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            output_path = f.name

        try:
            exporter = DataExporter(ExportConfig(format="csv", output_path=output_path))
            result = exporter.export(sample_data)
            assert result.success is True
            assert result.format == "csv"
            assert result.record_count == 3

            # Verify file content
            with open(output_path, "r") as f:
                content = f.read()
            assert "name" in content
            assert "Result 1" in content
        finally:
            os.unlink(output_path)

    def test_export_markdown(self, sample_data):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            output_path = f.name

        try:
            exporter = DataExporter(ExportConfig(format="markdown", output_path=output_path))
            result = exporter.export(sample_data)
            assert result.success is True
            assert result.format == "markdown"

            with open(output_path, "r") as f:
                content = f.read()
            assert "| name |" in content
            assert "Result 1" in content
        finally:
            os.unlink(output_path)

    def test_export_html(self, sample_data):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            output_path = f.name

        try:
            exporter = DataExporter(ExportConfig(format="html", output_path=output_path))
            result = exporter.export(sample_data)
            assert result.success is True
            assert result.format == "html"

            with open(output_path, "r") as f:
                content = f.read()
            assert "<table>" in content
            assert "Result 1" in content
        finally:
            os.unlink(output_path)

    def test_export_sqlite(self, sample_data):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            output_path = f.name

        try:
            exporter = DataExporter(ExportConfig(format="sqlite", output_path=output_path))
            result = exporter.export(sample_data)
            assert result.success is True
            assert result.format == "sqlite"
            assert result.file_size_bytes > 0
        finally:
            os.unlink(output_path)

    def test_export_with_field_selection(self, sample_data):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name

        try:
            config = ExportConfig(format="json", output_path=output_path, fields=["name", "url"])
            exporter = DataExporter(config=config)
            result = exporter.export(sample_data)
            assert result.success is True
            assert "score" not in result.fields_exported
            assert "name" in result.fields_exported
            assert "url" in result.fields_exported

            with open(output_path, "r") as f:
                data = json.load(f)
            assert "score" not in data[0]
        finally:
            os.unlink(output_path)

    def test_export_with_field_order(self, sample_data):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name

        try:
            config = ExportConfig(
                format="json",
                output_path=output_path,
                field_order=["url", "name", "score"],
            )
            exporter = DataExporter(config=config)
            result = exporter.export(sample_data)
            assert result.success is True
            assert result.fields_exported[0] == "url"
            assert result.fields_exported[1] == "name"
        finally:
            os.unlink(output_path)

    def test_export_empty_data(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name

        try:
            exporter = DataExporter(ExportConfig(format="json", output_path=output_path))
            result = exporter.export([])
            assert result.success is False
            assert "No data" in result.error_message
        finally:
            os.unlink(output_path)

    def test_export_no_output_path(self, sample_data):
        exporter = DataExporter(ExportConfig(format="json"))
        result = exporter.export(sample_data)
        assert result.success is False
        assert "output path" in result.error_message

    def test_export_unsupported_format(self, sample_data):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            output_path = f.name

        try:
            exporter = DataExporter(ExportConfig(format="txt", output_path=output_path))
            result = exporter.export(sample_data)
            assert result.success is False
            assert "Unsupported format" in result.error_message
        finally:
            os.unlink(output_path)

    def test_csv_append_mode(self, sample_data):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            output_path = f.name

        try:
            # First export
            config1 = ExportConfig(format="csv", output_path=output_path, append=False)
            exporter1 = DataExporter(config=config1)
            result1 = exporter1.export(sample_data)
            assert result1.success is True

            # Second export (append)
            config2 = ExportConfig(format="csv", output_path=output_path, append=True)
            exporter2 = DataExporter(config=config2)
            result2 = exporter2.export(sample_data)
            assert result2.success is True

            # Verify file has 7 lines (1 header + 3 + 3 data)
            with open(output_path, "r") as f:
                lines = f.readlines()
            assert len(lines) == 7
        finally:
            os.unlink(output_path)


class TestConvenienceFunction:
    """Test export_data convenience function."""

    def test_export_data_json(self):
        data = [{"name": "Test", "value": 123}]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name

        try:
            result = export_data(data, output_path, export_format="json")
            assert result.success is True
            assert result.format == "json"
            assert result.record_count == 1
        finally:
            os.unlink(output_path)

    def test_export_data_with_fields(self):
        data = [{"name": "Test", "value": 123, "extra": "ignore"}]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name

        try:
            result = export_data(data, output_path, export_format="json", fields=["name", "value"])
            assert result.success is True
            assert "extra" not in result.fields_exported
        finally:
            os.unlink(output_path)
