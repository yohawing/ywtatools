"""YWTA Link の例外型。"""

import math


class ProtocolError(ValueError):
    """Protocol上の不正を表す基底例外。"""


class ValidationError(ProtocolError):
    """受信データの検証失敗。"""


ProtocolValidationError = ValidationError


class EnvelopeValidationError(ValidationError):
    """共通Envelopeの検証失敗。"""


class ContractValidationError(ValidationError):
    """Sync Contractの検証失敗。"""


class InvalidStateTransition(ProtocolError):
    """Session状態機械で許可されない遷移。"""


class AuthorityViolation(ProtocolError):
    """ChannelのAuthority以外からの更新。"""


class RevisionError(ProtocolError):
    """Channel revisionの不正。"""


class StaleRevision(RevisionError):
    """古い、または重複したrevision。"""


def _bounded_error_details(error: BaseException) -> tuple[str, str]:
    """例外を型名と1024文字以内の安全なmessageへ変換する。"""

    try:
        message = str(error)
    except Exception:
        message = "<unprintable exception>"
    return type(error).__name__, message[:1024]


def _bounded_error_message(error: BaseException) -> str:
    """例外messageを1024文字以内の安全な文字列へ変換する。"""

    return _bounded_error_details(error)[1]


def _validate_identifier(value: object, field_name: str, error_type: type[Exception]) -> str:
    """空白だけでないUTF-8識別子を検証する。"""

    if not isinstance(value, str) or not value or not value.strip():
        raise error_type(f"{field_name} must be a non-whitespace string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise error_type(f"{field_name} must be valid UTF-8") from error
    return value


def _positive_finite(value: object) -> bool:
    """boolを除く正の有限数かを返す。"""

    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0


def _non_negative_finite(value: object) -> bool:
    """boolを除く0以上の有限数かを返す。"""

    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) >= 0
