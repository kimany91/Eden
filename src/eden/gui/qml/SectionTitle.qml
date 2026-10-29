import QtQuick
import "."

Item {
    id: st
    property string text: ""
    property int count: 0
    property int topPad: 0
    width: parent ? parent.width : 0
    height: 28 + topPad
    Row {
        anchors.bottom: parent.bottom
        spacing: 10
        Text {
            text: st.text
            color: Theme.text
            font.family: Theme.fontFamily; font.pixelSize: 16; font.weight: Font.DemiBold
        }
        Rectangle {
            visible: st.count >= 0
            anchors.verticalCenter: parent.verticalCenter
            width: countText.implicitWidth + 14; height: 20; radius: 10
            color: Theme.surface2
            Text { id: countText; anchors.centerIn: parent; text: st.count; color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 12; font.weight: Font.DemiBold }
        }
    }
}
