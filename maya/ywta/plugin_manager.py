"""YWTA Python ツール／プラグインのメタデータレジストリ。

このモジュールは Maya の ``loadPlugin`` を置き換えるローダーではない。
Python で実装されたツールを一覧表示したり検索したりするための、軽量な
descriptor registry だけを提供する。発見処理はモジュール名を列挙する
だけで、列挙したモジュールを import しない。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib.machinery import PathFinder
import pkgutil


def _text_field(value: object, field_name: str) -> str:
    """メタデータの文字列フィールドを検証して正規化する。"""

    if not isinstance(value, str):
        raise TypeError(f"{field_name} は文字列で指定してください")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} は空にできません")
    return normalized


@dataclass(frozen=True)
class PluginDescriptor:
    """YWTA Python ツールの不変なメタデータ。

    Args:
        name: レジストリ内で一意な表示名。
        version: ツールのバージョン文字列。
        description: ツールの説明。
        tags: 検索に使うタグの列。
        module: 実装モジュールの完全修飾名。

    ``tags`` は入力時に tuple へ変換されるため、登録後に内容を変更できない。
    バージョン形式（SemVer など）はここでは規定せず、空でない文字列だけを
    必須条件とする。
    """

    name: str
    version: str
    description: str
    module: str
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """文字列フィールドとタグ列を検証する。"""

        object.__setattr__(self, "name", _text_field(self.name, "name"))
        object.__setattr__(self, "version", _text_field(self.version, "version"))
        object.__setattr__(self, "description", _text_field(self.description, "description"))
        object.__setattr__(self, "module", _text_field(self.module, "module"))

        if isinstance(self.tags, (str, bytes)) or not isinstance(self.tags, Iterable):
            raise TypeError("tags は文字列以外の iterable で指定してください")

        normalized_tags: list[str] = []
        for tag in self.tags:
            normalized_tags.append(_text_field(tag, "tag"))
        object.__setattr__(self, "tags", tuple(normalized_tags))


class DuplicatePluginError(ValueError):
    """同じ名前のプラグインを登録しようとした場合のエラー。"""


class UnknownPluginError(KeyError):
    """レジストリに存在しないプラグインを参照した場合のエラー。"""


def _coerce_descriptor(
    descriptor: PluginDescriptor | None,
    metadata: dict[str, object],
) -> PluginDescriptor:
    """descriptor またはキーワードメタデータを PluginDescriptor に変換する。"""

    if descriptor is None:
        if not metadata:
            raise TypeError("descriptor またはメタデータを指定してください")
        try:
            return PluginDescriptor(**metadata)
        except TypeError as error:
            raise TypeError("プラグインメタデータの項目が不正です") from error
    if metadata:
        raise TypeError("descriptor とメタデータを同時に指定できません")
    if not isinstance(descriptor, PluginDescriptor):
        raise TypeError("descriptor は PluginDescriptor で指定してください")
    return descriptor


class PluginRegistry:
    """Python プラグイン descriptor を保持するレジストリ。

    名前は大文字・小文字を区別せず一意とする。メソッドが返すコレクションは
    tuple なので、呼び出し側がレジストリの内部状態を変更することはない。
    """

    def __init__(self) -> None:
        """空のレジストリを作成する。"""

        self._plugins: dict[str, PluginDescriptor] = {}

    def register(
        self,
        descriptor: PluginDescriptor | None = None,
        **metadata: object,
    ) -> PluginDescriptor:
        """descriptor を登録し、登録した descriptor を返す。

        ``descriptor`` の代わりに ``name=...`` などのキーワードでメタデータを
        渡してもよい。名前が既に登録済みなら ``DuplicatePluginError`` を送出する。
        """

        plugin = _coerce_descriptor(descriptor, metadata)
        key = plugin.name.casefold()
        if key in self._plugins:
            raise DuplicatePluginError(f"プラグイン名が重複しています: {plugin.name}")
        self._plugins[key] = plugin
        return plugin

    def unregister(self, name: str) -> PluginDescriptor:
        """名前に対応する descriptor を解除して返す。"""

        key = _lookup_key(name)
        try:
            return self._plugins.pop(key)
        except KeyError as error:
            raise UnknownPluginError(name) from error

    def get(self, name: str) -> PluginDescriptor:
        """名前に対応する descriptor を返す。名前は大文字・小文字を区別しない。"""

        key = _lookup_key(name)
        try:
            return self._plugins[key]
        except KeyError as error:
            raise UnknownPluginError(name) from error

    def list_plugins(self) -> tuple[PluginDescriptor, ...]:
        """登録済み descriptor を名前順の tuple で返す。"""

        return tuple(sorted(self._plugins.values(), key=lambda plugin: plugin.name.casefold()))

    def search(self, query: str) -> tuple[PluginDescriptor, ...]:
        """名前・説明・タグを対象に大文字・小文字を区別せず検索する。

        空文字列は全件検索として扱う。結果は ``list_plugins`` と同じ名前順で
        返される。
        """

        if not isinstance(query, str):
            raise TypeError("検索語は文字列で指定してください")
        normalized_query = query.strip().casefold()
        return tuple(
            plugin
            for plugin in self.list_plugins()
            if any(normalized_query in value.casefold() for value in (plugin.name, plugin.description, *plugin.tags))
        )

    def clear(self) -> None:
        """登録内容をすべて解除する。テスト間の状態リセットにも利用する。"""

        self._plugins.clear()


def _lookup_key(name: str) -> str:
    """検索・解除用の名前を検証して辞書キーへ変換する。"""

    return _text_field(name, "name").casefold()


_REGISTRY = PluginRegistry()


def register_plugin(
    descriptor: PluginDescriptor | None = None,
    **metadata: object,
) -> PluginDescriptor:
    """共有 registry に descriptor を登録する。"""

    return _REGISTRY.register(descriptor, **metadata)


def unregister_plugin(name: str) -> PluginDescriptor:
    """共有 registry から名前に対応する descriptor を解除する。"""

    return _REGISTRY.unregister(name)


def get_plugin(name: str) -> PluginDescriptor:
    """共有 registry から名前に対応する descriptor を取得する。"""

    return _REGISTRY.get(name)


def list_plugins() -> tuple[PluginDescriptor, ...]:
    """共有 registry の descriptor を名前順で取得する。"""

    return _REGISTRY.list_plugins()


def search_plugins(query: str) -> tuple[PluginDescriptor, ...]:
    """共有 registry を名前・説明・タグで検索する。"""

    return _REGISTRY.search(query)


def clear_registry() -> None:
    """共有 registry を空にする。テストの setup/teardown から明示的に呼び出す。"""

    _REGISTRY.clear()


def _package_search_paths(package_name: str) -> tuple[str, ...]:
    """import を実行せず package のサブモジュール検索パスを取得する。"""

    if not isinstance(package_name, str):
        raise TypeError("package_name は文字列で指定してください")
    package_name = package_name.strip()
    if not package_name or any(not part.isidentifier() for part in package_name.split(".")):
        raise ValueError("package_name は有効な Python package 名で指定してください")

    search_path: list[str] | None = None
    qualified_name = ""
    for part in package_name.split("."):
        qualified_name = f"{qualified_name}.{part}".lstrip(".")
        spec = PathFinder.find_spec(qualified_name, search_path)
        if spec is None:
            raise ModuleNotFoundError(qualified_name)
        if spec.submodule_search_locations is None:
            raise NotADirectoryError(f"package ではありません: {qualified_name}")
        search_path = list(spec.submodule_search_locations)
    return tuple(search_path or ())


def discover_plugins(package_name: str) -> tuple[str, ...]:
    """package 直下の公開モジュール名を決定的順序で列挙する。

    package や発見したモジュールを import せず、``_`` で始まるモジュール／
    サブパッケージを除外する。戻り値は完全修飾モジュール名の tuple である。
    """

    paths = _package_search_paths(package_name)
    prefix = f"{package_name}."
    discovered = []
    for module_info in pkgutil.iter_modules(paths, prefix=prefix):
        module_name = module_info.name
        child_name = module_name[len(prefix) :]
        if any(part.startswith("_") for part in child_name.split(".")):
            continue
        discovered.append(module_name)
    return tuple(sorted(discovered, key=str.casefold))


__all__ = [
    "DuplicatePluginError",
    "PluginDescriptor",
    "PluginRegistry",
    "UnknownPluginError",
    "clear_registry",
    "discover_plugins",
    "get_plugin",
    "list_plugins",
    "register_plugin",
    "search_plugins",
    "unregister_plugin",
]
