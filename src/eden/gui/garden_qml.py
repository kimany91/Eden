"""Qt Quick 3D side of the garden (``garden.py``): meshes, instance tables and the numbers the
camera needs, as QML types of the module ``Eden.Garden``.

Everything is computed once, when the garden is shown; the growth itself is done by the
shaders from one number, so no Python runs while the tree grows (a mix holds the Python
interpreter for minutes: anything Python per frame would stutter).
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Property, QByteArray, QObject, Signal, Slot
from PySide6.QtGui import QVector3D
from PySide6.QtQml import QmlElement, QmlSingleton
from PySide6.QtQuick3D import QQuick3DGeometry, QQuick3DInstancing

from eden.gui import garden

QML_IMPORT_NAME = "Eden.Garden"
QML_IMPORT_MAJOR_VERSION = 1

_Attribute = QQuick3DGeometry.Attribute


@QmlElement
class GardenMesh(QQuick3DGeometry):
    """One of ``garden.MESHES`` (property ``kind``): flat-shaded facets with vertex colours."""

    kindChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._kind = ""

    def _get_kind(self) -> str:
        return self._kind

    def _set_kind(self, kind: str) -> None:
        if kind == self._kind:
            return
        self._kind = kind
        vertices = garden.MESHES[kind]()
        self.clear()
        self.setVertexData(QByteArray(vertices.tobytes()))
        self.setStride(garden.STRIDE * 4)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        f32 = _Attribute.ComponentType.F32Type
        self.addAttribute(_Attribute.Semantic.PositionSemantic, 0, f32)
        self.addAttribute(_Attribute.Semantic.NormalSemantic, 12, f32)
        self.addAttribute(_Attribute.Semantic.ColorSemantic, 24, f32)
        low, high = vertices[:, :3].min(axis=0), vertices[:, :3].max(axis=0)
        self.setBounds(QVector3D(*low), QVector3D(*high))
        self.update()
        self.kindChanged.emit()

    kind = Property(str, _get_kind, _set_kind, notify=kindChanged)


def _table(kind: str) -> np.ndarray:
    tree = garden.grow_tree()
    if kind == "branches":
        return garden.branch_table(tree)
    if kind == "leaves":
        return garden.leaf_table(tree)
    return garden.scatter_table(kind)


@QmlElement
class GardenInstances(QQuick3DInstancing):
    """Instance table ``kind``: branches, leaves, grass, flowers or stones."""

    kindChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._kind = ""
        self._table = np.zeros((0, garden.TABLE), dtype=np.float32)

    def _get_kind(self) -> str:
        return self._kind

    def _set_kind(self, kind: str) -> None:
        if kind == self._kind:
            return
        self._kind = kind
        self._table = _table(kind)
        positions = self._table[:, [3, 7, 11]]
        # the tree is drawn whole from its first frame (the shaders hide what has not grown):
        # shadows must cover all of it
        self.setShadowBoundsMinimum(QVector3D(*(positions.min(axis=0) - 2.5)))
        self.setShadowBoundsMaximum(QVector3D(*(positions.max(axis=0) + 2.5)))
        self.markDirty()
        self.kindChanged.emit()

    kind = Property(str, _get_kind, _set_kind, notify=kindChanged)

    def getInstanceBuffer(self):
        return QByteArray(self._table.tobytes()), len(self._table)


@QmlElement
@QmlSingleton
class GardenInfo(QObject):
    """What the scene needs to know about the tree: its height as it grows (camera framing)
    and where the apple hangs."""

    @Property("QVariantList", constant=True)
    def heights(self) -> list[float]:
        return [float(h) for h in garden.grow_tree().heights]

    @Property(QVector3D, constant=True)
    def appleHang(self) -> QVector3D:
        return QVector3D(*garden.grow_tree().apple_hang)

    @Property(QVector3D, constant=True)
    def appleCenter(self) -> QVector3D:
        return QVector3D(*garden.grow_tree().apple_center)

    @Property(float, constant=True)
    def appleRadius(self) -> float:
        return garden.APPLE_RADIUS

    @Slot(float, result=float)
    def heightAt(self, growth: float) -> float:
        """For tests and tools; the scene interpolates ``heights`` itself."""
        h = garden.grow_tree().heights
        return float(np.interp(growth, np.linspace(0, 1, len(h)), h))
