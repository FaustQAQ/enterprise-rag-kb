"""Embedding 抽象接口测试。

使用测试替身验证接口契约，不访问网络，也不生成伪语义向量。
"""

import asyncio
from collections.abc import Sequence

import pytest

from app.services.embedding_service import (
    EmbeddingError,
    EmbeddingNotConfiguredError,
    EmbeddingService,
)


class FakeEmbeddingService(EmbeddingService):
    """仅用于测试接口契约的确定性替身。"""

    @property
    def dimension(self) -> int:
        return 3

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [
            [float(len(text)), float(index), 1.0]
            for index, text in enumerate(texts)
        ]

    async def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), 0.0, 1.0]


def test_embedding_service_is_abstract() -> None:
    with pytest.raises(TypeError):
        EmbeddingService()  # type: ignore[abstract]


def test_fake_embedding_contract_preserves_order() -> None:
    service = FakeEmbeddingService()

    async def run() -> tuple[list[list[float]], list[float]]:
        documents = await service.embed_documents(["a", "bb", "ccc"])
        query = await service.embed_query("query")
        return documents, query

    documents, query = asyncio.run(run())

    assert service.dimension == 3
    assert documents == [[1.0, 0.0, 1.0], [2.0, 1.0, 1.0], [3.0, 2.0, 1.0]]
    assert query == [5.0, 0.0, 1.0]


def test_not_configured_error_is_an_embedding_error() -> None:
    assert issubclass(EmbeddingNotConfiguredError, EmbeddingError)
