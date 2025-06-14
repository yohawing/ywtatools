"""
Settings Utilities

設定の保存、読み込み、管理に関連するユーティリティ関数を提供します。
これらの関数は、ユーザー設定の永続化と取得を簡素化します。
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import logging
import os

import maya.cmds as cmds

logger = logging.getLogger(__name__)

# PySide2とPySide6の両方をサポート
try:
    from PySide6.QtCore import QSettings
except ImportError:
    from PySide2.QtCore import QSettings


_settings = None


def _get_settings():
    """QSettingsインスタンスを取得します"""
    global _settings
    if _settings is None:
        _settings = QSettings("YWTA", "YWTATools")
    return _settings


def get_setting(key, default_value=None):
    """永続キャッシュから値を取得します。

    :param key: ハッシュキー
    :param default_value: キーが存在しない場合に返す値
    :return: 保存された値
    """
    settings = _get_settings()
    return settings.value(key, default_value)


def set_setting(key, value):
    """永続キャッシュに値を設定します。

    :param key: ハッシュキー
    :param value: 保存する値
    """
    settings = _get_settings()
    settings.setValue(key, value)


def get_save_file_name(file_filter, key=None):
    """保存ダイアログからファイルパスを取得します。

    :param file_filter: ファイルフィルタ（例："Maya Files (*.ma *.mb)"）
    :param key: 永続キャッシュに保存されている開始ディレクトリにアクセスするためのオプションのキー値
    :return: 選択されたファイルパス
    """
    return _get_file_path(file_filter, key, 0)


def get_open_file_name(file_filter, key=None):
    """オープンファイルダイアログからファイルパスを取得します。

    :param file_filter: ファイルフィルタ（例："Maya Files (*.ma *.mb)"）
    :param key: 永続キャッシュに保存されている開始ディレクトリにアクセスするためのオプションのキー値
    :return: 選択されたファイルパス
    """
    return _get_file_path(file_filter, key, 1)


def get_directory_name(key=None):
    """オープンファイルダイアログからファイルパスを取得します。

    :param key: 永続キャッシュに保存されている開始ディレクトリにアクセスするためのオプションのキー値
    :return: 選択されたファイルパス
    """
    return _get_file_path("", key, 3)


def _get_file_path(file_filter, key, file_mode):
    """ファイルダイアログからファイルパスを取得します。

    :param file_filter: ファイルフィルタ（例："Maya Files (*.ma *.mb)"）
    :param key: 永続キャッシュに保存されている開始ディレクトリにアクセスするためのオプションのキー値
    :param file_mode: 0 存在するかどうかに関わらず、任意のファイル
        1 単一の既存ファイル
        2 ディレクトリの名前。ダイアログにはディレクトリとファイルの両方が表示されます
        3 ディレクトリの名前。ダイアログにはディレクトリのみが表示されます
        4 1つ以上の既存ファイルの名前
    :return: 選択されたファイルパス
    """
    start_directory = cmds.workspace(q=True, rd=True)
    if key is not None:
        start_directory = get_setting(key, start_directory)

    file_path = cmds.fileDialog2(
        fileMode=file_mode, startingDirectory=start_directory, fileFilter=file_filter
    )
    if key is not None and file_path:
        file_path = file_path[0]
        directory = (
            file_path if os.path.isdir(file_path) else os.path.dirname(file_path)
        )
        set_setting(key, directory)
    return file_path
