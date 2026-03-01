from __future__ import annotations

from app.hook_extraction import extract_hooks_from_pages


def test_extracts_simple_hook_and_url_pair():
    records = extract_hooks_from_pages(
        [
            "\n".join(
                [
                    "1000 VIRAL HOOKS",
                    "EDUCATIONAL",
                    "This is a hook.",
                    "https://www.instagram.com/p/ABC123/?utm_source=ig_web_copy_link&igsh=123",
                ]
            )
        ]
    )

    assert len(records) == 1
    assert records[0].hook_text == "This is a hook"
    assert records[0].source_url == "https://www.instagram.com/p/ABC123/"
    assert records[0].page_number == 1
    assert records[0].section == "EDUCATIONAL"


def test_extracts_inline_hook_url_and_following_hook():
    records = extract_hooks_from_pages(
        [
            "\n".join(
                [
                    "First hook https://www.instagram.com/reel/AAA111/ Second hook starts here",
                    "https://www.instagram.com/reel/BBB222/?igsh=foo",
                ]
            )
        ]
    )

    assert [record.hook_text for record in records] == ["First hook", "Second hook starts here"]
    assert [record.source_url for record in records] == [
        "https://www.instagram.com/reel/AAA111/",
        "https://www.instagram.com/reel/BBB222/",
    ]


def test_reconstructs_url_query_fragment_on_next_line():
    records = extract_hooks_from_pages(
        [
            "\n".join(
                [
                    "A useful hook",
                    "https://www.instagram.com/reel/CCC333/?igs",
                    "h=tracking",
                ]
            )
        ]
    )

    assert len(records) == 1
    assert records[0].hook_text == "A useful hook"
    assert records[0].source_url == "https://www.instagram.com/reel/CCC333/"


def test_merges_hook_text_across_page_boundary():
    records = extract_hooks_from_pages(
        [
            "If you're a creator and you want",
            "\n".join(
                [
                    "better results in 30 days, listen to this video.",
                    "https://www.instagram.com/p/DDD444/",
                ]
            ),
        ]
    )

    assert len(records) == 1
    assert records[0].hook_text == "If you're a creator and you want better results in 30 days, listen to this video"
    assert records[0].page_number == 1


def test_deduplicates_same_hook_and_same_url():
    records = extract_hooks_from_pages(
        [
            "\n".join(
                [
                    "Repeat me",
                    "https://www.instagram.com/p/EEE555/",
                    "Repeat me",
                    "https://www.instagram.com/p/EEE555/",
                ]
            )
        ]
    )

    assert len(records) == 1
    assert records[0].id == "hook_0001"
