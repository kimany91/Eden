"""The garden's tree (gui/garden.py): it grows in the order of Eden's work, all of it by the end of the
master, from one seed to the same tree every time, and the Qt Quick 3D types hand it to the GPU whole."""

import math
import os

import numpy as np
import pytest

from eden.gui import garden
from eden.gui.garden import APPLE_RADIUS, COTYLEDON, GROWN, MESHES, STRIDE, TABLE, grow_tree

TREE = grow_tree()
REAL_LEAVES = TREE.leaf_t[:, 2] > 1  # the sprout's two first leaves wither; the others never do


def _leaves_open_by(t: float) -> int:
    return int(np.sum(REAL_LEAVES & (TREE.leaf_t[:, 1] <= t)))


def _grown_tip(seg: int) -> np.ndarray:
    return TREE.seg_start[seg] + TREE.seg_axis[seg][:, 1] * TREE.seg_length[seg]


def test_the_same_tree_every_time():
    again = garden.grow_tree.__wrapped__()
    assert np.array_equal(again.seg_start, TREE.seg_start) and np.array_equal(again.leaf_t, TREE.leaf_t)


def test_the_tree_grows_in_the_order_of_edens_work():
    # analysis (0 → 0.08): the sprout's two first leaves come out, nothing else
    assert TREE.heights[8] == pytest.approx(0.32, abs=0.01)
    assert _leaves_open_by(0.08) == 0
    cotyledons = TREE.leaf_t[~REAL_LEAVES]
    assert len(cotyledons) == 2 and np.allclose(cotyledons, COTYLEDON)
    # FL Studio's renders (0.08 → 0.40): the stem, the first branch, its first leaves
    first_branch = TREE.seg_t[9:, 0].min()  # segments 0–8 are the trunk
    assert 0.08 < first_branch < 0.30
    assert _leaves_open_by(0.40) >= 50
    # the mix (0.40 → 0.82) and the master (→ 0.97): the crown fills, everything has grown by then
    assert _leaves_open_by(0.82) > 3 * _leaves_open_by(0.40)
    assert TREE.seg_t.max() <= GROWN + 1e-9 and TREE.leaf_t[REAL_LEAVES, 1].max() <= GROWN + 1e-9
    # the first leaves are gone once the real ones are out
    assert COTYLEDON[2] > 0.08 and COTYLEDON[3] < 0.40
    # the tree only grows
    assert np.all(np.diff(TREE.heights) >= -1e-9) and TREE.heights[0] == 0.0
    assert 3.5 < TREE.heights[-1] < 5.5  # the wood's top; the crown's leaves rise a little above it


def test_a_branch_grows_only_from_a_grown_point_and_a_leaf_only_once_its_twig_is_there():
    tips = np.array([_grown_tip(i) for i in range(len(TREE.seg_start))])
    for i in range(1, len(TREE.seg_start)):
        # each segment starts at the tip (or the base) of a segment already grown, or on the ground
        start = TREE.seg_start[i]
        if np.allclose(start, 0):
            continue
        parents = np.flatnonzero(np.linalg.norm(tips - start, axis=1) < 1e-6)
        assert parents.size and TREE.seg_t[parents, 1].min() <= TREE.seg_t[i, 0] + 1e-9, i
    # every leaf opens next to a twig already grown (crowns cross: the nearest twig may be younger)
    for pos, (t0, *_) in zip(TREE.leaf_pos[REAL_LEAVES], TREE.leaf_t[REAL_LEAVES], strict=True):
        near = np.linalg.norm(tips - pos, axis=1) < 1.0
        assert np.any(near & (TREE.seg_t[:, 1] <= t0 + 1e-9))


def test_the_crown_is_a_dome_like_the_logo():
    leaves = TREE.leaf_pos[REAL_LEAVES]
    reach = np.hypot(leaves[:, 0], leaves[:, 2])
    assert np.percentile(reach, 90) > 1.4  # as wide as it is tall, around the trunk
    assert leaves[:, 1].min() > 1.0  # no leaf down the trunk
    # all round the trunk: leaves in every quarter
    angles = np.degrees(np.arctan2(leaves[:, 2], leaves[:, 0])) % 360
    assert all(np.sum((angles >= q) & (angles < q + 90)) > 50 for q in (0, 90, 180, 270))


