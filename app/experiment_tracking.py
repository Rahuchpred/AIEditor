from __future__ import annotations

import logging

from app.config import Settings
from app.schemas import ReelScript

logger = logging.getLogger(__name__)

_PROMPT_VERSION = "reel-script-v1"


def log_reel_prompt_experiment(
    settings: Settings,
    rough_idea: str,
    clip_count: int,
    prompt: str,
    *,
    result: ReelScript | None = None,
    error: str | None = None,
) -> None:
    if not settings.wandb_log_reel_prompts or not settings.wandb_project:
        return

    try:
        import wandb
    except ImportError:
        logger.warning("W&B logging requested but wandb is not installed")
        return

    try:
        if settings.wandb_api_key:
            wandb.login(key=settings.wandb_api_key)

        with wandb.init(
            project=settings.wandb_project,
            entity=settings.wandb_entity,
            job_type="reel-script",
            reinit="finish_previous",
            config={
                "prompt_version": _PROMPT_VERSION,
                "llm_provider": "mistral",
                "model": settings.mistral_model,
                "clip_count": clip_count,
            },
        ) as run:
            if run is None:
                return
            run.summary["rough_idea"] = rough_idea
            run.summary["prompt_text"] = prompt
            run.summary["request_succeeded"] = error is None

            metrics = {
                "prompt_chars": len(prompt),
                "rough_idea_chars": len(rough_idea),
                "request_succeeded": 1 if error is None else 0,
            }
            if result is not None:
                metrics.update(
                    {
                        "body_segments": len(result.body),
                        "hashtags_count": len(result.hashtags),
                        "hook_chars": len(result.hook),
                        "full_narration_chars": len(result.full_narration),
                    }
                )
                run.summary["generated_hook"] = result.hook
                run.summary["generated_body"] = result.body
                run.summary["generated_cta"] = result.cta
                run.summary["generated_full_narration"] = result.full_narration
                run.summary["generated_hashtags"] = result.hashtags
            if error is not None:
                run.summary["error"] = error
            run.log(metrics)
    except Exception:
        logger.exception("Failed to log reel prompt experiment to W&B")
