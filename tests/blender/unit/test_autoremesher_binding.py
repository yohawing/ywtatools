"""ywta_remesh.binding のテスト。

このモジュールはbpyに依存しないため、Blender本体を起動せず
素のPython（``python -m unittest`` 等）から直接実行できる。
C++側のDLLはまだ存在しない前提で、ctypesのFFI境界を偽のDLLオブジェクトで
差し替えて引数マーシャリング・戻り値の解釈を検証する。
"""

import ctypes
import os
import sys
import unittest


def _write_through_pointer(double_ptr, value_ptr):
    """``*double_ptr = value_ptr`` に相当する書き込みを行う。

    ctypesの ``pointer.contents = ...`` はPythonローカルの参照差し替えに過ぎず、
    実際のメモリへの書き込みを行わない（Cの ``*out = malloc(...)`` とは異なる）。
    偽DLLからCの出力引数（ダブルポインタ）を模倣するには、ポインタが指す
    メモリ位置に生のポインタ値を直接書き込む必要がある。
    """
    address_view = ctypes.cast(double_ptr, ctypes.POINTER(ctypes.c_void_p))
    address_view[0] = ctypes.cast(value_ptr, ctypes.c_void_p).value

# blender/modules を sys.path に追加してから ywta_remesh をimportする。
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
_MODULES_DIR = os.path.join(_REPO_ROOT, "blender", "modules")
if _MODULES_DIR not in sys.path:
    sys.path.insert(0, _MODULES_DIR)

from ywta_remesh import binding  # noqa: E402


class FakeAutoRemesherDLL:
    """ywta_autoremesher.dll の ``ywta_remesh`` / ``ywta_remesh_free`` を模した偽物。

    実際のctypes呼び出し境界の代わりにPython関数として呼ばれるため、
    ``binding.remesh`` が構築する引数（ctypes配列・構造体ポインタ・コールバック）を
    そのまま検査できる。
    """

    def __init__(self, out_vertices, out_faces):
        self.out_vertices_data = out_vertices
        self.out_face_indices_data = [i for face in out_faces for i in face]
        self.out_face_counts_data = [len(face) for face in out_faces]

        self.received_vertices = None
        self.received_tris = None
        self.received_params = None
        self.received_progress_calls = []
        self.free_called_with = None

        # 呼び出し先に返すバッファはPython側で寿命管理する（実DLLならmallocに相当）。
        self._out_vertices_arr = (ctypes.c_double * len(self.out_vertices_data))(*self.out_vertices_data)
        self._out_face_indices_arr = (ctypes.c_uint32 * len(self.out_face_indices_data))(
            *self.out_face_indices_data
        )
        self._out_face_counts_arr = (ctypes.c_uint32 * len(self.out_face_counts_data))(
            *self.out_face_counts_data
        )

    def ywta_remesh(
        self,
        verts_arr,
        vertex_count,
        tris_arr,
        tri_count,
        params_ptr,
        progress_cb,
        _tag,
        out_vertices_ptr,
        out_vertex_count_ptr,
        out_face_indices_ptr,
        out_face_counts_ptr,
        out_face_count_ptr,
    ):
        self.received_vertices = list(verts_arr[: vertex_count * 3])
        self.received_tris = list(tris_arr[: tri_count * 3])
        self.received_params = (
            params_ptr.contents.target_triangle_count,
            params_ptr.contents.scaling,
            params_ptr.contents.adaptivity,
            params_ptr.contents.model_type,
        )

        if progress_cb:
            progress_cb(None, 0.5, b"halfway")
            self.received_progress_calls.append((0.5, "halfway"))

        _write_through_pointer(out_vertices_ptr, self._out_vertices_arr)
        out_vertex_count_ptr[0] = len(self.out_vertices_data) // 3
        _write_through_pointer(out_face_indices_ptr, self._out_face_indices_arr)
        _write_through_pointer(out_face_counts_ptr, self._out_face_counts_arr)
        out_face_count_ptr[0] = len(self.out_face_counts_data)
        return 0

    def ywta_remesh_free(self, vertices_ptr, face_indices_ptr, face_counts_ptr):
        self.free_called_with = (vertices_ptr, face_indices_ptr, face_counts_ptr)


class FakeFailingDLL:
    """エラーコードを返す偽DLL（RuntimeErrorの検証用）。"""

    def ywta_remesh(self, *args, **kwargs):
        return 42

    def ywta_remesh_free(self, *args, **kwargs):
        pass


