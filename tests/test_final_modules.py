"""Tests for API server, OCR, translator, and alert channels modules."""

import pytest

from webscout_mcp.alert_channels import (
    AlertManager,
    AlertMessage,
    AlertResult,
    DingTalkAlert,
    FeishuAlert,
    ServerChanAlert,
    SlackAlert,
    TelegramAlert,
    WebhookAlert,
    WeComAlert,
    create_alert_manager,
)
from webscout_mcp.api_server import (
    APIResponse,
    FetchRequest,
    SearchRequest,
    create_app,
)
from webscout_mcp.ocr_engine import OCREngine, OCRResult, ocr_image
from webscout_mcp.translator import TranslationResult, Translator, translate_text

# ============ API Server Tests ============


class TestAPIServer:
    """Test API server models and creation."""

    def test_search_request(self):
        req = SearchRequest(query="test", max_results=5)
        assert req.query == "test"
        assert req.max_results == 5

    def test_search_request_defaults(self):
        req = SearchRequest(query="test")
        assert req.max_results == 10  # Default value
        assert req.backend is None  # Default value

    def test_fetch_request(self):
        req = FetchRequest(url="https://example.com", extract=True)
        assert req.url == "https://example.com"
        assert req.extract is True

    def test_api_response(self):
        resp = APIResponse(success=True, data={"key": "value"})
        assert resp.success is True
        assert resp.data["key"] == "value"

    def test_create_app(self):
        try:
            app = create_app(title="Test API", version="1.0.0")
            assert app is not None
            assert app.title == "Test API"
        except ImportError:
            pytest.skip("FastAPI not available")

    def test_create_app_with_auth(self):
        try:
            app = create_app(api_key="test-key-123")
            assert app is not None
        except ImportError:
            pytest.skip("FastAPI not available")


# ============ OCR Engine Tests ============


class TestOCREngine:
    """Test OCR engine."""

    def test_creation(self):
        engine = OCREngine(backend="tesseract")
        assert engine.backend == "tesseract"
        assert engine.languages == ["eng"]

    def test_creation_with_languages(self):
        engine = OCREngine(backend="tesseract", languages=["eng", "chi_sim"])
        assert engine.languages == ["eng", "chi_sim"]

    def test_ocr_result(self):
        result = OCRResult(text="Hello World", confidence=0.95)
        assert result.text == "Hello World"
        assert result.confidence == 0.95

    def test_ocr_result_to_dict(self):
        result = OCRResult(text="test", confidence=0.8, backend="tesseract")
        data = result.to_dict()
        assert data["text"] == "test"
        assert data["confidence"] == 0.8
        assert data["backend"] == "tesseract"

    def test_recognize_nonexistent_file(self):
        engine = OCREngine(backend="tesseract")
        result = engine.recognize("/nonexistent/image.png")
        assert result.text == ""
        assert result.confidence == 0.0

    def test_preprocess_disabled(self):
        engine = OCREngine(preprocess=False)
        assert engine.preprocess is False

    def test_is_available(self):
        engine = OCREngine(backend="tesseract")
        # Just check it doesn't crash
        _ = engine.is_available

    def test_ocr_image_convenience(self):
        result = ocr_image("/nonexistent.png", backend="tesseract")
        assert isinstance(result, OCRResult)


# ============ Translator Tests ============


class TestTranslator:
    """Test translator module."""

    def test_creation(self):
        translator = Translator(backend="google", target_language="zh")
        assert translator.backend == "google"
        assert translator.target_language == "zh"

    def test_translation_result(self):
        result = TranslationResult(
            source_text="Hello",
            translated_text="你好",
            source_language="en",
            target_language="zh",
            confidence=0.95,
        )
        assert result.source_text == "Hello"
        assert result.translated_text == "你好"

    def test_translation_result_to_dict(self):
        result = TranslationResult(source_text="test", translated_text="测试", backend="google")
        data = result.to_dict()
        assert data["source_language"] == ""
        assert data["backend"] == "google"

    def test_detect_language_chinese(self):
        translator = Translator()
        lang, conf = translator.detect_language("这是一段中文文本，用于测试语言检测功能")
        assert lang == "zh"
        assert conf > 0.5

    def test_detect_language_english(self):
        translator = Translator()
        lang, conf = translator.detect_language("This is an English text for testing language detection.")
        assert lang == "en"

    def test_detect_language_japanese(self):
        translator = Translator()
        lang, conf = translator.detect_language("これは日本語のテキストです")
        assert lang == "ja"

    def test_detect_language_short(self):
        translator = Translator()
        lang, conf = translator.detect_language("Hi")
        assert lang == "unknown"

    def test_chunk_text_short(self):
        translator = Translator()
        chunks = translator._chunk_text("Short text", max_size=1000)
        assert len(chunks) == 1
        assert chunks[0] == "Short text"

    def test_chunk_text_long(self):
        translator = Translator()
        long_text = "A" * 10000
        chunks = translator._chunk_text(long_text, max_size=1000)
        assert len(chunks) > 1
        assert sum(len(c) for c in chunks) == len(long_text)

    def test_translate_empty(self):
        translator = Translator()
        result = translator.translate("")
        assert result.translated_text == ""
        assert result.confidence == 0.0

    def test_cache_enabled(self):
        translator = Translator(enable_cache=True)
        assert translator.enable_cache is True

    def test_clear_cache(self):
        translator = Translator()
        translator._cache["test"] = TranslationResult()
        translator.clear_cache()
        assert translator.cache_size == 0

    def test_translate_text_convenience(self):
        result = translate_text("Hello", target_language="zh", backend="google")
        assert isinstance(result, TranslationResult)


