from types import SimpleNamespace

from creative_workflow.server.ui.view_models import (
    active_worker_job,
    format_user_message,
    gate_a_submit_blocked,
    infer_output_type,
    reference_summaries,
    task_user_message,
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


def test_format_user_message_lists_multiple_attachments_in_order() -> None:
    message = format_user_message(
        "Create a packshot series.",
        [
            {"name": "product_front.png", "size_label": "2.0 MB", "content_type": "image/png"},
            {"name": "mood_board.jpg", "size_label": "1.1 MB", "content_type": "image/jpeg"},
        ],
    )
    assert "product_front.png" in message
    assert "mood_board.jpg" in message
    assert message.index("product_front.png") < message.index("mood_board.jpg")


def test_gate_a_submit_blocked_returns_none_when_no_task_or_active_job() -> None:
    assert gate_a_submit_blocked(None, None, "key_abc", "") is None
    assert gate_a_submit_blocked("task_01", {"jobs": []}, "key_abc", "") is None


def test_gate_a_submit_blocked_blocks_on_duplicate_idempotency_key() -> None:
    reason = gate_a_submit_blocked("task_01", None, "key_abc", "key_abc")
    assert reason is not None
    assert "already submitted" in reason.lower()


def test_gate_a_submit_blocked_blocks_when_active_job_running() -> None:
    history = {"jobs": [{"job_id": "job_01", "state": "queued"}]}
    reason = gate_a_submit_blocked("task_01", history, "key_new", "key_old")
    assert reason is not None
    assert "already active" in reason.lower()


def test_gate_a_submit_blocked_allows_when_all_jobs_terminal() -> None:
    history = {
        "jobs": [
            {"job_id": "job_01", "state": "completed"},
            {"job_id": "job_02", "state": "failed_fatal"},
        ]
    }
    reason = gate_a_submit_blocked("task_01", history, "key_new", "key_old")
    assert reason is None


def test_task_user_message_reconstructs_brief_and_reference_names_from_history() -> None:
    summary = {"brief_text": "Create a cozy product visual."}
    history = {
        "assets": [
            {"asset_class": "reference", "original_filename": "front.png"},
            {"asset_class": "generated", "original_filename": "output.png"},
            {"asset_class": "reference", "original_filename": "side.jpg"},
        ]
    }

    message = task_user_message(summary, history)

    assert "Create a cozy product visual." in message
    assert "Attached references" in message
    assert "front.png" in message
    assert "side.jpg" in message
    assert "output.png" not in message