class ResolveDllPathTests(unittest.TestCase):
    """DLL探索順序（環境変数優先、次にデフォルトパス）のテスト。"""

    def setUp(self):
        self._orig_env = os.environ.get(binding._ENV_VAR)

    def tearDown(self):
        if self._orig_env is None:
            os.environ.pop(binding._ENV_VAR, None)
        else:
            os.environ[binding._ENV_VAR] = self._orig_env
        binding.reset_dll_cache()

    def test_env_var_overrides_default_path(self):
        os.environ[binding._ENV_VAR] = "C:/somewhere/custom.dll"
        self.assertEqual(str(binding.resolve_dll_path()), "C:\\somewhere\\custom.dll")

    def test_default_path_when_env_unset(self):
        os.environ.pop(binding._ENV_VAR, None)
        expected = binding.default_dll_path()
        self.assertEqual(binding.resolve_dll_path(), expected)
        self.assertTrue(str(expected).replace("\\", "/").endswith("bin/windows/ywta_autoremesher.dll"))

    def test_missing_dll_raises_file_not_found_error(self):
        os.environ[binding._ENV_VAR] = "F:/nonexistent/path/to/ywta_autoremesher.dll"
        binding.reset_dll_cache()
        with self.assertRaises(FileNotFoundError):
            binding._load_dll()


class RemeshMarshalingTests(unittest.TestCase):
    """binding.remesh() の引数マーシャリング・戻り値解釈のテスト（偽DLL使用）。"""

    def setUp(self):
        binding.reset_dll_cache()
        self._orig_load_dll = binding._load_dll

    def tearDown(self):
        binding._load_dll = self._orig_load_dll
        binding.reset_dll_cache()

    def test_flat_vertices_and_flat_triangles_roundtrip(self):
        # 入力: 立方体の1面を模した4頂点2三角形
        vertices = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0]
        triangles = [0, 1, 2, 0, 2, 3]

        # 出力: 三角形1つ + 四角形1つ（混在ngon）を返す偽DLL
        out_vertices = [0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 2.0, 2.0, 0.0, 0.0, 2.0, 0.0, 1.0, 1.0, 1.0]
        out_faces = [(0, 1, 4), (1, 2, 3, 4)]

        fake_dll = FakeAutoRemesherDLL(out_vertices, out_faces)
        binding._load_dll = lambda: fake_dll

        progress_events = []
        result_vertices, result_faces = binding.remesh(
            vertices,
            triangles,
            target_count=1234,
            scaling=0.5,
            adaptivity=0.75,
            model_type=binding.MODEL_TYPE_HARDSURFACE,
            progress_cb=lambda progress, message: progress_events.append((progress, message)),
        )

        # 入力側のマーシャリングが正しいか
        self.assertEqual(fake_dll.received_vertices, vertices)
        self.assertEqual(fake_dll.received_tris, triangles)
        target_count, scaling, adaptivity, model_type = fake_dll.received_params
        self.assertEqual(target_count, 1234)
        self.assertAlmostEqual(scaling, 0.5)
        self.assertAlmostEqual(adaptivity, 0.75)
        self.assertEqual(model_type, binding.MODEL_TYPE_HARDSURFACE)

        # 進捗コールバックが呼ばれたか
        self.assertEqual(len(progress_events), 1)
        self.assertAlmostEqual(progress_events[0][0], 0.5, places=5)
        self.assertEqual(progress_events[0][1], "halfway")

        # 出力側の解釈（三角形+四角形の混在ngon展開）が正しいか
        self.assertEqual(result_vertices, out_vertices)
        self.assertEqual(result_faces, out_faces)

        # 解放APIが呼ばれたか
        self.assertIsNotNone(fake_dll.free_called_with)

    def test_nested_triangle_tuples_are_flattened(self):
        vertices = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0]
        triangles = [(0, 1, 2)]

        fake_dll = FakeAutoRemesherDLL(vertices, [(0, 1, 2)])
        binding._load_dll = lambda: fake_dll

        binding.remesh(vertices, triangles)

        self.assertEqual(fake_dll.received_tris, [0, 1, 2])

    def test_no_progress_callback_does_not_error(self):
        vertices = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0]
        triangles = [0, 1, 2]

        fake_dll = FakeAutoRemesherDLL(vertices, [(0, 1, 2)])
        binding._load_dll = lambda: fake_dll

        # progress_cb省略時は例外が起きず、コールバックも呼ばれない
        binding.remesh(vertices, triangles)
        self.assertEqual(fake_dll.received_progress_calls, [])

    def test_nonzero_return_code_raises_runtime_error(self):
        binding._load_dll = lambda: FakeFailingDLL()

        with self.assertRaises(RuntimeError) as ctx:
            binding.remesh([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0], [0, 1, 2])

        self.assertIn("42", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
