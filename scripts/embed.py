#!/usr/bin/env python3
"""
Lazy-loaded sentence embedding wrapper.
Model: all-MiniLM-L6-v2 (384-dim, CPU-only, ~80MB)

Usage:
    from embed import embed
    vec = embed("some text")   # -> list[float], len=384
"""
from __future__ import annotations

_model = None


def embed(text: str) -> list:
    global _model
    if _model is None:
        import os, logging
        os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
        logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model.encode(text, normalize_embeddings=True).tolist()
