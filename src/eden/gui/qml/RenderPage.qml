import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

EdenPage {
    id: page
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
                    text: page.sum.ok === false ? "Le son de ton projet n'est pas validé" : "Le son de ton projet est prêt"
                    color: Theme.text
                    font.family: Theme.displayFamily; font.pixelSize: 30; font.weight: Font.DemiBold
                }
                Text {
                    objectName: "renderVerdict"
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: page.sum.verdict || ""
                    color: Theme.textMuted
                    font.family: Theme.fontFamily; font.pixelSize: 15
                }
            }
            EdenButton {
                visible: !!page.sum.folder
                text: "Ouvrir le dossier"
                iconName: "folder"
                onClicked: controller.openRenderFolder()
            }
            EdenButton {
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

            // the first time, how Eden learnt to drive FL Studio
            Card {
                Layout.preferredWidth: 330
                Layout.fillHeight: true
                visible: controller.probeLog.length > 0
                ColumnLayout {
                    anchors { fill: parent; margins: 18 }
                    spacing: 12
                    Text {
                        text: "Configuration de FL Studio"
                        color: Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
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
                                font.family: Theme.monoFamily; font.pixelSize: 11
                            }
                        }
                    }
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
                                : modelData.kind === "vocal_dry" ? "Voix sèche"
                                : modelData.kind === "check" ? "Vérification" : modelData.kind === "rest" ? "Contrôle"
                                : "Référence"
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 18
            visible: page.sum.folder !== undefined
            Repeater {
                model: [
                    { ok: page.sum.ok, title: "Son de ton projet récupéré", text: page.sum.nullMessage }
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
                    spacing: 10
                    Text {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: page.sum.ok ? "Étape suivante : Eden mixe ton morceau et fait le mastering."
                            : page.sum.complete ? "La vérification n'est pas passée : tu peux mixer quand même, puis écouter l'avant / après."
                            : "Le mixage sera possible quand la vérification sera validée."
                        color: Theme.textMuted
                        font.family: Theme.fontFamily; font.pixelSize: 12
                    }
                    EdenButton {
                        compact: true
                        primary: true
                        text: page.sum.ok === false && page.sum.complete === true ? "Mixer quand même" : "Mixer automatiquement"
                        iconName: "spark"
                        enabled: (page.sum.ok === true || page.sum.complete === true) && !controller.busy
                        onClicked: page.sum.ok ? controller.mixProject() : controller.mixAnyway()
                    }
                }
            }
        }

        // what the render plan and the checks of the renders found (also kept with each mix)
        ScrollView {
            id: warningScroll
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(warningCol.implicitHeight, 190)
            visible: (page.sum.warnings || []).length > 0
            contentWidth: availableWidth
            clip: true
            Column {
                id: warningCol
                width: warningScroll.availableWidth
                spacing: 8
                Repeater {
                    objectName: "renderWarnings"
                    model: page.sum.warnings || []
                    delegate: Rectangle {
                        required property var modelData
                        width: warningCol.width
                        height: wtext.implicitHeight + 22
                        radius: 10
                        color: Theme.warningSoft
                        border.width: 1
                        border.color: Qt.rgba(1, 0.7, 0.28, 0.25)
                        Icon { x: 14; anchors.verticalCenter: parent.verticalCenter; width: 16; height: 16; name: "warning"; color: Theme.warning }
                        Text {
                            id: wtext
                            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 42; rightMargin: 14 }
                            text: modelData
                            wrapMode: Text.WordWrap
                            color: Theme.text
                            font.family: Theme.fontFamily; font.pixelSize: 13
                        }
                    }
                }
            }
        }
    }
}
