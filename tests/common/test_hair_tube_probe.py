"""Hair Tube probeのcontract gateテスト。"""

from __future__ import annotations

import unittest

from tools.hair_tube_probe import MeshData, probe_mesh


def make_open_tube(station_sizes: tuple[int, ...] = (4, 4, 4)) -> MeshData:
    """4頂点ringが連続する、最小のopen tubeを作る。"""

    rings: list[tuple[int, ...]] = []
    next_vertex = 0
    for size in station_sizes:
        ring = tuple(range(next_vertex, next_vertex + size))
        rings.append(ring)
        next_vertex += size
    faces: list[tuple[int, ...]] = []
    for first, second in zip(rings, rings[1:]):
        if len(first) != 4 or len(second) != 4:
            faces.append(tuple(first) + tuple(second[:1]))
            continue
        for offset in range(4):
            faces.append(
                (
                    first[offset],
                    first[(offset + 1) % 4],
                    second[(offset + 1) % 4],
                    second[offset],
                )
            )
    return MeshData("fixture", tuple(faces), vertex_count=next_vertex)


class HairTubeProbeTests(unittest.TestCase):
    """入力contractの主要なfail-closed条件を検証する。"""

    def test_regular_open_tube_reports_rings_and_root_tip(self) -> None:
        result = probe_mesh(make_open_tube())

        self.assertEqual(result.status, "accepted")
        self.assertTrue(result.is_quad_tube)
        self.assertEqual(result.station_count, 3)
        self.assertEqual(result.root_loop_count, 1)
        self.assertEqual(result.tip_loop_count, 1)
        self.assertEqual(result.cap_count, 0)
        self.assertEqual(result.pole_vertex_count, 0)
        self.assertFalse(result.section_count_change)

    def test_closed_two_cap_tube_is_accepted(self) -> None:
        tube = make_open_tube()
        faces = list(tube.faces)
        faces.insert(0, (0, 3, 2, 1))
        faces.append((8, 9, 10, 11))
        result = probe_mesh(MeshData("capped", tuple(faces), vertex_count=tube.vertex_count))

        self.assertEqual(result.status, "accepted")
        self.assertTrue(result.is_quad_tube)
        self.assertEqual(result.cap_count, 2)
        self.assertEqual(result.station_count, 3)

    def test_non_quad_face_is_rejected_before_ring_inference(self) -> None:
        tube = make_open_tube()
        faces = list(tube.faces)
        faces[0] = faces[0][:3]
        result = probe_mesh(MeshData("triangle", tuple(faces), vertex_count=tube.vertex_count))

        self.assertEqual(result.status, "gated")
        self.assertFalse(result.is_quad_tube)
        self.assertEqual(result.non_quad_face_count, 1)
        self.assertIn("NON_QUAD_FACE", result.reason_codes)
        self.assertIsNone(result.station_count)

    def test_pole_is_rejected(self) -> None:
        tube = make_open_tube()
        faces = list(tube.faces)
        faces.append((0, 12, 13, 14))
        result = probe_mesh(MeshData("pole", tuple(faces), vertex_count=15))

        self.assertEqual(result.status, "gated")
        self.assertGreater(result.pole_vertex_count, 0)
        self.assertIn("POLE_VERTEX", result.reason_codes)

    def test_section_count_change_is_ambiguous_and_rejected(self) -> None:
        result = probe_mesh(make_open_tube((4, 4, 5)))

        self.assertEqual(result.status, "gated")
        self.assertFalse(result.is_quad_tube)
        self.assertTrue(result.section_count_change)
        self.assertIn("SECTION_COUNT_CHANGE_OR_AMBIGUOUS", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
