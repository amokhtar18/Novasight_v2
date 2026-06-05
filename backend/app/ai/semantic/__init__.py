"""Semantic-layer sub-package.

Exports the tenant-scoped ``SemanticLayerClient`` and its FastAPI dependency
``get_semantic_layer_client`` for use throughout the AI and reporting layers.
"""

from app.ai.semantic.client import SemanticLayerClient, get_semantic_layer_client

__all__ = ["SemanticLayerClient", "get_semantic_layer_client"]
