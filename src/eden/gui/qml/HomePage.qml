import QtQuick
import QtQuick.Layouts
import "."

// Your FL Studio projects, from the folder where you save them: a click and Eden starts.
EdenPage {
    id: page
    signal chooseFolder()
    property string query: ""
    readonly property var shown: controller.projects.filter(p => query === ""
                                                           || p.name.toLowerCase().includes(query.toLowerCase()))

    // what was saved in FL Studio meanwhile shows up when you come back
    onActiveChanged: if (active) controller.refreshProjects()
    Connections {
        target: Qt.application
        function onStateChanged() {
            if (page.active && Qt.application.state === Qt.ApplicationActive)
                controller.refreshProjects()
        }
    }

    ColumnLayout {
        anchors { top: parent.top; bottom: parent.bottom; horizontalCenter: parent.horizontalCenter }
        width: Math.min(parent.width - 40, 900)
        spacing: 26

        Reveal {
            Layout.fillWidth: true
            Layout.topMargin: 6
            implicitHeight: heading.implicitHeight
            delay: 80
            Column {
                id: heading
                width: parent.width
                spacing: 8
                Text {
                    text: "Tes voix, mixées comme un pro."
                    color: Theme.text
                    font.family: Theme.displayFamily; font.pixelSize: 32; font.weight: Font.DemiBold
                }
                Text {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: "Clique sur un projet : Eden récupère le son de chaque piste avec tous tes effets, puis fait le mix et le master."
                    color: Theme.textMuted
                    font.family: Theme.fontFamily; font.pixelSize: 15
                }
            }
        }

        // the first time: where are the projects?
        Reveal {
            Layout.fillWidth: true
            implicitHeight: ask.implicitHeight
            visible: controller.projectsFolder === ""
            delay: 220
            Card {
                id: ask
                width: parent.width
                implicitHeight: askCol.implicitHeight + 56
                Column {
                    id: askCol
                    anchors.centerIn: parent
                    width: parent.width - 56
                    spacing: 14
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 64; height: 64; radius: 20
                        color: Theme.goldSoft
                        Icon { anchors.centerIn: parent; width: 28; height: 28; name: "folder"; color: Theme.gold }
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Où sont tes projets FL Studio ?"
                        color: Theme.text
                        font.family: Theme.displayFamily; font.pixelSize: 22; font.weight: Font.DemiBold
                    }
                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: "Choisis une seule fois le dossier où tu enregistres tes projets : Eden s'en souvient et te les montre tous ici."
                        color: Theme.textMuted
                        font.family: Theme.fontFamily; font.pixelSize: 14
                    }
                    EdenButton {
                        anchors.horizontalCenter: parent.horizontalCenter
                        primary: true
                        text: "Choisir le dossier"
                        iconName: "folder"
                        onClicked: page.chooseFolder()
                    }
                }
            }
        }
        Item {  // keeps the question under the heading
            Layout.fillHeight: true
            visible: controller.projectsFolder === ""
        }

        // the projects of that folder
        Reveal {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: controller.projectsFolder !== ""
            delay: 220
            ColumnLayout {
                anchors.fill: parent
                spacing: 14

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Column {
                        Layout.fillWidth: true
                        spacing: 4
                        Text {
                            text: controller.projects.length > 0 ? "Tes projets FL Studio (" + controller.projects.length + ")"
                                                                : "Tes projets FL Studio"
                            color: Theme.text
                            font.family: Theme.fontFamily; font.pixelSize: 19; font.weight: Font.DemiBold
                        }
                        Text {
                            width: parent.width
                            text: controller.projectsFolder
                            elide: Text.ElideMiddle
                            color: Theme.textDim
                            font.family: Theme.fontFamily; font.pixelSize: 12
                        }
                    }
                    EdenField {
                        objectName: "projectSearch"
                        Layout.preferredWidth: 240
                        visible: controller.projects.length > 6
                        placeholderText: "Rechercher un projet"
                        onTextChanged: page.query = text
                    }
                    EdenButton {
                        compact: true
                        text: "Changer de dossier"
                        iconName: "folder"
                        onClicked: page.chooseFolder()
                    }
                }

                Card {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    ListView {
                        id: list
                        objectName: "projectList"
                        anchors { fill: parent; margins: 8 }
                        clip: true
                        spacing: 2
                        model: page.shown
                        boundsBehavior: Flickable.StopAtBounds
                        delegate: Rectangle {
                            required property var modelData
                            width: list.width
                            height: 60
                            radius: Theme.radiusSmall
                            color: row.containsMouse ? Theme.surfaceHover : "transparent"
                            Behavior on color { ColorAnimation { duration: Theme.fast } }

                            RowLayout {
                                anchors { fill: parent; leftMargin: 12; rightMargin: 16 }
                                spacing: 14
                                Rectangle {
                                    width: 36; height: 36; radius: 11
                                    color: Theme.goldSoft
                                    Icon { anchors.centerIn: parent; width: 18; height: 18; name: "wave"; color: Theme.gold }
                                }
                                Column {
                                    Layout.fillWidth: true
                                    spacing: 3
                                    Text {
                                        width: parent.width
                                        text: modelData.name
                                        elide: Text.ElideRight
                                        color: Theme.text
                                        font.family: Theme.fontFamily; font.pixelSize: 15; font.weight: Font.DemiBold
                                    }
                                    Text {
                                        width: parent.width
                                        text: modelData.folder !== "" ? modelData.folder + "  ·  " + modelData.saved : modelData.saved
                                        elide: Text.ElideMiddle
                                        color: Theme.textMuted
                                        font.family: Theme.fontFamily; font.pixelSize: 12
                                    }
                                }
                                Row {
                                    spacing: 6
                                    opacity: row.containsMouse ? 1 : 0
                                    Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: "Mixer"
                                        color: Theme.gold
                                        font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold
                                    }
                                    Icon {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 16; height: 16; name: "chevron"; color: Theme.gold; rotation: -90
                                    }
                                }
                            }
                            MouseArea {
                                id: row
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                enabled: !controller.busy
                                onClicked: controller.openProject(modelData.path)
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        width: parent.width - 60
                        visible: list.count === 0
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: controller.projectsMessage !== "" ? controller.projectsMessage
                              : "Aucun projet ne s'appelle « " + page.query + " »."
                        color: Theme.textMuted
                        font.family: Theme.fontFamily; font.pixelSize: 14
                    }
                }
            }
        }
    }
}
