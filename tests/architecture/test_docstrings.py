"""The API reference is generated from docstrings, so every public name must carry one."""

import inspect
from collections.abc import Iterator

import capitalcom
from capitalcom.api.accounts import AccountsResource
from capitalcom.api.history import HistoryResource
from capitalcom.api.markets import MarketsResource
from capitalcom.api.orders import OrdersResource
from capitalcom.api.positions import PositionsResource
from capitalcom.api.prices import PricesResource
from capitalcom.api.sentiment import SentimentResource
from capitalcom.api.session_resource import SessionResource
from capitalcom.api.stream import StreamResource
from capitalcom.api.watchlists import WatchlistsResource

NAMESPACES = (
    SessionResource,
    AccountsResource,
    HistoryResource,
    PositionsResource,
    OrdersResource,
    MarketsResource,
    PricesResource,
    SentimentResource,
    WatchlistsResource,
    StreamResource,
)


def _own_class_doc(cls: type) -> str:
    # The class's own docstring: inspect.getdoc would borrow a base class's, and a dataclass
    # without one gets its generated signature ("Name(field: type, ...)") instead.
    doc = cls.__dict__.get("__doc__") or ""
    return "" if doc.startswith(f"{cls.__name__}(") else doc.strip()


def _members(cls: type) -> Iterator[tuple[str, object]]:
    # Members defined by this library's classes, not by object, Exception or Enum.
    seen: set[str] = set()
    for base in cls.__mro__:
        if not base.__module__.startswith("capitalcom"):
            continue
        for name, member in vars(base).items():
            if name.startswith("_") or name in seen:
                continue
            if isinstance(member, property | staticmethod | classmethod) or inspect.isfunction(
                member
            ):
                seen.add(name)
                yield name, member


def _missing() -> list[str]:
    missing: list[str] = []
    public = [getattr(capitalcom, name) for name in dir(capitalcom) if not name.startswith("_")]
    targets = [obj for obj in public if not inspect.ismodule(obj)]
    for obj in [*targets, *NAMESPACES]:
        if not (inspect.isclass(obj) or inspect.isfunction(obj)):
            continue
        if not obj.__module__.startswith("capitalcom"):
            continue
        name = obj.__qualname__
        if inspect.isclass(obj):
            if not _own_class_doc(obj):
                missing.append(name)
            for member_name, member in _members(obj):
                target = member.fget if isinstance(member, property) else member
                if not inspect.getdoc(target):
                    missing.append(f"{name}.{member_name}")
        elif not inspect.getdoc(obj):
            missing.append(name)
    return sorted(set(missing))


def test_every_public_name_has_a_docstring() -> None:
    missing = _missing()
    assert not missing, "missing docstrings:\n" + "\n".join(missing)
