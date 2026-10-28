"""应用配置：统一从环境变量和本地 .env 文件读取。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py -> core -> app -> backend
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """项目运行配置。

    所有字段都可以通过同名环境变量覆盖（大小写不敏感）。
    敏感信息只允许来自环境变量或本地 .env，禁止硬编码到代码中。
    """

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用 ----------
    app_name: str = "Enterprise RAG Knowledge Base"
    app_version: str = "0.1.0"
    environment: Literal["development", "testing", "production"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # ---------- 文档上传 ----------
    # 单个上传文件的最大大小（MiB），默认 10 MB。
    max_upload_size_mb: int = Field(default=10, ge=1, le=100)

    # ---------- 数据库 ----------
    # 本地开发默认使用 SQLite，无需启动额外服务；仍可通过 DATABASE_URL 覆盖为
    # PostgreSQL（postgresql+asyncpg://...）。相对路径以启动目录（backend）为准。
    database_url: str = "sqlite+aiosqlite:///./rag_kb.db"

    # ---------- 前端联调 ----------
    # 多个来源用英文逗号分隔，避免 pydantic-settings 对 list 的 JSON 解析要求。
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---------- 在线大模型 ----------
    # 默认开发模式使用本地 Mock；只有显式关闭 Mock 且真实配置完整时才联网。
    llm_provider: str | None = "deepseek"
    llm_mock_enabled: bool = True
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = "https://api.deepseek.com"
    llm_model: str | None = "deepseek-flash"
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    # ---------- Embedding ----------
    # provider 为空表示尚未启用真实 Embedding，服务工厂会返回明确的配置错误。
    # 当前只实现 OpenAI 兼容的 /embeddings HTTP 协议；密钥只从环境变量或 .env 读取。
    embedding_provider: str | None = None
    # 仅显式开启时使用本地确定性 Mock；生产环境由服务工厂拒绝。
    embedding_mock_enabled: bool = False
    embedding_api_key: SecretStr | None = None
    embedding_base_url: str | None = "https://api.openai.com/v1"
    embedding_model: str | None = None
    embedding_dimension: int | None = Field(default=None, ge=1, le=65536)
    embedding_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    embedding_batch_size: int = Field(default=32, ge=1, le=2048)

    @field_validator("llm_api_key", "embedding_api_key", mode="before")
    @classmethod
    def empty_secret_as_none(cls, value: object) -> object:
        """把 .env 中的空字符串视为“未配置”，避免误判为已设置密钥。"""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "llm_base_url",
        "llm_model",
        "llm_provider",
        "embedding_provider",
        "embedding_base_url",
        "embedding_model",
        mode="before",
    )
    @classmethod
    def empty_optional_text_as_none(cls, value: object) -> object:
        """可选文本配置留空时统一转为 None，交给服务工厂给出清晰错误。"""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("embedding_dimension", mode="before")
    @classmethod
    def empty_embedding_dimension_as_none(cls, value: object) -> object:
        """允许 .env 中留空 EMBEDDING_DIMENSION，而不是在启动时解析失败。"""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的 CORS 配置转换为去空格后的列表。"""
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def max_upload_size_bytes(self) -> int:
        """把配置中的 MiB 转换为字节数，供上传读取逻辑使用。"""
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """返回进程内缓存的配置单例，避免重复读取和解析 .env。"""
    return Settings()
