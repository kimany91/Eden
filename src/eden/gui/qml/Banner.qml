import QtQuick
import QtQuick.Layouts
import "."

// Expanding message bar: kind = "error" | "update" | "info".
Item {
    id: banner
    property string kind: "info"
    property string title: ""
    property string message: ""
    property bool shown: message !== ""
    property alias actions: actionRow.data
    signal closed()

    readonly property color tint: kind === "error" ? Theme.danger : kind === "update" ? Theme.gold : Theme.textMuted
    implicitHeight: shown ? box.implicitHeight : 0
    clip: true
    Behavior on implicitHeight { NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic } }

    Rectangle {
        id: box
        width: parent.width
        implicitHeight: layout.implicitHeight + 26
        radius: 12
        color: banner.kind === "error" ? Theme.dangerSoft : banner.kind === "update" ? Theme.goldSoft : Theme.surface
        border.width: 1
        border.color: Qt.rgba(banner.tint.r, banner.tint.g, banner.tint.b, 0.35)
        opacity: banner.shown ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.normal } }

        RowLayout {
            id: layout
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 16; rightMargin: 12 }
            spacing: 14
            Icon {
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: 2
                width: 20; height: 20
                name: banner.kind === "error" ? "warning" : banner.kind === "update" ? "redo" : "spark"
                color: banner.tint
            }
            Column {
                Layout.fillWidth: true
                spacing: 3
                Text {
                    visible: banner.title !== ""
                    width: parent.width
                    text: banner.title
                    color: Theme.text
                    font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    text: banner.message
                    color: Theme.textMuted
                    font.family: Theme.fontFamily; font.pixelSize: 13
                    wrapMode: Text.WordWrap
                }
            }
            Row { id: actionRow; spacing: 8; Layout.alignment: Qt.AlignVCenter }
            Item {
                width: 28; height: 28
                Layout.alignment: Qt.AlignTop
                Icon { anchors.centerIn: parent; width: 14; height: 14; name: "close"; color: closeArea.containsMouse ? Theme.text : Theme.textDim }
                MouseArea { id: closeArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: banner.closed() }
            }
        }
    }
}
