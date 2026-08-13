"""YWTA全体で共有する例外階層と安定したエラーコード。"""

from enum import Enum


class ErrorCode(str, Enum):
    """ログや外部連携で利用する安定したエラーコード。"""

    UNKNOWN = "YWTA_UNKNOWN"
    CONFIGURATION = "YWTA_CONFIGURATION"
    VALIDATION = "YWTA_VALIDATION"
    RIG = "YWTA_RIG"
    DEFORM = "YWTA_DEFORM"
    MESH = "YWTA_MESH"
    ANIMATION = "YWTA_ANIMATION"
    PIPELINE = "YWTA_PIPELINE"


class YWTAError(Exception):
    """利用者へ提示可能なYWTA例外の基底クラス。"""

    default_code = ErrorCode.UNKNOWN

    def __init__(self, message, *, code=None, details=None):
        super().__init__(message)
        selected_code = code or self.default_code
        self.code = selected_code.value if isinstance(selected_code, ErrorCode) else str(selected_code)
        self.details = dict(details or {})

    def to_dict(self):
        """UI、ログ、RPCで扱えるdictionaryへ変換する。"""
        result = {"code": self.code, "message": str(self)}
        if self.details:
            result["details"] = self.details.copy()
        return result


class RigError(YWTAError):
    """Rig構築・編集の失敗。"""

    default_code = ErrorCode.RIG


class DeformError(YWTAError):
    """Deformer・weight処理の失敗。"""

    default_code = ErrorCode.DEFORM


class MeshError(YWTAError):
    """Mesh topology・geometry処理の失敗。"""

    default_code = ErrorCode.MESH


class AnimationError(YWTAError):
    """Animation処理の失敗。"""

    default_code = ErrorCode.ANIMATION


class PipelineError(YWTAError):
    """入出力・batch・pipeline処理の失敗。"""

    default_code = ErrorCode.PIPELINE
