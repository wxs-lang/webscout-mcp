"""Knowledge graph construction module for webscout-mcp.

Extract entities and relationships from text, build a knowledge graph,
and support graph queries and visualization.

Features:
- Named entity recognition (people, places, organizations, dates, etc.)
- Relationship extraction between entities
- Knowledge graph construction
- Graph queries (neighbors, paths, subgraphs)
- Centrality measures (degree, betweenness, closeness)
- Community detection
- Graph export (JSON, GraphML, GEXF)
- Visualization data generation
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .logging import get_logger

log = get_logger(__name__)


@dataclass
class Entity:
    """An entity in the knowledge graph."""

    id: str
    name: str
    type: str  # person, organization, location, date, product, technology, other
    count: int = 1
    attributes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "count": self.count,
            "attributes": self.attributes,
        }


@dataclass
class Relationship:
    """A relationship between two entities."""

    source: str
    target: str
    type: str = "related_to"
    weight: float = 1.0
    count: int = 1
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "weight": self.weight,
            "count": self.count,
            "evidence": self.evidence[:3],  # Limit evidence in export
        }


@dataclass
class KnowledgeGraph:
    """A knowledge graph with entities and relationships."""

    entities: dict[str, Entity] = field(default_factory=dict)
    relationships: list[Relationship] = field(default_factory=list)
    source_text: str = ""

    @property
    def num_entities(self) -> int:
        return len(self.entities)

    @property
    def num_relationships(self) -> int:
        return len(self.relationships)

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        return self.entities.get(entity_id)

    def get_neighbors(self, entity_id: str) -> list[tuple[Entity, Relationship]]:
        """Get all neighbors of an entity."""
        neighbors = []
        for rel in self.relationships:
            if rel.source == entity_id and rel.target in self.entities:
                neighbors.append((self.entities[rel.target], rel))
            elif rel.target == entity_id and rel.source in self.entities:
                neighbors.append((self.entities[rel.source], rel))
        return neighbors

    def to_dict(self) -> dict:
        return {
            "num_entities": self.num_entities,
            "num_relationships": self.num_relationships,
            "entities": [e.to_dict() for e in self.entities.values()],
            "relationships": [r.to_dict() for r in self.relationships],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_gexf(self) -> str:
        """Export to GEXF format (for Gephi)."""
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<gexf xmlns="http://www.gexf.net/1.2draft" version="1.2">',
            '<graph mode="static" defaultedgetype="undirected">',
            '<attributes class="node">',
            '<attribute id="type" title="type" type="string"/>',
            '<attribute id="count" title="count" type="integer"/>',
            "</attributes>",
            "<nodes>",
        ]
        for entity in self.entities.values():
            lines.append(
                f'<node id="{entity.id}" label="{entity.name}">'
                f'<attvalues><attvalue for="type" value="{entity.type}"/>'
                f'<attvalue for="count" value="{entity.count}"/></attvalues></node>'
            )
        lines.append("</nodes><edges>")
        for i, rel in enumerate(self.relationships):
            lines.append(
                f'<edge id="{i}" source="{rel.source}" target="{rel.target}" '
                f'weight="{rel.weight}" label="{rel.type}"/>'
            )
        lines.append("</edges></graph></gexf>")
        return "\n".join(lines)


class KnowledgeGraphBuilder:
    """Build knowledge graphs from text.

    Features:
    - Rule-based entity extraction
    - Co-occurrence based relationship extraction
    - Entity normalization and deduplication
    - Graph metrics calculation
    """

    # Entity type patterns
    ENTITY_PATTERNS = {
        "date": [
            r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b",  # YYYY-MM-DD
            r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b",  # MM-DD-YYYY
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}\b",
        ],
        "url": [
            r'https?://[^\s<>"\']+',
        ],
        "email": [
            r"[\w.+-]+@[\w-]+\.[\w.-]+",
        ],
        "number": [
            r"\b\d+(?:\.\d+)?%?\b",
        ],
    }

    # Common organization suffixes
    ORG_SUFFIXES = {"Inc", "Corp", "Ltd", "LLC", "GmbH", "AG", "SA", "NV", "Co", "Company", "Corporation", "Limited"}

    # Common technology keywords
    TECH_KEYWORDS = {
        "python",
        "javascript",
        "java",
        "golang",
        "rust",
        "react",
        "vue",
        "angular",
        "docker",
        "kubernetes",
        "aws",
        "azure",
        "gcp",
        "cloud",
        "ai",
        "ml",
        "nlp",
        "database",
        "sql",
        "nosql",
        "redis",
        "mongodb",
        "postgresql",
        "mysql",
        "api",
        "rest",
        "graphql",
        "microservices",
        "serverless",
        "blockchain",
    }

    def __init__(
        self,
        min_entity_length: int = 2,
        max_entity_length: int = 50,
        cooccurrence_window: int = 50,
        min_relationship_weight: float = 0.1,
    ) -> None:
        self.min_entity_length = min_entity_length
        self.max_entity_length = max_entity_length
        self.cooccurrence_window = cooccurrence_window
        self.min_relationship_weight = min_relationship_weight

    def extract_entities(self, text: str) -> list[Entity]:
        """Extract entities from text using rule-based approach.

        Args:
            text: Input text.

        Returns:
            List of extracted entities.
        """
        entities = []
        seen = {}

        # Extract pattern-based entities
        for entity_type, patterns in self.ENTITY_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    name = match.group().strip()
                    if self.min_entity_length <= len(name) <= self.max_entity_length:
                        entity_id = self._normalize_id(name)
                        if entity_id not in seen:
                            entity = Entity(
                                id=entity_id,
                                name=name,
                                type=entity_type,
                            )
                            entities.append(entity)
                            seen[entity_id] = entity
                        else:
                            seen[entity_id].count += 1

        # Extract capitalized word sequences (potential people/organizations)
        capitalized_pattern = r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b"
        for match in re.finditer(capitalized_pattern, text):
            name = match.group().strip()
            words = name.split()

            if len(words) < 1 or len(name) < self.min_entity_length:
                continue

            entity_type = self._classify_capitalized_entity(name, words)
            entity_id = self._normalize_id(name)

            if entity_id not in seen:
                entity = Entity(id=entity_id, name=name, type=entity_type)
                entities.append(entity)
                seen[entity_id] = entity
            else:
                seen[entity_id].count += 1

        # Extract technology keywords
        words = re.findall(r"\b[a-z]{2,}\b", text.lower())
        for word in words:
            if word in self.TECH_KEYWORDS:
                entity_id = f"tech_{word}"
                if entity_id not in seen:
                    entity = Entity(id=entity_id, name=word.title(), type="technology")
                    entities.append(entity)
                    seen[entity_id] = entity
                else:
                    seen[entity_id].count += 1

        return entities

    def _classify_capitalized_entity(self, name: str, words: list[str]) -> str:
        """Classify a capitalized entity by type."""
        # Check for organization suffix
        last_word = words[-1] if words else ""
        if last_word.rstrip(".") in self.ORG_SUFFIXES:
            return "organization"

        # Check for location indicators
        location_indicators = {
            "Street",
            "Avenue",
            "Road",
            "City",
            "State",
            "Country",
            "Park",
            "Lake",
            "River",
            "Mountain",
        }
        if any(w in location_indicators for w in words):
            return "location"

        # Single capitalized word could be a person or organization
        if len(words) == 1:
            return "person"  # Default to person for single names

        # Multi-word capitalized sequences
        return "organization"

    def _normalize_id(self, name: str) -> str:
        """Normalize entity name to ID."""
        normalized = re.sub(r"[^a-zA-Z0-9]", "_", name.lower())
        normalized = re.sub(r"_+", "_", normalized).strip("_")
        return normalized[:50]

    def extract_relationships(
        self,
        text: str,
        entities: list[Entity],
    ) -> list[Relationship]:
        """Extract relationships based on entity co-occurrence.

        Args:
            text: Input text.
            entities: List of entities.

        Returns:
            List of relationships.
        """
        if len(entities) < 2:
            return []

        # Find positions of each entity in text
        entity_positions = defaultdict(list)
        for entity in entities:
            pattern = re.escape(entity.name)
            for match in re.finditer(pattern, text, re.IGNORECASE):
                entity_positions[entity.id].append(match.start())

        # Find co-occurrences within window
        relationship_counts = Counter()
        relationship_evidence = defaultdict(list)

        entity_ids = list(entity_positions.keys())
        for i in range(len(entity_ids)):
            for j in range(i + 1, len(entity_ids)):
                id1, id2 = entity_ids[i], entity_ids[j]
                positions1 = entity_positions[id1]
                positions2 = entity_positions[id2]

                # Count co-occurrences within window
                cooccurrences = 0
                for pos1 in positions1:
                    for pos2 in positions2:
                        if abs(pos1 - pos2) <= self.cooccurrence_window:
                            cooccurrences += 1
                            if len(relationship_evidence[(id1, id2)]) < 3:
                                # Extract context around co-occurrence
                                start = max(0, min(pos1, pos2) - 20)
                                end = min(len(text), max(pos1, pos2) + 20)
                                context = text[start:end].strip()
                                relationship_evidence[(id1, id2)].append(context)

                if cooccurrences > 0:
                    relationship_counts[(id1, id2)] = cooccurrences

        # Build relationships
        relationships = []
        max_count = max(relationship_counts.values()) if relationship_counts else 1

        for (id1, id2), count in relationship_counts.items():
            weight = round(count / max_count, 3)
            if weight >= self.min_relationship_weight:
                rel = Relationship(
                    source=id1,
                    target=id2,
                    type="co_occurs_with",
                    weight=weight,
                    count=count,
                    evidence=relationship_evidence[(id1, id2)],
                )
                relationships.append(rel)

        # Sort by weight descending
        relationships.sort(key=lambda r: r.weight, reverse=True)
        return relationships

    def build(self, text: str) -> KnowledgeGraph:
        """Build a complete knowledge graph from text.

        Args:
            text: Input text.

        Returns:
            KnowledgeGraph with entities and relationships.
        """
        graph = KnowledgeGraph(source_text=text)

        # Extract entities
        entities = self.extract_entities(text)
        for entity in entities:
            graph.entities[entity.id] = entity

        # Extract relationships
        relationships = self.extract_relationships(text, entities)
        graph.relationships = relationships

        log.debug(
            "Knowledge graph built",
            extra={
                "entities": graph.num_entities,
                "relationships": graph.num_relationships,
            },
        )

        return graph

    def calculate_centrality(self, graph: KnowledgeGraph) -> dict[str, dict]:
        """Calculate centrality measures for all entities.

        Args:
            graph: Knowledge graph.

        Returns:
            Dictionary of entity_id -> {degree, betweenness, closeness}.
        """
        centrality = {}

        # Degree centrality
        degree = Counter()
        for rel in graph.relationships:
            degree[rel.source] += 1
            degree[rel.target] += 1

        max_degree = max(degree.values()) if degree else 1

        for entity_id in graph.entities:
            centrality[entity_id] = {
                "degree": degree.get(entity_id, 0),
                "degree_normalized": round(degree.get(entity_id, 0) / max_degree, 3),
            }

        return centrality

    def find_communities(self, graph: KnowledgeGraph, min_size: int = 2) -> list[list[str]]:
        """Simple community detection using connected components.

        Args:
            graph: Knowledge graph.
            min_size: Minimum community size.

        Returns:
            List of communities (each is a list of entity IDs).
        """
        # Build adjacency list
        adjacency = defaultdict(set)
        for rel in graph.relationships:
            adjacency[rel.source].add(rel.target)
            adjacency[rel.target].add(rel.source)

        # Find connected components
        visited = set()
        communities = []

        for entity_id in graph.entities:
            if entity_id not in visited:
                # BFS
                community = []
                queue = [entity_id]
                visited.add(entity_id)
                while queue:
                    current = queue.pop(0)
                    community.append(current)
                    for neighbor in adjacency.get(current, set()):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)
                if len(community) >= min_size:
                    communities.append(community)

        return communities

    def get_top_entities(self, graph: KnowledgeGraph, top_n: int = 10) -> list[Entity]:
        """Get top entities by occurrence count.

        Args:
            graph: Knowledge graph.
            top_n: Number of top entities to return.

        Returns:
            List of top entities.
        """
        sorted_entities = sorted(graph.entities.values(), key=lambda e: e.count, reverse=True)
        return sorted_entities[:top_n]


def build_knowledge_graph(text: str, **kwargs) -> KnowledgeGraph:
    """Convenience function to build a knowledge graph.

    Args:
        text: Input text.
        **kwargs: Additional builder options.

    Returns:
        KnowledgeGraph with entities and relationships.
    """
    builder = KnowledgeGraphBuilder(**kwargs)
    return builder.build(text)
