"""Unified Vector Embedding Provider Abstraction for EQUILIBRA RAG.

Provides:
- BaseEmbeddingProvider: Abstract base class for embedding models.
- NvidiaNimEmbeddingProvider: Genuine semantic neural embeddings via NVIDIA NIM API (default: nvidia/nemotron-3.5-embed-1b with Matryoshka dimension truncation).
- OfflineDeterministicEmbeddingProvider: Zero-network deterministic hashed lexical vector fallback for offline development and test safety.
- UnifiedEmbeddingProvider: Multi-tier failover manager ensuring RAG never fails even during network or credential interruptions.
"""

import hashlib
import re
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import httpx
from .config import settings

logger = logging.getLogger(__name__)


def deterministic_hash_vector(text: str, dimension: int = 384) -> List[float]:
    """Deterministic hashed lexical vector; OFFLINE FALLBACK ONLY, not a semantic model."""
    vec = [0.0] * dimension
    tokens = re.findall(r'[a-z0-9]+', text.lower())
    for term in tokens:
        digest = hashlib.sha256(term.encode('utf-8')).digest()
        pos = int.from_bytes(digest[:4], 'little') % dimension
        vec[pos] += 1.0 if digest[4] % 2 else -1.0
    norm = sum(x * x for x in vec) ** 0.5 or 1.0
    return [round(x / norm, 6) for x in vec]


