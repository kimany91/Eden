import QtQuick
import QtQuick.Controls
import "."

Slider {
    id: s
    implicitHeight: 28
    background: Rectangle {
        x: s.leftPadding
        y: s.topPadding + s.availableHeight / 2 - height / 2
        width: s.availableWidth
        height: 6
        radius: 3
        color: Theme.surface2
        Rectangle {
            width: s.visualPosition * parent.width
            height: parent.height
            radius: 3
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: Theme.goldDeep }
                GradientStop { position: 1; color: Theme.goldBright }
            }
        }
    }
    handle: Rectangle {
        x: s.leftPadding + s.visualPosition * (s.availableWidth - width)
        y: s.topPadding + s.availableHeight / 2 - height / 2
        width: 22; height: 22; radius: 11
        color: Theme.text
        border.width: 4
        border.color: Theme.gold
        scale: s.pressed ? 1.15 : (hover.hovered ? 1.07 : 1)
        Behavior on scale { NumberAnimation { duration: Theme.fast; easing.type: Easing.OutBack } }
        HoverHandler { id: hover }
    }
}
