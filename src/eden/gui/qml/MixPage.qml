import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

EdenPage {
    id: page
    signal chooseFolder()
    readonly property bool mixing: controller.stage === "mixing"
    readonly property var r: controller.mixResult
    readonly property bool hasResult: r.id !== undefined

    RowLayout {
        anchors.fill: parent
        spacing: 18

        // -- left: intensity, launch, progress, versions ---------------------------
        Card {
            Layout.preferredWidth: 320
            Layout.fillHeight: true
            ColumnLayout {
                anchors { fill: parent; margins: 22 }
                spacing: 14

                Text { text: "Mixage Eden"; color: Theme.text; font.family: Theme.displayFamily; font.pixelSize: 24; font.weight: Font.DemiBold }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: "Eden mixe tes voix comme un ingénieur du son (tonalité, espace, stéréo, basses) puis fait le mastering pour les plateformes."
                    color: Theme.textMuted
                    font.family: Theme.fontFamily; font.pixelSize: 13
                }

                Item { Layout.preferredHeight: 4 }
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Intensité des corrections"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: Math.round(controller.intensity * 100) + " %"
                        color: Theme.gold
                        font.family: Theme.displayFamily; font.pixelSize: 20; font.weight: Font.DemiBold
                    }
                }
                EdenSlider {
                    Layout.fillWidth: true
                    from: 0; to: 1; stepSize: 0.05
                    value: controller.intensity
                    enabled: !controller.busy
                    onMoved: controller.intensity = value
                }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: "0 % : ton morceau d'origine, à l'identique.  100 % : toutes les corrections recommandées."
                    color: Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: 12
                }
                EdenButton {
                    Layout.fillWidth: true
                    primary: true
                    text: page.hasResult ? "Remixer" : "Mixer automatiquement"
                    iconName: page.hasResult ? "redo" : "spark"
                    enabled: !controller.busy
                    onClicked: controller.mixProject()
                }

                // progress while mixing
                Column {
                    Layout.fillWidth: true
                    visible: page.mixing
                    spacing: 10
                    Repeater {
                        model: controller.mixSteps
                        Row {
                            required property var modelData
                            width: parent.width
                            spacing: 10
                            StatusIcon { status: modelData.status; width: 22; height: 22 }
                            Text {
                                width: parent.width - 32
                                anchors.verticalCenter: parent.verticalCenter
                                wrapMode: Text.WordWrap
                                text: modelData.label
                                color: modelData.status === "pending" ? Theme.textDim : Theme.text
                                font.family: Theme.fontFamily; font.pixelSize: 13
                            }
                        }
                    }
                }

                // versions
                Text {
                    visible: controller.mixVersions.length > 0
                    Layout.topMargin: 6
                    text: "VERSIONS"
                    color: Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: 11; font.letterSpacing: 2
                }
                ListView {
                    id: versions
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 4
                    model: controller.mixVersions
                    delegate: Rectangle {
                        required property var modelData
                        width: versions.width
                        height: 46
                        radius: 10
                        readonly property bool current: page.r.id === modelData.id
                        color: current ? Theme.goldSoft : (vHover.hovered ? Theme.surfaceHover : "transparent")
                        border.width: current ? 1 : 0
                        border.color: Qt.rgba(0.97, 0.77, 0.19, 0.3)
                        Behavior on color { ColorAnimation { duration: Theme.fast } }
                        HoverHandler { id: vHover }
                        Column {
                            anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                            spacing: 2
                            Text { text: modelData.date; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.Medium }
                            Text { text: "Intensité " + modelData.intensity + " %  ·  " + modelData.lufs; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: 11 }
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            enabled: !controller.busy
                            onClicked: controller.showVersion(modelData.id)
                        }
                    }
                }
                Item { Layout.fillHeight: true; visible: controller.mixVersions.length === 0 }
            }
        }

        // -- right: what Eden did, result, export ------------------------------------
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Column {
                anchors.centerIn: parent
                spacing: 16
                visible: page.mixing
                ProgressRing {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 220; height: 220
                    value: controller.progress
                    busy: controller.busy
                    caption: "Mixage"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: controller.progressLabel
                    color: Theme.textMuted
                    font.family: Theme.fontFamily; font.pixelSize: 14
                }
            }

            Column {
                anchors.centerIn: parent
                visible: !page.mixing && !page.hasResult
                spacing: 10
                Icon { anchors.horizontalCenter: parent.horizontalCenter; width: 40; height: 40; name: "spark"; color: Theme.gold }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Choisis l'intensité puis lance le mixage."
                    color: Theme.textMuted
                    font.family: Theme.fontFamily; font.pixelSize: 15
                }
            }

            ScrollView {
                id: scroll
                anchors.fill: parent
                visible: !page.mixing && page.hasResult
                contentWidth: availableWidth
                clip: true

                Column {
                    width: scroll.availableWidth
                    spacing: 16

                    // before / after
                    Row {
                        width: parent.width
                        spacing: 14
                        Repeater {
                            model: [
                                { title: "Ton morceau d'origine", data: page.r.original || {}, gold: false },
                                { title: "Avec Eden (mix + mastering)", data: page.r.final || {}, gold: true }
                            ]
                            delegate: Reveal {
                                required property var modelData
                                required property int index
                                width: (parent.width - 14) / 2
                                height: 104
                                delay: 60 + index * 120
                                Card {
                                    anchors.fill: parent
                                    border.color: modelData.gold ? Qt.rgba(0.97, 0.77, 0.19, 0.4) : Theme.border
                                    Column {
                                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 20 }
                                        spacing: 6
                                        Text { text: modelData.title; color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 13 }
                                        Text {
                                            text: modelData.data.lufs || "—"
                                            color: modelData.gold ? Theme.gold : Theme.text
                                            font.family: Theme.displayFamily; font.pixelSize: 26; font.weight: Font.DemiBold
                                        }
                                        Text { text: "Crête réelle " + (modelData.data.truePeak || "—"); color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: 12 }
                                    }
                                }
                            }
                        }
                    }

                    Repeater {
                        model: page.r.warnings || []
                        delegate: Rectangle {
                            required property var modelData
                            width: parent ? parent.width : 0
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

                    SectionTitle { text: "Le morceau"; count: -1; topPad: 4; visible: (page.r.song || []).length > 0 }
                    Card {
                        visible: (page.r.song || []).length > 0
                        width: parent.width
                        height: songCol.implicitHeight + 32
                        Column {
                            id: songCol
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
                            spacing: 6
                            Repeater {
                                model: page.r.song || []
                                Text { required property var modelData; text: modelData; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                            }
                        }
                    }

                    SectionTitle { text: "Ce qu'Eden a fait"; count: -1; topPad: 4 }
                    Text {
                        visible: page.r.untouched === true
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: "Rien : tes voix et ton instru ont été laissées exactement comme dans FL Studio."
                        color: Theme.textMuted
                        font.family: Theme.fontFamily; font.pixelSize: 13
                    }
                    Repeater {
                        model: page.r.parts || []
                        delegate: Reveal {
                            required property var modelData
                            required property int index
                            width: parent ? parent.width : 0
                            height: partCard.implicitHeight
                            delay: 120 + index * 80
                            Card {
                                id: partCard
                                width: parent.width
                                implicitHeight: partCol.implicitHeight + 32
                                Rectangle { x: 0; y: 14; width: 3; height: parent.height - 28; radius: 2; color: Theme.roleColor(modelData.roleKey) }
                                Column {
                                    id: partCol
                                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16; leftMargin: 22 }
                                    spacing: 10
                                    Row {
                                        spacing: 10
                                        Text { text: modelData.label; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 15; font.weight: Font.DemiBold }
                                        Chip {
                                            text: modelData.role
                                            tint: Theme.roleColor(modelData.roleKey)
                                            filled: true
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                        Text { text: modelData.change; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                                    }
                                    Text {
                                        visible: modelData.treatments.length === 0 && modelData.notes.length === 0
                                        text: "Laissé tel quel : rien à corriger."
                                        color: Theme.textDim
                                        font.family: Theme.fontFamily; font.pixelSize: 13; font.italic: true
                                    }
                                    Repeater {
                                        model: modelData.treatments
                                        Column {
                                            required property var modelData
                                            width: partCol.width
                                            spacing: 2
                                            Text { text: "• " + modelData.label; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.Medium }
                                            Text {
                                                width: parent.width
                                                leftPadding: 12
                                                wrapMode: Text.WordWrap
                                                text: modelData.reason
                                                color: Theme.textMuted
                                                font.family: Theme.fontFamily; font.pixelSize: 12
                                            }
                                        }
                                    }
                                    Repeater {
                                        model: modelData.notes
                                        Text {
                                            required property var modelData
                                            width: partCol.width
                                            wrapMode: Text.WordWrap
                                            text: "◦ " + modelData
                                            color: Theme.textMuted
                                            font.family: Theme.fontFamily; font.pixelSize: 12
                                        }
                                    }
                                }
                            }
                        }
                    }

                    SectionTitle { text: "Mastering Eden"; count: -1; topPad: 8; visible: (page.r.master || []).length > 0 }
                    Card {
                        visible: (page.r.master || []).length > 0
                        width: parent.width
                        height: masterCol.implicitHeight + 32
                        Column {
                            id: masterCol
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
                            spacing: 8
                            Repeater {
                                model: page.r.master || []
                                Column {
                                    required property var modelData
                                    width: masterCol.width
                                    spacing: 2
                                    Text { text: "• " + modelData.label; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.Medium }
                                    Text {
                                        width: parent.width
                                        leftPadding: 12
                                        wrapMode: Text.WordWrap
                                        text: modelData.reason
                                        color: Theme.textMuted
                                        font.family: Theme.fontFamily; font.pixelSize: 12
                                    }
                                }
                            }
                            Text {
                                width: masterCol.width
                                wrapMode: Text.WordWrap
                                text: (page.r.checks || []).join("   ·   ")
                                color: Theme.textDim
                                font.family: Theme.fontFamily; font.pixelSize: 12
                            }
                            Text {
                                topPadding: 6
                                text: "Ce que les plateformes en feront (elles ramènent les morceaux forts à leur niveau de référence)"
                                color: Theme.text
                                font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.Medium
                            }
                            Flow {
                                width: masterCol.width
                                spacing: 6
                                Repeater {
                                    model: page.r.platforms || []
                                    Chip { required property var modelData; text: modelData.name + " " + modelData.gain + " → " + modelData.heard }
                                }
                            }
                        }
                    }

                    SectionTitle { text: "Exporter le WAV"; count: -1; topPad: 8 }
                    Card {
                        width: parent.width
                        height: exportCol.implicitHeight + 36
                        ColumnLayout {
                            id: exportCol
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 18 }
                            spacing: 12
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10
                                Icon { width: 18; height: 18; name: "folder"; color: Theme.gold }
                                Text {
                                    Layout.fillWidth: true
                                    text: controller.exportFolder
                                    elide: Text.ElideMiddle
                                    color: Theme.text
                                    font.family: Theme.fontFamily; font.pixelSize: 13
                                }
                                EdenButton { compact: true; text: "Choisir le dossier"; onClicked: page.chooseFolder() }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10
                                EdenField {
                                    id: fileName
                                    Layout.fillWidth: true
                                    text: controller.projectName + " - Eden"
                                    placeholderText: "Nom du fichier"
                                }
                                Text { text: ".wav"; color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 14 }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10
                                EdenCombo {
                                    id: rate
                                    Layout.fillWidth: true
                                    model: [
                                        { label: "Comme FL Studio (" + ((page.r.final ? page.r.final.sampleRate : 0) / 1000) + " kHz)", value: 0 },
                                        { label: "44,1 kHz", value: 44100 },
                                        { label: "48 kHz", value: 48000 },
                                        { label: "88,2 kHz", value: 88200 },
                                        { label: "96 kHz", value: 96000 }
                                    ]
                                }
                                EdenCombo {
                                    id: depth
                                    Layout.fillWidth: true
                                    model: [
                                        { label: "24 bits", value: 24 },
                                        { label: "16 bits (avec dither)", value: 16 },
                                        { label: "32 bits flottant", value: 32 }
                                    ]
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10
                                EdenButton {
                                    primary: true
                                    text: "Exporter le WAV"
                                    iconName: "upload"
                                    enabled: !controller.busy
                                    onClicked: controller.exportWav(fileName.text, rate.currentValue, depth.currentValue)
                                }
                                EdenButton {
                                    visible: controller.exportMessage !== ""
                                    text: "Ouvrir le dossier"
                                    iconName: "folder"
                                    onClicked: controller.openExportFolder()
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: controller.exportMessage !== ""
                                wrapMode: Text.WrapAnywhere
                                text: controller.exportMessage
                                color: Theme.success
                                font.family: Theme.fontFamily; font.pixelSize: 13
                            }
                        }
                    }
                    Item { width: 1; height: 16 }
                }
            }
        }
    }
}
