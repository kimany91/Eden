import QtQuick
import QtQuick.Shapes
import "."

// Eden's low-poly tree, facet by facet; grow() plays the growing animation.
Item {
    id: art
    property var triangles: []
    property bool grown: false
    property int stagger: 7
    readonly property int growDuration: triangles.length * stagger + 520
    readonly property real s: width / 1024

    function grow() { grown = true }

    Repeater {
        model: art.triangles
        delegate: Shape {
            id: tri
            required property var modelData
            required property int index
            anchors.fill: parent
            readonly property var p: modelData.pts
            readonly property real cx: (p[0][0] + p[1][0] + p[2][0]) / 3 * art.s
            readonly property real cy: (p[0][1] + p[1][1] + p[2][1]) / 3 * art.s
            property real k: art.grown ? 1 : 0.15
            opacity: art.grown ? 1 : 0
            Behavior on k {
                SequentialAnimation {
                    PauseAnimation { duration: tri.index * art.stagger }
                    NumberAnimation { duration: 460; easing.type: Easing.OutBack; easing.overshoot: 1.6 }
                }
            }
            Behavior on opacity {
                SequentialAnimation {
                    PauseAnimation { duration: tri.index * art.stagger }
                    NumberAnimation { duration: 260 }
                }
            }
            transform: Scale { origin.x: tri.cx; origin.y: tri.cy; xScale: tri.k; yScale: tri.k }
            ShapePath {
                fillColor: tri.modelData.color
                strokeColor: "#000000"
                strokeWidth: Math.max(1, 2.2 * art.s)
                joinStyle: ShapePath.RoundJoin
                startX: tri.p[0][0] * art.s; startY: tri.p[0][1] * art.s
                PathLine { x: tri.p[1][0] * art.s; y: tri.p[1][1] * art.s }
                PathLine { x: tri.p[2][0] * art.s; y: tri.p[2][1] * art.s }
                PathLine { x: tri.p[0][0] * art.s; y: tri.p[0][1] * art.s }
            }
        }
    }
}
