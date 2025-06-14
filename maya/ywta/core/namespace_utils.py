"""
Namespace Utilities

Mayaの名前空間操作に関連するユーティリティ関数を提供します。
これらの関数は、名前空間の取得、操作、変換などの一般的なタスクを簡素化します。
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import logging
import re

logger = logging.getLogger(__name__)


def get_namespace_from_name(name):
    """指定された名前から名前空間を取得します。

    >>> print(get_namespace_from_name('BOB:character'))
    BOB:
    >>> print(get_namespace_from_name('YEP:BOB:character'))
    YEP:BOB:

    :param name: 名前空間を抽出する文字列
    :return: 抽出された名前空間
    """
    namespace = re.match("[_0-9a-zA-Z]+(?=:)(:[_0-9a-zA-Z]+(?=:))*", name)
    if namespace:
        namespace = "%s:" % str(namespace.group(0))
    else:
        namespace = ""
    return namespace


def remove_namespace_from_name(name):
    """指定された名前から名前空間を削除します

    >>> print(remove_namespace_from_name('character'))
    character
    >>> print(remove_namespace_from_name('BOB:character'))
    character
    >>> print(remove_namespace_from_name('YEP:BOB:character'))
    character

    :param name: 名前空間付きの名前
    :return: 名前空間なしの名前
    """
    namespace = get_namespace_from_name(name)
    if namespace:
        return re.sub("^{0}".format(namespace), "", name)
    return name