class BaseEmbeddingProvider(ABC):
    def __init__(self, model: str, dimension: int, is_semantic: bool = True):
        self.model = model
        self.dimension = dimension
        self.is_semantic = is_semantic

    @abstractmethod
    def embed_text(self, text: str, input_type: str = "query") -> List[float]:
        """Generate embedding vector for a single string."""
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str], input_type: str = "passage") -> List[List[float]]:
        """Generate embedding vectors for a batch of strings."""
        pass

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Check reachability and credentials."""
        pass


class OfflineDeterministicEmbeddingProvider(BaseEmbeddingProvider):
    """Offline deterministic hashed lexical vector provider."""

    def __init__(self, dimension: int = 384):
        super().__init__(model="deterministic-hash-v1", dimension=dimension, is_semantic=False)

    def embed_text(self, text: str, input_type: str = "query") -> List[float]:
        return deterministic_hash_vector(text, dimension=self.dimension)

    def embed_batch(self, texts: List[str], input_type: str = "passage") -> List[List[float]]:
        return [deterministic_hash_vector(t, dimension=self.dimension) for t in texts]

    def health_check(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "provider": "offline",
            "model": self.model,
            "dimension": self.dimension,
            "is_semantic": False,
            "message": "Deterministic offline lexical vector fallback is operational."
        }


class NvidiaNimEmbeddingProvider(BaseEmbeddingProvider):
    """Genuine semantic neural embeddings via NVIDIA NIM API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        dimension: Optional[int] = None,
        timeout: float = 12.0
    ):
        model_name = model or getattr(settings, "embedding_model", "nvidia/nemotron-3.5-embed-1b")
        dim = dimension or getattr(settings, "embedding_dimension", 384)
        super().__init__(model=model_name, dimension=dim, is_semantic=True)
        self.api_key = api_key or getattr(settings, "nvidia_nim_api_key", "")
        self.base_url = (base_url or getattr(settings, "embedding_base_url", "https://integrate.api.nvidia.com/v1")).rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.startswith("nvapi-"))

    def embed_text(self, text: str, input_type: str = "query") -> List[float]:
        vectors = self.embed_batch([text], input_type=input_type)
        if not vectors:
            raise RuntimeError(f"NVIDIA NIM embeddings returned empty response for query")
        return vectors[0]

    def embed_batch(self, texts: List[str], input_type: str = "passage") -> List[List[float]]:
        if not self.is_configured():
            raise ValueError("NVIDIA NIM API key is not configured")

        url = f"{self.base_url}/embeddings"
        payload = {
            "input": texts,
            "model": self.model,
            "input_type": input_type,
            "dimensions": self.dimension
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=self._headers(), json=payload)

        if resp.status_code != 200:
            raise RuntimeError(f"NVIDIA NIM Embedding failed [HTTP {resp.status_code}]: {resp.text[:200]}")

        data = resp.json()
        results = []
        for item in data.get("data", []):
            vec = np.array(item["embedding"], dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            results.append([round(float(x), 6) for x in vec])

        return results

    def health_check(self) -> Dict[str, Any]:
        if not self.is_configured():
            return {
                "status": "unconfigured",
                "provider": "nvidia",
                "model": self.model,
                "dimension": self.dimension,
                "is_semantic": True,
                "message": "NVIDIA NIM API key is missing or not configured."
            }
        try:
            vec = self.embed_text("Health check probe", input_type="query")
            return {
                "status": "healthy",
                "provider": "nvidia",
                "model": self.model,
                "dimension": len(vec),
                "is_semantic": True,
                "message": f"NVIDIA NIM embedding service verified live with model '{self.model}' ({len(vec)} dims)."
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "provider": "nvidia",
                "model": self.model,
                "dimension": self.dimension,
                "is_semantic": True,
                "message": f"NVIDIA NIM embedding check failed: {str(e)}"
            }


class UnifiedEmbeddingProvider:
    """Multi-tier Embedding Provider ensuring failover resilience and semantic metadata tracking."""

    def __init__(self):
        self.offline_provider = OfflineDeterministicEmbeddingProvider(
            dimension=getattr(settings, "embedding_dimension", 384)
        )
        self.nim_provider = NvidiaNimEmbeddingProvider()

    def get_active_provider_name(self) -> str:
        prov = getattr(settings, "embedding_provider", "auto").lower()
        if prov == "offline":
            return "offline"
        if prov in ("auto", "nvidia") and self.nim_provider.is_configured():
            return "nvidia"
        return "offline"

    def embed_text(self, text: str, input_type: str = "query") -> Tuple[List[float], Dict[str, Any]]:
        """Embed text with automatic failover and metadata tracking."""
        active = self.get_active_provider_name()
        if active == "nvidia":
            try:
                vec = self.nim_provider.embed_text(text, input_type=input_type)
                return vec, {
                    "provider": "nvidia",
                    "model": self.nim_provider.model,
                    "dimension": len(vec),
                    "is_semantic": True,
                    "fallback_used": False
                }
            except Exception as e:
                logger.warning(f"Semantic embedding failed, falling back to deterministic: {e}")

        # Fallback to offline
        vec = self.offline_provider.embed_text(text, input_type=input_type)
        return vec, {
            "provider": "offline",
            "model": self.offline_provider.model,
            "dimension": len(vec),
            "is_semantic": False,
            "fallback_used": (active != "offline")
        }

    def embed_batch(self, texts: List[str], input_type: str = "passage") -> Tuple[List[List[float]], Dict[str, Any]]:
        """Embed a batch of texts with automatic failover."""
        active = self.get_active_provider_name()
        if active == "nvidia":
            try:
                vecs = self.nim_provider.embed_batch(texts, input_type=input_type)
                return vecs, {
                    "provider": "nvidia",
                    "model": self.nim_provider.model,
                    "dimension": self.nim_provider.dimension,
                    "is_semantic": True,
                    "fallback_used": False
                }
            except Exception as e:
                logger.warning(f"Batch semantic embedding failed, falling back to deterministic: {e}")

        vecs = self.offline_provider.embed_batch(texts, input_type=input_type)
        return vecs, {
            "provider": "offline",
            "model": self.offline_provider.model,
            "dimension": self.offline_provider.dimension,
            "is_semantic": False,
            "fallback_used": (active != "offline")
        }

    def health_check(self) -> Dict[str, Any]:
        """Return comprehensive health diagnostics across embedding tiers."""
        active = self.get_active_provider_name()
        nim_health = self.nim_provider.health_check()
        return {
            "configured_mode": getattr(settings, "embedding_provider", "auto"),
            "active_provider": active,
            "is_semantic": (active == "nvidia" and nim_health.get("status") == "healthy"),
            "expected_dimension": getattr(settings, "embedding_dimension", 384),
            "nvidia_tier": nim_health,
            "offline_tier": self.offline_provider.health_check()
        }


# Singleton instance
embedding_service = UnifiedEmbeddingProvider()