# ============ Alert Channels Tests ============


class TestAlertChannels:
    """Test alert channels module."""

    def test_alert_message(self):
        msg = AlertMessage(title="Test Alert", content="Test content", level="warning")
        assert msg.title == "Test Alert"
        assert msg.content == "Test content"
        assert msg.level == "warning"

    def test_alert_message_to_dict(self):
        msg = AlertMessage(title="Test", content="Content", level="error")
        data = msg.to_dict()
        assert data["title"] == "Test"
        assert data["level"] == "error"

    def test_alert_result(self):
        result = AlertResult(success=True, channel="webhook", message="Sent")
        assert result.success is True
        assert result.channel == "webhook"

    def test_webhook_alert_creation(self):
        alert = WebhookAlert("https://hooks.example.com/alert")
        assert alert.name == "webhook"
        assert alert.webhook_url == "https://hooks.example.com/alert"

    def test_dingtalk_alert_creation(self):
        alert = DingTalkAlert("https://oapi.dingtalk.com/robot/send?access_token=test")
        assert alert.name == "dingtalk"

    def test_wecom_alert_creation(self):
        alert = WeComAlert("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
        assert alert.name == "wecom"

    def test_feishu_alert_creation(self):
        alert = FeishuAlert("https://open.feishu.cn/open-apis/bot/v2/hook/test")
        assert alert.name == "feishu"

    def test_slack_alert_creation(self):
        alert = SlackAlert("https://hooks.slack.com/services/T00/B00/XXX", channel="#alerts")
        assert alert.name == "slack"
        assert alert.channel == "#alerts"

    def test_telegram_alert_creation(self):
        alert = TelegramAlert(bot_token="123:ABC", chat_id="@testchannel")
        assert alert.name == "telegram"

    def test_serverchan_alert_creation(self):
        alert = ServerChanAlert(send_key="SCT123456Tabcdefg")
        assert alert.name == "serverchan"

    def test_alert_manager_creation(self):
        manager = AlertManager()
        assert manager.num_channels == 0

    def test_alert_manager_add_channel(self):
        manager = AlertManager()
        alert = WebhookAlert("https://example.com/hook")
        manager.add_channel(alert)
        assert manager.num_channels == 1
        assert "webhook" in manager.channels

    def test_alert_manager_remove_channel(self):
        manager = AlertManager()
        alert = WebhookAlert("https://example.com/hook")
        manager.add_channel(alert)
        assert manager.remove_channel("webhook") is True
        assert manager.num_channels == 0

    def test_alert_manager_remove_nonexistent(self):
        manager = AlertManager()
        assert manager.remove_channel("nonexistent") is False

    def test_alert_manager_set_min_level(self):
        manager = AlertManager()
        manager.set_min_level("warning")
        assert manager.min_level == "warning"

    def test_alert_manager_get_channel_status(self):
        manager = AlertManager()
        alert = WebhookAlert("https://example.com/hook", enabled=True)
        manager.add_channel(alert)
        status = manager.get_channel_status()
        assert status["webhook"] is True

    def test_format_message(self):
        alert = WebhookAlert("https://example.com/hook")
        msg = AlertMessage(title="Test", content="Content", level="error", url="https://example.com")
        formatted = alert.format_message(msg)
        assert "Test" in formatted
        assert "Content" in formatted
        assert "https://example.com" in formatted

    def test_create_alert_manager(self):
        config = {
            "webhook": {"url": "https://example.com/hook"},
            "dingtalk": {"webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=test"},
        }
        manager = create_alert_manager(config)
        assert manager.num_channels == 2
        assert "webhook" in manager.channels
        assert "dingtalk" in manager.channels

    def test_alert_disabled_channel(self):
        alert = WebhookAlert("https://example.com/hook", enabled=False)
        msg = AlertMessage(title="Test", content="Test")
        result = alert.send(msg)
        assert result.success is False
        assert "disabled" in result.message.lower()
