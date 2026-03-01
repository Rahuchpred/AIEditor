from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from app.schemas import HookTemplate


class HookCatalogError(RuntimeError):
    pass


_TOKEN_PATTERN = re.compile(r"[a-z0-9']+")


class HookCatalogService:
    def __init__(self, hooks: list[HookTemplate], source_path: Path):
        self._hooks = hooks
        self._source_path = source_path
        self._by_id = {hook.id: hook for hook in hooks}

    @classmethod
    def from_path(cls, catalog_path: Path | str) -> "HookCatalogService":
        path = Path(catalog_path)
        if not path.exists():
            raise HookCatalogError(f"Hook catalog not found: {path}")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HookCatalogError(f"Hook catalog is not valid JSON: {path}") from exc
        except OSError as exc:
            raise HookCatalogError(f"Hook catalog could not be read: {path}") from exc

        if not isinstance(payload, list):
            raise HookCatalogError("Hook catalog must be a JSON array")

        hooks: list[HookTemplate] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(payload):
            try:
                hook = HookTemplate.model_validate(item)
            except Exception as exc:
                raise HookCatalogError(f"Invalid hook record at index {index}") from exc
            if hook.id in seen_ids:
                raise HookCatalogError(f"Duplicate hook id in catalog: {hook.id}")
            seen_ids.add(hook.id)
            hooks.append(hook)

        if not hooks:
            raise HookCatalogError("Hook catalog is empty")

        return cls(hooks, path)

    def all_hooks(self) -> list[HookTemplate]:
        return list(self._hooks)

    def get_hook(self, hook_id: str) -> HookTemplate | None:
        return self._by_id.get(hook_id)

    def shortlist(self, rough_idea: str, limit: int = 30) -> list[HookTemplate]:
        requested_limit = max(1, limit)
        rough_tokens = _tokenize(rough_idea)
        rough_counts = Counter(rough_tokens)
        rough_phrases = _phrases(rough_tokens)

        scored: list[tuple[float, int, HookTemplate]] = []
        for index, hook in enumerate(self._hooks):
            score = _score_hook(hook, rough_counts, rough_phrases)
            scored.append((score, index, hook))

        ranked = sorted(scored, key=lambda item: (-item[0], item[1]))
        positive = [hook for score, _, hook in ranked if score > 0]
        if len(positive) >= requested_limit:
            return positive[:requested_limit]

        fallback = positive[:]
        for _score, _index, hook in ranked:
            if hook in fallback:
                continue
            fallback.append(hook)
            if len(fallback) >= requested_limit:
                break
        return fallback


@lru_cache(maxsize=8)
def get_hook_catalog_service(catalog_path: str) -> HookCatalogService:
    return HookCatalogService.from_path(catalog_path)


def _tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN_PATTERN.findall(text.lower()) if len(token) > 2]


def _phrases(tokens: list[str]) -> list[str]:
    phrases: list[str] = []
    for size in (3, 2):
        for index in range(0, len(tokens) - size + 1):
            phrases.append(" ".join(tokens[index:index + size]))
    return phrases


def _score_hook(hook: HookTemplate, rough_counts: Counter[str], rough_phrases: list[str]) -> float:
    hook_tokens = _tokenize(hook.hook_text)
    hook_counts = Counter(hook_tokens)
    shared_tokens = set(rough_counts).intersection(hook_counts)
    overlap = sum(min(rough_counts[token], hook_counts[token]) for token in shared_tokens)
    repeated_bonus = sum(
        (rough_counts[token] - 1) + (hook_counts[token] - 1)
        for token in shared_tokens
        if rough_counts[token] > 1 or hook_counts[token] > 1
    )

    normalized_hook_text = " ".join(hook_tokens)
    phrase_bonus = 0.0
    for phrase in rough_phrases:
        if phrase and phrase in normalized_hook_text:
            phrase_bonus += 1.5

    section_bonus = 0.0
    if hook.section:
        section_tokens = set(_tokenize(hook.section))
        section_bonus = 0.5 * len(section_tokens.intersection(rough_counts))

    return float(overlap) + (0.25 * repeated_bonus) + phrase_bonus + section_bonus
