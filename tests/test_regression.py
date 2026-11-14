# -*- coding: utf-8 -*-
"""真实 MP4 端到端回归（演示数据）。默认跳过；RUN_REGRESSION=1 时启用。"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REGRESSION") != "1",
    reason="端到端回归为本地集成测试：RUN_REGRESSION=1 启用（渲染约 2-4 分钟）")


def test_full_chain_regression():
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, str(root / "tools" / "regression.py")],
                       cwd=str(root), capture_output=True, text=True, timeout=1500)
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    assert "回归通过" in r.stdout
