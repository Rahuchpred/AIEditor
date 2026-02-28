from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from app.constants import (
    DEFAULT_TIPS_COUNT,
    ErrorCode,
    JobStatus,
    PRESET_STYLES,
    StyleMode,
    SUPPORTED_MEDIA_TYPES,
)
from app.errors import ServiceError
from app.models import AnalysisJob, utc_now
from app.providers import (
    LLMProvider,
    LLMProviderError,
    LLMTimeoutError,
    TranscriptionProvider,
    TranscriptionProviderError,
)
from app.schemas import (
    AnalysisJobAccepted,
    AnalysisJobResult,
    AnalysisJobStatus,
    CorrectedCaptions,
    ProcessingMetrics,
    ResultInputMetadata,
    TimedTextSegment,
    TranscriptPayload,
    TranscriptionResult,
)


class AnalysisJobService:
    def __init__(
        self,
        session_factory,
        settings,
        storage,
        media_processor,
        transcription_provider: TranscriptionProvider,
        llm_provider: LLMProvider,
        task_dispatcher,
    ):
        self._session_factory = session_factory
        self._settings = settings
        self._storage = storage
        self._media_processor = media_processor
        self._transcription_provider = transcription_provider
        self._llm_provider = llm_provider
        self._task_dispatcher = task_dispatcher

    def create_job(
        self,
        upload_file,
        style_mode: str,
        style_value: str,
        input_language_hint: str | None = None,
        include_raw_transcript: bool = True,
        include_timestamps: bool = True,
    ) -> AnalysisJobAccepted:
        normalized_style_mode = self._validate_style(style_mode, style_value)
        content_type = upload_file.content_type or ""
        if content_type not in SUPPORTED_MEDIA_TYPES:
            raise ServiceError(
                code=ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                message=f"Unsupported content type: {content_type}",
                status_code=415,
            )

        temp_path = self._persist_upload_to_temp(upload_file)
        try:
            media_info = self._media_processor.inspect(temp_path, content_type)
            if media_info.duration_seconds > self._settings.media_max_duration_seconds:
                raise ServiceError(
                    code=ErrorCode.DURATION_LIMIT_EXCEEDED,
                    message="Uploaded media exceeds the 15-minute limit",
                    status_code=400,
                )

            job_id = str(uuid4())
            suffix = temp_path.suffix or self._default_suffix(content_type)
            input_storage_key = f"jobs/{job_id}/input{suffix}"
            self._storage.put_file(input_storage_key, temp_path)

            with self._session_factory() as session:
                session.add(
                    AnalysisJob(
                        id=job_id,
                        status=JobStatus.QUEUED,
                        media_type=media_info.media_type,
                        input_storage_key=input_storage_key,
                        style_mode=normalized_style_mode,
                        style_value=style_value.strip(),
                        input_language_hint=input_language_hint,
                        duration_seconds=media_info.duration_seconds,
                        include_raw_transcript=include_raw_transcript,
                        include_timestamps=include_timestamps,
                    )
                )
                session.commit()
        finally:
            temp_path.unlink(missing_ok=True)

        if self._settings.task_execution_mode == "inline":
            self.process_job(job_id)
        else:
            self._task_dispatcher.enqueue(job_id)
        return AnalysisJobAccepted(
            job_id=job_id,
            status=self.get_status(job_id).status,
            status_url=f"/v1/analysis-jobs/{job_id}",
            result_url=f"/v1/analysis-jobs/{job_id}/result",
        )

    def get_status(self, job_id: str) -> AnalysisJobStatus:
        with self._session_factory() as session:
            job = self._load_job(session, job_id)
            return AnalysisJobStatus(
                job_id=job.id,
                status=job.status,
                created_at=job.created_at.isoformat(),
                updated_at=job.updated_at.isoformat(),
                error_code=job.error_code,
                error_message=job.error_message,
            )

    def get_result(self, job_id: str) -> AnalysisJobResult:
        with self._session_factory() as session:
            job = self._load_job(session, job_id)
            if job.status != JobStatus.SUCCEEDED or not job.result_storage_key:
                raise ServiceError(
                    code=ErrorCode.RESULT_NOT_READY,
                    message="Result is not ready",
                    status_code=404,
                )
            payload = self._storage.get_bytes(job.result_storage_key)
            return AnalysisJobResult.model_validate_json(payload)

    def process_job(self, job_id: str) -> None:
        started_at = time.perf_counter()
        with self._session_factory() as session:
            job = self._load_job(session, job_id)
            if job.status == JobStatus.SUCCEEDED:
                return
            job.status = JobStatus.PROCESSING
            job.error_code = None
            job.error_message = None
            job.updated_at = utc_now()
            session.commit()

            input_suffix = Path(job.input_storage_key).suffix or ".bin"
            with tempfile.NamedTemporaryFile(delete=False, suffix=input_suffix) as input_handle:
                input_path = Path(input_handle.name)
                input_handle.write(self._storage.get_bytes(job.input_storage_key))

            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as audio_handle:
                normalized_audio_path = Path(audio_handle.name)

            try:
                self._media_processor.normalize_to_wav(input_path, normalized_audio_path)
                normalized_audio_storage_key = f"jobs/{job.id}/normalized.wav"
                self._storage.put_file(normalized_audio_storage_key, normalized_audio_path)
                job.normalized_audio_storage_key = normalized_audio_storage_key
                job.updated_at = utc_now()
                session.commit()

                transcription_started = time.perf_counter()
                transcription = self._transcription_provider.transcribe(
                    normalized_audio_path,
                    job.input_language_hint,
                )
                transcription_ms = int((time.perf_counter() - transcription_started) * 1000)
                job.detected_language = transcription.language_detected
                job.updated_at = utc_now()
                session.commit()

                llm_started = time.perf_counter()
                corrected_captions = self._llm_provider.clean_captions(
                    transcription=transcription,
                    include_timestamps=job.include_timestamps,
                )
                rewrite_primary = self._llm_provider.rewrite_primary(
                    corrected_captions.full_text,
                    job.style_value,
                )
                speaking_tips = self._llm_provider.speaking_tips(
                    corrected_captions.full_text,
                    job.style_value,
                )
                llm_ms = int((time.perf_counter() - llm_started) * 1000)

                if len(speaking_tips) != DEFAULT_TIPS_COUNT:
                    raise LLMProviderError("LLM provider returned an invalid number of tips")

                total_ms = int((time.perf_counter() - started_at) * 1000)
                result = self._build_result(job, transcription, corrected_captions, rewrite_primary, speaking_tips, transcription_ms, llm_ms, total_ms)
                result_storage_key = f"jobs/{job.id}/result.json"
                self._storage.put_bytes(
                    result_storage_key,
                    result.model_dump_json(indent=2).encode("utf-8"),
                )

                job.result_storage_key = result_storage_key
                job.status = JobStatus.SUCCEEDED
                job.error_code = None
                job.error_message = None
                job.updated_at = utc_now()
                session.commit()
            except TranscriptionProviderError as exc:
                self._mark_failed(session, job, ErrorCode.TRANSCRIPTION_FAILED, str(exc))
            except LLMTimeoutError as exc:
                self._mark_failed(session, job, ErrorCode.LLM_TIMEOUT, str(exc))
            except LLMProviderError as exc:
                self._mark_failed(session, job, ErrorCode.LLM_PROVIDER_ERROR, str(exc))
            finally:
                input_path.unlink(missing_ok=True)
                normalized_audio_path.unlink(missing_ok=True)

    def _build_result(
        self,
        job: AnalysisJob,
        transcription: TranscriptionResult,
        corrected_captions: CorrectedCaptions,
        rewrite_primary: str,
        speaking_tips: list[str],
        transcription_ms: int,
        llm_ms: int,
        total_ms: int,
    ) -> AnalysisJobResult:
        transcript_payload = None
        if job.include_raw_transcript:
            transcript_payload = TranscriptPayload(
                language_detected=transcription.language_detected,
                segments=self._apply_timestamp_preference(transcription.segments, job.include_timestamps),
            )

        return AnalysisJobResult(
            job_id=job.id,
            input=ResultInputMetadata(
                media_type=job.media_type,
                duration_seconds=job.duration_seconds,
                style_mode=job.style_mode,
                style_value=job.style_value,
            ),
            transcript_raw=transcript_payload,
            captions_corrected_en=CorrectedCaptions(
                segments=self._apply_timestamp_preference(corrected_captions.segments, job.include_timestamps),
                full_text=corrected_captions.full_text,
            ),
            rewrite_primary_en=rewrite_primary,
            speaking_tips_en=speaking_tips,
            processing_metrics=ProcessingMetrics(
                transcription_provider="elevenlabs",
                llm_provider="mistral",
                transcription_ms=transcription_ms,
                llm_ms=llm_ms,
                total_ms=total_ms,
            ),
        )

    def _apply_timestamp_preference(self, segments: list[TimedTextSegment], include_timestamps: bool) -> list[TimedTextSegment]:
        return [
            TimedTextSegment(
                start_ms=segment.start_ms if include_timestamps else None,
                end_ms=segment.end_ms if include_timestamps else None,
                text=segment.text,
            )
            for segment in segments
        ]

    def _load_job(self, session, job_id: str) -> AnalysisJob:
        job = session.get(AnalysisJob, job_id)
        if job is None:
            raise ServiceError(
                code=ErrorCode.JOB_NOT_FOUND,
                message=f"Analysis job {job_id} does not exist",
                status_code=404,
            )
        return job

    def _mark_failed(self, session, job: AnalysisJob, code: ErrorCode, message: str) -> None:
        job.status = JobStatus.FAILED
        job.error_code = code
        job.error_message = message[:255]
        job.updated_at = utc_now()
        session.commit()

    def _validate_style(self, style_mode: str, style_value: str) -> str:
        if style_mode not in {StyleMode.PRESET, StyleMode.CUSTOM}:
            raise ServiceError(
                code=ErrorCode.INVALID_STYLE_VALUE,
                message="style_mode must be 'preset' or 'custom'",
                status_code=400,
            )

        stripped_value = style_value.strip()
        if not stripped_value:
            raise ServiceError(
                code=ErrorCode.INVALID_STYLE_VALUE,
                message="style_value is required",
                status_code=400,
            )

        if style_mode == StyleMode.PRESET and stripped_value not in PRESET_STYLES:
            raise ServiceError(
                code=ErrorCode.INVALID_STYLE_VALUE,
                message="Invalid preset style",
                status_code=400,
            )

        if style_mode == StyleMode.CUSTOM and len(stripped_value) > 80:
            raise ServiceError(
                code=ErrorCode.INVALID_STYLE_VALUE,
                message="Custom style values must be 80 characters or fewer",
                status_code=400,
            )

        return str(style_mode)

    def _persist_upload_to_temp(self, upload_file) -> Path:
        original_suffix = Path(upload_file.filename or "").suffix or self._default_suffix(upload_file.content_type or "")
        with tempfile.NamedTemporaryFile(delete=False, suffix=original_suffix) as handle:
            temp_path = Path(handle.name)
            total_bytes = 0
            while True:
                chunk = upload_file.file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > self._settings.media_max_bytes:
                    handle.close()
                    temp_path.unlink(missing_ok=True)
                    raise ServiceError(
                        code=ErrorCode.FILE_TOO_LARGE,
                        message="Uploaded media exceeds the 200 MB limit",
                        status_code=413,
                    )
                handle.write(chunk)
        return temp_path

    def _default_suffix(self, content_type: str) -> str:
        if content_type == "audio/wav":
            return ".wav"
        if content_type == "audio/mpeg":
            return ".mp3"
        if content_type == "audio/x-m4a":
            return ".m4a"
        if content_type == "audio/mp4":
            return ".mp4"
        if content_type == "video/quicktime":
            return ".mov"
        if content_type == "video/webm":
            return ".webm"
        return ".mp4"
