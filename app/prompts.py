from __future__ import annotations

import json

from app.schemas import TranscriptionResult


def build_caption_cleanup_prompt(transcription: TranscriptionResult, include_timestamps: bool) -> str:
    transcript_json = json.dumps(transcription.model_dump(mode="json"), ensure_ascii=True)
    return (
        "You are rewriting speech-to-text output into concise, natural English captions. "
        "Preserve meaning, remove filler unless meaning depends on it, improve grammar and punctuation, "
        "and do not invent facts. Return strict JSON with keys 'segments' and 'full_text'. "
        "Each segment must contain 'text' and may include 'start_ms' and 'end_ms'. "
        f"If timestamps are disabled, set both values to null. Input transcript JSON: {transcript_json}"
    )


def build_rewrite_prompt(corrected_text: str, style_value: str) -> str:
    return (
        "Rewrite the following English text in exactly one concise English version. "
        "Preserve meaning, do not add new facts, and broadly mimic the requested style without impersonation claims. "
        f"Requested style: {style_value!r}. Text: {corrected_text!r}"
    )


def build_tips_prompt(corrected_text: str, style_value: str) -> str:
    return (
        "Produce exactly three short English speaking tips as a JSON array of strings. "
        "Focus on wording, clarity, sentence shape, and tone relative to the requested style. "
        f"Requested style: {style_value!r}. Text: {corrected_text!r}"
    )
