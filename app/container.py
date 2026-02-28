from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings
from app.db import build_engine, build_session_factory, init_database
from app.media import FfmpegMediaProcessor
from app.providers import HttpElevenLabsTranscriptionProvider, MistralLLMProvider
from app.queueing import CeleryTaskDispatcher, TaskDispatcher
from app.services import AnalysisJobService
from app.storage import ObjectStorageClient, build_storage_client


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    session_factory: object
    storage: ObjectStorageClient
    media_processor: object
    transcription_provider: object
    llm_provider: object
    task_dispatcher: TaskDispatcher

    def create_analysis_service(self) -> AnalysisJobService:
        return AnalysisJobService(
            session_factory=self.session_factory,
            settings=self.settings,
            storage=self.storage,
            media_processor=self.media_processor,
            transcription_provider=self.transcription_provider,
            llm_provider=self.llm_provider,
            task_dispatcher=self.task_dispatcher,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_container() -> AppContainer:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    init_database(engine)
    session_factory = build_session_factory(engine)
    return AppContainer(
        settings=settings,
        session_factory=session_factory,
        storage=build_storage_client(settings),
        media_processor=FfmpegMediaProcessor(),
        transcription_provider=HttpElevenLabsTranscriptionProvider(settings),
        llm_provider=MistralLLMProvider(settings),
        task_dispatcher=CeleryTaskDispatcher(),
    )
