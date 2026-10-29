import QtQuick
import QtQuick.Layouts
import "."

EdenPage {
    id: page
    signal pickProject()

    ColumnLayout {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(parent.width - 40, 880)
        spacing: 30

        Reveal {
            Layout.fillWidth: true
            implicitHeight: heading.implicitHeight
            delay: 80
            Column {
                id: heading
                width: parent.width
                spacing: 10
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: "Tes voix, mixées comme un pro."
                    color: Theme.text
                    font.family: Theme.displayFamily; font.pixelSize: 38; font.weight: Font.DemiBold
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    text: "Eden lit ton projet FL Studio, récupère le son de chaque piste avec tous tes effets, puis s'occupe du mixage."
                    color: Theme.textMuted
                    font.family: Theme.fontFamily; font.pixelSize: 16
                }
            }
        }

        Reveal {
            Layout.fillWidth: true
            Layout.preferredHeight: 320
            delay: 220
            DropZone {
                anchors.fill: parent
                onPick: page.pickProject()
                onDropped: (url) => controller.openProject(url)
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 16
            Repeater {
                model: [
                    { icon: "lock", title: "Projet intact", text: "Ton .flp n'est jamais modifié, et rien n'est ajouté dans son dossier." },
                    { icon: "wave", title: "Ton son, à l'identique", text: "C'est FL Studio qui joue chaque piste : Auto-Tune, delays, échos et automations restent tels quels." },
                    { icon: "crown", title: "Mix et mastering pro", text: "Tonalité, espace, stéréo, basses, puis un master fort et propre pour les plateformes." }
                ]
                delegate: Reveal {
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true
                    Layout.preferredHeight: 132
                    delay: 380 + index * 110
                    Card {
                        anchors.fill: parent
                        hoverable: true
                        Column {
                            anchors { fill: parent; margins: 18 }
                            spacing: 8
                            Rectangle {
                                width: 34; height: 34; radius: 10
                                color: Theme.goldSoft
                                Icon { anchors.centerIn: parent; width: 18; height: 18; name: modelData.icon; color: Theme.gold }
                            }
                            Text { text: modelData.title; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 15; font.weight: Font.DemiBold }
                            Text {
                                width: parent.width
                                text: modelData.text
                                wrapMode: Text.WordWrap
                                color: Theme.textMuted
                                font.family: Theme.fontFamily; font.pixelSize: 13
                            }
                        }
                    }
                }
            }
        }
    }
}
