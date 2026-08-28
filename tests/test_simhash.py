"""Tests for SimHash duplicate detection module."""

import pytest

from webscout_mcp.simhash import DuplicateDetector, SimHash, SimHashResult, compute_simhash, hamming_distance


class TestSimHash:
    """Test SimHash class."""

    def test_creation(self):
        simhash = SimHash()
        assert simhash.hash_bits == 64
        assert simhash.n_grams == 1
        assert simhash.use_stop_words is True

    def test_creation_128bit(self):
        simhash = SimHash(hash_bits=128)
        assert simhash.hash_bits == 128

    def test_invalid_hash_bits(self):
        with pytest.raises(ValueError):
            SimHash(hash_bits=32)

    def test_tokenize_basic(self):
        simhash = SimHash()
        tokens = simhash.tokenize("The quick brown fox jumps over the lazy dog")
        assert "quick" in tokens
        assert "brown" in tokens
        assert "fox" in tokens
        # Stop words should be filtered
        assert "the" not in tokens

    def test_tokenize_empty(self):
        simhash = SimHash()
        assert simhash.tokenize("") == []

    def test_tokenize_chinese(self):
        simhash = SimHash(use_stop_words=False)
        tokens = simhash.tokenize("这是一个中文测试")
        assert len(tokens) > 0

    def test_tokenize_ngrams(self):
        simhash = SimHash(n_grams=2)
        tokens = simhash.tokenize("quick brown fox jumps")
        assert any("quick brown" in t for t in tokens)
        assert any("brown fox" in t for t in tokens)

    def test_compute_fingerprint(self):
        simhash = SimHash()
        fp = simhash.compute_fingerprint("The quick brown fox jumps over the lazy dog")
        assert isinstance(fp, int)
        assert fp > 0

    def test_compute_fingerprint_empty(self):
        simhash = SimHash()
        assert simhash.compute_fingerprint("") == 0

    def test_similar_texts_similar_fingerprints(self):
        simhash = SimHash()
        text1 = "The quick brown fox jumps over the lazy dog"
        text2 = "The quick brown fox jumps over the lazy dog!"
        fp1 = simhash.compute_fingerprint(text1)
        fp2 = simhash.compute_fingerprint(text2)
        distance = simhash.hamming_distance(fp1, fp2)
        assert distance < 10  # Similar texts should have small distance

    def test_different_texts_different_fingerprints(self):
        simhash = SimHash()
        text1 = "The quick brown fox jumps over the lazy dog"
        text2 = "Machine learning is a subset of artificial intelligence"
        fp1 = simhash.compute_fingerprint(text1)
        fp2 = simhash.compute_fingerprint(text2)
        distance = simhash.hamming_distance(fp1, fp2)
        assert distance > 10  # Different texts should have larger distance

    def test_hamming_distance_identical(self):
        assert SimHash.hamming_distance(0b1010, 0b1010) == 0

    def test_hamming_distance_different(self):
        assert SimHash.hamming_distance(0b1010, 0b0101) == 4

    def test_similarity_identical(self):
        simhash = SimHash()
        assert simhash.similarity(0b1010, 0b1010) == 1.0

    def test_similarity_completely_different(self):
        simhash = SimHash(hash_bits=64)
        # All bits different: 64 bits different out of 64 = 0.0 similarity
        all_ones = (1 << 64) - 1
        assert simhash.similarity(0, all_ones) == 0.0

    def test_is_duplicate_true(self):
        simhash = SimHash()
        assert simhash.is_duplicate(0b1010, 0b1011, threshold=1) is True

    def test_is_duplicate_false(self):
        simhash = SimHash()
        assert simhash.is_duplicate(0b1010, 0b0101, threshold=1) is False

    def test_custom_stop_words(self):
        simhash = SimHash(custom_stop_words={"custom", "stopword"})
        tokens = simhash.tokenize("this is a custom stopword test")
        assert "custom" not in tokens
        assert "stopword" not in tokens
        assert "test" in tokens

    def test_with_weights(self):
        simhash = SimHash()
        weights = {"important": 10.0, "trivial": 0.1}
        fp = simhash.compute_fingerprint("important trivial word", weights=weights)
        assert isinstance(fp, int)


