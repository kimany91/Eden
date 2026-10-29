import QtQuick
import "."

// Slowly drifting golden light behind the interface.
Item {
    id: bd
    clip: true
    property url glow: Qt.resolvedUrl("../../assets/glow.png")

    Image {
        source: bd.glow
        width: bd.width * 0.9; height: width
        opacity: 0.075
        x: bd.width * 0.55; y: -height * 0.45
        SequentialAnimation on x {
            loops: Animation.Infinite
            NumberAnimation { to: bd.width * 0.35; duration: 18000; easing.type: Easing.InOutSine }
            NumberAnimation { to: bd.width * 0.55; duration: 18000; easing.type: Easing.InOutSine }
        }
    }
    Image {
        source: bd.glow
        width: bd.width * 0.7; height: width
        opacity: 0.05
        x: -width * 0.3; y: bd.height - height * 0.5
        SequentialAnimation on y {
            loops: Animation.Infinite
            NumberAnimation { to: bd.height - bd.width * 0.7 * 0.7; duration: 15000; easing.type: Easing.InOutSine }
            NumberAnimation { to: bd.height - bd.width * 0.7 * 0.5; duration: 15000; easing.type: Easing.InOutSine }
        }
    }
}
