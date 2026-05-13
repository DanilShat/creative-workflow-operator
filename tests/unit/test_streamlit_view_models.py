from types import SimpleNamespace

from creative_workflow.server.ui.view_models import (
    active_worker_job,
    format_user_message,
    infer_output_type,
    reference_summaries,
)


def test_reference_summaries_keep_all_uploaded_files_in_order() -> None:
    uploads = [
        SimpleNamespace(name="front.png", size=120_000, type="image/png"),
        SimpleNamespace(name="side.webp", size=240_000, type="image/webp"),
    ]

    summaries = reference_summaries(uploads)

    assert [item["name"] for item in summaries] == ["front.png", "side.webp"]
    assert summaries[0]["size_label"] == "117.2 KB"
    assert summaries[1]["content_type"] == "image/webp"


def test_format_user_message_includes_attached_file_names() -> None:
    message = format_user_message(
        "Make a square product visual.",
        [{"name": "front.png", "size_label": "117.2 KB", "content_type": "image/png"}],
    )

    assert "Make a square product visual." in message
    assert "Attached references" in message
    assert "front.png" in message


def test_active_worker_job_detects_nonterminal_latest_job() -> None:
    history = {
        "jobs": [
            {"job_id": "job_done", "state": "completed"},
            {"job_id": "job_waiting", "state": "queued"},
        ]
    }

    assert active_worker_job(history)["job_id"] == "job_waiting"
    assert active_worker_job({"jobs": [{"job_id": "job_done", "state": "completed"}]}) is None


def test_infer_output_type_uses_video_keyword_only_when_present() -> None:
    assert infer_output_type("Create a short looping video for this product.") == "video"
    assert infer_output_type("Create a square product image.") == "static_image"
