from __future__ import annotations

import httpx

from app.config import Settings
from app.hook_catalog import HookCatalogService
from app.providers import MistralReelScriptProvider
from app.schemas import HookTemplate


class FakeHttpClient:
    def __init__(self, responses):
        self._responses = list(responses)

    def post(self, *_args, **_kwargs):
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _json_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        request=httpx.Request("POST", "https://example.com"),
        json=payload,
    )


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+pysqlite:///./providers-test.db",
        task_execution_mode="inline",
        storage_backend="local",
        local_storage_path=".local-storage",
        mistral_api_key="test-mistral-key",
    )


def test_hook_catalog_shortlist_prefers_overlap(tmp_path):
    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(
        """[
          {"id":"hook_1","hook_text":"5 productivity habits for creators","source_url":null,"page_number":1,"section":"EDUCATIONAL"},
          {"id":"hook_2","hook_text":"Day in the life of a millionaire","source_url":null,"page_number":1,"section":"DAY IN THE LIFE"},
          {"id":"hook_3","hook_text":"Three creator habits you should copy","source_url":null,"page_number":1,"section":"EDUCATIONAL"}
        ]""",
        encoding="utf-8",
    )

    catalog = HookCatalogService.from_path(hooks_path)
    shortlist = catalog.shortlist("productivity habits for creators", limit=2)

    assert [hook.id for hook in shortlist] == ["hook_1", "hook_3"]


def test_suggest_hooks_ignores_unknown_ids_and_backfills():
    provider = MistralReelScriptProvider(_settings())
    provider._client = FakeHttpClient(
        [
            _json_response(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"suggestions":[{"id":"hook_2","reason":"Exact fit"},{"id":"unknown","reason":"bad"}]}'
                            }
                        }
                    ]
                }
            )
        ]
    )
    candidates = [
        HookTemplate(id="hook_1", hook_text="Strong hook one", source_url=None, page_number=1, section="EDUCATIONAL"),
        HookTemplate(id="hook_2", hook_text="Strong hook two", source_url=None, page_number=1, section="EDUCATIONAL"),
        HookTemplate(id="hook_3", hook_text="Strong hook three", source_url=None, page_number=1, section="EDUCATIONAL"),
    ]

    suggestions = provider.suggest_hooks("productivity how-to", candidates, limit=2)

    assert len(suggestions) == 2
    assert suggestions[0].id == "hook_2"
    assert suggestions[1].id in {"hook_1", "hook_3"}


def test_generate_reel_script_uses_selected_hook_text():
    provider = MistralReelScriptProvider(_settings())
    captured: dict[str, str] = {}

    def fake_chat_json(prompt, **_kwargs):
        captured["prompt"] = prompt
        return {
            "hook": "Hook",
            "body": ["Beat 1"],
            "cta": "CTA",
            "full_narration": "Hook Beat 1 CTA",
            "hashtags": ["#test"],
        }

    provider._chat_json = fake_chat_json  # type: ignore[method-assign]
    hook = HookTemplate(
        id="hook_9",
        hook_text="This is the selected hook",
        source_url=None,
        page_number=1,
        section="EDUCATIONAL",
    )

    result = provider.generate_reel_script("show a before and after", hook, 1)

    assert result.hook == "Hook"
    assert hook.hook_text in captured["prompt"]
