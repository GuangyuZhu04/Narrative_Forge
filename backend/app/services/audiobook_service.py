import asyncio
import base64
import copy
import hashlib
import html
import json
import re
import shutil
import tempfile
import wave
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_api_key
from app.db.session import AsyncSessionLocal
from app.models.audiobook import AudiobookConfig, AudiobookJob
from app.models.character import Character
from app.models.chapter import Chapter
from app.models.llm_config import LLMConfig
from app.models.outline import Outline, OutlineNode
from app.models.project import Project
from app.llm.json_mode import json_object_response_kwargs
from app.llm.providers.base import LLMOutputTruncatedError
from app.llm.prompts.audiobook import (
    AUDIOBOOK_API_DOCS_PARSE_SYSTEM,
    AUDIOBOOK_API_DOCS_PARSE_USER,
    AUDIOBOOK_SCRIPT_SYSTEM,
    AUDIOBOOK_SCRIPT_USER,
)
from app.services.llm_orchestrator import llm_orchestrator
from app.tts import (
    ComfyUITTSProvider,
    CustomHTTPTTSProvider,
    CustomWebSocketTTSProvider,
    MiniMaxAsyncTTSProvider,
    OpenAICompatibleTTSProvider,
)


AUDIOBOOK_ROOT = Path("data/audiobooks")
MINIMAX_SEGMENT_CONCURRENCY = 4
SAME_VOICE_PAUSE_MS = 200
VOICE_SWITCH_PAUSE_MS = 400
CHAPTER_END_PAUSE_MS = 800
DEEPSEEK_SCRIPT_MAX_TOKENS = 384 * 1024
DEFAULT_SCRIPT_MAX_TOKENS = 16 * 1024
SPEECH_VERBS = "说|问|道|喊|叫|答|嚷|吼|嘀咕|低语|轻声说|高声说|开口|回应"
QUOTE_PATTERN = re.compile(
    r"“(?P<cn>[^”]+)”|「(?P<corner>[^」]+)」|『(?P<double>[^』]+)』|\"(?P<ascii>[^\"\n]+)\""
)


class AudiobookValidationError(ValueError):
    pass


class AudiobookVoiceServiceError(RuntimeError):
    pass


