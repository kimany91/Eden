import QtQuick
import QtQuick.Controls
import "."

ComboBox {
    id: c
    implicitHeight: 40
    textRole: "label"
    valueRole: "value"
    font.family: Theme.fontFamily
    font.pixelSize: 14

    contentItem: Text {
        leftPadding: 12
        rightPadding: 30
        text: c.displayText
        font: c.font
        color: Theme.text
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: Icon {
        x: c.width - width - 12
        y: (c.height - height) / 2
        width: 14; height: 14
        name: "chevron"
        color: Theme.textMuted
        rotation: c.popup.visible ? 180 : 0
        Behavior on rotation { NumberAnimation { duration: Theme.fast } }
    }
    background: Rectangle {
        radius: 10
        color: Theme.surface2
        border.width: 1
        border.color: c.popup.visible ? Theme.gold : (c.hovered ? Theme.borderStrong : Theme.border)
        Behavior on border.color { ColorAnimation { duration: Theme.fast } }
    }
    delegate: ItemDelegate {
        id: d
        required property var model
        required property int index
        width: c.width
        height: 38
        contentItem: Text {
            text: d.model[c.textRole]
            color: c.currentIndex === d.index ? Theme.gold : Theme.text
            font: c.font
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle { color: d.highlighted || d.hovered ? Theme.surfaceHover : "transparent"; radius: 8 }
        highlighted: c.highlightedIndex === index
    }
    popup: Popup {
        y: c.height + 4
        width: c.width
        padding: 4
        implicitHeight: contentItem.implicitHeight + 8
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: c.popup.visible ? c.delegateModel : null
        }
        background: Rectangle { radius: 10; color: Theme.surface; border.width: 1; border.color: Theme.borderStrong }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.fast } }
        exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Theme.fast } }
    }
}
