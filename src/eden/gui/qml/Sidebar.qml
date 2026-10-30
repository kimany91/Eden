import QtQuick
import QtQuick.Layouts
import "."

Rectangle {
    id: side
    color: Theme.sidebar
    property string shownPage: "home"
    signal picked(string name)
    readonly property var pages: ["home", "analysis", "render", "mix", "mix"]
    readonly property var steps: [
        { title: "Projet", sub: "Choisir dans tes projets" },
        { title: "Analyse", sub: "Pistes, voix, effets" },
        { title: "Son de FL Studio", sub: "Pistes, voix sèches" },
        { title: "Mixage Eden", sub: "Mix et mastering" },
        { title: "Export WAV", sub: "Dossier et format" }
    ]
    readonly property int current: shownPage === "home" ? 0 : shownPage === "analysis" ? 1
                                  : shownPage === "render" ? 2 : controller.exportMessage !== "" ? 4 : 3
    function stepDone(i) {  // from what exists, whatever page is shown
        if (i <= 1) return controller.report.name !== undefined
        if (i === 2) return controller.renderSummary.ok === true
        if (i === 3) return controller.mixResult.id !== undefined
        return controller.exportMessage !== ""
    }

    Rectangle { anchors { right: parent.right; top: parent.top; bottom: parent.bottom } width: 1; color: Theme.border }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 0

        Row {
            spacing: 12
            Layout.bottomMargin: 34
            Image {
                source: controller.logoUrl
                width: 42; height: 42
                smooth: true; mipmap: true
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                Text { text: "Eden"; color: Theme.text; font.family: Theme.displayFamily; font.pixelSize: 20; font.weight: Font.DemiBold; font.letterSpacing: 1.5 }
                Text { text: "version " + controller.version; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: 11 }
            }
        }

        Text {
            text: "ÉTAPES"
            color: Theme.textDim
            font.family: Theme.fontFamily; font.pixelSize: 11; font.letterSpacing: 2
            Layout.bottomMargin: 12
        }

        Item {
            Layout.fillWidth: true
            implicitHeight: stepCol.implicitHeight

            // sliding highlight behind the active step
            Rectangle {
                width: parent.width
                height: 58
                radius: 12
                color: Theme.goldSoft
                border.width: 1
                border.color: Qt.rgba(0.97, 0.77, 0.19, 0.25)
                y: side.current * 64
                Behavior on y { NumberAnimation { duration: 520; easing.type: Easing.OutCubic } }
            }

            Column {
                id: stepCol
                width: parent.width
                spacing: 6
                Repeater {
                    model: side.steps
                    delegate: Item {
                        required property var modelData
                        required property int index
                        width: stepCol.width
                        height: 58
                        readonly property bool isCurrent: index === side.current
                        readonly property bool done: side.stepDone(index)

                        MouseArea {  // a done step opens its page again
                            anchors.fill: parent
                            enabled: parent.done && index > 0 && !controller.busy
                            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                            onClicked: side.picked(side.pages[index])
                        }

                        Rectangle {
                            id: badge
                            x: 12
                            anchors.verticalCenter: parent.verticalCenter
                            width: 30; height: 30; radius: 15
                            color: parent.done ? Theme.successSoft : parent.isCurrent ? Theme.gold : Theme.surface2
                            border.width: 1
                            border.color: parent.done ? Qt.rgba(0.27, 0.84, 0.6, 0.5) : parent.isCurrent ? Theme.gold : Theme.border
                            Behavior on color { ColorAnimation { duration: Theme.normal } }
                            Text {
                                anchors.centerIn: parent
                                visible: !parent.parent.done
                                text: index + 1
                                color: parent.parent.isCurrent ? Theme.goldInk : Theme.textMuted
                                font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold
                            }
                            Icon {
                                anchors.centerIn: parent
                                width: 15; height: 15
                                name: "check"; color: Theme.success
                                visible: parent.parent.done
                                scale: visible ? 1 : 0.2
                                Behavior on scale { NumberAnimation { duration: 400; easing.type: Easing.OutBack } }
                            }
                        }
                        Column {
                            anchors.left: badge.right
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 2
                            Text {
                                text: modelData.title
                                color: parent.parent.isCurrent ? Theme.text : Theme.textMuted
                                font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold
                            }
                            Text {
                                text: modelData.sub
                                color: Theme.textDim
                                font.family: Theme.fontFamily; font.pixelSize: 12
                            }
                        }
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }

        // current project
        Card {
            Layout.fillWidth: true
            visible: controller.projectName !== ""
            implicitHeight: projCol.implicitHeight + 28
            Column {
                id: projCol
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
                spacing: 10
                Text { text: "PROJET"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: 11; font.letterSpacing: 2 }
                Text {
                    width: parent.width
                    text: controller.projectName
                    elide: Text.ElideRight
                    color: Theme.text
                    font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold
                }
                EdenButton {
                    compact: true
                    width: parent.width
                    text: "Nouveau projet"
                    iconName: "plus"
                    enabled: !controller.busy
                    onClicked: controller.goHome()
                }
            }
        }

        Text {
            Layout.topMargin: 16
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: "Ton projet FL Studio n'est jamais modifié."
            color: Theme.textDim
            font.family: Theme.fontFamily; font.pixelSize: 11
        }
    }
}
