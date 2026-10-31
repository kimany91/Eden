import QtQuick
import "."

// A labelled on/off pill, in Eden's theme.
Item {
    id: s
    property bool checked: true
    property string label: ""
    property string hint: ""
    signal toggled(bool value)
    implicitHeight: Math.max(26, column.implicitHeight)
    implicitWidth: parent ? parent.width : column.implicitWidth + 60

    Column {
        id: column
        anchors { left: parent.left; right: pill.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
        spacing: 2
        Text { text: s.label; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.Medium }
        Text {
            visible: s.hint !== ""
            width: column.width
            wrapMode: Text.WordWrap
            text: s.hint
            color: Theme.textDim
            font.family: Theme.fontFamily; font.pixelSize: 11
        }
    }
    Rectangle {
        id: pill
        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
        width: 42; height: 24; radius: 12
        color: s.checked ? Theme.goldSoft : Theme.surface2
        border.width: 1
        border.color: s.checked ? Qt.rgba(0.97, 0.77, 0.19, 0.5) : Theme.border
        Behavior on color { ColorAnimation { duration: Theme.fast } }
        Rectangle {
            width: 18; height: 18; radius: 9
            y: 3
            x: s.checked ? parent.width - width - 3 : 3
            color: s.checked ? Theme.gold : Theme.textDim
            Behavior on x { NumberAnimation { duration: Theme.fast } }
            Behavior on color { ColorAnimation { duration: Theme.fast } }
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: s.toggled(!s.checked)
        }
    }
}
