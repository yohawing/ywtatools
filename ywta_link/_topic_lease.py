"""Transport間で共有するRoom/Topicの排他的lease。"""

import threading
import weakref


_LOCK = threading.Lock()
_LeaseMap = dict[tuple[str, str], weakref.ReferenceType[object]]
_CLIENTS: dict[int, tuple[weakref.ReferenceType[object], _LeaseMap]] = {}


def claim_topic(
    client: object,
    room: str,
    topic: str,
    owner: object,
    error_type: type[RuntimeError],
) -> None:
    """Client identity内のRoom/Topicを一つのtransportへ貸し出す。"""

    client_id, key = id(client), (room, topic)
    try:
        owner_ref = weakref.ref(owner)
        client_ref = weakref.ref(client, lambda ref: _discard_client(client_id, ref))
    except TypeError as exc:
        raise error_type("client must support identity-based weak references") from exc

    with _LOCK:
        entry = _CLIENTS.get(client_id)
        if entry is None or entry[0]() is not client:
            leases: _LeaseMap = {}
            _CLIENTS[client_id] = (client_ref, leases)
        else:
            leases = entry[1]
        if (existing := leases.get(key)) is not None and existing() is not None:
            raise error_type("Room/Topic is already owned by another transport")
        leases[key] = owner_ref


def release_topic(client: object, room: str, topic: str, owner: object) -> None:
    """自身が所有するleaseだけを解放する。"""

    client_id, key = id(client), (room, topic)
    with _LOCK:
        entry = _CLIENTS.get(client_id)
        if entry is None or entry[0]() is not client:
            return
        leases = entry[1]
        if (existing := leases.get(key)) is not None and existing() is owner:
            del leases[key]
        if not leases:
            del _CLIENTS[client_id]


def _discard_client(client_id: int, client_ref: weakref.ReferenceType[object]) -> None:
    """GC済みClientと一致するregistry entryだけを破棄する。"""

    with _LOCK:
        entry = _CLIENTS.get(client_id)
        if entry is not None and entry[0] is client_ref:
            del _CLIENTS[client_id]
