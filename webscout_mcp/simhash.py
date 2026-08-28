"""SimHash-based near-duplicate detection module.

Efficiently detects near-duplicate documents using SimHash algorithm.
Supports millions of documents with sub-linear lookup time.

Features:
- SimHash fingerprint generation (64-bit / 128-bit)
- Hamming distance calculation
- Bulk duplicate detection
- Incremental fingerprint storage
- Configurable similarity threshold
- Tokenization with weight support
- Stop word filtering
- N-gram support
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

from .logging import get_logger

log = get_logger(__name__)


@dataclass
class SimHashResult:
    """Result of SimHash comparison."""

    fingerprint: int
    hamming_distance: int
    is_duplicate: bool
    similarity: float
    matched_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "fingerprint": self.fingerprint,
            "hamming_distance": self.hamming_distance,
            "is_duplicate": self.is_duplicate,
            "similarity": self.similarity,
            "matched_id": self.matched_id,
        }


class SimHash:
    """SimHash fingerprint generator and duplicate detector.

    Features:
    - 64-bit or 128-bit fingerprints
    - Weighted token hashing
    - Stop word filtering
    - N-gram tokenization
    - Hamming distance calculation
    """

    # Common English stop words
    DEFAULT_STOP_WORDS = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "need",
        "this",
        "that",
        "these",
        "those",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "where",
        "when",
        "why",
        "how",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "also",
        "now",
        "here",
        "there",
        "then",
        "once",
        "if",
        "because",
        "as",
        "until",
        "while",
        "about",
        "between",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "up",
        "down",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "any",
        "into",
        "its",
        "their",
        "your",
        "my",
        "our",
    }

    def __init__(
        self,
        hash_bits: int = 64,
        n_grams: int = 1,
        use_stop_words: bool = True,
        custom_stop_words: Optional[set[str]] = None,
        min_token_length: int = 2,
    ) -> None:
        if hash_bits not in (64, 128):
            raise ValueError("hash_bits must be 64 or 128")
        self.hash_bits = hash_bits
        self.n_grams = n_grams
        self.use_stop_words = use_stop_words
        self.stop_words = self.DEFAULT_STOP_WORDS.copy()
        if custom_stop_words:
            self.stop_words.update(custom_stop_words)
        self.min_token_length = min_token_length

    def tokenize(self, text: str) -> list[str]:
        """Tokenize text into words/n-grams.

        Args:
            text: Input text.

        Returns:
            List of tokens.
        """
        if not text:
            return []

        # Clean and lowercase
        text = text.lower()
        # Extract words (alphanumeric sequences)
        words = re.findall(r"[a-z0-9\u4e00-\u9fff]+", text)

        # Filter stop words and short tokens
        if self.use_stop_words:
            words = [w for w in words if w not in self.stop_words and len(w) >= self.min_token_length]
        else:
            words = [w for w in words if len(w) >= self.min_token_length]

        # Generate n-grams
        if self.n_grams > 1:
            ngrams = []
            for i in range(len(words) - self.n_grams + 1):
                ngram = " ".join(words[i : i + self.n_grams])
                ngrams.append(ngram)
            return ngrams if ngrams else words

        return words

    def _hash_token(self, token: str) -> int:
        """Hash a token to an integer.

        Args:
            token: Token string.

        Returns:
            Integer hash value.
        """
        if self.hash_bits == 64:
            return int(hashlib.md5(token.encode("utf-8")).hexdigest()[:16], 16)
        else:
            return int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:32], 16)

    def compute_fingerprint(self, text: str, weights: Optional[dict[str, float]] = None) -> int:
        """Compute SimHash fingerprint for text.

        Args:
            text: Input text.
            weights: Optional dictionary of token weights.

        Returns:
            SimHash fingerprint as integer.
        """
        tokens = self.tokenize(text)
        if not tokens:
            return 0

        # Initialize vector
        vector = [0] * self.hash_bits

        for token in tokens:
            token_hash = self._hash_token(token)
            weight = weights.get(token, 1.0) if weights else 1.0

            for i in range(self.hash_bits):
                if token_hash & (1 << i):
                    vector[i] += weight
                else:
                    vector[i] -= weight

        # Build fingerprint
        fingerprint = 0
        for i in range(self.hash_bits):
            if vector[i] > 0:
                fingerprint |= 1 << i

        return fingerprint

    @staticmethod
    def hamming_distance(hash1: int, hash2: int) -> int:
        """Calculate Hamming distance between two fingerprints.

        Args:
            hash1: First fingerprint.
            hash2: Second fingerprint.

        Returns:
            Number of differing bits.
        """
        xor = hash1 ^ hash2
        return bin(xor).count("1")

    def similarity(self, hash1: int, hash2: int) -> float:
        """Calculate similarity between two fingerprints.

        Args:
            hash1: First fingerprint.
            hash2: Second fingerprint.

        Returns:
            Similarity score (0.0 to 1.0).
        """
        distance = self.hamming_distance(hash1, hash2)
        return 1.0 - (distance / self.hash_bits)

    def is_duplicate(
        self,
        hash1: int,
        hash2: int,
        threshold: int = 3,
    ) -> bool:
        """Check if two fingerprints are near-duplicates.

        Args:
            hash1: First fingerprint.
            hash2: Second fingerprint.
            threshold: Maximum Hamming distance to consider duplicate.

        Returns:
            True if near-duplicate.
        """
        return self.hamming_distance(hash1, hash2) <= threshold


class DuplicateDetector:
    """Near-duplicate detector with fingerprint storage.

    Features:
    - Incremental fingerprint storage
    - Fast duplicate lookup using bit partitioning
    - Bulk duplicate detection
    - Configurable similarity threshold
    - Document ID mapping
    """

    def __init__(
        self,
        hash_bits: int = 64,
        threshold: int = 3,
        n_grams: int = 1,
        use_stop_words: bool = True,
    ) -> None:
        self.simhash = SimHash(
            hash_bits=hash_bits,
            n_grams=n_grams,
            use_stop_words=use_stop_words,
        )
        self.threshold = threshold
        self.hash_bits = hash_bits
        # Storage: doc_id -> fingerprint
        self.fingerprints: dict[str, int] = {}
        # Index for fast lookup: partition_key -> list of (doc_id, fingerprint)
        self._index: dict[int, list[tuple[str, int]]] = defaultdict(list)
        # Number of partitions for indexing (4 partitions for 64-bit)
        self._num_partitions = 4

    def _get_partition_keys(self, fingerprint: int) -> list[int]:
        """Get partition keys for a fingerprint.

        For 64-bit with 4 partitions, each partition is 16 bits.
        """
        bits_per_partition = self.hash_bits // self._num_partitions
        mask = (1 << bits_per_partition) - 1
        keys = []
        for i in range(self._num_partitions):
            key = (fingerprint >> (i * bits_per_partition)) & mask
            keys.append(key)
        return keys

    def add_document(self, doc_id: str, text: str, weights: Optional[dict[str, float]] = None) -> int:
        """Add a document to the detector.

        Args:
            doc_id: Document identifier.
            text: Document text.
            weights: Optional token weights.

        Returns:
            Document fingerprint.
        """
        fingerprint = self.simhash.compute_fingerprint(text, weights)
        self.fingerprints[doc_id] = fingerprint

        # Add to index
        for key in self._get_partition_keys(fingerprint):
            self._index[key].append((doc_id, fingerprint))

        log.debug("Added document to duplicate detector", extra={"doc_id": doc_id, "fingerprint": fingerprint})
        return fingerprint

    def add_fingerprint(self, doc_id: str, fingerprint: int) -> None:
        """Add a pre-computed fingerprint.

        Args:
            doc_id: Document identifier.
            fingerprint: Pre-computed SimHash fingerprint.
        """
        self.fingerprints[doc_id] = fingerprint
        for key in self._get_partition_keys(fingerprint):
            self._index[key].append((doc_id, fingerprint))

    def check_duplicate(
        self,
        text: str,
        weights: Optional[dict[str, float]] = None,
        threshold: Optional[int] = None,
    ) -> SimHashResult:
        """Check if text is a duplicate of any stored document.

        Args:
            text: Text to check.
            weights: Optional token weights.
            threshold: Override default threshold.

        Returns:
            SimHashResult with duplicate detection results.
        """
        fingerprint = self.simhash.compute_fingerprint(text, weights)
        return self.check_fingerprint(fingerprint, threshold)

    def check_fingerprint(
        self,
        fingerprint: int,
        threshold: Optional[int] = None,
    ) -> SimHashResult:
        """Check if a fingerprint matches any stored document.

        Args:
            fingerprint: Fingerprint to check.
            threshold: Override default threshold.

        Returns:
            SimHashResult with duplicate detection results.
        """
        thresh = threshold if threshold is not None else self.threshold
        result = SimHashResult(
            fingerprint=fingerprint,
            hamming_distance=self.hash_bits,
            is_duplicate=False,
            similarity=0.0,
        )

        if not self.fingerprints:
            return result

        # Candidate set from index (documents sharing at least one partition)
        candidates = set()
        for key in self._get_partition_keys(fingerprint):
            for doc_id, fp in self._index.get(key, []):
                candidates.add((doc_id, fp))

        # Check all candidates
        best_distance = self.hash_bits
        best_id = None

        for doc_id, stored_fp in candidates:
            distance = self.simhash.hamming_distance(fingerprint, stored_fp)
            if distance < best_distance:
                best_distance = distance
                best_id = doc_id

        result.hamming_distance = best_distance
        result.similarity = self.simhash.similarity(fingerprint, self.fingerprints.get(best_id, 0)) if best_id else 0.0
        result.matched_id = best_id
        result.is_duplicate = best_distance <= thresh

        return result

    def find_duplicates(
        self,
        documents: dict[str, str],
        threshold: Optional[int] = None,
    ) -> list[tuple[str, str, int, float]]:
        """Find all duplicate pairs in a collection of documents.

        Args:
            documents: Dictionary of doc_id -> text.
            threshold: Override default threshold.

        Returns:
            List of (doc_id1, doc_id2, hamming_distance, similarity) tuples.
        """
        thresh = threshold if threshold is not None else self.threshold
        fingerprints = {}
        for doc_id, text in documents.items():
            fingerprints[doc_id] = self.simhash.compute_fingerprint(text)

        duplicates = []
        doc_ids = list(fingerprints.keys())

        for i in range(len(doc_ids)):
            for j in range(i + 1, len(doc_ids)):
                id1, id2 = doc_ids[i], doc_ids[j]
                distance = self.simhash.hamming_distance(fingerprints[id1], fingerprints[id2])
                if distance <= thresh:
                    similarity = self.simhash.similarity(fingerprints[id1], fingerprints[id2])
                    duplicates.append((id1, id2, distance, similarity))

        return duplicates

    def remove_document(self, doc_id: str) -> bool:
        """Remove a document from the detector.

        Args:
            doc_id: Document identifier.

        Returns:
            True if document was removed.
        """
        if doc_id not in self.fingerprints:
            return False

        fingerprint = self.fingerprints.pop(doc_id)

        # Remove from index
        for key in self._get_partition_keys(fingerprint):
            self._index[key] = [(d_id, fp) for d_id, fp in self._index[key] if d_id != doc_id]

        return True

    def clear(self) -> None:
        """Clear all stored fingerprints."""
        self.fingerprints.clear()
        self._index.clear()

    @property
    def document_count(self) -> int:
        """Get number of stored documents."""
        return len(self.fingerprints)

    def get_stats(self) -> dict:
        """Get detector statistics.

        Returns:
            Dictionary of statistics.
        """
        return {
            "document_count": self.document_count,
            "hash_bits": self.hash_bits,
            "threshold": self.threshold,
            "index_partitions": self._num_partitions,
            "index_size": sum(len(v) for v in self._index.values()),
        }


def compute_simhash(text: str, hash_bits: int = 64, n_grams: int = 1) -> int:
    """Convenience function to compute SimHash fingerprint.

    Args:
        text: Input text.
        hash_bits: Hash size (64 or 128).
        n_grams: N-gram size.

    Returns:
        SimHash fingerprint.
    """
    simhash = SimHash(hash_bits=hash_bits, n_grams=n_grams)
    return simhash.compute_fingerprint(text)


def hamming_distance(hash1: int, hash2: int) -> int:
    """Convenience function to calculate Hamming distance.

    Args:
        hash1: First fingerprint.
        hash2: Second fingerprint.

    Returns:
        Hamming distance.
    """
    return SimHash.hamming_distance(hash1, hash2)
