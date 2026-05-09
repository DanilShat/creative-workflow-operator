import pytest
from pydantic import ValidationError

from creative_workflow.shared.contracts.assets import AssetUploadMetadata
from creative_workflow.shared.contracts.jobs import GeminiPromptOutput, JobEnvelope
from creative_workflow.shared.enums import AssetClass, JobType, RetentionClass, SourceService


def test_asset_metadata_requires_real_checksum_shape():
    with pytest.raises(ValidationError):
        AssetUploadMetadata(
            task_id="task_1",
            asset_class=AssetClass.GENERATED,
            retention_class=RetentionClass.TTL_30D,
            original_filename="../bad.png",
            content_type="image/png",
            size_bytes=10,
            sha256="too-short",
            source_service=SourceService.FREEPIK,
        )


def test_job_envelope_serializes_canonical_browser_job():
    job = JobEnvelope(
        job_id="job_1",
        task_id="task_1",
        run_id="run_1",
        job_type=JobType.BROWSER_FLOW,
        required_capability="browser.gemini",
        action_name="gemini_build_prompt_from_brief_and_refs",
        inputs={"brief_text": "Create a product hero."},
    )
    assert job.model_dump(mode="json")["job_type"] == "browser_flow"


def test_gemini_prompt_output_requires_prompt_text():
    with pytest.raises(ValidationError):
        GeminiPromptOutput()

