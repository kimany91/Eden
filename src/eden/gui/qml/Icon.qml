import QtQuick
import QtQuick.Shapes

// Line icons drawn as vector paths on a 24×24 grid.
Item {
    id: icon
    property string name: "check"
    property color color: "white"
    property real stroke: 2
    implicitWidth: 20
    implicitHeight: 20

    readonly property var paths: ({
        "check": "M5 12.5 L10 17.5 L19 7",
        "close": "M6 6 L18 18 M18 6 L6 18",
        "upload": "M12 15 V4 M7 9 L12 4 L17 9 M4 15 V20 H20 V15",
        "folder": "M3 6.5 V19 H21 V8.5 H11.5 L9.5 6.5 Z",
        "lock": "M6 11 H18 V20 H6 Z M8.5 11 V8 A3.5 3.5 0 0 1 15.5 8 V11",
        "wave": "M4 10 V14 M8 7 V17 M12 4 V20 M16 8 V16 M20 11 V13",
        "crown": "M4 18 H20 M5 15.5 L4 7 L9 11 L12 5 L15 11 L20 7 L19 15.5 Z",
        "warning": "M12 4 L21.5 20 H2.5 Z M12 10 V14 M12 17 V17.4",
        "spark": "M12 3 L13.8 10.2 L21 12 L13.8 13.8 L12 21 L10.2 13.8 L3 12 L10.2 10.2 Z",
        "plus": "M12 5 V19 M5 12 H19",
        "dash": "M7 12 H17",
        "chevron": "M7 10 L12 15 L17 10",
        "redo": "M4 12 A8 8 0 1 0 6.5 6.2 M4 4 V9 H9",
        "play": "M8 5 L19 12 L8 19 Z",
        "pause": "M8.5 5 V19 M15.5 5 V19"
    })

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        transform: Scale { xScale: icon.width / 24; yScale: icon.height / 24 }
        ShapePath {
            strokeColor: icon.color
            strokeWidth: icon.stroke * 24 / Math.max(icon.width, 1)
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: icon.paths[icon.name] || "" }
        }
    }
}
