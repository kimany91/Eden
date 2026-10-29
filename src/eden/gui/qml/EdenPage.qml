import QtQuick
import "."

// A page that fades and slides in when it becomes active.
Item {
    id: page
    property bool active: false
    opacity: active ? 1 : 0
    visible: opacity > 0.01
    enabled: active
    transform: Translate { y: page.active ? 0 : 26; Behavior on y { NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } } }
    Behavior on opacity { NumberAnimation { duration: Theme.slow; easing.type: Easing.OutCubic } }
}
