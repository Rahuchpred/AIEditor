"""Prompt templates for viral Instagram reel script generation."""

from __future__ import annotations

import json

from app.schemas import HookTemplate


def build_hook_suggestion_prompt(rough_idea: str, candidates: list[HookTemplate], limit: int) -> str:
    """Build the Mistral prompt for selecting the best hook options."""
    candidates_json = json.dumps(
        [
            {
                "id": candidate.id,
                "hook_text": candidate.hook_text,
                "section": candidate.section,
            }
            for candidate in candidates
        ],
        ensure_ascii=True,
    )
    return f"""You are selecting the best existing hook templates for a short-form Instagram Reel.

Do not write new hooks. Choose only from the provided candidates.

**User's rough idea/topic:**
{rough_idea}

**Candidate hooks (JSON array):**
{candidates_json}

Select exactly {limit} hooks that best match the user's idea.

**Selection criteria:**
- Strong semantic fit with the user's idea
- High first-3-seconds attention potential
- Diverse options, not near-duplicates
- Easy to build a strong reel around

Return valid JSON only with this exact structure:
{{
  "suggestions": [
    {{
      "id": "<candidate id>",
      "reason": "<one short sentence explaining the fit>"
    }}
  ]
}}

**Rules:**
- Return exactly {limit} suggestions when enough candidates are provided
- Use only candidate IDs from the provided JSON
- Do not rewrite hook text
- No markdown, no code fences, no extra text
"""


def build_style_analysis_prompt(transcript: str) -> str:
    """Build the Mistral prompt for analyzing a transcript's script style."""
    return f"""Analyze the **style** of the following transcript. Describe its tone, pacing, sentence structure, energy level, rhetorical devices, vocabulary level, and transitions.

**Rules:**
- Do NOT summarize the content or topic of the transcript
- Do NOT quote any words or phrases from the transcript
- Focus only on stylistic qualities that could be applied to a completely different topic
- Return valid JSON only, no markdown or extra text

**Transcript:**
{transcript}

Return a JSON object with this exact structure:
{{
  "style_notes": "<a concise paragraph describing the style>"
}}"""


def build_reel_script_prompt(
    rough_idea: str,
    selected_hook_text: str,
    clip_count: int,
    selected_hook_section: str | None = None,
    style_notes: str | None = None,
) -> str:
    """Build the Mistral prompt for generating a viral reel script."""
    section_line = f"\n**Selected hook section/category:** {selected_hook_section}\n" if selected_hook_section else "\n"
    style_block = ""
    if style_notes:
        style_block = f"""
**Style reference (match this style, but do NOT copy any words from the example):**
{style_notes}
"""
    return f"""You are an expert Instagram Reels content strategist. Create a viral-style script for an Instagram Reel.
{style_block}

**Selected hook chosen by the user:**
{selected_hook_text}
{section_line}
**User's rough idea/topic:**
{rough_idea}

**Number of B-roll video clips (in consecutive order):** {clip_count}
Each clip will be auto-cut to 5-7 seconds. Write exactly {clip_count} body segments so each segment matches one clip.

**Script structure for viral Reels:**
1. **Hook** (1-2 sentences): Use the selected hook as the opening angle. You may tighten the wording, but keep the same core strategy and intent.
2. **Body** (list of {clip_count} segments): Each segment is 1-2 sentences, ~5-7 seconds when spoken. Deliver value, tips, or story beats. Match pacing to B-roll.
3. **CTA** (1-2 sentences): Clear call-to-action. Save, follow, comment, or share.
4. **Hashtags**: 5-8 relevant, high-engagement hashtags for discoverability.

**Rules:**
- Write in a conversational, energetic tone
- Keep sentences short and punchy
- No filler words (um, uh, like)
- Build the script around the selected hook and the user's rough idea
- full_narration must be the exact concatenated script for text-to-speech (hook + body segments + cta, no hashtags)
- Return valid JSON only, no markdown or extra text

Return a JSON object with this exact structure:
{{
  "hook": "<attention-grabbing opening>",
  "body": ["<segment 1>", "<segment 2>", ...],
  "cta": "<call-to-action closing>",
  "full_narration": "<complete script for TTS: hook + all body segments + cta>",
  "hashtags": ["#hashtag1", "#hashtag2", ...]
}}"""
