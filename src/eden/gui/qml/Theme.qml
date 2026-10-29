pragma Singleton
import QtQuick

QtObject {
    readonly property color bg: "#09090B"
    readonly property color sidebar: "#0E0E11"
    readonly property color surface: "#141418"
    readonly property color surface2: "#1B1B21"
    readonly property color surfaceHover: "#202028"
    readonly property color border: "#25252E"
    readonly property color borderStrong: "#33333F"
    readonly property color text: "#F4F4F6"
    readonly property color textMuted: "#A0A0AE"
    readonly property color textDim: "#6C6C7A"
    readonly property color gold: "#F7C531"
    readonly property color goldBright: "#FFDA5C"
    readonly property color goldDeep: "#E3A400"
    readonly property color goldSoft: "#2B230B"
    readonly property color goldInk: "#16120A"
    readonly property color success: "#45D69A"
    readonly property color successSoft: "#10281F"
    readonly property color danger: "#FF6B6B"
    readonly property color dangerSoft: "#2A1416"
    readonly property color warning: "#FFB347"
    readonly property color warningSoft: "#2A1F10"

    readonly property int radius: 14
    readonly property int radiusSmall: 9
    readonly property string fontFamily: Qt.platform.os === "windows" ? "Segoe UI Variable Text" : "Inter"
    readonly property string displayFamily: Qt.platform.os === "windows" ? "Segoe UI Variable Display" : "Inter"

    readonly property int fast: 160
    readonly property int normal: 320
    readonly property int slow: 620

    function roleColor(key) {
        switch (key) {
        case "lead_vocal": return gold
        case "double": return "#FFA94D"
        case "back_vocal": return "#7AA2FF"
        case "adlib": return "#C38BFF"
        case "vocal": return "#E6E6EE"
        case "beat": return success
        case "drums": return "#FF7A7A"
        case "bass": return "#FF9F43"
        case "music": return "#4FD1C5"
        case "fx": return "#A0A0B0"
        default: return textDim
        }
    }
}
