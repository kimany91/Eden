import QtQuick
import QtQuick.Controls
import "."

Card {
    id: card
    property var source: ({})
    hoverable: true
    implicitHeight: col.implicitHeight + 36
    readonly property color tint: Theme.roleColor(source.roleKey)
    transform: Translate { y: card.hovered ? -3 : 0; Behavior on y { NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic } } }

    // colored accent on the left edge
    Rectangle {
        x: 0; y: 16
        width: 3; height: parent.height - 32
        radius: 2
        color: card.tint
    }

    Column {
        id: col
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 18; leftMargin: 22 }
        spacing: 10

        Item {
            width: parent.width
            height: 26
            Chip { text: card.source.role || ""; tint: card.tint; filled: true }
            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 4
                Repeater {
                    model: 3
                    Rectangle {
                        required property int index
                        width: 14; height: 4; radius: 2
                        color: index < (card.source.confidence === "haute" ? 3 : card.source.confidence === "moyenne" ? 2 : 1)
                               ? card.tint : Theme.surface2
                    }
                }
            }
        }

        Text {
            width: parent.width
            text: card.source.label || ""
            elide: Text.ElideRight
            color: Theme.text
            font.family: Theme.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold
        }
        Text {
            width: parent.width
            elide: Text.ElideMiddle
            text: card.source.file
                  ? card.source.file + (card.source.fileInfo ? "  ·  " + card.source.fileInfo : "")
                    + (card.source.fileStatus === "missing" ? "  ·  introuvable" : "")
                  : (card.source.instrument ? "Instrument : " + card.source.instrument : "")
            color: card.source.fileStatus === "missing" ? Theme.danger : Theme.textMuted
            font.family: Theme.fontFamily; font.pixelSize: 13
        }
        Text {
            text: "→ " + (card.source.insert || "Master") + (card.source.span ? "   ·   " + card.source.span : "")
            color: Theme.textDim
            font.family: Theme.fontFamily; font.pixelSize: 12
        }
        Flow {
            width: parent.width
            spacing: 6
            visible: (card.source.effects || []).length > 0
            Repeater {
                model: card.source.effects || []
                Chip {
                    required property var modelData
                    text: modelData.name
                    tint: modelData.categoryKey === "pitch_correction" ? Theme.gold : Theme.textMuted
                    filled: modelData.categoryKey === "pitch_correction"
                    dim: !modelData.active
                    ToolTip.visible: chipHover.hovered
                    ToolTip.text: modelData.category + " · " + modelData.where + (modelData.active ? "" : " · " + modelData.inactive)
                    HoverHandler { id: chipHover }
                }
            }
        }
        Text {
            visible: (card.source.effects || []).length === 0
            text: "Aucun effet sur cette piste"
            color: Theme.textDim
            font.family: Theme.fontFamily; font.pixelSize: 12; font.italic: true
        }
    }

    ToolTip.visible: card.hovered && !!card.source.reasons
    ToolTip.delay: 700
    ToolTip.text: "Pourquoi ce rôle : " + (card.source.reasons || []).join(" · ")
}
