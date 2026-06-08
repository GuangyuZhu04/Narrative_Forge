# Novel Writing Agent — 编码实现文档

## 1. 概述

本文档基于架构设计文档，详细描述各模块的编码实现方案，包括项目初始化、核心代码结构、关键算法实现、数据库设计及前后端交互细节。

**核心设计原则**：写作项目（Project）是系统的核心组织单元，所有创作资源（大纲、人物、章节、一致性分析报告）均从属于某个写作项目。API 路由采用嵌套资源路径 `/projects/{project_id}/...`，前端采用项目工作区嵌套路由。

---

## 2. 项目初始化

### 2.1 后端项目初始化

```bash
mkdir -p backend/app/{api/v1,core,models,schemas,services,llm/{providers,prompts},db}
mkdir -p backend/tests

cd backend
python -m venv .venv
.venv\Scripts\activate
pip install fastapi uvicorn sqlalchemy alembic httpx pydantic cryptography python-dotenv aiofiles
```

**pyproject.toml**：

```toml
[project]
name = "novel-writing-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.20",
    "alembic>=1.13",
    "httpx>=0.27",
    "pydantic>=2.6",
    "cryptography>=42.0",
    "python-dotenv>=1.0",
    "aiofiles>=23.2",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

### 2.2 前端项目初始化

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend

npm install zustand axios react-router-dom
npm install @tiptap/react @tiptap/starter-kit @tiptap/extension-annotation @tiptap/pm
npm install @xyflow/react tailwindcss @tailwindcss/typography
npm install diff-match-patch lucide-react
npm install -D @types/diff-match-patch
```

**vite.config.ts**：

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
})
```

---

## 3. 数据库设计

### 3.1 ER 关系

```
Project 1──* Outline 1──* OutlineNode(自引用树)
Project 1──* Chapter 1──* ChapterVersion
Project 1──* Character *──* CharacterRelationship
Project 1──* AnalysisReport
LLMConfig (独立全局资源)
```

**关键约束**：所有业务实体（Outline, Character, Chapter, AnalysisReport）必须通过 `project_id` 外键关联到 Project，不存在脱离项目的独立资源。

### 3.2 SQLAlchemy 模型

**基础模型** (`backend/app/models/base.py`)：

```python
import uuid
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class UUIDMixin:
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid.uuid4()))
```

**项目模型** (`backend/app/models/project.py`)：

```python
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin, UUIDMixin

