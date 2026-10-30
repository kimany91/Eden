import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

// Before / after: the song as FL Studio renders it and Eden's version, on one playhead
// (gui/player.py). Space plays or pauses, A and B switch.
Card {
    id: card
    readonly property var p: controller.player
    implicitHeight: col.implicitHeight + 40

    function clock(s) {
        const t = Math.max(0, Math.floor(s))
        return Math.floor(t / 60) + ":" + String(t % 60).padStart(2, "0")
    }

    Shortcut { sequence: "Space"; enabled: card.visible && card.p.ready; onActivated: card.p.toggle() }
    Shortcut { sequence: "A"; enabled: card.visible && card.p.ready && card.p.hasBefore; onActivated: card.p.choose("before") }
    Shortcut { sequence: "B"; enabled: card.visible && card.p.ready; onActivated: card.p.choose("after") }

    ColumnLayout {
        id: col
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 20 }
        spacing: 14

        RowLayout {
            Layout.fillWidth: true
            spacing: 16

            Rectangle {  // play / pause
                width: 52; height: 52; radius: 26
                enabled: card.p.ready
                opacity: enabled ? 1 : 0.4
                gradient: Gradient {
                    GradientStop { position: 0; color: Theme.goldBright }
                    GradientStop { position: 1; color: Theme.goldDeep }
                }
                scale: playArea.pressed ? 0.94 : playHover.hovered ? 1.05 : 1
                Behavior on scale { NumberAnimation { duration: Theme.fast; easing.type: Easing.OutBack } }
                Icon {
                    anchors.centerIn: parent
                    anchors.horizontalCenterOffset: card.p.playing ? 0 : 2
                    width: 22; height: 22
                    name: card.p.playing ? "pause" : "play"
                    color: Theme.goldInk
                    stroke: 2.6
                }
                HoverHandler { id: playHover; enabled: parent.enabled }
                MouseArea {
                    id: playArea
                    anchors.fill: parent
                    enabled: parent.enabled
                    cursorShape: Qt.PointingHandCursor
                    onClicked: card.p.toggle()
                }
            }

            Rectangle {  // before | after
                id: switcher
                implicitWidth: 248
                implicitHeight: 44
                radius: 22
                color: Theme.surface2
                border.width: 1
                border.color: Theme.border
                opacity: card.p.ready ? 1 : 0.4
                Rectangle {
                    width: parent.width / 2 - 4
                    height: parent.height - 8
                    y: 4
                    x: card.p.source === "before" ? 4 : parent.width / 2
                    radius: height / 2
                    color: card.p.source === "before" ? Theme.surfaceHover : Theme.goldSoft
                    border.width: 1
                    border.color: card.p.source === "before" ? Theme.borderStrong : Qt.rgba(0.97, 0.77, 0.19, 0.45)
                    Behavior on x { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
                }
                Row {
                    anchors.fill: parent
                    Repeater {
                        model: [{ key: "before", label: "Avant", hint: "A" }, { key: "after", label: "Après · Eden", hint: "B" }]
                        delegate: Item {
                            required property var modelData
                            width: switcher.width / 2
                            height: switcher.height
                            readonly property bool on: card.p.source === modelData.key
                            readonly property bool usable: card.p.ready && (modelData.key === "after" || card.p.hasBefore)
                            opacity: usable ? 1 : 0.4
                            Text {
                                anchors.centerIn: parent
                                text: modelData.label
                                color: parent.on ? (modelData.key === "after" ? Theme.gold : Theme.text) : Theme.textMuted
                                font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold
                            }
                            MouseArea {
                                anchors.fill: parent
                                enabled: parent.usable
                                cursorShape: Qt.PointingHandCursor
                                onClicked: card.p.choose(modelData.key)
                            }
                        }
                    }
                }
            }

            Item { Layout.fillWidth: true }

            Row {  // même volume
                spacing: 10
                opacity: card.p.ready && card.p.hasBefore ? 1 : 0.4
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 40; height: 22; radius: 11
                    color: card.p.matched ? Theme.gold : Theme.surface2
                    border.width: 1
                    border.color: card.p.matched ? Theme.gold : Theme.borderStrong
                    Behavior on color { ColorAnimation { duration: Theme.fast } }
                    Rectangle {
                        width: 16; height: 16; radius: 8
                        y: 3
                        x: card.p.matched ? parent.width - width - 3 : 3
                        color: card.p.matched ? Theme.goldInk : Theme.textMuted
                        Behavior on x { NumberAnimation { duration: Theme.fast; easing.type: Easing.OutCubic } }
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: card.p.ready && card.p.hasBefore
                        cursorShape: Qt.PointingHandCursor
                        onClicked: card.p.setMatched(!card.p.matched)
                    }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Même volume"
                    color: Theme.text
                    font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.Medium
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Text {
                text: card.clock(seek.pressed ? seek.value : card.p.position)
                color: Theme.textMuted
                font.family: Theme.monoFamily; font.pixelSize: 12
            }
            EdenSlider {
                id: seek
                Layout.fillWidth: true
                from: 0; to: Math.max(1, card.p.duration)
                value: card.p.position
                enabled: card.p.ready
                onMoved: card.p.seek(value)
            }
            Text {
                text: card.clock(card.p.duration)
                color: Theme.textMuted
                font.family: Theme.monoFamily; font.pixelSize: 12
            }
        }

        Text {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: card.p.message !== "" ? card.p.message
                  : "Avant : ton morceau tel que FL Studio l'exporte, effets du Master compris. Après : le mix et le master d'Eden. "
                    + (card.p.matched && card.p.matchDb > 0.05
                       ? "Même volume : la version la plus forte est baissée de " + card.p.matchDb.toFixed(1).replace(".", ",")
                         + " dB pendant l'écoute, pour juger le mix et pas le volume (le WAV exporté n'est pas touché)."
                       : "Espace : lecture / pause · A / B : changer de version au même instant.")
            color: Theme.textDim
            font.family: Theme.fontFamily; font.pixelSize: 12
        }
    }
}
