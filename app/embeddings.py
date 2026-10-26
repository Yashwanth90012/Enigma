"""Unified Vector Embedding Provider Abstraction for EQUILIBRA RAG.

Provides:
- BaseEmbeddingProvider: Abstract base class for embedding models.
- NvidiaNimEmbeddingProvider: Genuine semantic neural embeddings via NVIDIA NIM API (default: nvidia/nemotron-3.5-embed-1b with Matryoshka dimension truncation).
- OfflineDeterministicEmbeddingProvider: Zero-network deterministic hashed lexical vector fallback for offline development and test safety.
- UnifiedEmbeddingProvider: Multi-tier failover manager ensuring RAG never fails even during network or credential interruptions.
"""

import hashlib
import re
import threading
import time
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
    """Genuine semantic neural embeddings via NVIDIA NIM API with connection pooling and caching."""

    _shared_client: Optional[httpx.Client] = None
    _vector_cache: Dict[str, List[float]] = {}
    _cache_lock = threading.Lock()

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

    @classmethod
    def get_client(cls, timeout: float = 12.0) -> httpx.Client:
        if cls._shared_client is None or cls._shared_client.is_closed:
            with cls._cache_lock:
                if cls._shared_client is None or cls._shared_client.is_closed:
                    cls._shared_client = httpx.Client(
                        limits=httpx.Limits(max_connections=15, max_keepalive_connections=10, keepalive_expiry=30.0),
                        timeout=httpx.Timeout(connect=5.0, read=timeout, write=5.0, pool=5.0)
                    )
        return cls._shared_client

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.startswith("nvapi-"))

    def embed_text(self, text: str, input_type: str = "query") -> List[float]:
        cache_key = f"{self.model}:{self.dimension}:{input_type}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
        with self._cache_lock:
            if cache_key in self._vector_cache:
                return self._vector_cache[cache_key]

        vectors = self.embed_batch([text], input_type=input_type)
        if not vectors:
            raise RuntimeError(f"NVIDIA NIM embeddings returned empty response for query")
        
        with self._cache_lock:
            if len(self._vector_cache) < 2000:
                self._vector_cache[cache_key] = vectors[0]
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

        client = self.get_client(timeout=self.timeout)
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


def normalize_meterless_url(raw_url: str) -> str:
    """Normalize pasted Meterless URL to <host>/v1 without producing /v1/v1."""
    u = raw_url.strip()
    u = re.sub(r'/(v1|chat|completions|models|embeddings|healthz).*$', '', u)
    u = u.rstrip('/')
    if not u.endswith('/v1'):
        u = f"{u}/v1"
    return u


