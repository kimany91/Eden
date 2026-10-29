import QtQuick
import QtQuick.Controls
import "."

// Primary (gold) or secondary button with hover lift, press scale and a light sweep.
Button {
    id: btn
    property bool primary: false
    property string iconName: ""
    property bool compact: false

    hoverEnabled: true
    padding: 0
    implicitHeight: compact ? 38 : 48
    implicitWidth: row.implicitWidth + (compact ? 30 : 44)
    font.family: Theme.fontFamily
    font.pixelSize: compact ? 13 : 15
    font.weight: Font.DemiBold
    scale: down ? 0.97 : 1
    Behavior on scale { NumberAnimation { duration: Theme.fast; easing.type: Easing.OutCubic } }
    opacity: enabled ? 1 : 0.45
    Behavior on opacity { NumberAnimation { duration: Theme.normal } }

    background: Rectangle {
        id: bg
        radius: btn.compact ? 10 : 12
        clip: true
        color: btn.primary ? Theme.gold : (btn.hovered ? Theme.surfaceHover : Theme.surface2)
        border.width: btn.primary ? 0 : 1
        border.color: btn.hovered && btn.enabled ? Qt.rgba(0.97, 0.77, 0.19, 0.55) : Theme.border
        Behavior on color { ColorAnimation { duration: Theme.normal } }
        Behavior on border.color { ColorAnimation { duration: Theme.normal } }

        gradient: btn.primary ? goldGradient : null
        Gradient {
            id: goldGradient
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: btn.hovered ? Theme.goldBright : "#FFD443" }
            GradientStop { position: 1; color: btn.hovered ? Theme.gold : Theme.goldDeep }
        }

        // light sweep when hovered
        Rectangle {
            id: sweep
            visible: btn.primary && btn.enabled
            width: parent.height * 1.2
            height: parent.height * 3
            y: -parent.height
            rotation: 20
            x: -width * 2
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "#00FFFFFF" }
                GradientStop { position: 0.5; color: "#55FFFFFF" }
                GradientStop { position: 1; color: "#00FFFFFF" }
            }
            NumberAnimation on x {
                id: sweepAnim
                running: false
                from: -sweep.width * 2
                to: bg.width + sweep.width
                duration: 900
                easing.type: Easing.InOutCubic
            }
        }
    }

    onHoveredChanged: if (hovered && primary && enabled) sweepAnim.restart()

    contentItem: Item {
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 10
            Icon {
                visible: btn.iconName !== ""
                name: btn.iconName
                width: btn.compact ? 16 : 18
                height: width
                anchors.verticalCenter: parent.verticalCenter
                color: btn.primary ? Theme.goldInk : Theme.text
            }
            Text {
                text: btn.text
                font: btn.font
                color: btn.primary ? Theme.goldInk : Theme.text
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