class Project(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    genre: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    word_count_target: Mapped[int | None] = mapped_column()
    settings: Mapped[str | None] = mapped_column(Text)
    outlines = relationship("Outline", back_populates="project", cascade="all, delete-orphan")
    chapters = relationship("Chapter", back_populates="project", cascade="all, delete-orphan")
    characters = relationship("Character", back_populates="project", cascade="all, delete-orphan")
    analysis_reports = relationship("AnalysisReport", back_populates="project", cascade="all, delete-orphan")
```

**大纲模型** (`backend/app/models/outline.py`)：

```python
from sqlalchemy import String, Text, Integer, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin, UUIDMixin

class Outline(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "outlines"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    project = relationship("Project", back_populates="outlines")
    nodes = relationship("OutlineNode", back_populates="outline", cascade="all, delete-orphan")

class OutlineNode(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "outline_nodes"
    outline_id: Mapped[str] = mapped_column(ForeignKey("outlines.id", ondelete="CASCADE"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("outline_nodes.id", ondelete="CASCADE"))
    node_type: Mapped[str] = mapped_column(String(20))  # VOLUME|CHAPTER|SCENE|PLOT_POINT|KEY_EVENT
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON)
    llm_generated: Mapped[bool] = mapped_column(default=False)
    outline = relationship("Outline", back_populates="nodes")
    parent = relationship("OutlineNode", remote_side="OutlineNode.id", back_populates="children")
    children = relationship("OutlineNode", back_populates="parent", cascade="all, delete-orphan")
```

**人物模型** (`backend/app/models/character.py`)：

```python
from sqlalchemy import String, Text, Integer, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin, UUIDMixin

class Character(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "characters"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    aliases: Mapped[dict | None] = mapped_column(JSON, default=list)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    basic_info: Mapped[dict | None] = mapped_column(JSON)      # {age, gender, occupation, appearance, background}
    personality: Mapped[dict | None] = mapped_column(JSON)      # {traits, mbti, values, flaws, speaking_style}
    growth_arc: Mapped[dict | None] = mapped_column(JSON)       # {starting_state, catalyst, transformation, ending_state}
    notes: Mapped[str | None] = mapped_column(Text)
    project = relationship("Project", back_populates="characters")
    source_relationships = relationship("CharacterRelationship", foreign_keys="CharacterRelationship.source_id", cascade="all, delete-orphan")
    target_relationships = relationship("CharacterRelationship", foreign_keys="CharacterRelationship.target_id", cascade="all, delete-orphan")

class CharacterRelationship(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "character_relationships"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    source_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"))
    target_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"))
    relationship_type: Mapped[str] = mapped_column(String(30))  # FAMILY|FRIEND|ENEMY|LOVER|MENTOR|SUBORDINATE|ALLY|RIVAL|OTHER
    description: Mapped[str | None] = mapped_column(Text)
    intensity: Mapped[int] = mapped_column(Integer, default=5)
    start_chapter: Mapped[str | None] = mapped_column(String(50))
    end_chapter: Mapped[str | None] = mapped_column(String(50))
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON)
    source = relationship("Character", foreign_keys=[source_id])
    target = relationship("Character", foreign_keys=[target_id])
```

**章节模型** (`backend/app/models/chapter.py`)：

```python
from sqlalchemy import String, Text, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin, UUIDMixin

class Chapter(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "chapters"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    outline_node_id: Mapped[str | None] = mapped_column(ForeignKey("outline_nodes.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|in_progress|completed|revised
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    project = relationship("Project", back_populates="chapters")
    versions = relationship("ChapterVersion", back_populates="chapter", cascade="all, delete-orphan")

class ChapterVersion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "chapter_versions"
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    version_number: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer)
    change_summary: Mapped[str | None] = mapped_column(Text)
    chapter = relationship("Chapter", back_populates="versions")
```

**LLM 配置模型** (`backend/app/models/llm_config.py`)：

```python
from sqlalchemy import String, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, TimestampMixin, UUIDMixin

class LLMConfig(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "llm_configs"
    provider: Mapped[str] = mapped_column(String(50))          # deepseek|openai_compatible
    api_key_encrypted: Mapped[str] = mapped_column(String)
    base_url: Mapped[str] = mapped_column(String(500))
    model_name: Mapped[str] = mapped_column(String(100))
    default_params: Mapped[dict | None] = mapped_column(JSON)  # {temperature, top_p, max_tokens, ...}
    rate_limit: Mapped[dict | None] = mapped_column(JSON)      # {requests_per_minute, max_concurrent}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
```

**分析报告模型** (`backend/app/models/analysis.py`)：

```python
from sqlalchemy import String, Float, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, TimestampMixin, UUIDMixin

class AnalysisReport(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "analysis_reports"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"))
    analysis_type: Mapped[str] = mapped_column(String(50))     # character|plot|timeline|overall
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|completed|error
    issues: Mapped[dict | None] = mapped_column(JSON)
    suggestions: Mapped[dict | None] = mapped_column(JSON)
    score: Mapped[float | None] = mapped_column(Float)
    project = relationship("Project", back_populates="analysis_reports")
```

### 3.3 数据库会话管理

```python
# backend/app/db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args={"check_same_thread": False},
)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

```python
# backend/app/core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/novel_agent.db"
    SECRET_KEY: str = "change-me-in-production"
    DEBUG: bool = True
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## 4. 后端核心服务

### 4.1 安全模块

```python
# backend/app/core/security.py
import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from app.core.config import settings

def _derive_key(master_key: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480000)
    return kdf.derive(master_key.encode())

def encrypt_api_key(api_key: str) -> str:
    salt = os.urandom(16)
    key = _derive_key(settings.SECRET_KEY, salt)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, api_key.encode(), None)
    return base64.urlsafe_b64encode(salt + nonce + ciphertext).decode()

def decrypt_api_key(encrypted: str) -> str:
    payload = base64.urlsafe_b64decode(encrypted.encode())
    salt, nonce, ciphertext = payload[:16], payload[16:28], payload[28:]
    key = _derive_key(settings.SECRET_KEY, salt)
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode()
```

### 4.2 项目归属校验依赖

所有项目级 API 需要校验资源是否属于指定项目，通过 FastAPI 依赖注入实现：

```python
# backend/app/api/deps.py
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal
from app.models.project import Project

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

async def verify_project_access(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> Project:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project
```

### 4.3 LLM Provider 抽象与实现

```python
# backend/app/llm/providers/base.py
from abc import ABC, abstractmethod
from typing import AsyncIterator

class LLMProvider(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def chat_completion(self, messages: list[dict], **kwargs) -> str: ...

    @abstractmethod
    async def stream_completion(self, messages: list[dict], **kwargs) -> AsyncIterator[str]: ...

    @abstractmethod
    def validate_config(self) -> bool: ...
```

```python
# backend/app/llm/providers/deepseek.py
import json
import httpx
from typing import AsyncIterator
from .base import LLMProvider
from app.core.security import decrypt_api_key

class DeepSeekProvider(LLMProvider):
    API_BASE = "https://api.deepseek.com"

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = decrypt_api_key(config["api_key_encrypted"])
        self.model = config.get("model_name", "deepseek-v4-pro")
        self.base_url = config.get("base_url", self.API_BASE)
        self.default_params = config.get("default_params", {})

    async def chat_completion(self, messages: list[dict], **kwargs) -> str:
        payload = self._build_payload(messages, stream=False, **kwargs)
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def stream_completion(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        payload = self._build_payload(messages, stream=True, **kwargs)
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions", json=payload, headers=self._headers()) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        if content := chunk["choices"][0].get("delta", {}).get("content"):
                            yield content

    def _build_payload(self, messages: list[dict], stream: bool, **kwargs) -> dict:
        params = {**self.default_params, **kwargs}
        return {"model": self.model, "messages": messages, "stream": stream, **{k: v for k, v in params.items() if v is not None}}

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def validate_config(self) -> bool:
        return bool(self.api_key and self.model)
```

```python
# backend/app/llm/providers/openai_compatible.py
from .deepseek import DeepSeekProvider

class OpenAICompatibleProvider(DeepSeekProvider):
    API_BASE = "https://api.openai.com/v1"
    def __init__(self, config: dict):
        config.setdefault("base_url", self.API_BASE)
        super().__init__(config)
```

### 4.4 频率限制器

```python
# backend/app/llm/rate_limiter.py
import asyncio
import time

class TokenBucketRateLimiter:
    def __init__(self):
        self._rpm = 60
        self._tokens = 60.0
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def configure(self, config: dict):
        self._rpm = config.get("requests_per_minute", 60)
        self._tokens = float(self._rpm)
        self._last_refill = time.monotonic()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(self._rpm, self._tokens + (now - self._last_refill) * (self._rpm / 60.0))
            self._last_refill = now
            if self._tokens < 1:
                await asyncio.sleep((1 - self._tokens) / (self._rpm / 60.0))
                self._tokens = 0
            else:
                self._tokens -= 1
```

### 4.5 LLM 编排器

```python
# backend/app/services/llm_orchestrator.py
from typing import AsyncIterator
from app.llm.providers.base import LLMProvider
from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.providers.openai_compatible import OpenAICompatibleProvider
from app.llm.rate_limiter import TokenBucketRateLimiter

PROVIDER_MAP = {"deepseek": DeepSeekProvider, "openai_compatible": OpenAICompatibleProvider}

class LLMOrchestrator:
    def __init__(self):
        self._providers: dict[str, LLMProvider] = {}
        self._rate_limiter = TokenBucketRateLimiter()

    async def initialize(self, config_id: str, db_config_dict: dict):
        provider_cls = PROVIDER_MAP.get(db_config_dict["provider"], OpenAICompatibleProvider)
        provider = provider_cls(db_config_dict)
        if rate_limit := db_config_dict.get("rate_limit"):
            self._rate_limiter.configure(rate_limit)
        self._providers[config_id] = provider

    async def chat(self, config_id: str, messages: list[dict], **kwargs) -> str:
        provider = self._providers.get(config_id)
        if not provider:
            raise ValueError(f"LLM config {config_id} not initialized")
        await self._rate_limiter.acquire()
        return await provider.chat_completion(messages, **kwargs)

    async def stream_chat(self, config_id: str, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        provider = self._providers.get(config_id)
        if not provider:
            raise ValueError(f"LLM config {config_id} not initialized")
        await self._rate_limiter.acquire()
        async for chunk in provider.stream_completion(messages, **kwargs):
            yield chunk
```

### 4.6 Prompt 模板

```python
# backend/app/llm/prompts/outline.py
OUTLINE_GENERATE_SYSTEM = """你是一位资深小说策划编辑...（见架构文档完整模板）"""
OUTLINE_GENERATE_USER = """体裁：{genre}\n主题：{theme}\n风格：{style}\n篇幅目标：{word_count_target}字\n额外要求：{extra_requirements}"""
OUTLINE_EXPAND_SYSTEM = """你是一位小说大纲扩展专家..."""
OUTLINE_EXPAND_USER = """父节点类型：{parent_type}\n父节点标题：{parent_title}\n父节点概述：{parent_summary}\n扩展要求：{expand_request}\n请生成 {count} 个子节点。"""
OUTLINE_OPTIMIZE_SYSTEM = """你是一位叙事结构顾问..."""
```

```python
# backend/app/llm/prompts/consistency.py
CONSISTENCY_CHARACTER_SYSTEM = """你是一位小说内容审校专家，专注于人物行为一致性分析..."""
CONSISTENCY_CHARACTER_USER = """## 人物设定\n{character_profiles}\n## 前文摘要\n{previous_summary}\n## 当前章节内容\n{chapter_content}"""
CONSISTENCY_PLOT_SYSTEM = """你是一位小说情节连贯性分析专家..."""
```

```python
# backend/app/llm/prompts/chapter.py
CHAPTER_CONTINUE_SYSTEM = """你是一位小说续写助手..."""
CHAPTER_CONTINUE_USER = """请续写以下内容：\n{previous_content}\n续写要求：{requirements}"""
CHAPTER_REWRITE_SYSTEM = """你是一位小说润色改写专家..."""
CHAPTER_REWRITE_USER = """请改写以下文本：\n{selected_text}\n上下文：{context}"""
```

### 4.7 一致性分析服务

```python
# backend/app/services/consistency_service.py
import asyncio
import json
from typing import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.chapter import Chapter
from app.models.character import Character
from app.services.llm_orchestrator import LLMOrchestrator
from app.llm.prompts.consistency import CONSISTENCY_CHARACTER_SYSTEM, CONSISTENCY_CHARACTER_USER, CONSISTENCY_PLOT_SYSTEM

class ConsistencyService:
    def __init__(self, llm_orchestrator: LLMOrchestrator):
        self._orchestrator = llm_orchestrator

    async def analyze_chapter(self, db: AsyncSession, project_id: str, chapter_id: str, llm_config_id: str, dimensions: list[str] | None = None) -> dict:
        dimensions = dimensions or ["character", "plot", "timeline"]
        chapter = await db.get(Chapter, chapter_id)
        characters = (await db.execute(select(Character).where(Character.project_id == project_id))).scalars().all()
        context = await self._assemble_context(db, project_id, chapter)

        tasks = []
        for dim in dimensions:
            if dim == "character":
                tasks.append(self._analyze_character(llm_config_id, context, characters))
            elif dim == "plot":
                tasks.append(self._analyze_plot(llm_config_id, context))
            elif dim == "timeline":
                tasks.append(self._analyze_timeline(llm_config_id, context))

        results = {}
        task_results = await asyncio.gather(*tasks, return_exceptions=True)
        for dim, result in zip(dimensions, task_results):
            results[dim] = result if not isinstance(result, Exception) else {"status": "error", "message": str(result)}
        return results

    async def _assemble_context(self, db: AsyncSession, project_id: str, chapter: Chapter) -> dict:
        prev = (await db.execute(select(Chapter).where(Chapter.project_id == project_id).where(Chapter.sort_order < chapter.sort_order).order_by(Chapter.sort_order.desc()).limit(3))).scalars().all()
        return {"chapter_content": chapter.content or "", "chapter_title": chapter.title, "previous_summary": "\n".join(c.summary or "" for c in prev)}

    async def _analyze_character(self, llm_config_id: str, context: dict, characters: list) -> dict:
        profiles = "\n".join(f"- {c.name}: 性格{c.personality.get('traits', []) if c.personality else []}" for c in characters)
        messages = [{"role": "system", "content": CONSISTENCY_CHARACTER_SYSTEM}, {"role": "user", "content": CONSISTENCY_CHARACTER_USER.format(character_profiles=profiles, previous_summary=context["previous_summary"], chapter_content=context["chapter_content"])}]
        return json.loads(await self._orchestrator.chat(llm_config_id, messages))

    async def _analyze_plot(self, llm_config_id: str, context: dict) -> dict:
        messages = [{"role": "system", "content": CONSISTENCY_PLOT_SYSTEM}, {"role": "user", "content": f"请分析以下章节的情节连贯性：\n\n{context['chapter_content']}"}]
        return json.loads(await self._orchestrator.chat(llm_config_id, messages))

    async def _analyze_timeline(self, llm_config_id: str, context: dict) -> dict:
        messages = [{"role": "system", "content": "你是一位时间线一致性分析专家。"}, {"role": "user", "content": f"前文摘要：{context['previous_summary']}\n\n当前章节：{context['chapter_content']}"}]
        return json.loads(await self._orchestrator.chat(llm_config_id, messages))

    async def stream_analyze(self, llm_config_id: str, context: dict, dimension: str) -> AsyncIterator[str]:
        system = CONSISTENCY_CHARACTER_SYSTEM if dimension == "character" else CONSISTENCY_PLOT_SYSTEM
        user = CONSISTENCY_CHARACTER_USER.format(**context) if dimension == "character" else f"请分析：{context.get('chapter_content', '')}"
        async for chunk in self._orchestrator.stream_chat(llm_config_id, [{"role": "system", "content": system}, {"role": "user", "content": user}]):
            yield chunk
```

### 4.8 大纲服务

```python
# backend/app/services/outline_service.py
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.outline import Outline, OutlineNode
from app.services.llm_orchestrator import LLMOrchestrator
from app.llm.prompts.outline import OUTLINE_GENERATE_SYSTEM, OUTLINE_GENERATE_USER, OUTLINE_EXPAND_SYSTEM, OUTLINE_EXPAND_USER, OUTLINE_OPTIMIZE_SYSTEM

class OutlineService:
    def __init__(self, llm_orchestrator: LLMOrchestrator):
        self._orchestrator = llm_orchestrator

    async def generate_outline(self, db: AsyncSession, llm_config_id: str, project_id: str, params: dict) -> Outline:
        messages = [{"role": "system", "content": OUTLINE_GENERATE_SYSTEM}, {"role": "user", "content": OUTLINE_GENERATE_USER.format(**params)}]
        response = await self._orchestrator.chat(llm_config_id, messages, temperature=1.1)
        outline_data = json.loads(response)
        outline = Outline(project_id=project_id, title=outline_data.get("title", "未命名大纲"), description=outline_data.get("description", ""))
        db.add(outline)
        await db.flush()
        await self._save_nodes_recursive(db, outline.id, None, outline_data.get("children", []), 0)
        await db.commit()
        await db.refresh(outline)
        return outline

    async def _save_nodes_recursive(self, db: AsyncSession, outline_id: str, parent_id: str | None, nodes_data: list[dict], start_order: int):
        for idx, nd in enumerate(nodes_data):
            node = OutlineNode(outline_id=outline_id, parent_id=parent_id, node_type=nd.get("node_type", "CHAPTER"), title=nd.get("title", ""), summary=nd.get("summary", ""), sort_order=start_order + idx, metadata_=nd.get("metadata"), llm_generated=True)
            db.add(node)
            await db.flush()
            if children := nd.get("children"):
                await self._save_nodes_recursive(db, outline_id, node.id, children, 0)

    async def expand_node(self, db: AsyncSession, llm_config_id: str, node_id: str, params: dict) -> list[OutlineNode]:
        node = await db.get(OutlineNode, node_id)
        messages = [{"role": "system", "content": OUTLINE_EXPAND_SYSTEM}, {"role": "user", "content": OUTLINE_EXPAND_USER.format(parent_type=node.node_type, parent_title=node.title, parent_summary=node.summary or "", siblings_info=params.get("siblings_info", "无"), expand_request=params.get("request", "请自然扩展"), count=params.get("count", 3))}]
        response = await self._orchestrator.chat(llm_config_id, messages, temperature=1.1)
        children_data = json.loads(response)
        created = []
        for idx, cd in enumerate(children_data if isinstance(children_data, list) else children_data.get("children", [])):
            child = OutlineNode(outline_id=node.outline_id, parent_id=node_id, node_type=cd.get("node_type", "SCENE"), title=cd.get("title", ""), summary=cd.get("summary", ""), sort_order=idx, metadata_=cd.get("metadata"), llm_generated=True)
            db.add(child)
            created.append(child)
        await db.commit()
        return created

    async def optimize_outline(self, db: AsyncSession, llm_config_id: str, outline_id: str, direction: str = "") -> dict:
        tree_data = await self.get_outline_tree(db, outline_id)
        messages = [{"role": "system", "content": OUTLINE_OPTIMIZE_SYSTEM}, {"role": "user", "content": f"请分析并优化以下大纲：\n\n{json.dumps(tree_data, ensure_ascii=False, indent=2)}\n\n优化方向：{direction or '综合优化'}"}]
        response = await self._orchestrator.chat(llm_config_id, messages, temperature=1.1)
        return json.loads(response)

    async def get_outline_tree(self, db: AsyncSession, outline_id: str) -> dict:
        outline = await db.get(Outline, outline_id)
        nodes = (await db.execute(select(OutlineNode).where(OutlineNode.outline_id == outline_id))).scalars().all()
        node_map = {n.id: n for n in nodes}
        root_nodes = sorted([n for n in nodes if n.parent_id is None], key=lambda x: x.sort_order)
        return {"outline": outline, "tree": [self._build_tree(n, node_map) for n in root_nodes]}

    def _build_tree(self, node: OutlineNode, node_map: dict) -> dict:
        children = sorted([n for n in node_map.values() if n.parent_id == node.id], key=lambda x: x.sort_order)
        return {"id": node.id, "node_type": node.node_type, "title": node.title, "summary": node.summary, "sort_order": node.sort_order, "metadata": node.metadata_, "llm_generated": node.llm_generated, "children": [self._build_tree(c, node_map) for c in children]}
```

### 4.9 章节服务

```python
# backend/app/services/chapter_service.py
import difflib
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.chapter import Chapter, ChapterVersion
from app.services.llm_orchestrator import LLMOrchestrator
from app.llm.prompts.chapter import CHAPTER_CONTINUE_SYSTEM, CHAPTER_CONTINUE_USER, CHAPTER_REWRITE_SYSTEM, CHAPTER_REWRITE_USER

class ChapterService:
    def __init__(self, llm_orchestrator: LLMOrchestrator):
        self._orchestrator = llm_orchestrator

    async def save_version(self, db: AsyncSession, chapter: Chapter) -> ChapterVersion:
        latest = await self._get_latest_version(db, chapter.id)
        next_v = (latest.version_number + 1) if latest else 1
        version = ChapterVersion(chapter_id=chapter.id, version_number=next_v, content=chapter.content or "", word_count=chapter.word_count)
        db.add(version)
        await db.commit()
        return version

    async def compare_versions(self, db: AsyncSession, chapter_id: str, v1: int, v2: int) -> dict:
        ver1, ver2 = await self._get_version(db, chapter_id, v1), await self._get_version(db, chapter_id, v2)
        lines1, lines2 = ver1.content.splitlines(keepends=True), ver2.content.splitlines(keepends=True)
        diff = list(difflib.unified_diff(lines1, lines2, lineterm=""))
        return {"version1": v1, "version2": v2, "additions": sum(1 for l in diff if l.startswith("+") and not l.startswith("+++")), "deletions": sum(1 for l in diff if l.startswith("-") and not l.startswith("---")), "unified_diff": diff, "html_diff": difflib.HtmlDiff().make_table(lines1, lines2)}

    async def ai_continue(self, db: AsyncSession, llm_config_id: str, chapter_id: str, requirements: str = "") -> str:
        chapter = await db.get(Chapter, chapter_id)
        messages = [{"role": "system", "content": CHAPTER_CONTINUE_SYSTEM}, {"role": "user", "content": CHAPTER_CONTINUE_USER.format(previous_content=chapter.content or "", requirements=requirements)}]
        return await self._orchestrator.chat(llm_config_id, messages, temperature=1.3)

    async def ai_rewrite(self, llm_config_id: str, selected_text: str, action: str, context: str = "") -> str:
        messages = [{"role": "system", "content": CHAPTER_REWRITE_SYSTEM.format(action=action)}, {"role": "user", "content": CHAPTER_REWRITE_USER.format(selected_text=selected_text, context=context)}]
        return await self._orchestrator.chat(llm_config_id, messages, temperature=1.2)

    async def _get_version(self, db: AsyncSession, chapter_id: str, num: int) -> ChapterVersion:
        return (await db.execute(select(ChapterVersion).where(ChapterVersion.chapter_id == chapter_id, ChapterVersion.version_number == num))).scalar_one()

    async def _get_latest_version(self, db: AsyncSession, chapter_id: str) -> ChapterVersion | None:
        return (await db.execute(select(ChapterVersion).where(ChapterVersion.chapter_id == chapter_id).order_by(ChapterVersion.version_number.desc()).limit(1))).scalar_one_or_none()
```

### 4.10 导出服务

```python
# backend/app/services/export_service.py
import io
from abc import ABC, abstractmethod
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.project import Project
from app.models.chapter import Chapter

class BaseExporter(ABC):
    @abstractmethod
    async def export(self, db: AsyncSession, project_id: str, options: dict | None = None) -> bytes: ...

class TxtExporter(BaseExporter):
    async def export(self, db: AsyncSession, project_id: str, options: dict | None = None) -> bytes:
        project = await db.get(Project, project_id)
        chapters = (await db.execute(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.sort_order))).scalars().all()
        buf = io.StringIO()
        buf.write(f"{project.name}\n{'='*40}\n\n")
        for ch in chapters:
            buf.write(f"第{ch.sort_order+1}章 {ch.title}\n{'-'*30}\n\n{ch.content or ''}\n\n")
        return buf.getvalue().encode("utf-8")

class MarkdownExporter(BaseExporter):
    async def export(self, db: AsyncSession, project_id: str, options: dict | None = None) -> bytes:
        project = await db.get(Project, project_id)
        chapters = (await db.execute(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.sort_order))).scalars().all()
        buf = io.StringIO()
        buf.write(f"# {project.name}\n\n> {project.description or ''}\n\n")
        for ch in chapters:
            buf.write(f"## 第{ch.sort_order+1}章 {ch.title}\n\n{ch.content or ''}\n\n")
        return buf.getvalue().encode("utf-8")

class DocxExporter(BaseExporter):
    async def export(self, db: AsyncSession, project_id: str, options: dict | None = None) -> bytes:
        from docx import Document
        project = await db.get(Project, project_id)
        chapters = (await db.execute(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.sort_order))).scalars().all()
        doc = Document()
        doc.add_heading(project.name, level=0)
        for ch in chapters:
            doc.add_heading(f"第{ch.sort_order+1}章 {ch.title}", level=1)
            for para in (ch.content or "").split("\n"):
                if para.strip():
                    doc.add_paragraph(para)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

EXPORTER_MAP = {"txt": TxtExporter, "markdown": MarkdownExporter, "docx": DocxExporter}
```

### 4.11 FastAPI 入口（嵌套路由注册）

```python
# backend/app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.core.exceptions import AppException
from app.api.v1 import projects, outlines, characters, chapters, analysis, llm_config, export
from app.db.session import engine
from app.models.base import Base

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(title="Novel Writing Agent API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 项目级路由：嵌套在 /projects/{project_id} 下
app.include_router(projects.router, prefix="/api/v1/projects", tags=["Projects"])
app.include_router(outlines.router, prefix="/api/v1/projects/{project_id}/outlines", tags=["Outlines"])
app.include_router(characters.router, prefix="/api/v1/projects/{project_id}/characters", tags=["Characters"])
app.include_router(chapters.router, prefix="/api/v1/projects/{project_id}/chapters", tags=["Chapters"])
app.include_router(analysis.router, prefix="/api/v1/projects/{project_id}/analysis", tags=["Analysis"])
app.include_router(export.router, prefix="/api/v1/projects/{project_id}/export", tags=["Export"])

# 全局路由：不绑定项目
app.include_router(llm_config.router, prefix="/api/v1/llm-configs", tags=["LLM Config"])

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "error_code": exc.error_code},
    )
```

**关键变化**：大纲、人物、章节、分析、导出路由均嵌套在 `/projects/{project_id}/` 下，`project_id` 作为路径参数自动注入，确保所有操作都在项目上下文中进行。LLM 配置作为全局资源保持独立。

---

## 5. 前端核心实现

### 5.1 API 服务层

```typescript
// frontend/src/services/api.ts
import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    console.error('API Error:', error.response?.data?.detail || error.message)
    return Promise.reject(error)
  }
)

export const projectApi = {
  list: () => api.get('/projects'),
  get: (id: string) => api.get(`/projects/${id}`),
  create: (data: unknown) => api.post('/projects', data),
  update: (id: string, data: unknown) => api.put(`/projects/${id}`, data),
  delete: (id: string) => api.delete(`/projects/${id}`),
}

// 所有项目级 API 都以 /projects/{projectId} 为前缀
export const outlineApi = {
  list: (projectId: string) => api.get(`/projects/${projectId}/outlines`),
  get: (projectId: string, id: string) => api.get(`/projects/${projectId}/outlines/${id}`),
  getTree: (projectId: string, id: string) => api.get(`/projects/${projectId}/outlines/${id}/tree`),
  create: (projectId: string, data: unknown) => api.post(`/projects/${projectId}/outlines`, data),
  generate: (projectId: string, llmConfigId: string, params: Record<string, string>) =>
    api.post(`/projects/${projectId}/outlines/generate`, { llm_config_id: llmConfigId, params }),
  expandNode: (projectId: string, llmConfigId: string, nodeId: string, params: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/outlines/nodes/${nodeId}/expand`, { llm_config_id: llmConfigId, params }),
  addNode: (projectId: string, outlineId: string, parentId: string | null, data: unknown) =>
    api.post(`/projects/${projectId}/outlines/nodes`, { outline_id: outlineId, parent_id: parentId, ...data }),
  updateNode: (projectId: string, nodeId: string, data: unknown) =>
    api.put(`/projects/${projectId}/outlines/nodes/${nodeId}`, data),
  deleteNode: (projectId: string, nodeId: string) =>
    api.delete(`/projects/${projectId}/outlines/nodes/${nodeId}`),
  moveNode: (projectId: string, nodeId: string, newParentId: string | null, newOrder: number) =>
    api.put(`/projects/${projectId}/outlines/nodes/${nodeId}/move`, { new_parent_id: newParentId, new_order: newOrder }),
  optimize: (projectId: string, outlineId: string, llmConfigId: string, direction?: string) =>
    api.post(`/projects/${projectId}/outlines/${outlineId}/optimize`, { llm_config_id: llmConfigId, direction }),
}

export const characterApi = {
  list: (projectId: string) => api.get(`/projects/${projectId}/characters`),
  get: (projectId: string, id: string) => api.get(`/projects/${projectId}/characters/${id}`),
  create: (projectId: string, data: unknown) => api.post(`/projects/${projectId}/characters`, data),
  update: (projectId: string, id: string, data: unknown) => api.put(`/projects/${projectId}/characters/${id}`, data),
  delete: (projectId: string, id: string) => api.delete(`/projects/${projectId}/characters/${id}`),
  getRelationships: (projectId: string) => api.get(`/projects/${projectId}/characters/relationships`),
  createRelationship: (projectId: string, data: unknown) => api.post(`/projects/${projectId}/characters/relationships`, data),
  updateRelationship: (projectId: string, id: string, data: unknown) => api.put(`/projects/${projectId}/characters/relationships/${id}`, data),
  deleteRelationship: (projectId: string, id: string) => api.delete(`/projects/${projectId}/characters/relationships/${id}`),
  generateProfile: (projectId: string, llmConfigId: string, description: string) =>
    api.post(`/projects/${projectId}/characters/generate`, { llm_config_id: llmConfigId, description }),
}

export const chapterApi = {
  list: (projectId: string) => api.get(`/projects/${projectId}/chapters`),
  get: (projectId: string, id: string) => api.get(`/projects/${projectId}/chapters/${id}`),
  create: (projectId: string, data: unknown) => api.post(`/projects/${projectId}/chapters`, data),
  update: (projectId: string, id: string, data: unknown) => api.put(`/projects/${projectId}/chapters/${id}`, data),
  delete: (projectId: string, id: string) => api.delete(`/projects/${projectId}/chapters/${id}`),
  getVersions: (projectId: string, chapterId: string) => api.get(`/projects/${projectId}/chapters/${chapterId}/versions`),
  compareVersions: (projectId: string, chapterId: string, v1: number, v2: number) =>
    api.get(`/projects/${projectId}/chapters/${chapterId}/versions/compare`, { params: { v1, v2 } }),
  aiAssist: (projectId: string, llmConfigId: string, chapterId: string, action: string, selection: string, context?: string) =>
    api.post(`/projects/${projectId}/chapters/${chapterId}/ai-assist`, { llm_config_id: llmConfigId, action, selection, context }),
}

export const analysisApi = {
  analyze: (projectId: string, llmConfigId: string, chapterId: string, dimensions: string[]) =>
    api.post(`/projects/${projectId}/analysis/consistency`, { llm_config_id: llmConfigId, chapter_id: chapterId, dimensions }),
  streamAnalyze: (projectId: string, llmConfigId: string, chapterId: string, dimensions: string[]) =>
    api.post(`/projects/${projectId}/analysis/consistency/stream`, { llm_config_id: llmConfigId, chapter_id: chapterId, dimensions }),
  getReports: (projectId: string) => api.get(`/projects/${projectId}/analysis/reports`),
  getReport: (projectId: string, id: string) => api.get(`/projects/${projectId}/analysis/reports/${id}`),
}

export const llmConfigApi = {
  list: () => api.get('/llm-configs'),
  get: (id: string) => api.get(`/llm-configs/${id}`),
  create: (data: unknown) => api.post('/llm-configs', data),
  update: (id: string, data: unknown) => api.put(`/llm-configs/${id}`, data),
  delete: (id: string) => api.delete(`/llm-configs/${id}`),
  test: (id: string) => api.post(`/llm-configs/${id}/test`),
}

export const exportApi = {
  exportProject: (projectId: string, format: string, options?: unknown) =>
    api.post(`/projects/${projectId}/export`, { format, options }, { responseType: 'blob' }),
}
```

### 5.2 路由结构（项目工作区嵌套路由）

```typescript
// frontend/src/App.tsx
import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ProjectList } from '@/modules/project/ProjectList'
import { ProjectWorkspace } from '@/modules/workspace/ProjectWorkspace'
import { LLMConfigPanel } from '@/modules/llm-config/LLMConfigPanel'

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        {/* 项目列表页 - 独立布局 */}
        <Route path="/" element={<ProjectList />} />

        {/* 项目工作区 - 嵌套布局，所有子路由都在项目上下文中 */}
        <Route path="/projects/:projectId" element={<ProjectWorkspace />}>
          <Route path="outline" element={<OutlinePage />} />
          <Route path="characters" element={<CharacterManager />} />
          <Route path="chapters/:chapterId" element={<ChapterPage />} />
          <Route path="consistency" element={<ConsistencyReport />} />
          <Route path="export" element={<ExportPanel />} />
        </Route>

        {/* 全局设置 - 独立布局 */}
        <Route path="/settings" element={<LLMConfigPanel />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
```

### 5.3 项目工作区布局

```typescript
// frontend/src/modules/workspace/ProjectWorkspace.tsx
import React, { useState, useEffect } from 'react'
import { Outlet, useNavigate, useLocation, useParams } from 'react-router-dom'
import { useProjectStore } from '@/stores/projectStore'
import {
  FileText,
  Users,
  BookOpen,
  Shield,
  Download,
  Menu,
  X,
  ArrowLeft,
} from 'lucide-react'

const workspaceNavItems = [
  { path: 'outline', label: '大纲', icon: FileText },
  { path: 'characters', label: '人物', icon: Users },
  { path: 'consistency', label: '一致性', icon: Shield },
  { path: 'export', label: '导出', icon: Download },
]

export const ProjectWorkspace: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { currentProject, setCurrentProject, fetchProjects } = useProjectStore()
  const [sidebarOpen, setSidebarOpen] = useState(true)

  useEffect(() => {
    if (projectId && (!currentProject || currentProject.id !== projectId)) {
      fetchProjects().then(() => {
        const project = useProjectStore.getState().projects.find(p => p.id === projectId)
        if (project) setCurrentProject(project)
      })
    }
  }, [projectId])

  const currentPath = location.pathname.split('/').pop() || ''

  return (
    <div className="flex h-screen bg-gray-50">
      <aside className={`flex flex-col border-r bg-white transition-width ${sidebarOpen ? 'w-56' : 'w-14'}`}>
        <div className="flex items-center justify-between border-b p-3">
          {sidebarOpen && <span className="text-sm font-bold text-gray-700">NWA</span>}
          <button onClick={() => setSidebarOpen(!sidebarOpen)} className="text-gray-400 hover:text-gray-600">
            {sidebarOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
        </div>

        {sidebarOpen && currentProject && (
          <div className="border-b p-3">
            <button onClick={() => navigate('/')} className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 mb-1">
              <ArrowLeft className="h-3 w-3" /> 返回项目列表
            </button>
            <p className="truncate text-sm font-medium text-blue-600">{currentProject.name}</p>
          </div>
        )}

        <nav className="flex-1 space-y-1 p-2">
          {workspaceNavItems.map((item) => {
            const Icon = item.icon
            const active = currentPath === item.path || (item.path === 'outline' && currentPath.startsWith('outline'))
            return (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                className={`flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm transition-colors ${
                  active ? 'bg-blue-50 text-blue-600' : 'text-gray-600 hover:bg-gray-50'
                }`}
              >
                <Icon className="h-4 w-4 flex-shrink-0" />
                {sidebarOpen && <span>{item.label}</span>}
              </button>
            )
          })}
        </nav>
      </aside>

      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
```

### 5.4 Zustand 状态管理

**项目 Store** (`frontend/src/stores/projectStore.ts`)：

```typescript
import { create } from 'zustand'
import { projectApi } from '@/services/api'

interface Project {
  id: string; name: string; description: string | null; genre: string | null
  status: string; word_count_target: number | null; created_at: string; updated_at: string
}

interface ProjectState {
  projects: Project[]; currentProject: Project | null; loading: boolean
  fetchProjects: () => Promise<void>
  createProject: (data: Partial<Project>) => Promise<Project>
  setCurrentProject: (project: Project) => void
  updateProject: (id: string, data: Partial<Project>) => Promise<void>
  deleteProject: async (id: string) => Promise<void>
}

export const useProjectStore = create<ProjectState>((set) => ({
  projects: [], currentProject: null, loading: false,
  fetchProjects: async () => { set({ loading: true }); const projects = await projectApi.list(); set({ projects, loading: false }) },
  createProject: async (data) => { const project = await projectApi.create(data); set((s) => ({ projects: [...s.projects, project] })); return project },
  setCurrentProject: (project) => set({ currentProject: project }),
  updateProject: async (id, data) => { const updated = await projectApi.update(id, data); set((s) => ({ projects: s.projects.map((p) => p.id === id ? updated : p), currentProject: s.currentProject?.id === id ? updated : s.currentProject })) },
  deleteProject: async (id) => { await projectApi.delete(id); set((s) => ({ projects: s.projects.filter((p) => p.id !== id), currentProject: s.currentProject?.id === id ? null : s.currentProject })) },
}))
```

**大纲 Store** (`frontend/src/stores/outlineStore.ts`)：

```typescript
import { create } from 'zustand'
import { outlineApi } from '@/services/api'

interface OutlineNode {
  id: string; node_type: 'VOLUME' | 'CHAPTER' | 'SCENE' | 'PLOT_POINT' | 'KEY_EVENT'
  title: string; summary: string | null; sort_order: number
  metadata: Record<string, unknown> | null; llm_generated: boolean; children: OutlineNode[]
}

interface Outline { id: string; project_id: string; title: string; description: string | null; version: number; tree: OutlineNode[] }

interface OutlineState {
  outlines: Outline[]; currentOutline: Outline | null; generating: boolean
  fetchOutlines: (projectId: string) => Promise<void>
  generateOutline: (projectId: string, llmConfigId: string, params: Record<string, string>) => Promise<void>
  expandNode: (projectId: string, llmConfigId: string, nodeId: string, params: Record<string, unknown>) => Promise<OutlineNode[]>
  addNode: (projectId: string, outlineId: string, parentId: string | null, data: Partial<OutlineNode>) => Promise<OutlineNode>
  updateNode: (projectId: string, nodeId: string, data: Partial<OutlineNode>) => Promise<void>
  deleteNode: (projectId: string, nodeId: string) => Promise<void>
  moveNode: (projectId: string, nodeId: string, newParentId: string | null, newOrder: number) => Promise<void>
}

export const useOutlineStore = create<OutlineState>((set, get) => ({
  outlines: [], currentOutline: null, generating: false,
  fetchOutlines: async (projectId) => { set({ outlines: await outlineApi.list(projectId) }) },
  generateOutline: async (projectId, llmConfigId, params) => {
    set({ generating: true }); try { const outline = await outlineApi.generate(projectId, llmConfigId, params); set((s) => ({ outlines: [...s.outlines, outline], currentOutline: outline })) } finally { set({ generating: false }) }
  },
  expandNode: async (projectId, llmConfigId, nodeId, params) => {
    const newNodes = await outlineApi.expandNode(projectId, llmConfigId, nodeId, params); const o = get().currentOutline
    if (o) set({ currentOutline: { ...o, tree: insertChildren(o.tree, nodeId, newNodes) } }); return newNodes
  },
  addNode: async (projectId, outlineId, parentId, data) => {
    const node = await outlineApi.addNode(projectId, outlineId, parentId, data); const o = get().currentOutline
    if (o) set({ currentOutline: { ...o, tree: insertChild(o.tree, parentId, node) } }); return node
  },
  updateNode: async (projectId, nodeId, data) => { await outlineApi.updateNode(projectId, nodeId, data); const o = get().currentOutline; if (o) set({ currentOutline: { ...o, tree: updateNodeInTree(o.tree, nodeId, data) } }) },
  deleteNode: async (projectId, nodeId) => { await outlineApi.deleteNode(projectId, nodeId); const o = get().currentOutline; if (o) set({ currentOutline: { ...o, tree: removeNodeFromTree(o.tree, nodeId) } }) },
  moveNode: async (projectId, nodeId, newParentId, newOrder) => { await outlineApi.moveNode(projectId, nodeId, newParentId, newOrder) },
}))

function insertChildren(tree: OutlineNode[], parentId: string, newNodes: OutlineNode[]): OutlineNode[] {
  return tree.map((n) => n.id === parentId ? { ...n, children: [...n.children, ...newNodes] } : n.children.length ? { ...n, children: insertChildren(n.children, parentId, newNodes) } : n)
}
function insertChild(tree: OutlineNode[], parentId: string | null, node: OutlineNode): OutlineNode[] {
  if (!parentId) return [...tree, node]; return tree.map((n) => n.id === parentId ? { ...n, children: [...n.children, node] } : n.children.length ? { ...n, children: insertChild(n.children, parentId, node) } : n)
}
function updateNodeInTree(tree: OutlineNode[], nodeId: string, data: Partial<OutlineNode>): OutlineNode[] {
  return tree.map((n) => n.id === nodeId ? { ...n, ...data } : n.children.length ? { ...n, children: updateNodeInTree(n.children, nodeId, data) } : n)
}
function removeNodeFromTree(tree: OutlineNode[], nodeId: string): OutlineNode[] {
  return tree.filter((n) => n.id !== nodeId).map((n) => n.children.length ? { ...n, children: removeNodeFromTree(n.children, nodeId) } : n)
}
```

### 5.5 核心组件

**大纲编辑器** (`frontend/src/modules/outline/OutlineEditor.tsx`)：

```typescript
import React, { useCallback, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useOutlineStore } from '@/stores/outlineStore'
import { OutlineNodeTree } from './OutlineNodeTree'
import { OutlineGenerateDialog } from './OutlineGenerateDialog'
import { Button } from '@/components/ui/Button'
import { Plus, Sparkles } from 'lucide-react'

export const OutlineEditor: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const { currentOutline, fetchOutlines, generating, expandNode, addNode } = useOutlineStore()
  const [showGenDialog, setShowGenDialog] = useState(false)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  React.useEffect(() => { if (projectId) fetchOutlines(projectId) }, [projectId])

  const handleExpand = useCallback(async (nodeId: string) => {
    const cfgId = localStorage.getItem('active_llm_config_id')
    if (cfgId && projectId) await expandNode(projectId, cfgId, nodeId, { count: 3 })
  }, [projectId, expandNode])

  const handleAdd = useCallback(async (parentId: string | null, nodeType: string) => {
    if (!currentOutline || !projectId) return
    await addNode(projectId, currentOutline.id, parentId, { node_type: nodeType as any, title: '新节点', summary: '', sort_order: 0 })
  }, [projectId, currentOutline, addNode])

  if (!currentOutline) return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center space-y-4">
        <p className="text-gray-500">暂无大纲</p>
        <Button onClick={() => setShowGenDialog(true)}><Sparkles className="w-4 h-4 mr-2" />AI 生成大纲</Button>
      </div>
    </div>
  )

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-4 border-b">
        <h2 className="text-lg font-semibold">{currentOutline.title}</h2>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => handleAdd(null, 'VOLUME')}><Plus className="w-4 h-4 mr-1" />添加卷</Button>
          <Button variant="outline" size="sm" onClick={() => setShowGenDialog(true)}><Sparkles className="w-4 h-4 mr-1" />AI 优化</Button>
        </div>
      </div>
      <div className="flex-1 overflow-auto p-4">
        <OutlineNodeTree nodes={currentOutline.tree} selectedNodeId={selectedNodeId} onSelectNode={setSelectedNodeId} onExpandNode={handleExpand} onAddChild={handleAdd} />
      </div>
      <OutlineGenerateDialog open={showGenDialog} onClose={() => setShowGenDialog(false)} projectId={projectId!} />
    </div>
  )
}
```

**人物关系图谱** (`frontend/src/modules/character/RelationshipGraph.tsx`)：

```typescript
import React, { useMemo } from 'react'
import { ReactFlow, Background, Controls, MiniMap, Node, Edge, NodeTypes, MarkerType } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { CharacterNode } from './CharacterNode'

const COLORS: Record<string, string> = { FAMILY: '#ef4444', FRIEND: '#22c55e', ENEMY: '#dc2626', LOVER: '#ec4899', MENTOR: '#8b5cf6', SUBORDINATE: '#f59e0b', ALLY: '#06b6d4', RIVAL: '#f97316', OTHER: '#6b7280' }

interface Props {
  characters: Array<{ id: string; name: string }>
  relationships: Array<{ id: string; source_id: string; target_id: string; relationship_type: string; description: string; intensity: number }>
}

export const RelationshipGraph: React.FC<Props> = ({ characters, relationships }) => {
  const nodeTypes: NodeTypes = useMemo(() => ({ character: CharacterNode }), [])
  const nodes: Node[] = useMemo(() => {
    const step = (2 * Math.PI) / characters.length
    return characters.map((c, i) => ({ id: c.id, type: 'character', position: { x: 300 + 250 * Math.cos(step * i - Math.PI / 2), y: 300 + 250 * Math.sin(step * i - Math.PI / 2) }, data: { label: c.name, character: c } }))
  }, [characters])
  const edges: Edge[] = useMemo(() => relationships.map((r) => ({ id: r.id, source: r.source_id, target: r.target_id, label: r.description || r.relationship_type, style: { stroke: COLORS[r.relationship_type] || COLORS.OTHER, strokeWidth: Math.max(1, r.intensity / 3) }, markerEnd: { type: MarkerType.ArrowClosed, color: COLORS[r.relationship_type] || COLORS.OTHER } })), [relationships])

  return (
    <div className="w-full h-[600px] border rounded-lg">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView>
        <Background /><Controls /><MiniMap />
      </ReactFlow>
    </div>
  )
}
```

**章节编辑器** (`frontend/src/modules/chapter/ChapterEditor.tsx`)：

```typescript
import React, { useCallback, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { ChapterToolbar } from './ChapterToolbar'
import { AiAssistPanel } from './AiAssistPanel'
import { VersionPanel } from './VersionPanel'
import { chapterApi } from '@/services/api'
import { debounce } from '@/utils/debounce'

export const ChapterEditor: React.FC = () => {
  const { projectId, chapterId } = useParams<{ projectId: string; chapterId: string }>()
  const [showAi, setShowAi] = useState(false)
  const [showVer, setShowVer] = useState(false)
  const [saving, setSaving] = useState(false)
  const [wordCount, setWordCount] = useState(0)

  const editor = useEditor({
    extensions: [StarterKit],
    content: '',
    onUpdate: ({ editor }) => { setWordCount(editor.getText().length); debouncedSave(editor.getHTML()) },
  })

  const debouncedSave = useCallback(debounce(async (content: string) => { setSaving(true); try { if (projectId && chapterId) await chapterApi.update(projectId, chapterId, { content, word_count: content.length }) } finally { setSaving(false) } }, 3000), [projectId, chapterId])

  const handleAiAssist = useCallback(async (action: string, selection: string, context?: string) => {
    const cfgId = localStorage.getItem('active_llm_config_id')
    if (!cfgId || !projectId || !chapterId || !editor) return
    return await chapterApi.aiAssist(projectId, cfgId, chapterId, action, selection, context)
  }, [projectId, chapterId, editor])

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col">
        <ChapterToolbar editor={editor} wordCount={wordCount} saving={saving} onToggleAiPanel={() => setShowAi(!showAi)} onToggleVersionPanel={() => setShowVer(!showVer)} />
        <div className="flex-1 overflow-auto p-8 max-w-4xl mx-auto w-full">
          <EditorContent editor={editor} className="prose prose-lg max-w-none" />
        </div>
      </div>
      {showAi && <div className="w-80 border-l overflow-auto"><AiAssistPanel editor={editor} onAssist={handleAiAssist} onClose={() => setShowAi(false)} /></div>}
      {showVer && <div className="w-96 border-l overflow-auto"><VersionPanel projectId={projectId!} chapterId={chapterId!} onClose={() => setShowVer(false)} /></div>}
    </div>
  )
}
```

### 5.6 工具函数

```typescript
// frontend/src/utils/debounce.ts
export function debounce<T extends (...args: any[]) => any>(fn: T, delay: number): (...args: Parameters<T>) => void {
  let timer: ReturnType<typeof setTimeout>
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay) }
}
```

```typescript
// frontend/src/utils/localStorage.ts
const P = 'nwa_'
export const storage = {
  get: <T>(key: string): T | null => { const r = localStorage.getItem(P + key); return r ? JSON.parse(r) : null },
  set: (key: string, value: unknown) => localStorage.setItem(P + key, JSON.stringify(value)),
  remove: (key: string) => localStorage.removeItem(P + key),
}
```

---

## 6. 关键实现要点

### 6.1 LLM 流式输出

后端通过 SSE (Server-Sent Events) 将 LLM 的流式响应转发给前端：

```python
# backend/app/api/v1/chapters.py (流式续写端点示例)
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

@router.post("/{chapter_id}/ai-stream")
async def ai_stream_continue(
    project_id: str,
    chapter_id: str,
    request: AIStreamRequest,
    db: AsyncSession = Depends(get_db),
    project: Project = Depends(verify_project_access),
):
    async def event_generator():
        async for chunk in chapter_service.ai_stream(db, request.llm_config_id, chapter_id, request.action, request.selection, request.context):
            yield f"event: chunk\ndata: {json.dumps({'content': chunk})}\n\n"
        yield "event: done\ndata: {}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

前端使用 `fetch` + `ReadableStream` 接收：

```typescript
const response = await fetch(`/api/v1/projects/${projectId}/chapters/${chapterId}/ai-stream`, { method: 'POST', body: JSON.stringify(payload), headers: { 'Content-Type': 'application/json' } })
const reader = response.body!.getReader()
const decoder = new TextDecoder()
while (true) {
  const { done, value } = await reader.read()
  if (done) break
  const text = decoder.decode(value)
  const lines = text.split('\n').filter(l => l.startsWith('data: '))
  for (const line of lines) {
    const data = line.slice(6)
    if (data === '[DONE]') break
    const { content } = JSON.parse(data)
    onChunk(content)
  }
}
```

### 6.2 项目归属校验

所有项目级 API 路由通过 `verify_project_access` 依赖注入校验：
1. 路径参数 `project_id` 自动从 URL 提取
2. 依赖函数查询数据库验证项目存在
3. 业务操作时额外校验资源（大纲/人物/章节）的 `project_id` 与路径参数一致

### 6.3 版本对比

使用 Python 标准库 `difflib` 实现版本差异对比，前端通过双栏视图展示：
- 左栏：旧版本（红色标记删除内容）
- 右栏：新版本（绿色标记新增内容）
- 统一差异视图（unified diff）

### 6.4 自动保存策略

- 编辑器内容变更触发防抖保存（3 秒）
- 手动 Ctrl+S 立即保存
- 保存时自动创建版本快照（每 10 次保存或用户手动创建）
- 保存失败时本地缓存到 IndexedDB，网络恢复后重试

### 6.5 响应式设计

使用 TailwindCSS 断点实现：

| 断点 | 宽度 | 布局调整 |
|------|------|----------|
| sm | 640px | 单栏布局，侧边栏折叠 |
| md | 768px | 双栏布局，侧边栏可展开 |
| lg | 1024px | 三栏布局，完整功能 |
| xl | 1280px | 宽屏优化，编辑区域加大 |
