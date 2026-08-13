"""DCCに依存しないRBF mesh deformation solver。

RBFの拡大行列とkernelはPyGeMのMITライセンス実装を基にしている。
由来とライセンスは同じdirectoryの ``PyGeM-LICENSE.rst`` を参照。
"""

from collections.abc import Callable, Iterable

import numpy as np
from scipy.spatial.distance import cdist


ProgressCallback = Callable[[str, int, int], None]
CancelCallback = Callable[[], bool]


class CancelledError(RuntimeError):
    """RBF処理が利用者によって中断されたことを示す。"""


def _notify(progress: ProgressCallback | None, phase: str, done: int, total: int):
    """進捗callbackがあれば現在位置を通知する。"""
    if progress is not None:
        progress(phase, done, total)


def _check_cancel(cancelled: CancelCallback | None):
    """キャンセル要求があれば処理を中断する。"""
    if cancelled is not None and cancelled():
        raise CancelledError("RBF deformation was cancelled")


def sample_spatial_indices(points, max_points):
    """Farthest-point samplingで空間的に分散したindexを返す。

    Args:
        points: shape ``(n, 3)`` の座標。
        max_points: 選択する最大点数。affine項のため4以上が必要。

    Returns:
        元配列順にsortしたindex配列。
    """
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points must have shape (n, 3)")
    if max_points < 4:
        raise ValueError("max_points must be at least 4")
    if len(points) <= max_points:
        return np.arange(len(points), dtype=np.int64)

    first = int(np.lexsort((points[:, 2], points[:, 1], points[:, 0]))[0])
    selected = [first]
    minimum_squared_distance = np.full(len(points), np.inf)
    for _ in range(1, max_points):
        delta = points - points[selected[-1]]
        squared_distance = np.einsum("ij,ij->i", delta, delta)
        minimum_squared_distance = np.minimum(minimum_squared_distance, squared_distance)
        minimum_squared_distance[selected] = -1.0
        selected.append(int(np.argmax(minimum_squared_distance)))
    return np.sort(np.asarray(selected, dtype=np.int64))


class RBF:
    """Mesh Retargetで利用するRBF kernel群。"""

    @classmethod
    def linear(cls, matrix, radius):
        return matrix

    @classmethod
    def gaussian(cls, matrix, radius):
        return np.exp(-(matrix * matrix) / (radius * radius))

    @classmethod
    def thin_plate(cls, matrix, radius):
        result = matrix / radius
        result *= matrix
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(result > 0, np.log(result), result)

    @classmethod
    def multi_quadratic_biharmonic(cls, matrix, radius):
        return np.sqrt((matrix * matrix) + (radius * radius))

    @classmethod
    def inv_multi_quadratic_biharmonic(cls, matrix, radius):
        return 1.0 / np.sqrt((matrix * matrix) + (radius * radius))

    @classmethod
    def beckert_wendland_c2_basis(cls, matrix, radius):
        arg = matrix / radius
        first = np.where(1 - arg > 0, np.power(1 - arg, 4), 0.0)
        return first * ((4 * arg) + 1)


def get_distance_matrix(v1, v2, rbf, radius):
    """2点群間のkernel距離行列を返す。"""
    matrix = cdist(v1, v2, "euclidean")
    if rbf != RBF.linear:
        matrix = rbf(matrix, radius)
    return matrix


def get_weight_matrix(source, target, rbf, radius):
    """RBF重みとaffine項を含む係数行列を解く。"""
    source = np.asarray(source, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    if source.ndim != 2 or source.shape[1] != 3:
        raise ValueError("source must have shape (n, 3)")
    if target.shape != source.shape:
        raise ValueError("source and target must have the same (n, 3) shape")
    if len(source) < 4:
        raise ValueError("at least four control points are required")
    if rbf != RBF.linear and radius <= 0:
        raise ValueError("radius must be positive for this kernel")

    identity = np.ones((len(source), 1))
    distance = get_distance_matrix(source, source, rbf, radius)
    dimension = 3
    matrix = np.block(
        [
            [distance, identity, source],
            [identity.T, np.zeros((1, 1)), np.zeros((1, dimension))],
            [source.T, np.zeros((dimension, 1)), np.zeros((dimension, dimension))],
        ]
    )
    right_hand_side = np.vstack([target, np.zeros((1, dimension)), np.zeros((dimension, dimension))])
    return np.linalg.solve(matrix, right_hand_side)


class RbfSolver:
    """一度解いた重みを複数のfollower点群へ適用するsolver。"""

    def __init__(self, source, weights, rbf, radius):
        self.source = source
        self.weights = weights
        self.rbf = rbf
        self.radius = radius

    @classmethod
    def fit(
        cls,
        source,
        target,
        rbf=None,
        radius=0.5,
        max_control_points=None,
        progress: ProgressCallback | None = None,
        cancelled: CancelCallback | None = None,
    ):
        """対応点からsolverを構築する。"""
        source = np.asarray(source, dtype=np.float64)
        target = np.asarray(target, dtype=np.float64)
        if target.shape != source.shape:
            raise ValueError("source and target must have the same (n, 3) shape")
        _notify(progress, "sampling", 0, 1)
        _check_cancel(cancelled)
        if max_control_points is not None:
            indices = sample_spatial_indices(source, max_control_points)
            source = source[indices]
            target = target[indices]
        _notify(progress, "sampling", 1, 1)
        _check_cancel(cancelled)
        rbf = rbf or RBF.linear
        _notify(progress, "solving", 0, 1)
        weights = get_weight_matrix(source, target, rbf, radius)
        _notify(progress, "solving", 1, 1)
        _check_cancel(cancelled)
        return cls(source, weights, rbf, radius)

    def transform(self, points, cancelled: CancelCallback | None = None):
        """1点群を変形する。"""
        _check_cancel(cancelled)
        points = np.asarray(points, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError("points must have shape (n, 3)")
        distance = get_distance_matrix(points, self.source, self.rbf, self.radius)
        basis = np.block([distance, np.ones((len(points), 1)), points])
        result = basis @ self.weights
        _check_cancel(cancelled)
        return result

    def transform_many(
        self,
        point_sets: Iterable,
        progress: ProgressCallback | None = None,
        cancelled: CancelCallback | None = None,
    ):
        """共有weightで複数点群を順番に変形する。"""
        point_sets = list(point_sets)
        results = []
        _notify(progress, "deforming", 0, len(point_sets))
        for index, points in enumerate(point_sets, start=1):
            results.append(self.transform(points, cancelled))
            _notify(progress, "deforming", index, len(point_sets))
        return results
