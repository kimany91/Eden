import QtQuick
import QtQuick.Shapes
import "."

// pending · running (spinner) · done / resumed (check pops in) · failed · skipped
Item {
    id: s
    property string status: "pending"
    implicitWidth: 26
    implicitHeight: 26

    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: s.status === "done" || s.status === "resumed" ? Theme.successSoft
             : s.status === "failed" ? Theme.dangerSoft
             : s.status === "running" ? Theme.goldSoft : Theme.surface2
        border.width: 1
        border.color: s.status === "done" || s.status === "resumed" ? Qt.rgba(0.27, 0.84, 0.6, 0.5)
                    : s.status === "failed" ? Qt.rgba(1, 0.42, 0.42, 0.5)
                    : s.status === "running" ? Qt.rgba(0.97, 0.77, 0.19, 0.5) : Theme.border
        Behavior on color { ColorAnimation { duration: Theme.normal } }
    }

    Shape {
        anchors.fill: parent
        visible: s.status === "running"
        preferredRendererType: Shape.CurveRenderer
        RotationAnimation on rotation { running: s.status === "running"; loops: Animation.Infinite; from: 0; to: 360; duration: 900 }
        ShapePath {
            strokeColor: Theme.gold
            strokeWidth: 2.4
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc { centerX: s.width / 2; centerY: s.height / 2; radiusX: s.width / 2 - 5; radiusY: s.width / 2 - 5; startAngle: 0; sweepAngle: 250 }
        }
    }

    Icon {
        anchors.centerIn: parent
        width: 14; height: 14
        name: s.status === "failed" ? "close" : s.status === "skipped" ? "dash" : "check"
        color: s.status === "failed" ? Theme.danger : s.status === "skipped" ? Theme.textDim : Theme.success
        visible: s.status === "done" || s.status === "resumed" || s.status === "failed" || s.status === "skipped"
        scale: visible ? 1 : 0.3
        Behavior on scale { NumberAnimation { duration: 380; easing.type: Easing.OutBack } }
    }

    Rectangle {
        anchors.centerIn: parent
        visible: s.status === "pending"
        width: 6; height: 6; radius: 3
        color: Theme.textDim
    }
}
