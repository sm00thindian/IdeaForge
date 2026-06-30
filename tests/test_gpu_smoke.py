"""Optional GPU smoke tests — run via workflow_dispatch or IDEAFORGE_GPU_CI=1."""

import os

import pytest


@pytest.mark.gpu
def test_gpu_mlx_whisper_importable():
    """Sanity check that mlx-whisper is installed on manual GPU CI runners."""
    if os.getenv("IDEAFORGE_GPU_CI") != "1":
        pytest.skip("GPU CI only — set IDEAFORGE_GPU_CI=1 on self-hosted macOS runners")
    pytest.importorskip("mlx_whisper")