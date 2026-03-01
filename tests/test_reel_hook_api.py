from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import HookSuggestion, ReelScript


def _make_hooks_file(tmp_path):
    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(
        json.dumps(
            [
                {
                    "id": "hook_0001",
                    "hook_text": "This is a strong productivity hook",
                    "source_url": "https://example.com/1",
                    "page_number": 1,
                    "section": "EDUCATIONAL",
                },
                {
                    "id": "hook_0002",
                    "hook_text": "Use this hook for creator habits",
                    "source_url": "https://example.com/2",
                    "page_number": 1,
                    "section": "EDUCATIONAL",
                },
                {
                    "id": "hook_0003",
                    "hook_text": "A day in the life angle",
                    "source_url": "https://example.com/3",
                    "page_number": 1,
                    "section": "DAY IN THE LIFE",
                },
                {
                    "id": "hook_0004",
                    "hook_text": "Three mistakes creators make",
                    "source_url": "https://example.com/4",
                    "page_number": 1,
                    "section": "EDUCATIONAL",
                },
            ]
        ),
        encoding="utf-8",
    )
    return hooks_path


def _settings(hooks_path) -> Settings:
    return Settings(
        database_url="sqlite+pysqlite:///./reel-hook-api-test.db",
        task_execution_mode="inline",
        storage_backend="local",
        local_storage_path=".local-storage",
        mistral_api_key="test-mistral-key",
        hooks_catalog_path=str(hooks_path),
    )


def test_suggest_hooks_returns_suggestions(monkeypatch, tmp_path):
    hooks_path = _make_hooks_file(tmp_path)
    monkeypatch.setattr("app.api.reel_routes.get_settings", lambda: _settings(hooks_path))

    def fake_suggest(self, rough_idea, candidates, limit=4):
        return [
            HookSuggestion(
                id=candidate.id,
                hook_text=candidate.hook_text,
                reason="Fits the idea.",
                section=candidate.section,
                source_url=candidate.source_url,
            )
            for candidate in candidates[:limit]
        ]

    monkeypatch.setattr("app.api.reel_routes.MistralReelScriptProvider.suggest_hooks", fake_suggest)

    with TestClient(create_app()) as client:
        response = client.post("/v1/reel/suggest-hooks", json={"rough_idea": "creator productivity"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["suggestions"]) == 4
    assert body["suggestions"][0]["id"] == "hook_0001"


def test_reel_generator_ui_includes_dictation_controls():
    with TestClient(create_app()) as client:
        response = client.get("/reel-generator")

    assert response.status_code == 200
    html = response.text
    assert 'id="roughIdeaDictationBtn"' in html
    assert 'id="dictationStatus"' in html
    assert "Export Timeline to Premiere Pro" in html
    assert 'id="downloadCaptionsOverlay"' in html
    assert 'id="reelPreviewToggleBtn"' in html
    assert 'id="reelPreviewTime"' in html
    assert "Prepare B-roll + Captions" in html
    assert "window.SpeechRecognition || window.webkitSpeechRecognition" in html
    assert "Speech dictation is not available in this browser." in html


def test_generate_script_requires_selected_hook_id(monkeypatch, tmp_path):
    hooks_path = _make_hooks_file(tmp_path)
    monkeypatch.setattr("app.api.reel_routes.get_settings", lambda: _settings(hooks_path))

    with TestClient(create_app()) as client:
        response = client.post("/v1/reel/generate-script", json={"rough_idea": "creator productivity"})

    assert response.status_code == 400
    assert response.json()["error"] == "selected_hook_id is required"


def test_generate_script_uses_selected_hook(monkeypatch, tmp_path):
    hooks_path = _make_hooks_file(tmp_path)
    monkeypatch.setattr("app.api.reel_routes.get_settings", lambda: _settings(hooks_path))

    def fake_generate(self, rough_idea, selected_hook, clip_count, style_notes=None):
        assert selected_hook.id == "hook_0002"
        return ReelScript(
            hook="Custom hook",
            body=["Beat 1"],
            cta="CTA",
            full_narration="Custom hook Beat 1 CTA",
            hashtags=["#test"],
        )

    monkeypatch.setattr("app.api.reel_routes.MistralReelScriptProvider.generate_reel_script", fake_generate)

    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/reel/generate-script",
            json={
                "rough_idea": "creator productivity",
                "selected_hook_id": "hook_0002",
                "clip_count": 1,
            },
        )

    assert response.status_code == 200
    assert response.json()["hook"] == "Custom hook"
