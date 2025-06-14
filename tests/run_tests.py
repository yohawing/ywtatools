#!/usr/bin/env python
"""
YWTA Tools テスト実行スクリプト

このスクリプトは、コマンドラインからテストを実行するためのエントリーポイントを提供します。
"""

import os
import sys
import argparse
from pathlib import Path

# プロジェクトルートをPythonパスに追加
project_root = str(Path(__file__).parent.parent.absolute())
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tests.utils.test_runner import main


if __name__ == "__main__":
    main()
