"""Verify duplicated shared contracts stay identical across split repos."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


CONTRACT_CLASSES = {
    "creative_workflow.shared.contracts.assets": [
        "AssetUploadMetadata",
        "ReferenceUploadMetadata",
        "AssetUploadResponse",
        "ReferenceUploadResponse",
        "JobInputAsset",
    ],
    "creative_workflow.shared.contracts.jobs": [
        "RetryPolicy",
        "JobEnvelope",
        "JobProgressRequest",
        "BrowserFlowResult",
        "GeminiPromptOutput",
        "FreepikGenerationOutput",
        "JobCompleteRequest",
        "JobCompleteResponse",
        "JobFailRequest",
        "JobFailResponse",
    ],
    "creative_workflow.shared.contracts.workers": [
        "WorkerRegisterRequest",
        "WorkerRegisterResponse",
        "WorkerHeartbeatRequest",
        "WorkerHeartbeatResponse",
        "ClaimNextRequest",
        "JobForWorker",
        "ClaimNextResponse",
    ],
}


def _repo_schema(repo_root: Path) -> dict:
    code = f"""
import importlib
import json
import sys
sys.path.insert(0, {str(repo_root / "src")!r})
classes = {CONTRACT_CLASSES!r}
schemas = {{}}
for module_name, class_names in classes.items():
    module = importlib.import_module(module_name)
    for class_name in class_names:
        model = getattr(module, class_name)
        schemas[f"{{module_name}}.{{class_name}}"] = model.model_json_schema()
print(json.dumps(schemas, sort_keys=True))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_worker_shared_contracts_match_operator_copy():
    operator_root = Path(__file__).resolve().parents[1]
    worker_root = Path(os.getenv("CREATIVE_WORKFLOW_WORKER_REPO", operator_root.parent / "creative_workflow_worker"))
    if not (worker_root / "src" / "creative_workflow" / "shared").exists():
        pytest.skip("Worker repo not available; set CREATIVE_WORKFLOW_WORKER_REPO to run parity check.")

    assert _repo_schema(operator_root) == _repo_schema(worker_root)
