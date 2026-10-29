import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

EdenPage {
    id: page
    readonly property bool rendering: controller.stage === "rendering"
    readonly property var sum: controller.renderSummary

    ColumnLayout {
        anchors.fill: parent
        spacing: 20

        RowLayout {
            Layout.fillWidth: true
            Column {
                Layout.fillWidth: true
                spacing: 6
                Text {
                    text: page.rendering ? "FL Studio travaille pour toi…" : "Le son de ton projet est prêt"
                    color: Theme.text
                    font.family: Theme.displayFamily; font.pixelSize: 30; font.weight: Font.DemiBold
                }
                Text {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: page.rendering
                          ? "Eden ouvre FL Studio en arrière-plan sur des copies de ton projet et récupère chaque groupe de pistes, avec tous tes effets."
                          : "Chaque groupe de pistes a été rendu par FL Studio puis vérifié par Eden."
                    color: Theme.textMuted
                    font.family: Theme.fontFamily; font.pixelSize: 15
                }
            }
            EdenButton {
                visible: !page.rendering && !!page.sum.folder
                text: "Ouvrir le dossier"
                iconName: "folder"
                onClicked: controller.openRenderFolder()
            }
            EdenButton {
                visible: !page.rendering
                text: "Relancer"
                iconName: "redo"
                enabled: !controller.busy
                onClicked: controller.renderFromFl()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 18

            Card {
                Layout.preferredWidth: 330
                Layout.fillHeight: true
                ColumnLayout {
                    anchors { fill: parent; margins: 22 }
                    spacing: 18
                    ProgressRing {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.preferredWidth: 190
                        Layout.preferredHeight: 190
                        value: controller.progress
                        busy: controller.busy
                        caption: page.rendering ? "Rendu" : "Terminé"
                    }
                    Text {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: controller.progressLabel
                        color: Theme.textMuted
                        font.family: Theme.fontFamily; font.pixelSize: 13
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: controller.probeLog.length > 0
                        radius: 10
                        color: "#0B0B0E"
                        border.width: 1
                        border.color: Theme.border
                        clip: true
                        ListView {
                            id: logView
                            anchors { fill: parent; margins: 10 }
                            model: controller.probeLog
                            spacing: 4
                            onCountChanged: positionViewAtEnd()
                            delegate: Text {
                                required property var modelData
                                width: logView.width
                                wrapMode: Text.WrapAnywhere
                                text: modelData
                                color: Theme.textMuted
                                font.family: "Consolas"; font.pixelSize: 11
                            }
                        }
                    }
                    Item { Layout.fillHeight: true; visible: controller.probeLog.length === 0 }
                }
            }

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                ListView {
                    id: jobs
                    anchors { fill: parent; margins: 10 }
                    clip: true
                    model: controller.renderRows
                    spacing: 2
                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        width: jobs.width
                        height: 56
                        radius: 10
                        color: modelData.status === "running" ? Qt.rgba(0.97, 0.77, 0.19, 0.06) : "transparent"
                        Behavior on color { ColorAnimation { duration: Theme.normal } }
                        StatusIcon { id: si; x: 12; anchors.verticalCenter: parent.verticalCenter; status: modelData.status }
                        Column {
                            anchors { left: si.right; leftMargin: 14; right: kindChip.left; rightMargin: 10; verticalCenter: parent.verticalCenter }
                            spacing: 3
                            Text {
                                width: parent.width
                                elide: Text.ElideRight
                                text: modelData.description
                                color: modelData.status === "pending" ? Theme.textMuted : Theme.text
                                font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.Medium
                            }
                            Text {
                                width: parent.width
                                visible: modelData.detail !== ""
                                elide: Text.ElideRight
                                text: modelData.detail + (modelData.status === "resumed" ? "  ·  réutilisé" : "")
                                color: modelData.status === "failed" ? Theme.danger : Theme.textDim
                                font.family: Theme.fontFamily; font.pixelSize: 12
                            }
                        }
                        Chip {
                            id: kindChip
                            anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                            text: modelData.kind === "stem" ? "Groupe" : modelData.kind === "vocal" ? "Voix"
                                : modelData.kind === "check" ? "Vérification" : modelData.kind === "control" ? "Master"
                                : "Référence"
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 18
            visible: !page.rendering && page.sum.folder !== undefined
            Repeater {
                model: [
                    { ok: page.sum.stemsOk, title: "Pistes reconstruites", text: page.sum.nullMessage, icon: "wave" },
                    { ok: page.sum.masterOk, title: "Mastering FL conservé", text: page.sum.masterMessage, icon: "crown" }
                ]
                delegate: Reveal {
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true
                    Layout.preferredHeight: 112
                    delay: 100 + index * 140
                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.radius
                        color: modelData.ok ? Theme.successSoft : Theme.dangerSoft
                        border.width: 1
                        border.color: modelData.ok ? Qt.rgba(0.27, 0.84, 0.6, 0.35) : Qt.rgba(1, 0.42, 0.42, 0.35)
                        Rectangle {
                            id: badge
                            x: 18; anchors.verticalCenter: parent.verticalCenter
                            width: 44; height: 44; radius: 22
                            color: modelData.ok ? Qt.rgba(0.27, 0.84, 0.6, 0.18) : Qt.rgba(1, 0.42, 0.42, 0.18)
                            Icon { anchors.centerIn: parent; width: 22; height: 22; name: modelData.ok ? "check" : "close"; color: modelData.ok ? Theme.success : Theme.danger; stroke: 2.4 }
                        }
                        Column {
                            anchors { left: badge.right; leftMargin: 16; right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
                            spacing: 4
                            Text { text: modelData.title; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 15; font.weight: Font.DemiBold }
                            Text {
                                width: parent.width
                                wrapMode: Text.WordWrap
                                maximumLineCount: 3
                                elide: Text.ElideRight
                                text: modelData.text || ""
                                color: Theme.textMuted
                                font.family: Theme.fontFamily; font.pixelSize: 13
                            }
                        }
                    }
                }
            }
            Card {
                Layout.preferredWidth: 300
                Layout.preferredHeight: 112
                Column {
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 18 }
                    spacing: 6
                    Row {
                        spacing: 8
                        Icon { width: 16; height: 16; name: "spark"; color: Theme.gold }
                        Text { text: "Prochaine étape : mixage Eden"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
                    }
                    Text {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: "Disponible dans la prochaine version d'Eden."
                        color: Theme.textMuted
                        font.family: Theme.fontFamily; font.pixelSize: 13
                    }
                }
            }
        }
    }
}