def test_the_apple_hangs_under_an_outer_twig_and_falls_clear_to_the_ground():
    center = TREE.apple_center
    assert center[1] - APPLE_RADIUS > 1.5  # a real fall
    assert np.hypot(center[0], center[2]) > 1.2  # out from the trunk
    # nothing of the tree under it on the way down (segments within 15 cm of its vertical)
    for i in range(len(TREE.seg_start)):
        for k in np.linspace(0, 1, 6):
            p = TREE.seg_start[i] + TREE.seg_axis[i][:, 1] * TREE.seg_length[i] * k
            if p[1] < center[1] - APPLE_RADIUS:
                assert np.hypot(p[0] - center[0], p[2] - center[2]) > 0.15 + TREE.seg_radius[i]


@pytest.mark.parametrize("kind", sorted(MESHES))
def test_meshes_are_flat_shaded_facets_with_unit_normals_and_colours(kind):
    v = MESHES[kind]()
    assert v.dtype == np.float32 and v.shape[1] == STRIDE and len(v) % 3 == 0 and np.isfinite(v).all()
    normals = v[:, 3:6]
    assert np.allclose(np.linalg.norm(normals, axis=1), 1, atol=1e-4)
    # one normal per facet, matching the winding (a facet seen from its front is lit)
    tri = v.reshape(-1, 3, STRIDE)
    face = np.cross(tri[:, 1, :3] - tri[:, 0, :3], tri[:, 2, :3] - tri[:, 0, :3])
    big = np.linalg.norm(face, axis=1) > 1e-9
    assert np.all(np.einsum("ij,ij->i", face[big], tri[big, 0, 3:6]) > 0)
    assert np.all((v[:, 6:9] >= 0) & (v[:, 6:9] <= 1.2)) and np.all(v[:, 9] == 1)


@pytest.mark.parametrize("kind", ["seed", "mound", "apple", "stone"])
def test_round_meshes_face_outwards(kind):
    tri = MESHES[kind]().reshape(-1, 3, STRIDE)
    center = tri[:, :, :3].reshape(-1, 3).mean(axis=0)
    outward = tri[:, :, :3].mean(axis=1) - center
    facing = np.einsum("ij,ij->i", outward, tri[:, 0, 3:6])
    assert np.mean(facing > 0) > 0.85  # the stalk and the apple's leaf aside


def test_instance_tables_place_every_segment_and_leaf():
    branches = garden.branch_table(TREE)
    assert branches.shape == (len(TREE.seg_start), TABLE)
    assert np.allclose(branches[:, [3, 7, 11]], TREE.seg_start)
    # the mesh's +y (unit length) becomes the segment, a little longer to close the joints
    y_axis = branches[:, [1, 5, 9]]
    lengths = np.linalg.norm(y_axis, axis=1)
    assert np.all(lengths >= TREE.seg_length) and np.all(lengths < TREE.seg_length + 0.2)
    assert np.allclose(branches[:, 16:18], TREE.seg_t)
    leaves = garden.leaf_table(TREE)
    assert leaves.shape == (len(TREE.leaf_pos), TABLE)
    assert np.allclose(leaves[:, 16:20], TREE.leaf_t) and np.allclose(leaves[:, 12:15], TREE.leaf_color)
    for kind in ("grass", "flowers", "stones"):
        table = garden.scatter_table(kind)
        reach = np.hypot(table[:, 3], table[:, 11])
        assert len(table) and reach.min() > 0.5  # never on the tree's mound


def test_the_tree_wears_the_logos_colours():
    trunk, crown = garden.palette()
    assert len(trunk) > 20 and len(crown) > 100
    assert np.all(crown[:, 0] > crown[:, 2])  # yellows
    assert all(any(np.allclose(c, k) for k in crown) for c in TREE.leaf_color[:20])


# -- Qt Quick 3D types (module Eden.Garden) -------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtGui = pytest.importorskip("PySide6.QtGui")
    return QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])


def test_the_qt_types_hand_the_gpu_the_whole_tree(app):
    from eden.gui.garden_qml import GardenInfo, GardenInstances, GardenMesh

    mesh = GardenMesh()
    mesh.kind = "leaf"
    assert mesh.vertexData().size() == MESHES["leaf"]().nbytes and mesh.stride() == STRIDE * 4
    leaves = GardenInstances()
    leaves.kind = "leaves"
    data, count = leaves.getInstanceBuffer()
    assert count == len(TREE.leaf_pos) and data.size() == count * TABLE * 4
    info = GardenInfo()
    assert len(info.heights) == 101 and info.heightAt(1.0) == pytest.approx(TREE.heights[-1])
    assert math.isclose(info.appleCenter.y(), TREE.apple_center[1], rel_tol=1e-6)
