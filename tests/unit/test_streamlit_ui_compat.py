"""Compatibility checks for the pinned Streamlit runtime."""

from __future__ import annotations

import ast
from pathlib import Path


def test_streamlit_image_calls_use_streamlit_135_keyword() -> None:
    """Streamlit 1.35 accepts `use_column_width`, not image `use_container_width`."""

    source = Path("src/creative_workflow/server/ui/streamlit_app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    bad_calls: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "image":
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "st":
            continue
        if any(keyword.arg == "use_container_width" for keyword in node.keywords):
            bad_calls.append(node.lineno)

    assert bad_calls == []
