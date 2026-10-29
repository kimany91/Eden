import QtQuick
import QtQuick.Shapes
import "."

// Circular progress: smooth arc for real progress, rotating comet while working.
Item {
    id: ring
    property real value: 0          // 0..1, real progress reported by the engine
    property bool busy: false
    property real thickness: 10
    property string caption: ""
    implicitWidth: 200
    implicitHeight: 200

    property real shown: value
    Behavior on shown { NumberAnimation { duration: 700; easing.type: Easing.OutCubic } }

    readonly property real r: Math.min(width, height) / 2 - thickness

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: Theme.surface2
            strokeWidth: ring.thickness
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc { centerX: ring.width / 2; centerY: ring.height / 2; radiusX: ring.r; radiusY: ring.r; startAngle: 0; sweepAngle: 360 }
        }
        ShapePath {
            strokeColor: Theme.gold
            strokeWidth: ring.thickness
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc { centerX: ring.width / 2; centerY: ring.height / 2; radiusX: ring.r; radiusY: ring.r; startAngle: -90; sweepAngle: Math.max(0.01, 360 * ring.shown) }
        }
    }

    // comet showing the engine is working (independent from the real value)
    Shape {
        anchors.fill: parent
        visible: ring.busy
        opacity: 0.55
        preferredRendererType: Shape.CurveRenderer
        RotationAnimation on rotation { running: ring.busy; loops: Animation.Infinite; from: 0; to: 360; duration: 1600 }
        ShapePath {
            strokeColor: Theme.goldBright
            strokeWidth: ring.thickness * 0.35
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc { centerX: ring.width / 2; centerY: ring.height / 2; radiusX: ring.r + ring.thickness * 1.1; radiusY: ring.r + ring.thickness * 1.1; startAngle: 0; sweepAngle: 40 }
        }
    }

    Column {
        anchors.centerIn: parent
        spacing: 2
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Math.round(ring.shown * 100) + " %"
            color: Theme.text
            font.family: Theme.displayFamily
            font.pixelSize: ring.width * 0.2
            font.weight: Font.DemiBold
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: ring.caption
            color: Theme.textMuted
            font.family: Theme.fontFamily
            font.pixelSize: 12
        }
    }
}
