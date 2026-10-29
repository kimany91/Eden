import QtQuick
import "."

// Container whose content rises and fades in after `delay` ms, each time it is created.
Item {
    id: reveal
    property int delay: 0
    default property alias content: holder.data
    implicitWidth: holder.childrenRect.width
    implicitHeight: holder.childrenRect.height

    Item {
        id: holder
        anchors.fill: parent
        opacity: 0
        transform: Translate { id: shift; y: 18 }
    }

    SequentialAnimation {
        running: true
        PauseAnimation { duration: reveal.delay }
        ParallelAnimation {
            NumberAnimation { target: holder; property: "opacity"; to: 1; duration: 480; easing.type: Easing.OutCubic }
            NumberAnimation { target: shift; property: "y"; to: 0; duration: 620; easing.type: Easing.OutCubic }
        }
    }
}
