import QtQuick
import "."

Rectangle {
    id: card
    property bool hoverable: false
    property bool hovered: hover.hovered
    radius: Theme.radius
    color: hoverable && hovered ? Theme.surfaceHover : Theme.surface
    border.width: 1
    border.color: hoverable && hovered ? Qt.rgba(0.97, 0.77, 0.19, 0.35) : Theme.border
    Behavior on color { ColorAnimation { duration: Theme.normal } }
    Behavior on border.color { ColorAnimation { duration: Theme.normal } }
    HoverHandler { id: hover }
}
