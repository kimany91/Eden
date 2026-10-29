import QtQuick
import QtQuick.Controls
import "."

TextField {
    id: f
    implicitHeight: 40
    color: Theme.text
    selectionColor: Theme.goldDeep
    selectedTextColor: Theme.goldInk
    placeholderTextColor: Theme.textDim
    font.family: Theme.fontFamily
    font.pixelSize: 14
    leftPadding: 12
    rightPadding: 12
    background: Rectangle {
        radius: 10
        color: Theme.surface2
        border.width: 1
        border.color: f.activeFocus ? Theme.gold : (hover.hovered ? Theme.borderStrong : Theme.border)
        Behavior on border.color { ColorAnimation { duration: Theme.fast } }
        HoverHandler { id: hover }
    }
}
