import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

EdenPage {
    id: page
    readonly property bool analyzing: controller.stage === "analyzing"
    readonly property var r: controller.report

    // -- while analysing -------------------------------------------------------
    Item {
        anchors.fill: parent
        opacity: page.analyzing ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: Theme.normal } }

        RowLayout {
            anchors.centerIn: parent
            spacing: 60
            ProgressRing {
                Layout.preferredWidth: 220
                Layout.preferredHeight: 220
                value: controller.progress
                busy: controller.busy
                caption: "Analyse"
            }
            Column {
                spacing: 14
                Text { text: "Analyse de " + controller.projectName; color: Theme.text; font.family: Theme.displayFamily; font.pixelSize: 24; font.weight: Font.DemiBold }
                Repeater {
                    model: controller.analysisSteps
                    Row {
                        required property var modelData
                        spacing: 12
                        StatusIcon { status: modelData.status; width: 24; height: 24 }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.label
                            color: modelData.status === "pending" ? Theme.textDim : Theme.text
                            font.family: Theme.fontFamily; font.pixelSize: 14
                            Behavior on color { ColorAnimation { duration: Theme.normal } }
                        }
                    }
                }
            }
        }
    }

    // -- results ------------------------------------------------------------------
    Item {
        id: results
        anchors.fill: parent
        opacity: !page.analyzing && page.r.name !== undefined ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: Theme.slow } }

        ColumnLayout {
            anchors.fill: parent
            spacing: 20

            RowLayout {
                Layout.fillWidth: true
                spacing: 20
                Column {
                    Layout.fillWidth: true
                    spacing: 10
                    Text {
                        width: parent.width
                        text: page.r.name || ""
                        elide: Text.ElideRight
                        color: Theme.text
                        font.family: Theme.displayFamily; font.pixelSize: 30; font.weight: Font.DemiBold
                    }
                    Flow {
                        width: parent.width
                        spacing: 8
                        Chip { text: "FL Studio " + (page.r.flVersion || "") }
                        Chip { text: page.r.tempo || "" }
                        Chip { text: "Mesure " + (page.r.timeSignature || "") }
                        Chip { text: "Durée " + (page.r.duration || "") }
                        Chip { text: (page.r.insertCount || 0) + " pistes de Mixer utilisées" }
                    }
                }
                EdenButton {
                    primary: true
                    text: "Récupérer le son depuis FL Studio"
                    iconName: "wave"
                    enabled: !controller.busy
                    onClicked: controller.renderFromFl()
                }
            }

            ScrollView {
                id: scroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: availableWidth
                clip: true

                Column {
                    width: scroll.availableWidth
                    spacing: 18

                    SectionTitle { text: "Voix détectées"; count: (page.r.voices || []).length }
                    Text {
                        visible: (page.r.voices || []).length === 0
                        text: "Aucune voix reconnue automatiquement : vérifie les noms de tes pistes."
                        color: Theme.warning
                        font.family: Theme.fontFamily; font.pixelSize: 14
                    }
                    Grid {
                        id: voiceGrid
                        width: parent.width
                        columns: width > 1100 ? 3 : 2
                        spacing: 14
                        Repeater {
                            model: page.r.voices || []
                            delegate: Reveal {
                                required property var modelData
                                required property int index
                                width: (voiceGrid.width - (voiceGrid.columns - 1) * voiceGrid.spacing) / voiceGrid.columns
                                height: vc.implicitHeight
                                delay: 120 + index * 90
                                VoiceCard { id: vc; width: parent.width; source: modelData }
                            }
                        }
                    }

                    SectionTitle { text: "Instru et autres sources"; count: (page.r.others || []).length; topPad: 10 }
                    Card {
                        width: parent.width
                        height: otherCol.implicitHeight + 12
                        visible: (page.r.others || []).length > 0
                        Column {
                            id: otherCol
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 6 }
                            Repeater {
                                model: page.r.others || []
                                delegate: Rectangle {
                                    required property var modelData
                                    required property int index
                                    width: otherCol.width
                                    height: 52
                                    radius: 10
                                    color: rowHover.hovered ? Theme.surfaceHover : "transparent"
                                    Behavior on color { ColorAnimation { duration: Theme.fast } }
                                    HoverHandler { id: rowHover }
                                    Rectangle { x: 14; anchors.verticalCenter: parent.verticalCenter; width: 8; height: 8; radius: 4; color: Theme.roleColor(modelData.roleKey) }
                                    Text {
                                        x: 34; anchors.verticalCenter: parent.verticalCenter
                                        width: parent.width * 0.32
                                        elide: Text.ElideRight
                                        text: modelData.label
                                        color: Theme.text
                                        font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.Medium
                                    }
                                    Text {
                                        x: parent.width * 0.36; anchors.verticalCenter: parent.verticalCenter
                                        width: parent.width * 0.22
                                        elide: Text.ElideRight
                                        text: modelData.role
                                        color: Theme.textMuted
                                        font.family: Theme.fontFamily; font.pixelSize: 13
                                    }
                                    Text {
                                        x: parent.width * 0.6; anchors.verticalCenter: parent.verticalCenter
                                        width: parent.width * 0.38
                                        elide: Text.ElideRight
                                        text: (modelData.effects.length ? modelData.effects.map(e => e.name).join(", ") : "Aucun effet") + "  →  " + modelData.insert
                                        color: Theme.textDim
                                        font.family: Theme.fontFamily; font.pixelSize: 13
                                    }
                                }
                            }
                        }
                    }

                    SectionTitle { text: "Effets de ton Master FL Studio"; count: -1; topPad: 10 }
                    Card {
                        width: parent.width
                        height: masterRow.implicitHeight + 36
                        Row {
                            id: masterRow
                            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 18 }
                            spacing: 16
                            Rectangle {
                                width: 40; height: 40; radius: 12
                                color: Theme.goldSoft
                                Icon { anchors.centerIn: parent; width: 20; height: 20; name: "crown"; color: Theme.gold }
                            }
                            Column {
                                width: parent.width - 60
                                spacing: 8
                                Text {
                                    text: "Eden fait lui-même le mastering : ces effets servent à ton écoute dans FL Studio, pas au fichier final."
                                    width: parent.width
                                    wrapMode: Text.WordWrap
                                    color: Theme.text
                                    font.family: Theme.fontFamily; font.pixelSize: 14
                                }
                                Flow {
                                    width: parent.width
                                    spacing: 6
                                    Repeater {
                                        model: page.r.masterEffects || []
                                        Chip { required property var modelData; text: modelData.name; dim: !modelData.active }
                                    }
                                    Text {
                                        visible: (page.r.masterEffects || []).length === 0
                                        text: "Aucun effet sur ton Master"
                                        color: Theme.textDim
                                        font.family: Theme.fontFamily; font.pixelSize: 13
                                    }
                                }
                            }
                        }
                    }

                    SectionTitle { text: "À vérifier"; count: (page.r.warnings || []).length; topPad: 10; visible: (page.r.warnings || []).length > 0 }
                    Repeater {
                        model: page.r.warnings || []
                        delegate: Rectangle {
                            required property var modelData
                            width: parent ? parent.width : 0
                            height: wt.implicitHeight + 22
                            radius: 10
                            color: Theme.warningSoft
                            border.width: 1
                            border.color: Qt.rgba(1, 0.7, 0.28, 0.25)
                            Icon { x: 14; anchors.verticalCenter: parent.verticalCenter; width: 16; height: 16; name: "warning"; color: Theme.warning }
                            Text {
                                id: wt
                                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 42; rightMargin: 14 }
                                text: modelData
                                wrapMode: Text.WordWrap
                                color: Theme.text
                                font.family: Theme.fontFamily; font.pixelSize: 13
                            }
                        }
                    }
                    Item { width: 1; height: 20 }
                }
            }
        }
    }
}