class _TextExtractor(HTMLParser):
    BLOCK_TAGS = {
        "p",
        "div",
        "br",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def get_text(self) -> str:
        return "".join(self.parts)


@dataclass(slots=True)
class SpeechSegment:
    text: str
    speaker_id: str | None = None


@dataclass(frozen=True, slots=True)
class ChapterDisplayInfo:
    title: str
    position: int


class AudiobookService:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    async def get_scopes(self, db: AsyncSession, project_id: str) -> dict[str, Any]:
        project = await db.get(Project, project_id)
        outline, nodes, chapter_entries = await self._project_content_structure(
            db, project_id
        )
        chapters = [chapter for chapter, _node in chapter_entries]
        chapter_by_node = {
            node.id: chapter for chapter, node in chapter_entries
        }
        children_by_parent: dict[str | None, list[OutlineNode]] = {}
        for node in nodes:
            children_by_parent.setdefault(node.parent_id, []).append(node)

        volumes = []
        for volume in (
            node
            for node in self._ordered_outline_nodes(nodes)
            if node.node_type == "VOLUME"
        ):
            descendant_ids = self._descendant_ids(volume.id, children_by_parent)
            descendant_ids.add(volume.id)
            volumes.append(
                {
                    "id": volume.id,
                    "title": volume.title,
                    "chapter_count": sum(
                        1 for node_id in descendant_ids if node_id in chapter_by_node
                    ),
                    "outline_title": outline.title if outline else None,
                }
            )

        return {
            "book_title": project.name if project else "",
            "book_chapter_count": len(chapters),
            "volumes": volumes,
            "chapters": [
                {
                    "id": chapter.id,
                    "title": self._chapter_display_title(chapter, node, index),
                    "chapter_count": 1,
                    "outline_title": None,
                }
                for index, (chapter, node) in enumerate(chapter_entries)
            ],
        }

    async def resolve_scope(
        self,
        db: AsyncSession,
        project_id: str,
        scope_type: str,
        scope_id: str | None,
    ) -> tuple[str, list[Chapter], list[str]]:
        project = await db.get(Project, project_id)
        _outline, nodes, chapter_entries = await self._project_content_structure(
            db, project_id
        )
        ordered_chapters = [chapter for chapter, _node in chapter_entries]
        display_info = {
            chapter.id: ChapterDisplayInfo(
                title=self._chapter_display_title(chapter, node, index),
                position=index + 1,
            )
            for index, (chapter, node) in enumerate(chapter_entries)
        }
        if scope_type == "book":
            chapters = ordered_chapters
            title = project.name if project else "全书"
        elif scope_type == "chapter":
            if not scope_id:
                raise AudiobookValidationError("请选择要生成的章节")
            chapter = next(
                (item for item in ordered_chapters if item.id == scope_id), None
            )
            if not chapter:
                raise AudiobookValidationError("所选章节不存在")
            chapters = [chapter]
            title = display_info[chapter.id].title
        elif scope_type == "volume":
            if not scope_id:
                raise AudiobookValidationError("请选择要生成的卷")
            node_by_id = {node.id: node for node in nodes}
            volume = node_by_id.get(scope_id)
            if not volume or volume.node_type != "VOLUME":
                raise AudiobookValidationError("所选卷不存在")
            children_by_parent: dict[str | None, list[OutlineNode]] = {}
            for node in nodes:
                children_by_parent.setdefault(node.parent_id, []).append(node)
            descendant_ids = self._descendant_ids(volume.id, children_by_parent)
            descendant_ids.add(volume.id)
            chapters = [
                chapter
                for chapter in ordered_chapters
                if chapter.outline_node_id in descendant_ids
            ]
            title = volume.title
        else:
            raise AudiobookValidationError("不支持的生成范围")

        skipped = [
            display_info[chapter.id].title
            for chapter in chapters
            if not self.clean_text(chapter.content)
        ]
        chapters = [chapter for chapter in chapters if self.clean_text(chapter.content)]
        if not chapters:
            raise AudiobookValidationError("所选范围没有可朗读的章节正文")
        return title, list(chapters), skipped

    async def create_job(
        self,
        db: AsyncSession,
        project_id: str,
        scope_type: str,
        scope_id: str | None,
        llm_config_id: str,
    ) -> AudiobookJob:
        config = await self._get_config(db, project_id)
        self.validate_config(config)
        llm_config = await db.get(LLMConfig, llm_config_id)
        if not llm_config:
            raise AudiobookValidationError("所选语音脚本 LLM 配置不存在")
        if not llm_config.is_active:
            raise AudiobookValidationError("所选语音脚本 LLM 配置未启用")
        if config.provider == "minimax_async" and config.use_ffmpeg:
            self.require_ffmpeg()
        title, chapters, skipped = await self.resolve_scope(db, project_id, scope_type, scope_id)
        job = AudiobookJob(
            project_id=project_id,
            config_id=config.id,
            script_llm_config_id=llm_config.id,
            scope_type=scope_type,
            scope_id=scope_id,
            scope_title=title,
            chapter_ids=[chapter.id for chapter in chapters],
            total_chapters=len(chapters),
            speech_scripts={},
            segment_tasks=[],
            output_files=[],
            error_message=(
                f"已跳过 {len(skipped)} 个空章节：{'、'.join(skipped)}" if skipped else None
            ),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job

    def start_job(self, job_id: str) -> None:
        if job_id in self._tasks and not self._tasks[job_id].done():
            return
        task = asyncio.create_task(self.run_job(job_id))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(job_id, None))

    def cancel_task(self, job_id: str) -> None:
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()

    async def resume_pending_jobs(self) -> None:
        async with AsyncSessionLocal() as db:
            jobs = list(
                (
                    await db.execute(
                        select(AudiobookJob).where(
                            AudiobookJob.status.in_(["queued", "processing"])
                        )
                    )
                )
                .scalars()
                .all()
            )
            for job in jobs:
                job.status = "queued"
                job.progress = 0
                job.processed_chapters = 0
                job.current_chapter_title = None
                job.output_files = []
                job.error_message = "服务重启后已自动恢复任务"
                job.started_at = None
                job.completed_at = None
            await db.commit()
        for job in jobs:
            self.start_job(job.id)

    async def run_job(self, job_id: str) -> None:
        output_dir: Path | None = None
        provider: Any | None = None
        try:
            async with AsyncSessionLocal() as db:
                job = await db.get(AudiobookJob, job_id)
                if not job or job.status == "cancelled":
                    return
                config = await db.get(AudiobookConfig, job.config_id)
                if not config:
                    raise AudiobookValidationError("有声书配置已被删除")
                self.validate_config(config)
                script_llm_config = await db.get(LLMConfig, job.script_llm_config_id)
                if not script_llm_config:
                    raise AudiobookValidationError("语音脚本 LLM 配置已被删除")
                if not script_llm_config.is_active:
                    raise AudiobookValidationError("语音脚本 LLM 配置已停用")
                provider = self.build_provider(config)
                chapter_display_info = await self.get_chapter_display_info(
                    db, job.project_id
                )
                if job.scope_type == "chapter" and job.scope_id in chapter_display_info:
                    job.scope_title = chapter_display_info[job.scope_id].title
                ffmpeg = (
                    self.require_ffmpeg()
                    if isinstance(provider, MiniMaxAsyncTTSProvider) and config.use_ffmpeg
                    else None
                )
                characters = list(
                    (
                        await db.execute(
                            select(Character)
                            .where(Character.project_id == job.project_id)
                            .order_by(Character.sort_order, Character.created_at, Character.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                chapters_by_id = {
                    chapter.id: chapter
                    for chapter in (
                        await db.execute(select(Chapter).where(Chapter.id.in_(job.chapter_ids)))
                    )
                    .scalars()
                    .all()
                }
                chapters = [
                    chapters_by_id[chapter_id]
                    for chapter_id in job.chapter_ids
                    if chapter_id in chapters_by_id
                ]
                if not chapters:
                    raise AudiobookValidationError("待生成章节已不存在")

                job.status = "processing"
                job.started_at = datetime.now()
                job.error_message = None
                await db.commit()

                output_dir = AUDIOBOOK_ROOT / job.project_id / job.id
                output_dir.mkdir(parents=True, exist_ok=True)
                artifacts: list[dict[str, Any]] = []
                chapter_paths: list[Path] = []
                chapter_master_paths: list[Path] = []

                for chapter_index, chapter in enumerate(chapters):
                    display_info = chapter_display_info.get(chapter.id)
                    chapter_position = (
                        display_info.position if display_info else chapter_index + 1
                    )
                    chapter_title = (
                        display_info.title
                        if display_info
                        else (chapter.title or "").strip()
                        or f"第{chapter_position}章"
                    )
                    await db.refresh(job, ["status"])
                    if job.status == "cancelled":
                        shutil.rmtree(output_dir, ignore_errors=True)
                        return
                    job.current_chapter_title = chapter_title
                    await db.commit()

                    spoken = [
                        SpeechSegment(
                            self.spoken_chapter_title(
                                chapter,
                                title=chapter_title,
                                position=chapter_position,
                            )
                        )
                    ]
                    spoken.extend(
                        await self._get_or_create_speech_script(
                            db=db,
                            job=job,
                            config=config,
                            chapter=chapter,
                            chapter_title=chapter_title,
                            characters=characters,
                        )
                    )
                    chunks = self.build_chunks(
                        spoken,
                        config.character_voices or {},
                        config.narrator_voice,
                        config.max_chars_per_segment,
                    )
                    if not chunks:
                        continue
                    filename = (
                        f"{chapter_position:03d}_{self.safe_filename(chapter_title)}.mp3"
                    )
                    chapter_path = output_dir / filename
                    if isinstance(provider, MiniMaxAsyncTTSProvider):
                        segment_paths = await self._generate_minimax_segments(
                            db=db,
                            job=job,
                            provider=provider,
                            config=config,
                            chapter=chapter,
                            chapter_index=chapter_index,
                            chapter_count=len(chapters),
                            chunks=chunks,
                            output_dir=output_dir,
                        )
                        if config.use_ffmpeg:
                            chapter_master = await self.render_minimax_chapter(
                                ffmpeg=ffmpeg or self.require_ffmpeg(),
                                segment_paths=segment_paths,
                                pauses=self.segment_pauses(chunks),
                                work_dir=(
                                    output_dir
                                    / ".work"
                                    / f"chapter_{chapter_index + 1:04d}"
                                ),
                                output_mp3=chapter_path,
                            )
                            chapter_master_paths.append(chapter_master)
                        else:
                            chapter_path.write_bytes(
                                self.concatenate_mp3(
                                    [path.read_bytes() for path in segment_paths]
                                )
                            )
                    else:
                        audio_parts: list[bytes] = []
                        for segment_index, (text, voice) in enumerate(chunks):
                            await db.refresh(job, ["status"])
                            if job.status == "cancelled":
                                shutil.rmtree(output_dir, ignore_errors=True)
                                return
                            result = await provider.synthesize(
                                text,
                                voice,
                                config.speed,
                                f"{job.id}_{chapter_index + 1}_{segment_index + 1}",
                            )
                            await db.refresh(job, ["status"])
                            if job.status == "cancelled":
                                shutil.rmtree(output_dir, ignore_errors=True)
                                return
                            audio_parts.append(result.content)
                            chapter_fraction = (segment_index + 1) / len(chunks)
                            job.progress = min(
                                99,
                                int(
                                    (
                                        (chapter_index + chapter_fraction)
                                        / len(chapters)
                                    )
                                    * 100
                                ),
                            )
                            await db.commit()
                        chapter_path.write_bytes(self.concatenate_mp3(audio_parts))
                    chapter_paths.append(chapter_path)
                    artifacts.append(
                        {
                            "kind": "chapter",
                            "filename": filename,
                            "title": chapter_title,
                            "size_bytes": chapter_path.stat().st_size,
                            "chapter_id": chapter.id,
                        }
                    )
                    job.processed_chapters = chapter_index + 1
                    job.output_files = list(artifacts)
                    await db.commit()

                await db.refresh(job, ["status"])
                if job.status == "cancelled":
                    shutil.rmtree(output_dir, ignore_errors=True)
                    return
                combined_filename = f"{self.safe_filename(job.scope_title)}.mp3"
                combined_path = output_dir / combined_filename
                if chapter_master_paths:
                    await self.render_minimax_combined(
                        ffmpeg=ffmpeg or self.require_ffmpeg(),
                        chapter_paths=chapter_master_paths,
                        work_dir=output_dir / ".work" / "combined",
                        output_mp3=combined_path,
                    )
                else:
                    self.concatenate_mp3_files(chapter_paths, combined_path)
                artifacts.insert(
                    0,
                    {
                        "kind": "combined",
                        "filename": combined_filename,
                        "title": job.scope_title,
                        "size_bytes": combined_path.stat().st_size,
                        "chapter_id": None,
                    },
                )
                job.output_files = list(artifacts)
                job.status = "completed"
                job.progress = 100
                job.current_chapter_title = None
                job.completed_at = datetime.now()
                await db.commit()
        except asyncio.CancelledError:
            async with AsyncSessionLocal() as db:
                job = await db.get(AudiobookJob, job_id)
                if job and job.status not in {"completed", "failed", "cancelled"}:
                    job.status = "queued"
                    job.current_chapter_title = None
                    job.error_message = "服务停止，任务将在下次启动后恢复"
                    await db.commit()
        except Exception as exc:
            async with AsyncSessionLocal() as db:
                job = await db.get(AudiobookJob, job_id)
                if job and job.status != "cancelled":
                    job.status = "failed"
                    job.error_message = str(exc)[:2000]
                    job.current_chapter_title = None
                    job.completed_at = datetime.now()
                    await db.commit()
        finally:
            if isinstance(provider, CustomWebSocketTTSProvider):
                await provider.aclose()

    async def preview(
        self, db: AsyncSession, project_id: str, text: str, voice: str | None
    ) -> bytes:
        config = await self._get_config(db, project_id)
        self.validate_config(config)
        provider = self.build_provider(config)
        try:
            result = await provider.synthesize(
                self.clean_text(text),
                voice or config.narrator_voice,
                config.speed,
                "preview",
            )
        finally:
            if isinstance(provider, CustomWebSocketTTSProvider):
                await provider.aclose()
        if isinstance(provider, MiniMaxAsyncTTSProvider) and config.use_ffmpeg:
            with tempfile.TemporaryDirectory(prefix="audiobook-preview-") as temp_dir:
                root = Path(temp_dir)
                source = root / f"source{result.extension}"
                output = root / "preview.mp3"
                source.write_bytes(result.content)
                await self.transcode_preview(self.require_ffmpeg(), source, output)
                return output.read_bytes()
        return result.content

    async def _generate_minimax_segments(
        self,
        *,
        db: AsyncSession,
        job: AudiobookJob,
        provider: MiniMaxAsyncTTSProvider,
        config: AudiobookConfig,
        chapter: Chapter,
        chapter_index: int,
        chapter_count: int,
        chunks: list[tuple[str, str]],
        output_dir: Path,
    ) -> list[Path]:
        pauses = self.segment_pauses(chunks)
        existing = {
            (str(item.get("chapter_id")), int(item.get("segment_index", -1))): item
            for item in (job.segment_tasks or [])
            if isinstance(item, dict)
        }
        chapter_records: list[dict[str, Any]] = []
        for segment_index, (text, voice) in enumerate(chunks):
            input_hash = self.segment_request_hash(config, text, voice)
            old = existing.get((chapter.id, segment_index))
            if old and old.get("input_hash") == input_hash:
                record = copy.deepcopy(old)
                record["pause_after_ms"] = pauses[segment_index]
                record["error_message"] = None
            else:
                record = {
                    "chapter_id": chapter.id,
                    "chapter_index": chapter_index,
                    "segment_index": segment_index,
                    "voice_id": voice,
                    "input_hash": input_hash,
                    "status": "pending",
                    "task_id": None,
                    "file_id": None,
                    "audio_filename": None,
                    "pause_after_ms": pauses[segment_index],
                    "retry_count": 0,
                    "error_message": None,
                }
            chapter_records.append(record)

        retained = [
            copy.deepcopy(item)
            for item in (job.segment_tasks or [])
            if isinstance(item, dict) and str(item.get("chapter_id")) != chapter.id
        ]
        job.segment_tasks = sorted(
            [*retained, *chapter_records],
            key=lambda item: (
                int(item.get("chapter_index", 0)),
                int(item.get("segment_index", 0)),
            ),
        )
        await db.commit()

        update_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(MINIMAX_SEGMENT_CONCURRENCY)
        raw_dir = output_dir / ".segments" / chapter.id
        raw_dir.mkdir(parents=True, exist_ok=True)

        async def update_record(segment_index: int, **values: Any) -> None:
            async with update_lock:
                records = copy.deepcopy(job.segment_tasks or [])
                for record in records:
                    if (
                        str(record.get("chapter_id")) == chapter.id
                        and int(record.get("segment_index", -1)) == segment_index
                    ):
                        record.update(values)
                        break
                job.segment_tasks = records
                await db.commit()

        async def generate_one(
            segment_index: int,
            text: str,
            voice: str,
            record: dict[str, Any],
        ) -> tuple[int, Path]:
            cached_name = str(record.get("audio_filename") or "")
            cached_path = raw_dir / cached_name if cached_name else None
            if (
                record.get("status") == "completed"
                and cached_path is not None
                and cached_path.is_file()
            ):
                return segment_index, cached_path

            async def on_status(status: str, metadata: dict[str, str | None]) -> None:
                await update_record(
                    segment_index,
                    status=status,
                    task_id=metadata.get("task_id"),
                    file_id=metadata.get("file_id"),
                    error_message=None,
                )

            resume_file_id = (
                str(record.get("file_id")) if record.get("file_id") else None
            )
            resume_task_id = (
                str(record.get("task_id"))
                if record.get("task_id")
                and (
                    record.get("status") in {"processing", "downloading"}
                    or resume_file_id
                )
                else None
            )
            try:
                async with semaphore:
                    result = await provider.synthesize(
                        text,
                        voice,
                        config.speed,
                        f"{job.id}_{chapter_index + 1}_{segment_index + 1}",
                        task_status_callback=on_status,
                        resume_task_id=resume_task_id,
                        resume_file_id=resume_file_id,
                    )
            except Exception as first_error:
                if resume_task_id or resume_file_id:
                    await update_record(
                        segment_index,
                        status="pending",
                        task_id=None,
                        file_id=None,
                        audio_filename=None,
                        retry_count=int(record.get("retry_count", 0)) + 1,
                        error_message=f"恢复已有任务失败，已重新创建：{first_error}"[:1000],
                    )
                    try:
                        async with semaphore:
                            result = await provider.synthesize(
                                text,
                                voice,
                                config.speed,
                                f"{job.id}_{chapter_index + 1}_{segment_index + 1}",
                                task_status_callback=on_status,
                            )
                    except Exception as retry_error:
                        await update_record(
                            segment_index,
                            status="failed",
                            error_message=str(retry_error)[:1000],
                        )
                        raise
                else:
                    await update_record(
                        segment_index,
                        status="failed",
                        retry_count=int(record.get("retry_count", 0)) + 1,
                        error_message=str(first_error)[:1000],
                    )
                    raise

            extension = result.extension.lower()
            if extension not in MiniMaxAsyncTTSProvider.AUDIO_EXTENSIONS:
                extension = ".bin"
            filename = f"segment_{segment_index:04d}{extension}"
            path = raw_dir / filename
            path.write_bytes(result.content)
            await update_record(
                segment_index,
                status="completed",
                task_id=result.task_id,
                file_id=result.file_id,
                audio_filename=filename,
                error_message=None,
            )
            return segment_index, path

        tasks = [
            asyncio.create_task(generate_one(index, text, voice, chapter_records[index]))
            for index, (text, voice) in enumerate(chunks)
        ]
        paths: dict[int, Path] = {}
        completed_segments = 0
        try:
            for future in asyncio.as_completed(tasks):
                segment_index, path = await future
                paths[segment_index] = path
                completed_segments += 1
                async with update_lock:
                    chapter_fraction = completed_segments / len(chunks)
                    job.progress = min(
                        99,
                        int(((chapter_index + chapter_fraction) / chapter_count) * 100),
                    )
                    await db.commit()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return [paths[index] for index in range(len(chunks))]

    @staticmethod
    def segment_request_hash(config: AudiobookConfig, text: str, voice: str) -> str:
        value = json.dumps(
            {
                "model": config.model_name,
                "voice": voice,
                "speed": config.speed,
                "text": text.strip(),
                "output_format": "wav" if config.use_ffmpeg else "mp3",
                "sample_rate": 32000,
                "channel": 1,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def segment_pauses(chunks: list[tuple[str, str]]) -> list[int]:
        pauses: list[int] = []
        for index, (_, voice) in enumerate(chunks):
            if index == len(chunks) - 1:
                pauses.append(CHAPTER_END_PAUSE_MS)
            elif chunks[index + 1][1] == voice:
                pauses.append(SAME_VOICE_PAUSE_MS)
            else:
                pauses.append(VOICE_SWITCH_PAUSE_MS)
        return pauses

    @staticmethod
    def require_ffmpeg() -> str:
        executable = shutil.which("ffmpeg")
        if not executable:
            raise AudiobookValidationError(
                "MiniMax 异步有声书需要 FFmpeg。请安装 FFmpeg 并将 ffmpeg 加入 PATH，"
                "再创建任务。"
            )
        return executable

    async def render_minimax_chapter(
        self,
        *,
        ffmpeg: str,
        segment_paths: list[Path],
        pauses: list[int],
        work_dir: Path,
        output_mp3: Path,
    ) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        concat_items: list[Path] = []
        for index, source in enumerate(segment_paths):
            normalized = work_dir / f"normalized_{index:04d}.wav"
            await self._normalize_audio(ffmpeg, source, normalized)
            concat_items.append(normalized)
            pause_ms = pauses[index]
            if pause_ms > 0:
                silence = work_dir / f"silence_{index:04d}_{pause_ms}.wav"
                self.create_silence_wav(silence, pause_ms)
                concat_items.append(silence)
        master = work_dir / "chapter_master.wav"
        await self._concatenate_wavs(ffmpeg, concat_items, work_dir / "concat.txt", master)
        await self._encode_mp3(ffmpeg, master, output_mp3)
        return master

    async def render_minimax_combined(
        self,
        *,
        ffmpeg: str,
        chapter_paths: list[Path],
        work_dir: Path,
        output_mp3: Path,
    ) -> None:
        work_dir.mkdir(parents=True, exist_ok=True)
        master = work_dir / "book_master.wav"
        await self._concatenate_wavs(
            ffmpeg,
            chapter_paths,
            work_dir / "concat.txt",
            master,
        )
        await self._encode_mp3(ffmpeg, master, output_mp3)

    async def transcode_preview(
        self, ffmpeg: str, source: Path, output_mp3: Path
    ) -> None:
        normalized = output_mp3.with_suffix(".wav")
        await self._normalize_audio(ffmpeg, source, normalized)
        await self._encode_mp3(ffmpeg, normalized, output_mp3)

    async def _normalize_audio(self, ffmpeg: str, source: Path, output: Path) -> None:
        await self._run_ffmpeg(
            ffmpeg,
            "-i",
            str(source),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar",
            "32000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output),
        )

    async def _concatenate_wavs(
        self,
        ffmpeg: str,
        paths: list[Path],
        manifest: Path,
        output: Path,
    ) -> None:
        if not paths:
            raise AudiobookValidationError("没有可拼接的语音片段")
        lines = []
        for path in paths:
            escaped = path.resolve().as_posix().replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        await self._run_ffmpeg(
            ffmpeg,
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest),
            "-ar",
            "32000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output),
        )

    async def _encode_mp3(self, ffmpeg: str, source: Path, output: Path) -> None:
        await self._run_ffmpeg(
            ffmpeg,
            "-i",
            str(source),
            "-af",
            "alimiter=limit=0.95",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(output),
        )

    @staticmethod
    async def _run_ffmpeg(ffmpeg: str, *arguments: str) -> None:
        process = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[:1500]
            raise AudiobookValidationError(f"FFmpeg 音频处理失败：{detail or '未知错误'}")

    @staticmethod
    def create_silence_wav(
        output_path: Path,
        duration_ms: int,
        sample_rate: int = 32000,
    ) -> Path:
        frame_count = int(sample_rate * duration_ms / 1000)
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"\x00\x00" * frame_count)
        return output_path

    async def query_voices(
        self,
        db: AsyncSession,
        project_id: str,
        voice_type: str = "all",
    ) -> dict[str, Any]:
        config = await self._get_config(db, project_id)
        payload = await self._call_minimax_voice_api(
            config,
            "/v1/get_voice",
            {"voice_type": voice_type},
        )
        remote_voices = self.normalize_minimax_voices(payload)
        deleted_voice_ids = {
            str(item).strip()
            for item in (config.deleted_voice_ids or [])
            if str(item).strip()
        }
        local_voices = [
            voice
            for voice in self.normalize_managed_voices(config.managed_voices or [])
            if voice["voice_id"] not in deleted_voice_ids
        ]
        if voice_type != "all":
            remote_voices = [
                voice for voice in remote_voices if voice["voice_type"] == voice_type
            ]
            local_voices = [
                voice for voice in local_voices if voice["voice_type"] == voice_type
            ]
        remote_ids = {voice["voice_id"] for voice in remote_voices}
        return {
            "voices": [
                *remote_voices,
                *(
                    voice
                    for voice in local_voices
                    if voice["voice_id"] not in remote_ids
                ),
            ]
        }

    async def design_voice(
        self,
        db: AsyncSession,
        project_id: str,
        *,
        prompt: str,
        preview_text: str,
        voice_id: str | None,
        aigc_watermark: bool,
    ) -> dict[str, Any]:
        config = await self._get_config(db, project_id)
        deleted_voice_ids = {
            str(item).strip()
            for item in (config.deleted_voice_ids or [])
            if str(item).strip()
        }
        if voice_id and voice_id in deleted_voice_ids:
            raise AudiobookValidationError(
                f"voice_id {voice_id} 已从 MiniMax 删除，平台不允许再次使用该 ID。"
                "请填写新的 voice_id，或留空让 MiniMax 自动生成。"
            )
        request_body: dict[str, Any] = {
            "prompt": prompt,
            "preview_text": preview_text,
            "aigc_watermark": aigc_watermark,
        }
        if voice_id:
            request_body["voice_id"] = voice_id
        try:
            payload = await self._call_minimax_voice_api(
                config,
                "/v1/voice_design",
                request_body,
            )
        except AudiobookVoiceServiceError as exc:
            if voice_id and "duplicate" in str(exc).casefold():
                raise AudiobookValidationError(
                    f"voice_id {voice_id} 已被 MiniMax 占用，删除后也不能复用。"
                    "请填写新的 voice_id，或留空让 MiniMax 自动生成。"
                ) from exc
            raise
        generated_voice_id = str(payload.get("voice_id", "")).strip()
        trial_audio = payload.get("trial_audio")
        if not generated_voice_id:
            raise AudiobookVoiceServiceError("MiniMax 音色设计接口未返回 voice_id")
        if not isinstance(trial_audio, str) or not trial_audio.strip():
            raise AudiobookVoiceServiceError("MiniMax 音色设计接口未返回试听音频")
        try:
            trial_audio_bytes = bytes.fromhex(trial_audio)
        except ValueError as exc:
            raise AudiobookVoiceServiceError("MiniMax 返回的试听音频不是有效的十六进制数据") from exc
        voice = {
            "voice_id": generated_voice_id,
            "voice_name": None,
            "description": [prompt],
            "created_time": datetime.now().date().isoformat(),
            "voice_type": "voice_generation",
            "is_local_only": True,
        }
        config.managed_voices = [
            voice,
            *(
                item
                for item in (config.managed_voices or [])
                if isinstance(item, dict)
                and str(item.get("voice_id", "")).strip() != generated_voice_id
            ),
        ]
        config.deleted_voice_ids = [
            item
            for item in (config.deleted_voice_ids or [])
            if str(item).strip() != generated_voice_id
        ]
        await db.commit()
        return {
            "voice": voice,
            "trial_audio_base64": base64.b64encode(trial_audio_bytes).decode("ascii"),
            "trial_audio_content_type": "audio/mpeg",
        }

    async def delete_voice(
        self,
        db: AsyncSession,
        project_id: str,
        *,
        voice_id: str,
        voice_type: str,
    ) -> dict[str, Any]:
        config = await self._get_config(db, project_id)
        payload = await self._call_minimax_voice_api(
            config,
            "/v1/delete_voice",
            {"voice_type": voice_type, "voice_id": voice_id},
        )
        config.managed_voices = [
            item
            for item in (config.managed_voices or [])
            if not isinstance(item, dict)
            or str(item.get("voice_id", "")).strip() != voice_id
        ]
        config.deleted_voice_ids = list(
            dict.fromkeys(
                [
                    *(
                        str(item).strip()
                        for item in (config.deleted_voice_ids or [])
                        if str(item).strip()
                    ),
                    voice_id,
                ]
            )
        )
        await db.commit()
        return {
            "voice_id": str(payload.get("voice_id", "")).strip() or voice_id,
            "voice_type": voice_type,
            "created_time": str(payload.get("created_time", "")).strip() or None,
        }

    async def _call_minimax_voice_api(
        self,
        config: AudiobookConfig,
        path: str,
        request_body: dict[str, Any],
    ) -> dict[str, Any]:
        if not config.api_key_encrypted:
            raise AudiobookValidationError("请先保存 MiniMax API Key")
        api_base = self._minimax_management_api_base(config.base_url)
        api_key = decrypt_api_key(config.api_key_encrypted)
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout_seconds) as client:
                response = await client.post(
                    f"{api_base}{path}",
                    json=request_body,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500].strip()
            raise AudiobookVoiceServiceError(
                f"MiniMax 音色接口返回 {exc.response.status_code}: {detail or '请求失败'}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AudiobookVoiceServiceError(f"无法连接 MiniMax 音色接口：{exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise AudiobookVoiceServiceError("MiniMax 音色接口返回了无法解析的 JSON") from exc
        if not isinstance(payload, dict):
            raise AudiobookVoiceServiceError("MiniMax 音色接口返回的数据格式不正确")
        base_resp = payload.get("base_resp") or {}
        if not isinstance(base_resp, dict):
            raise AudiobookVoiceServiceError("MiniMax 音色接口缺少 base_resp")
        status_code = base_resp.get("status_code")
        if str(status_code) != "0":
            status_msg = str(base_resp.get("status_msg", "")).strip()
            detail = status_msg or f"错误码 {status_code}"
            raise AudiobookVoiceServiceError(f"MiniMax 音色接口返回错误：{detail}")
        return payload

    @staticmethod
    def _minimax_management_api_base(base_url: str) -> str:
        hostname = (urlparse(base_url).hostname or "").lower()
        if hostname == "api.minimaxi.com" or hostname.endswith(".minimaxi.com"):
            return "https://api.minimaxi.com"
        if hostname == "api.minimax.io" or hostname.endswith(".minimax.io"):
            return "https://api.minimax.io"
        raise AudiobookValidationError(
            "音色管理仅支持 MiniMax 配置，请先保存 MiniMax TTS 服务地址"
        )

    @staticmethod
    def normalize_minimax_voices(payload: dict[str, Any]) -> list[dict[str, Any]]:
        voices: list[dict[str, Any]] = []
        seen: set[str] = set()
        for voice_type in ("system", "voice_cloning", "voice_generation"):
            raw_items = payload.get("system_voice" if voice_type == "system" else voice_type)
            if raw_items is None:
                continue
            if not isinstance(raw_items, list):
                raise AudiobookVoiceServiceError(
                    f"MiniMax 返回的 {voice_type} 音色列表格式不正确"
                )
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                voice_id = str(raw_item.get("voice_id", "")).strip()
                if not voice_id or voice_id in seen:
                    continue
                raw_description = raw_item.get("description") or []
                if isinstance(raw_description, str):
                    descriptions = [raw_description.strip()] if raw_description.strip() else []
                elif isinstance(raw_description, list):
                    descriptions = [
                        str(item).strip() for item in raw_description if str(item).strip()
                    ]
                else:
                    descriptions = []
                voice_name = str(raw_item.get("voice_name", "")).strip() or None
                created_time = str(raw_item.get("created_time", "")).strip() or None
                voices.append(
                    {
                        "voice_id": voice_id,
                        "voice_name": voice_name,
                        "description": descriptions,
                        "created_time": created_time,
                        "voice_type": voice_type,
                        "is_local_only": False,
                    }
                )
                seen.add(voice_id)
        return voices

    @staticmethod
    def normalize_managed_voices(raw_items: list[Any]) -> list[dict[str, Any]]:
        voices: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            voice_id = str(raw_item.get("voice_id", "")).strip()
            voice_type = str(raw_item.get("voice_type", "")).strip()
            if (
                not voice_id
                or voice_id in seen
                or voice_type not in {"voice_cloning", "voice_generation"}
            ):
                continue
            raw_description = raw_item.get("description") or []
            if isinstance(raw_description, str):
                descriptions = [raw_description.strip()] if raw_description.strip() else []
            elif isinstance(raw_description, list):
                descriptions = [
                    str(item).strip() for item in raw_description if str(item).strip()
                ]
            else:
                descriptions = []
            voices.append(
                {
                    "voice_id": voice_id,
                    "voice_name": str(raw_item.get("voice_name", "")).strip() or None,
                    "description": descriptions,
                    "created_time": (
                        str(raw_item.get("created_time", "")).strip() or None
                    ),
                    "voice_type": voice_type,
                    "is_local_only": True,
                }
            )
            seen.add(voice_id)
        return voices

    async def _get_or_create_speech_script(
        self,
        *,
        db: AsyncSession,
        job: AudiobookJob,
        config: AudiobookConfig,
        chapter: Chapter,
        chapter_title: str | None = None,
        characters: list[Character],
    ) -> list[SpeechSegment]:
        llm_config_id = str(job.script_llm_config_id or "").strip()
        if not llm_config_id:
            raise AudiobookValidationError("有声书任务未配置语音脚本 LLM")
        source_text = self.clean_text(chapter.content)
        input_hash = self.speech_script_request_hash(
            llm_config_id=llm_config_id,
            chapter=chapter,
            chapter_title=chapter_title,
            characters=characters,
            config=config,
        )
        scripts = copy.deepcopy(job.speech_scripts or {})
        cached = scripts.get(chapter.id)
        if isinstance(cached, dict) and cached.get("input_hash") == input_hash:
            try:
                return self.normalize_speech_script_segments(
                    {"segments": cached.get("segments")},
                    characters,
                    source_text,
                    validate_coverage=False,
                )
            except AudiobookValidationError:
                pass

        llm_config = await db.get(LLMConfig, llm_config_id)
        if not llm_config:
            raise AudiobookValidationError("语音脚本 LLM 配置已被删除")
        segments = await self.generate_speech_script(
            llm_config_id=llm_config_id,
            chapter=chapter,
            chapter_title=chapter_title,
            characters=characters,
            max_chars=config.max_chars_per_segment,
            max_output_tokens=self.speech_script_max_tokens(llm_config),
        )
        character_voices = config.character_voices or {}
        scripts[chapter.id] = {
            "input_hash": input_hash,
            "llm_config_id": llm_config_id,
            "segments": [
                {
                    "speaker_id": segment.speaker_id,
                    "voice_id": (
                        character_voices.get(segment.speaker_id or "")
                        or config.narrator_voice
                    ),
                    "text": segment.text,
                }
                for segment in segments
            ],
        }
        job.speech_scripts = scripts
        await db.commit()
        return segments

    async def generate_speech_script(
        self,
        *,
        llm_config_id: str,
        chapter: Chapter,
        chapter_title: str | None = None,
        characters: list[Character],
        max_chars: int,
        max_output_tokens: int = DEFAULT_SCRIPT_MAX_TOKENS,
    ) -> list[SpeechSegment]:
        chapter_content = self.clean_text(chapter.content)
        if not chapter_content:
            return []
        character_catalog = [
            {
                "id": character.id,
                "name": character.name,
                "aliases": character.aliases if isinstance(character.aliases, list) else [],
            }
            for character in characters
        ]
        messages = [
            {"role": "system", "content": AUDIOBOOK_SCRIPT_SYSTEM},
            {
                "role": "user",
                "content": AUDIOBOOK_SCRIPT_USER.format(
                    chapter_title=chapter_title or chapter.title or "未命名章节",
                    max_chars=max_chars,
                    characters_json=json.dumps(
                        character_catalog,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    chapter_content=chapter_content,
                ),
            },
        ]
        try:
            response = await llm_orchestrator.chat(
                llm_config_id,
                messages,
                temperature=0.1,
                max_tokens=max_output_tokens,
                **json_object_response_kwargs(),
            )
        except LLMOutputTruncatedError as exc:
            raise AudiobookValidationError(
                f"LLM 在 max_tokens={max_output_tokens} 时仍达到输出或上下文长度限制；"
                "请缩短章节内容或换用上下文更长的模型"
            ) from exc
        try:
            parsed = json.loads(self._strip_json_fence(response))
        except (json.JSONDecodeError, TypeError) as exc:
            raise AudiobookValidationError("LLM 未返回有效的语音脚本 JSON") from exc
        return self.normalize_speech_script_segments(
            parsed,
            characters,
            chapter_content,
            validate_coverage=True,
        )

    @staticmethod
    def speech_script_max_tokens(config: LLMConfig) -> int:
        hostname = (urlparse(config.base_url or "").hostname or "").lower()
        if config.provider == "deepseek" or hostname == "api.deepseek.com":
            return DEEPSEEK_SCRIPT_MAX_TOKENS
        configured = (config.default_params or {}).get("max_tokens")
        if isinstance(configured, int) and configured > 0:
            return max(configured, DEFAULT_SCRIPT_MAX_TOKENS)
        return DEFAULT_SCRIPT_MAX_TOKENS

    @classmethod
    def normalize_speech_script_segments(
        cls,
        payload: Any,
        characters: list[Character],
        source_text: str,
        *,
        validate_coverage: bool,
    ) -> list[SpeechSegment]:
        if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list):
            raise AudiobookValidationError("LLM 返回的语音脚本缺少 segments 数组")
        raw_segments = payload["segments"]
        if not raw_segments or len(raw_segments) > 1000:
            raise AudiobookValidationError("LLM 返回的语音脚本片段数量不正确")
        character_ids = {character.id for character in characters}
        segments: list[SpeechSegment] = []
        for index, raw_segment in enumerate(raw_segments):
            if not isinstance(raw_segment, dict):
                raise AudiobookValidationError(f"语音脚本第 {index + 1} 段格式不正确")
            text_value = cls.clean_text(str(raw_segment.get("text", "")))
            if not text_value:
                raise AudiobookValidationError(f"语音脚本第 {index + 1} 段文本为空")
            raw_speaker_id = raw_segment.get("speaker_id")
            speaker_id = str(raw_speaker_id).strip() if raw_speaker_id is not None else None
            if not speaker_id:
                speaker_id = None
            if speaker_id is not None and speaker_id not in character_ids:
                speaker_id = None
            segments.append(SpeechSegment(text=text_value, speaker_id=speaker_id))

        if validate_coverage:
            cls.validate_speech_script_coverage(source_text, segments)
        return segments

    @classmethod
    def validate_speech_script_coverage(
        cls,
        source_text: str,
        segments: list[SpeechSegment],
    ) -> None:
        source_length = len(re.sub(r"\s+", "", cls.clean_text(source_text)))
        output_length = sum(len(re.sub(r"\s+", "", segment.text)) for segment in segments)
        minimum_length = max(1, int(source_length * 0.5))
        maximum_length = int(source_length * 1.6) + 200
        if output_length < minimum_length:
            raise AudiobookValidationError("LLM 语音脚本疑似大幅删减了章节内容")
        if output_length > maximum_length:
            raise AudiobookValidationError("LLM 语音脚本疑似添加了过多原文外内容")

    @classmethod
    def speech_script_request_hash(
        cls,
        *,
        llm_config_id: str,
        chapter: Chapter,
        chapter_title: str | None = None,
        characters: list[Character],
        config: AudiobookConfig,
    ) -> str:
        payload = {
            "llm_config_id": llm_config_id,
            "chapter_title": chapter_title or chapter.title,
            "chapter_content": cls.clean_text(chapter.content),
            "max_chars": config.max_chars_per_segment,
            "narrator_voice": config.narrator_voice,
            "character_voices": config.character_voices or {},
            "characters": [
                {
                    "id": character.id,
                    "name": character.name,
                    "aliases": character.aliases if isinstance(character.aliases, list) else [],
                }
                for character in characters
            ],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    async def parse_api_documentation(
        self, llm_config_id: str, api_documentation: str
    ) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": AUDIOBOOK_API_DOCS_PARSE_SYSTEM},
            {
                "role": "user",
                "content": AUDIOBOOK_API_DOCS_PARSE_USER.format(
                    api_documentation=self.redact_document_secrets(api_documentation.strip())
                ),
            },
        ]
        response = await llm_orchestrator.chat(
            llm_config_id,
            messages,
            temperature=0.1,
            max_tokens=4096,
            **json_object_response_kwargs(),
        )
        try:
            parsed = json.loads(self._strip_json_fence(response))
        except (json.JSONDecodeError, TypeError) as exc:
            raise AudiobookValidationError("LLM 未返回有效的语音 API 配置 JSON") from exc
        if not isinstance(parsed, dict):
            raise AudiobookValidationError("LLM 返回的语音 API 配置格式不正确")
        return self.normalize_api_suggestion(parsed)

    async def _get_config(self, db: AsyncSession, project_id: str) -> AudiobookConfig:
        config = (
            await db.execute(
                select(AudiobookConfig).where(AudiobookConfig.project_id == project_id)
            )
        ).scalar_one_or_none()
        if not config:
            raise AudiobookValidationError("请先保存有声书服务配置")
        return config

    @staticmethod
    def validate_config(config: AudiobookConfig) -> None:
        if not config.base_url.strip():
            raise AudiobookValidationError("请填写 TTS 服务地址")
        if not config.narrator_voice.strip():
            raise AudiobookValidationError("请设置旁白声音")
        if not 1 <= config.requests_per_minute <= 120:
            raise AudiobookValidationError("每分钟最大新连接数必须在 1–120 之间")
        if config.provider == "comfyui":
            if not config.comfyui_workflow:
                raise AudiobookValidationError("请粘贴 ComfyUI API 工作流 JSON")
            workflow_text = str(config.comfyui_workflow)
            if "{{text}}" not in workflow_text:
                raise AudiobookValidationError("ComfyUI 工作流必须包含 {{text}} 占位符")
        elif config.provider in {"custom_http", "custom_websocket"}:
            if not config.custom_request:
                raise AudiobookValidationError("请先粘贴 API 文档并生成自定义请求映射")
            request_text = str(config.custom_request)
            if "{{text}}" not in request_text:
                raise AudiobookValidationError("自定义请求映射必须包含 {{text}} 占位符")
            if config.provider == "custom_http":
                method = str(config.custom_request.get("method", "POST")).upper()
                if method not in CustomHTTPTTSProvider.ALLOWED_METHODS:
                    raise AudiobookValidationError("自定义请求仅支持 GET、POST 或 PUT")
            else:
                if not config.base_url.lower().startswith(("ws://", "wss://")):
                    raise AudiobookValidationError("WebSocket TTS 服务地址必须以 ws:// 或 wss:// 开头")
                required = {"start_message", "continue_message", "response"}
                missing = sorted(required - set(config.custom_request))
                if missing:
                    raise AudiobookValidationError(
                        f"WebSocket 请求映射缺少字段：{'、'.join(missing)}"
                    )
        elif config.provider == "minimax_async":
            if not config.api_key_encrypted:
                raise AudiobookValidationError("请先保存 MiniMax API Key")
            AudiobookService._minimax_management_api_base(config.base_url)
            if not config.model_name.strip():
                raise AudiobookValidationError("请填写 MiniMax TTS 模型名称")
        elif not config.model_name.strip():
            raise AudiobookValidationError("请填写 TTS 模型名称")

    @staticmethod
    def build_provider(config: AudiobookConfig):
        if config.provider == "comfyui":
            return ComfyUITTSProvider(
                base_url=config.base_url,
                workflow=config.comfyui_workflow or {},
                timeout_seconds=config.request_timeout_seconds,
            )
        api_key = decrypt_api_key(config.api_key_encrypted) if config.api_key_encrypted else ""
        if config.provider == "custom_http":
            return CustomHTTPTTSProvider(
                endpoint_url=config.base_url,
                api_key=api_key,
                model_name=config.model_name,
                request_config=config.custom_request or {},
                timeout_seconds=config.request_timeout_seconds,
            )
        if config.provider == "custom_websocket":
            return CustomWebSocketTTSProvider(
                endpoint_url=config.base_url,
                api_key=api_key,
                model_name=config.model_name,
                request_config=config.custom_request or {},
                timeout_seconds=config.request_timeout_seconds,
                requests_per_minute=config.requests_per_minute,
            )
        if config.provider == "minimax_async":
            return MiniMaxAsyncTTSProvider(
                base_url=config.base_url,
                api_key=api_key,
                model_name=config.model_name,
                timeout_seconds=config.request_timeout_seconds,
                output_format="wav" if config.use_ffmpeg else "mp3",
            )
        return OpenAICompatibleTTSProvider(
            base_url=config.base_url,
            api_key=api_key,
            model_name=config.model_name,
            timeout_seconds=config.request_timeout_seconds,
        )

    @staticmethod
    def normalize_api_suggestion(value: dict[str, Any]) -> dict[str, Any]:
        provider = str(value.get("provider", "custom_http")).strip().lower()
        if provider not in {
            "openai_compatible",
            "custom_http",
            "custom_websocket",
            "minimax_async",
        }:
            provider = "custom_http"
        base_url = str(value.get("base_url", "")).strip().rstrip("/")
        if base_url.lower().startswith(("ws://", "wss://")):
            provider = "custom_websocket"
        if base_url.endswith("/t2a_async_v2"):
            provider = "minimax_async"
            base_url = base_url[: -len("/t2a_async_v2")]
        if provider == "openai_compatible" and base_url.endswith("/audio/speech"):
            base_url = base_url[: -len("/audio/speech")]

        custom_request = value.get("custom_request")
        legacy_requests_per_minute = None
        warnings = [
            str(item).strip() for item in (value.get("warnings") or []) if str(item).strip()
        ]
        if provider == "custom_websocket":
            warnings = [
                warning
                for warning in warnings
                if not (
                    "当前适配器" in warning
                    and ("不支持" in warning or "无法" in warning or "仅支持 HTTP" in warning)
                )
            ]
        if provider in {"custom_http", "custom_websocket"}:
            if not isinstance(custom_request, dict):
                custom_request = (
                    AudiobookService._default_websocket_request()
                    if provider == "custom_websocket"
                    else {
                        "method": "POST",
                        "headers": {"Authorization": "Bearer {{api_key}}"},
                        "query": {},
                        "body_type": "json",
                        "body": {"text": "{{text}}", "voice": "{{voice}}"},
                        "response": {"type": "binary", "path": ""},
                    }
                )
                warnings.append("LLM 未生成完整请求映射，已填入通用模板，请对照文档检查")
            else:
                custom_request = copy.deepcopy(custom_request)
                legacy_requests_per_minute = custom_request.pop(
                    "requests_per_minute", None
                )
                custom_request = AudiobookService.sanitize_request_secrets(custom_request)
                headers = custom_request.get("headers")
                if not isinstance(headers, dict):
                    headers = {}
                    custom_request["headers"] = headers
                for key, header_value in list(headers.items()):
                    header_name = str(key).lower()
                    if any(
                        marker in header_name
                        for marker in ("authorization", "api-key", "apikey", "token")
                    ):
                        prefix = "Bearer " if "bearer" in str(header_value).lower() else ""
                        headers[key] = f"{prefix}{{{{api_key}}}}"
                if provider == "custom_websocket":
                    defaults = AudiobookService._default_websocket_request()
                    missing = []
                    for key in (
                        "start_message",
                        "continue_message",
                        "finish_message",
                        "response",
                    ):
                        if key not in custom_request:
                            custom_request[key] = defaults[key]
                            missing.append(key)
                    if missing:
                        warnings.append(
                            "WebSocket 请求映射缺少 "
                            f"{'、'.join(missing)}，已按通用事件协议补全，请对照文档检查"
                        )
                else:
                    custom_request.setdefault("method", "POST")
                    custom_request.setdefault("query", {})
                    custom_request.setdefault("body_type", "json")
                    custom_request.setdefault("body", {})
                    custom_request.setdefault("response", {"type": "binary", "path": ""})
        else:
            custom_request = None

        if not base_url:
            warnings.append("未能从文档确定请求地址，请手动填写")
        return {
            "provider": provider,
            "base_url": base_url,
            "model_name": str(value.get("model_name", "")).strip(),
            "narrator_voice": str(value.get("narrator_voice", "default")).strip() or "default",
            "speed": AudiobookService._bounded_float(value.get("speed"), 1.0, 0.25, 4.0),
            "max_chars_per_segment": AudiobookService._bounded_int(
                value.get("max_chars_per_segment"),
                50_000 if provider == "minimax_async" else 800,
                100,
                50_000,
            ),
            "request_timeout_seconds": AudiobookService._bounded_int(
                value.get("request_timeout_seconds"), 180, 10, 1800
            ),
            "requests_per_minute": AudiobookService._bounded_int(
                value.get("requests_per_minute", legacy_requests_per_minute),
                20,
                1,
                120,
            ),
            "custom_request": custom_request,
            "warnings": list(dict.fromkeys(warnings)),
        }

    @staticmethod
    def _default_websocket_request() -> dict[str, Any]:
        return {
            "headers": {"Authorization": "Bearer {{api_key}}"},
            "connect_ack": {"path": "event", "equals": "connected_success"},
            "start_message": {
                "event": "task_start",
                "model": "{{model}}",
                "voice_setting": {
                    "voice_id": "{{voice}}",
                    "speed": "{{speed}}",
                    "vol": 1,
                    "pitch": 0,
                    "english_normalization": False,
                },
                "audio_setting": {
                    "sample_rate": 32000,
                    "bitrate": 128000,
                    "format": "mp3",
                    "channel": 1,
                },
            },
            "start_ack": {"path": "event", "equals": "task_started"},
            "continue_message": {"event": "task_continue", "text": "{{text}}"},
            "finish_message": {"event": "task_finish"},
            "response": {
                "audio_path": "data.audio",
                "audio_encoding": "hex",
                "final_path": "is_final",
                "final_value": True,
                "final_event_path": "event",
                "final_event_value": "task_finished",
                "failure_event_path": "event",
                "failure_event_value": "task_failed",
                "error_code_path": "base_resp.status_code",
                "success_value": 0,
                "error_message_path": "base_resp.status_msg",
            },
        }

    @staticmethod
    def redact_document_secrets(value: str) -> str:
        text = re.sub(
            r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?\s*bearer\s+)"
            r"[A-Za-z0-9._~+/=-]{8,}",
            r"\1[REDACTED]",
            value,
        )
        return re.sub(
            r"(?i)((?:x[-_])?api[-_ ]?key|access[-_ ]?token|secret[-_ ]?key)"
            r"([\"']?\s*[:=]\s*[\"']?)([^\s,\"'}]{8,})",
            r"\1\2[REDACTED]",
            text,
        )

    @staticmethod
    def sanitize_request_secrets(value: Any, field_name: str = "") -> Any:
        if isinstance(value, dict):
            return {
                key: AudiobookService.sanitize_request_secrets(item, str(key))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [AudiobookService.sanitize_request_secrets(item) for item in value]
        normalized_name = re.sub(r"[^a-z0-9]", "", field_name.lower())
        is_secret = normalized_name in {
            "authorization",
            "apikey",
            "xapikey",
            "accesstoken",
            "secretkey",
        }
        if is_secret and isinstance(value, str) and "{{api_key}}" not in value:
            prefix = "Bearer " if "bearer" in value.lower() else ""
            return f"{prefix}{{{{api_key}}}}"
        return value

    @staticmethod
    def _strip_json_fence(value: str) -> str:
        text = value.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        return text.strip()

    @staticmethod
    def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError):
            result = default
        return max(minimum, min(maximum, result))

    @staticmethod
    def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            result = default
        return max(minimum, min(maximum, result))

    async def _all_project_chapters(
        self, db: AsyncSession, project_id: str
    ) -> list[Chapter]:
        _outline, _nodes, chapter_entries = await self._project_content_structure(
            db, project_id
        )
        return [chapter for chapter, _node in chapter_entries]

    async def get_chapter_display_info(
        self, db: AsyncSession, project_id: str
    ) -> dict[str, ChapterDisplayInfo]:
        """Return current outline titles and book-wide positions for visible chapters."""
        _outline, _nodes, chapter_entries = await self._project_content_structure(
            db, project_id
        )
        return {
            chapter.id: ChapterDisplayInfo(
                title=self._chapter_display_title(chapter, node, index),
                position=index + 1,
            )
            for index, (chapter, node) in enumerate(chapter_entries)
        }

    async def _project_content_structure(
        self, db: AsyncSession, project_id: str
    ) -> tuple[Outline | None, list[OutlineNode], list[tuple[Chapter, OutlineNode]]]:
        """Return the same visible chapters and tree order used by Novel Content."""
        outline = (
            (
                await db.execute(
                    select(Outline)
                    .where(Outline.project_id == project_id)
                    .order_by(Outline.created_at, Outline.id)
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if not outline:
            return None, [], []

        nodes = list(
            (
                await db.execute(
                    select(OutlineNode).where(OutlineNode.outline_id == outline.id)
                )
            )
            .scalars()
            .all()
        )
        if not nodes:
            return outline, [], []

        node_ids = [node.id for node in nodes]
        chapters = list(
            (
                await db.execute(
                    select(Chapter)
                    .where(
                        Chapter.project_id == project_id,
                        Chapter.outline_node_id.in_(node_ids),
                    )
                    .order_by(Chapter.sort_order, Chapter.created_at, Chapter.id)
                )
            )
            .scalars()
            .all()
        )
        chapter_by_node: dict[str, Chapter] = {}
        for chapter in chapters:
            if chapter.outline_node_id:
                chapter_by_node.setdefault(chapter.outline_node_id, chapter)

        entries = [
            (chapter_by_node[node.id], node)
            for node in self._ordered_outline_nodes(nodes)
            if node.node_type == "CHAPTER" and node.id in chapter_by_node
        ]
        return outline, nodes, entries

    @staticmethod
    def _chapter_display_title(
        chapter: Chapter,
        node: OutlineNode,
        index: int,
    ) -> str:
        return (
            (node.title or "").strip()
            or (chapter.title or "").strip()
            or f"第{index + 1}章"
        )

    @staticmethod
    def _ordered_outline_nodes(nodes: list[OutlineNode]) -> list[OutlineNode]:
        """Flatten an outline in its tree order, with deterministic fallbacks."""
        children_by_parent: dict[str | None, list[OutlineNode]] = {}
        for node in nodes:
            children_by_parent.setdefault(node.parent_id, []).append(node)

        def sort_key(node: OutlineNode) -> tuple[Any, ...]:
            return node.sort_order, node.created_at, node.id

        for children in children_by_parent.values():
            children.sort(key=sort_key)

        ordered: list[OutlineNode] = []
        visited: set[str] = set()

        def visit(node: OutlineNode) -> None:
            if node.id in visited:
                return
            visited.add(node.id)
            ordered.append(node)
            for child in children_by_parent.get(node.id, []):
                visit(child)

        for root in children_by_parent.get(None, []):
            visit(root)
        for node in sorted(nodes, key=sort_key):
            visit(node)
        return ordered

    @staticmethod
    def _descendant_ids(
        node_id: str, children_by_parent: dict[str | None, list[OutlineNode]]
    ) -> set[str]:
        result: set[str] = set()
        stack = list(children_by_parent.get(node_id, []))
        while stack:
            node = stack.pop()
            if node.id in result:
                continue
            result.add(node.id)
            stack.extend(children_by_parent.get(node.id, []))
        return result

    @classmethod
    def clean_text(cls, content: str | None) -> str:
        if not content:
            return ""
        if re.search(r"<\/?[a-zA-Z][^>]*>", content):
            parser = _TextExtractor()
            parser.feed(content)
            content = parser.get_text()
        content = html.unescape(content)
        content = content.replace("\u00a0", " ").replace("\r", "")
        content = re.sub(r"[ \t]+", " ", content)
        content = re.sub(r"\n\s*\n+", "\n", content)
        return content.strip()

    @classmethod
    def split_dialogue(cls, content: str, characters: list[Character]) -> list[SpeechSegment]:
        text = cls.clean_text(content)
        if not text:
            return []
        segments: list[SpeechSegment] = []
        cursor = 0
        for match in QUOTE_PATTERN.finditer(text):
            if match.start() > cursor:
                segments.append(SpeechSegment(text[cursor : match.start()]))
            quote_text = next(value for value in match.groupdict().values() if value is not None)
            speaker_id = cls._detect_speaker(
                text[max(0, match.start() - 80) : match.start()],
                text[match.end() : match.end() + 60],
                characters,
            )
            segments.append(SpeechSegment(quote_text, speaker_id))
            cursor = match.end()
        if cursor < len(text):
            segments.append(SpeechSegment(text[cursor:]))
        return [segment for segment in segments if segment.text.strip()]

    @classmethod
    def _detect_speaker(cls, left: str, right: str, characters: list[Character]) -> str | None:
        candidates: list[tuple[int, int, str]] = []
        for name, character_id in cls._character_name_index(characters):
            escaped = re.escape(name)
            left_matches = list(
                re.finditer(
                    rf"{escaped}[^。！？\n]{{0,12}}(?:{SPEECH_VERBS})|{escaped}\s*[：:]",
                    left,
                )
            )
            if left_matches:
                distance = len(left) - left_matches[-1].end()
                candidates.append((distance, -len(name), character_id))
            right_match = re.search(
                rf"^[\s，,。.!！?？]*{escaped}[^。！？\n]{{0,12}}(?:{SPEECH_VERBS})",
                right,
            )
            if right_match:
                candidates.append((right_match.start(), -len(name), character_id))
        if not candidates:
            return None
        return min(candidates, key=lambda item: (item[0], item[1]))[2]

    @staticmethod
    def _character_name_index(characters: list[Character]) -> list[tuple[str, str]]:
        """Map every canonical name and alias to the owning character ID."""
        index: list[tuple[str, str]] = []
        for character in characters:
            aliases = character.aliases if isinstance(character.aliases, list) else []
            seen: set[str] = set()
            for raw_name in [character.name, *aliases]:
                if not isinstance(raw_name, str):
                    continue
                name = raw_name.strip()
                normalized = name.casefold()
                if not name or normalized in seen:
                    continue
                index.append((name, character.id))
                seen.add(normalized)
        return index

    @classmethod
    def build_chunks(
        cls,
        segments: list[SpeechSegment],
        character_voices: dict[str, str],
        narrator_voice: str,
        max_chars: int,
    ) -> list[tuple[str, str]]:
        merged: list[tuple[str, str]] = []
        for segment in segments:
            text = cls.clean_text(segment.text)
            if not text:
                continue
            voice = character_voices.get(segment.speaker_id or "") or narrator_voice
            if merged and merged[-1][1] == voice:
                merged[-1] = (f"{merged[-1][0]} {text}", voice)
            else:
                merged.append((text, voice))

        chunks: list[tuple[str, str]] = []
        for text, voice in merged:
            for chunk in cls._chunk_text(text, max_chars):
                chunks.append((chunk, voice))
        return chunks

    @staticmethod
    def _chunk_text(text: str, max_chars: int) -> list[str]:
        chunks = []
        remaining = text.strip()
        while len(remaining) > max_chars:
            search_start = max_chars // 2
            boundary = max(
                (
                    remaining.rfind(mark, search_start, max_chars + 1)
                    for mark in "。！？；，.!?;\n "
                ),
                default=-1,
            )
            if boundary < search_start:
                boundary = max_chars
            else:
                boundary += 1
            chunks.append(remaining[:boundary].strip())
            remaining = remaining[boundary:].strip()
        if remaining:
            chunks.append(remaining)
        return chunks

    @staticmethod
    def safe_filename(value: str | None) -> str:
        cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", (value or "有声书").strip())
        cleaned = cleaned.rstrip(". ")[:100]
        return cleaned or "有声书"

    @staticmethod
    def spoken_chapter_title(
        chapter: Chapter,
        *,
        title: str | None = None,
        position: int | None = None,
    ) -> str:
        title = (title or chapter.title or "").strip()
        if re.match(r"^第.{1,12}章(?:\s|[：:、，,.。]|$)", title):
            return title.rstrip("。") + "。"
        chapter_number = position if position is not None else chapter.sort_order + 1
        return f"第{chapter_number}章，{title or '未命名章节'}。"

    @classmethod
    def concatenate_mp3(cls, parts: list[bytes]) -> bytes:
        output = bytearray()
        for index, part in enumerate(parts):
            clean = cls._strip_id3(part, strip_leading=index > 0)
            output.extend(clean)
        return bytes(output)

    @classmethod
    def concatenate_mp3_files(cls, paths: list[Path], output_path: Path) -> None:
        with output_path.open("wb") as output:
            for index, path in enumerate(paths):
                data = path.read_bytes()
                output.write(cls._strip_id3(data, strip_leading=index > 0))

    @staticmethod
    def _strip_id3(data: bytes, *, strip_leading: bool) -> bytes:
        end = len(data) - 128 if len(data) >= 128 and data[-128:-125] == b"TAG" else len(data)
        start = 0
        if strip_leading and len(data) >= 10 and data[:3] == b"ID3":
            size = (
                (data[6] & 0x7F) << 21
                | (data[7] & 0x7F) << 14
                | (data[8] & 0x7F) << 7
                | (data[9] & 0x7F)
            )
            start = min(10 + size, end)
        return data[start:end]


audiobook_service = AudiobookService()
