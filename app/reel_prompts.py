"""Prompt templates for viral Instagram reel script generation."""

from __future__ import annotations


def build_reel_script_prompt(rough_idea: str, clip_count: int) -> str:
    """Build the Mistral prompt for generating a viral reel script."""
    return f"""You are an expert Instagram Reels content strategist. Create a viral-style script for an Instagram Reel.

**User's rough idea/topic:**
{rough_idea}

**Number of B-roll video clips (in consecutive order):** {clip_count}
Each clip will be auto-cut to 5-7 seconds. Write exactly {clip_count} body segments so each segment matches one clip.

**Script structure for viral Reels:**
1. **Hook** (1-2 sentences): Grab attention in the first 3 seconds. Use a bold claim, question, or surprising statement. No fluff.
2. **Body** (list of {clip_count} segments): Each segment is 1-2 sentences, ~5-7 seconds when spoken. Deliver value, tips, or story beats. Match pacing to B-roll.
3. **CTA** (1-2 sentences): Clear call-to-action. Save, follow, comment, or share.
4. **Hashtags**: 5-8 relevant, high-engagement hashtags for discoverability.

**Rules:**
- Write in a conversational, energetic tone
- Keep sentences short and punchy
- No filler words (um, uh, like)
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
