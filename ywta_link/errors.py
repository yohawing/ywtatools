"""YWTA Link の例外型。"""


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
