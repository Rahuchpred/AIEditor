from __future__ import annotations

from app.hook_extraction import extract_hooks_from_pages


def test_strips_inspo_hook_label_from_text():
    records = extract_hooks_from_pages(
        [
            "\n".join(
                [
                    "EDUCATIONAL",
                    "INSPO HOOK: This represents your X before, during, and after X",
                    "https://www.instagram.com/p/C-ta_pvhfvK/",
                ]
            )
        ]
    )

    assert len(records) == 1
    assert records[0].hook_text == "This represents your X before, during, and after X"
