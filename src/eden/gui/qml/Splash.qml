import QtQuick
import "."

// Opening animation: the tree grows facet by facet, then the name appears.
Rectangle {
    id: splash
    property bool play: true
    signal finished()
    color: "#000000"
    visible: opacity > 0.01

    TreeArt {
        id: tree
        triangles: controller.treeTriangles
        width: Math.min(parent.width, parent.height) * 0.46
        height: width
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -50
    }

    Column {
        id: words
        anchors.top: tree.bottom
        anchors.topMargin: -6
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 6
        opacity: 0
        transform: Translate { id: wordsShift; y: 16 }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Eden"
            color: Theme.text
            font.family: Theme.displayFamily
            font.pixelSize: 46
            font.weight: Font.DemiBold
            font.letterSpacing: 6
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "MIXAGE VOCAL AUTOMATIQUE"
            color: Theme.gold
            font.family: Theme.fontFamily
            font.pixelSize: 12
            font.letterSpacing: 4
        }
    }

    SequentialAnimation {
        id: intro
        PauseAnimation { duration: 250 }
        ScriptAction { script: tree.grow() }
        PauseAnimation { duration: tree.growDuration }
        ParallelAnimation {
            NumberAnimation { target: words; property: "opacity"; to: 1; duration: 600; easing.type: Easing.OutCubic }
            NumberAnimation { target: wordsShift; property: "y"; to: 0; duration: 700; easing.type: Easing.OutCubic }
        }
        PauseAnimation { duration: 750 }
        ScriptAction { script: splash.close() }
    }

    NumberAnimation { id: fadeOut; target: splash; property: "opacity"; to: 0; duration: 650; easing.type: Easing.InOutCubic }

    function close() {
        intro.stop()
        fadeOut.start()
        finished()
    }

    MouseArea { anchors.fill: parent; onClicked: splash.close() }

    Component.onCompleted: {
        if (play) intro.start()
        else { opacity = 0; finished() }
    }
}