class MeterlessEmbeddingProvider(BaseEmbeddingProvider):
    """Semantic vector embeddings via Meterless Runtime OpenAI-compatible /v1/embeddings endpoint."""

    _shared_client: Optional[httpx.Client] = None
    _vector_cache: Dict[str, List[float]] = {}
    _cache_lock = threading.Lock()
    _last_failed_at: float = 0.0

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        model: Optional[str] = None,
        dimension: Optional[int] = None,
        timeout: float = 180.0
    ):
        raw_base = base_url or getattr(settings, "meterless_base_url", "http://host.docker.internal:8088/v1")
        self.base_url = normalize_meterless_url(raw_base)
        self.token = token if token is not None else getattr(settings, "meterless_token", "")
        model_name = model or getattr(settings, "meterless_model", "meterless/auto")
        dim = dimension or getattr(settings, "embedding_dimension", 384)
        super().__init__(model=model_name, dimension=dim, is_semantic=True)
        self.timeout = timeout

    @classmethod
    def get_client(cls, timeout: float = 180.0) -> httpx.Client:
        if cls._shared_client is None or cls._shared_client.is_closed:
            with cls._cache_lock:
                if cls._shared_client is None or cls._shared_client.is_closed:
                    cls._shared_client = httpx.Client(
                        limits=httpx.Limits(max_connections=15, max_keepalive_connections=10, keepalive_expiry=60.0),
                        timeout=httpx.Timeout(connect=2.0, read=timeout, write=5.0, pool=2.0)
                    )
        return cls._shared_client

    def _headers(self) -> Dict[str, str]:
        headers = {
            "meterless-app": "equilibra",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        else:
            headers["Authorization"] = "Bearer "
        return headers

    def embed_text(self, text: str, input_type: str = "query") -> List[float]:
        cache_key = f"meterless:{self.model}:{self.dimension}:{input_type}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
        with self._cache_lock:
            if cache_key in self._vector_cache:
                return self._vector_cache[cache_key]

        vectors = self.embed_batch([text], input_type=input_type)
        if not vectors:
            raise RuntimeError("Meterless embeddings returned empty response for query")

        with self._cache_lock:
            if len(self._vector_cache) < 2000:
                self._vector_cache[cache_key] = vectors[0]
        return vectors[0]

    def embed_batch(self, texts: List[str], input_type: str = "passage") -> List[List[float]]:
        now = time.time()
        if now - MeterlessEmbeddingProvider._last_failed_at < 15.0:
            raise RuntimeError(f"Meterless Runtime circuit open (unreachable at {self.base_url})")

        url = f"{self.base_url}/embeddings"
        payload = {
            "input": texts,
            "model": self.model,
            "dimensions": self.dimension
        }

        try:
            client = self.get_client(timeout=self.timeout)
            resp = client.post(url, headers=self._headers(), json=payload)
        except Exception:
            MeterlessEmbeddingProvider._last_failed_at = time.time()
            raise

        if resp.status_code != 200:
            raise RuntimeError(f"Meterless Embedding failed [HTTP {resp.status_code}]: {resp.text[:200]}")

        data = resp.json()
        results = []
        for item in data.get("data", []):
            vec = np.array(item["embedding"], dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            vec_list = [round(float(x), 6) for x in vec[:self.dimension]]
            if len(vec_list) < self.dimension:
                vec_list.extend([0.0] * (self.dimension - len(vec_list)))
            results.append(vec_list)

        return results

    def health_check(self) -> Dict[str, Any]:
        try:
            client = self.get_client(timeout=5.0)
            resp = client.get(f"{self.base_url}/models", headers=self._headers())
            if resp.status_code == 200:
                return {
                    "status": "healthy",
                    "provider": "meterless",
                    "model": self.model,
                    "endpoint": f"{self.base_url}/embeddings",
                    "dimension": self.dimension,
                    "is_semantic": True,
                    "message": f"Connected to Meterless Runtime at {self.base_url}"
                }
            elif resp.status_code in (401, 403):
                return {
                    "status": "unauthorized",
                    "provider": "meterless",
                    "model": self.model,
                    "endpoint": f"{self.base_url}/embeddings",
                    "dimension": self.dimension,
                    "is_semantic": True,
                    "message": f"Meterless Runtime reached at {self.base_url}; token verification pending."
                }
            else:
                return {
                    "status": "degraded",
                    "provider": "meterless",
                    "model": self.model,
                    "endpoint": f"{self.base_url}/embeddings",
                    "dimension": self.dimension,
                    "is_semantic": True,
                    "message": f"Meterless HTTP {resp.status_code}: {resp.text[:100]}"
                }
        except Exception as e:
            return {
                "status": "unreachable",
                "provider": "meterless",
                "model": self.model,
                "endpoint": f"{self.base_url}/embeddings",
                "dimension": self.dimension,
                "is_semantic": True,
                "message": f"Cannot connect to Meterless Runtime at {self.base_url}: {str(e)}"
            }


class UnifiedEmbeddingProvider:
    """Multi-tier Embedding Provider ensuring all RAG embeddings route through Meterless first."""

    def __init__(self):
        self.meterless_provider = MeterlessEmbeddingProvider()
        self.nim_provider = NvidiaNimEmbeddingProvider()
        self.offline_provider = OfflineDeterministicEmbeddingProvider(
            dimension=getattr(settings, "embedding_dimension", 384)
        )

    def get_active_provider_name(self) -> str:
        prov = getattr(settings, "embedding_provider", "meterless").lower()
        if prov == "offline":
            return "offline"
        if prov == "nvidia" and self.nim_provider.is_configured():
            return "nvidia"
        return "meterless"

    def embed_text(self, text: str, input_type: str = "query") -> Tuple[List[float], Dict[str, Any]]:
        """Embed text with Meterless as primary tier."""
        active = self.get_active_provider_name()
        
        # Primary: Meterless Runtime
        if active == "meterless":
            try:
                vec = self.meterless_provider.embed_text(text, input_type=input_type)
                return vec, {
                    "provider": "meterless",
                    "model": self.meterless_provider.model,
                    "dimension": len(vec),
                    "is_semantic": True,
                    "fallback_used": False
                }
            except Exception as e:
                logger.warning(f"Meterless embedding call failed ({e}), falling back to secondary tier")

        # Secondary: NVIDIA NIM only if explicitly configured as primary or active
        if active == "nvidia" and self.nim_provider.is_configured():
            try:
                vec = self.nim_provider.embed_text(text, input_type=input_type)
                return vec, {
                    "provider": "nvidia",
                    "model": self.nim_provider.model,
                    "dimension": len(vec),
                    "is_semantic": True,
                    "fallback_used": True
                }
            except Exception as e:
                logger.warning(f"NVIDIA NIM embedding fallback failed: {e}")

        # Final safety net: Offline deterministic
        vec = self.offline_provider.embed_text(text, input_type=input_type)
        return vec, {
            "provider": "offline",
            "model": self.offline_provider.model,
            "dimension": len(vec),
            "is_semantic": False,
            "fallback_used": (active != "offline")
        }

    def embed_batch(self, texts: List[str], input_type: str = "passage") -> Tuple[List[List[float]], Dict[str, Any]]:
        """Embed batch of texts with Meterless as primary tier."""
        active = self.get_active_provider_name()

        # Primary: Meterless Runtime
        if active == "meterless":
            try:
                vecs = self.meterless_provider.embed_batch(texts, input_type=input_type)
                return vecs, {
                    "provider": "meterless",
                    "model": self.meterless_provider.model,
                    "dimension": self.meterless_provider.dimension,
                    "is_semantic": True,
                    "fallback_used": False
                }
            except Exception as e:
                logger.warning(f"Meterless batch embedding failed ({e}), falling back to secondary tier")

        # Secondary: NVIDIA NIM only if explicitly configured as primary or active
        if active == "nvidia" and self.nim_provider.is_configured():
            try:
                vecs = self.nim_provider.embed_batch(texts, input_type=input_type)
                return vecs, {
                    "provider": "nvidia",
                    "model": self.nim_provider.model,
                    "dimension": self.nim_provider.dimension,
                    "is_semantic": True,
                    "fallback_used": True
                }
            except Exception as e:
                logger.warning(f"NVIDIA NIM batch embedding fallback failed: {e}")

        # Final safety net: Offline deterministic
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
        meterless_health = self.meterless_provider.health_check()
        nim_health = self.nim_provider.health_check()
        return {
            "configured_mode": getattr(settings, "embedding_provider", "meterless"),
            "active_provider": active,
            "is_semantic": True,
            "expected_dimension": getattr(settings, "embedding_dimension", 384),
            "meterless_tier": meterless_health,
            "nvidia_tier": nim_health,
            "offline_tier": self.offline_provider.health_check()
        }


# Singleton instance
embedding_service = UnifiedEmbeddingProvider()
