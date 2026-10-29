import QtQuick
import "."

Rectangle {
    id: chip
    property string text: ""
    property color tint: Theme.textMuted
    property bool filled: false
    property bool dim: false
    implicitHeight: 26
    implicitWidth: label.implicitWidth + 22
    radius: 13
    color: filled ? Qt.rgba(tint.r, tint.g, tint.b, 0.16) : Theme.surface2
    border.width: 1
    border.color: filled ? Qt.rgba(tint.r, tint.g, tint.b, 0.35) : Theme.border
    opacity: dim ? 0.5 : 1
    Text {
        id: label
        anchors.centerIn: parent
        text: chip.text
        color: chip.filled ? chip.tint : Theme.textMuted
        font.family: Theme.fontFamily
        font.pixelSize: 12
        font.weight: Font.Medium
        font.strikeout: chip.dim
    }
}