class TestDuplicateDetector:
    """Test DuplicateDetector class."""

    def test_creation(self):
        detector = DuplicateDetector()
        assert detector.document_count == 0
        assert detector.threshold == 3

    def test_add_document(self):
        detector = DuplicateDetector()
        fp = detector.add_document("doc1", "The quick brown fox jumps over the lazy dog")
        assert detector.document_count == 1
        assert isinstance(fp, int)

    def test_add_fingerprint(self):
        detector = DuplicateDetector()
        detector.add_fingerprint("doc1", 12345)
        assert detector.document_count == 1

    def test_check_duplicate_found(self):
        detector = DuplicateDetector(threshold=5)
        detector.add_document("doc1", "The quick brown fox jumps over the lazy dog")
        result = detector.check_duplicate("The quick brown fox jumps over the lazy dog!")
        assert result.is_duplicate is True
        assert result.matched_id == "doc1"

    def test_check_duplicate_not_found(self):
        detector = DuplicateDetector()
        detector.add_document("doc1", "The quick brown fox jumps over the lazy dog")
        result = detector.check_duplicate("Machine learning is a subset of artificial intelligence")
        assert result.is_duplicate is False

    def test_check_fingerprint(self):
        detector = DuplicateDetector()
        detector.add_fingerprint("doc1", 0b10101010)
        result = detector.check_fingerprint(0b10101011)
        assert result.hamming_distance == 1

    def test_check_empty_detector(self):
        detector = DuplicateDetector()
        result = detector.check_duplicate("some text")
        assert result.is_duplicate is False
        assert result.hamming_distance == 64

    def test_find_duplicates(self):
        detector = DuplicateDetector(threshold=5)
        docs = {
            "doc1": "The quick brown fox jumps over the lazy dog",
            "doc2": "The quick brown fox jumps over the lazy dog!",
            "doc3": "Completely different text about machine learning",
        }
        duplicates = detector.find_duplicates(docs)
        assert len(duplicates) >= 1
        # doc1 and doc2 should be duplicates
        duplicate_pairs = [(d[0], d[1]) for d in duplicates]
        assert ("doc1", "doc2") in duplicate_pairs or ("doc2", "doc1") in duplicate_pairs

    def test_remove_document(self):
        detector = DuplicateDetector()
        detector.add_document("doc1", "test text")
        assert detector.remove_document("doc1") is True
        assert detector.document_count == 0

    def test_remove_nonexistent(self):
        detector = DuplicateDetector()
        assert detector.remove_document("nonexistent") is False

    def test_clear(self):
        detector = DuplicateDetector()
        detector.add_document("doc1", "test1")
        detector.add_document("doc2", "test2")
        detector.clear()
        assert detector.document_count == 0

    def test_get_stats(self):
        detector = DuplicateDetector()
        detector.add_document("doc1", "test text")
        stats = detector.get_stats()
        assert stats["document_count"] == 1
        assert stats["hash_bits"] == 64
        assert stats["threshold"] == 3

    def test_custom_threshold(self):
        detector = DuplicateDetector(threshold=10)
        detector.add_document("doc1", "The quick brown fox jumps over the lazy dog")
        # With higher threshold, more texts will be considered duplicates
        result = detector.check_duplicate("A quick brown fox leaps over a lazy dog")
        assert result.hamming_distance <= 20  # Should be somewhat similar

    def test_128bit_detector(self):
        detector = DuplicateDetector(hash_bits=128)
        fp = detector.add_document("doc1", "test text")
        assert fp > 0
        assert detector.hash_bits == 128


class TestSimHashResult:
    """Test SimHashResult class."""

    def test_creation(self):
        result = SimHashResult(fingerprint=123, hamming_distance=5, is_duplicate=True, similarity=0.92)
        assert result.fingerprint == 123
        assert result.hamming_distance == 5
        assert result.is_duplicate is True
        assert result.similarity == 0.92

    def test_to_dict(self):
        result = SimHashResult(
            fingerprint=123,
            hamming_distance=5,
            is_duplicate=True,
            similarity=0.92,
            matched_id="doc1",
        )
        data = result.to_dict()
        assert data["fingerprint"] == 123
        assert data["hamming_distance"] == 5
        assert data["is_duplicate"] is True
        assert data["similarity"] == 0.92
        assert data["matched_id"] == "doc1"


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_compute_simhash(self):
        fp = compute_simhash("The quick brown fox jumps over the lazy dog")
        assert isinstance(fp, int)
        assert fp > 0

    def test_compute_simhash_128bit(self):
        fp = compute_simhash("test text", hash_bits=128)
        assert isinstance(fp, int)

    def test_hamming_distance(self):
        assert hamming_distance(0b1010, 0b1010) == 0
        assert hamming_distance(0b1010, 0b0101) == 4
