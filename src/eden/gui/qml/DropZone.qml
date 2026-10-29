import QtQuick
import QtQuick.Shapes
import "."

// Large drop target for a .flp file, with an animated dashed outline.
Item {
    id: zone
    signal pick()
    signal dropped(string url)
    property bool hovering: drop.containsDrag || mouse.containsMouse

    Rectangle {
        anchors.fill: parent
        radius: 22
        color: zone.hovering ? Qt.rgba(0.97, 0.77, 0.19, 0.06) : Qt.rgba(1, 1, 1, 0.015)
        Behavior on color { ColorAnimation { duration: Theme.normal } }
    }

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            id: outline
            strokeColor: zone.hovering ? Theme.gold : Theme.borderStrong
            strokeWidth: 1.6
            strokeStyle: ShapePath.DashLine
            dashPattern: [6, 5]
            fillColor: "transparent"
            NumberAnimation on dashOffset { from: 0; to: 22; duration: 1400; loops: Animation.Infinite; running: zone.hovering }
            startX: 22; startY: 0.8
            PathLine { x: zone.width - 22; y: 0.8 }
            PathArc { x: zone.width - 0.8; y: 22; radiusX: 21.2; radiusY: 21.2 }
            PathLine { x: zone.width - 0.8; y: zone.height - 22 }
            PathArc { x: zone.width - 22; y: zone.height - 0.8; radiusX: 21.2; radiusY: 21.2 }
            PathLine { x: 22; y: zone.height - 0.8 }
            PathArc { x: 0.8; y: zone.height - 22; radiusX: 21.2; radiusY: 21.2 }
            PathLine { x: 0.8; y: 22 }
            PathArc { x: 22; y: 0.8; radiusX: 21.2; radiusY: 21.2 }
        }
    }

    Column {
        anchors.centerIn: parent
        spacing: 18
        scale: drop.containsDrag ? 1.04 : 1
        Behavior on scale { NumberAnimation { duration: Theme.normal; easing.type: Easing.OutBack } }

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 76; height: 76; radius: 24
            color: Theme.goldSoft
            border.width: 1
            border.color: Qt.rgba(0.97, 0.77, 0.19, 0.35)
            Icon { anchors.centerIn: parent; width: 32; height: 32; name: "upload"; color: Theme.gold; stroke: 2 }
            SequentialAnimation on y {
                loops: Animation.Infinite
                NumberAnimation { from: 0; to: -6; duration: 1500; easing.type: Easing.InOutSine }
                NumberAnimation { from: -6; to: 0; duration: 1500; easing.type: Easing.InOutSine }
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: drop.containsDrag ? "Lâche ton projet ici" : "Glisse ton projet FL Studio ici"
            color: Theme.text
            font.family: Theme.displayFamily; font.pixelSize: 22; font.weight: Font.DemiBold
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Fichier .flp · l'analyse démarre automatiquement"
            color: Theme.textMuted
            font.family: Theme.fontFamily; font.pixelSize: 14
        }
        EdenButton {
            anchors.horizontalCenter: parent.horizontalCenter
            primary: true
            text: "Choisir un projet"
            iconName: "folder"
            onClicked: zone.pick()
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        z: -1
        cursorShape: Qt.PointingHandCursor
        onClicked: zone.pick()
    }

    DropArea {
        id: drop
        anchors.fill: parent
        keys: ["text/uri-list"]
        onEntered: (drag) => {
            drag.accepted = drag.hasUrls && drag.urls.length === 1
                && drag.urls[0].toString().toLowerCase().endsWith(".flp")
        }
        onDropped: (d) => { if (d.hasUrls) zone.dropped(d.urls[0].toString()) }
    }
}
