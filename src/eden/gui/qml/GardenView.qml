import QtQuick
import QtQuick.Layouts
import Eden.Garden
import "."

// The whole window while Eden works: the tree grows in its garden with the work done
// (controller.growth), the journal below says what is happening. At the end an apple grows,
// falls, and the result is shown (finished()).
Item {
    id: garden
    signal finished()

    readonly property real target: controller.growth
    // the growth drawn, and the percentage shown with it: it grows towards the work done, easing in and
    // out of each step (a new journey winds it back as smoothly), never jumping
    property real shown: controller.growth
    property real growing: 0  // how fast it grows, per second
    readonly property real growSeconds: 2.2  // about how long the tree takes to reach a new step
    property real time: 0
    readonly property var heights: GardenInfo.heights  // read once: nothing calls Python per frame
    readonly property bool threeD: GraphicsInfo.api !== GraphicsInfo.Software && GraphicsInfo.api !== GraphicsInfo.Unknown
    readonly property bool software: GraphicsInfo.api === GraphicsInfo.Software
    readonly property real pace: threeD ? 1 : 0.05  // without 3D the end is only a short fade

    // camera: turns slowly round the tree; the user can turn it (drag) and zoom (wheel)
    property real autoYaw: 30
    property real userYaw: 0
    property real userPitch: 0
    property real zoom: 1
    property real idle: 10  // seconds since the user last moved the camera

    // the end: toApple 0 → 1, the camera goes to the apple; the apple grows, falls, rolls
    property real toApple: 0
    property real appleScale: 0
    property real appleDrop: 0  // metres fallen
    property real appleRoll: 0  // metres rolled on the grass after the fall
    property real appleSpin: 0
    property real fade: 0
    readonly property vector3d hang: GardenInfo.appleCenter
    readonly property real appleFloor: GardenInfo.appleRadius + 0.02
    readonly property real fallHeight: hang.y - appleFloor
    readonly property real appleAzimuth: Math.atan2(hang.x, hang.z) * 180 / Math.PI
    readonly property vector3d outward: Qt.vector3d(hang.x, 0, hang.z).normalized()
    readonly property vector3d applePosition: Qt.vector3d(hang.x + outward.x * appleRoll,
                                                          hang.y - appleDrop,
                                                          hang.z + outward.z * appleRoll)

    function heightAt(g) {
        const x = Math.max(0, Math.min(1, g)) * (heights.length - 1)
        const i = Math.floor(x)
        return i + 1 < heights.length ? heights[i] + (heights[i + 1] - heights[i]) * (x - i) : heights[i]
    }
    function mix(a, b, t) { return a + (b - a) * t }
    // one frame of growth: a spring without bounce (critically damped, solved exactly for the frame) towards
    // the work done, so each step of the work is seen growing, easing in and out; a new journey's lower
    // target winds it back the same way. Growing, it never goes past the work done.
    function growTowardsWork(dt) {
        const k = 2 / (garden.growSeconds * garden.pace)
        const y = garden.shown - garden.target
        const c = garden.growing + k * y
        const e = Math.exp(-k * dt)
        garden.shown = garden.target + (y + c * dt) * e
        garden.growing = (garden.growing - k * c * dt) * e
        if ((y < 0 && garden.shown > garden.target)
                || (Math.abs(garden.shown - garden.target) < 0.0005 && Math.abs(garden.growing) < 0.001)) {
            garden.shown = garden.target
            garden.growing = 0
        }
    }
    function shortestYaw(from, to) { return from + ((((to - from) % 360) + 540) % 360 - 180) }

    readonly property real treeHeight: heightAt(shown)
    readonly property real frameYaw: autoYaw + userYaw
    // the camera's framing of the tree, eased: it follows the tree as it grows, glides, never jumps
    readonly property real frameDistance: (1.0 + treeHeight * 2.1) * zoom
    readonly property real frameHeight: 0.05 + treeHeight * 0.5
    readonly property real framePitch: -18 + 10 * Math.min(treeHeight / 4.9, 1)
    property real camDistance: frameDistance
    property real camHeight: frameHeight
    property real camPitch: framePitch
    readonly property real cameraSeconds: 1.2  // about how long the camera takes to reframe the tree
    property real focusYaw: frameYaw  // set when the end starts: the shortest turn to the apple's side

    Rectangle {  // a blue sky, paler down to the horizon, where the scene's fog fades the lawn into it
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#2F6DC6" }
            GradientStop { position: 0.32; color: "#5E9BE0" }
            GradientStop { position: 0.6; color: "#CFE6F7" }
            GradientStop { position: 1.0; color: "#CFE6F7" }
        }
    }

    Loader {
        id: sceneLoader
        anchors.fill: parent
        active: garden.threeD
        sourceComponent: GardenScene {
            growth: garden.shown
            time: garden.time
            yaw: garden.mix(garden.frameYaw, garden.focusYaw, garden.toApple)
            pitch: garden.mix(garden.camPitch + garden.userPitch,
                              -5 - 13 * Math.min(1, garden.appleDrop / Math.max(0.1, garden.fallHeight)), garden.toApple)
            distance: garden.mix(garden.camDistance, 2.8, garden.toApple)
            target: Qt.vector3d(garden.mix(0, garden.applePosition.x, garden.toApple),
                                garden.mix(garden.camHeight, garden.applePosition.y, garden.toApple),
                                garden.mix(0, garden.applePosition.z, garden.toApple))
            appleScale: garden.appleScale
            applePosition: garden.applePosition
            appleRotation: Qt.vector3d(0, 0, garden.appleSpin)
            appleLight: garden.toApple
        }
    }

    // without 3D (software rendering): the logo grows with the work
    TreeArt {
        visible: garden.software
        triangles: visible ? controller.treeTriangles : []
        width: Math.min(parent.width, parent.height) * 0.42
        height: width
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -parent.height * 0.12
        opacity: 0.25 + 0.75 * garden.shown
        scale: 0.4 + 0.6 * garden.shown
        Component.onCompleted: grow()
    }

    FrameAnimation {
        running: garden.visible
        onTriggered: {
            const dt = Math.min(frameTime, 0.1)
            garden.time += dt
            garden.idle += dt
            garden.growTowardsWork(dt)
            const reframe = 1 - Math.exp(-dt / garden.cameraSeconds)
            garden.camDistance += (garden.frameDistance - garden.camDistance) * reframe
            garden.camHeight += (garden.frameHeight - garden.camHeight) * reframe
            garden.camPitch += (garden.framePitch - garden.camPitch) * reframe
            if (garden.idle > 3 && garden.toApple === 0)
                garden.autoYaw += 6 * dt * Math.min(1, (garden.idle - 3) / 2)
        }
    }

    DragHandler {
        target: null
        enabled: garden.toApple === 0
        property point last
        onActiveChanged: last = centroid.position
        onCentroidChanged: {
            if (!active)
                return
            garden.userYaw -= (centroid.position.x - last.x) * 0.3
            garden.userPitch = Math.max(-30, Math.min(12, garden.userPitch - (centroid.position.y - last.y) * 0.15))
            last = centroid.position
            garden.idle = 0
        }
    }
    WheelHandler {
        enabled: garden.toApple === 0
        onWheel: (event) => {
            garden.zoom = Math.max(0.55, Math.min(1.8, garden.zoom * Math.pow(0.9, event.angleDelta.y / 120)))
            garden.idle = 0
        }
    }

    // -- the end: the apple ------------------------------------------------------------------
    readonly property bool ripe: controller.journeyFinished && shown > 0.995
    onRipeChanged: if (ripe) ending.start()

    SequentialAnimation {
        id: ending
        // from the apple's side but not in line with the trunk: the apple is seen against the garden
        ScriptAction { script: garden.focusYaw = garden.shortestYaw(garden.frameYaw, garden.appleAzimuth + 55) }
        ParallelAnimation {
            NumberAnimation { target: garden; property: "toApple"; to: 1; duration: 2400 * garden.pace; easing.type: Easing.InOutCubic }
            SequentialAnimation {
                PauseAnimation { duration: 500 * garden.pace }
                NumberAnimation { target: garden; property: "appleScale"; to: 1; duration: 2600 * garden.pace; easing.type: Easing.OutBack; easing.overshoot: 1.2 }
            }
        }
        PauseAnimation { duration: 450 * garden.pace }
        SequentialAnimation {  // it comes loose
            NumberAnimation { target: garden; property: "appleSpin"; to: 9; duration: 160 * garden.pace; easing.type: Easing.InOutSine }
            NumberAnimation { target: garden; property: "appleSpin"; to: -7; duration: 220 * garden.pace; easing.type: Easing.InOutSine }
            NumberAnimation { target: garden; property: "appleSpin"; to: 0; duration: 180 * garden.pace; easing.type: Easing.InOutSine }
        }
        // it falls (constant acceleration: 9.81 m/s², a touch slowed down to be seen), bounces, rolls
        NumberAnimation {
            target: garden; property: "appleDrop"; to: garden.fallHeight
            duration: 1000 * Math.sqrt(2 * garden.fallHeight / 9.81) * 1.25 * garden.pace; easing.type: Easing.InQuad
        }
        ParallelAnimation {
            SequentialAnimation {
                NumberAnimation { target: garden; property: "appleDrop"; to: garden.fallHeight - 0.12; duration: 190 * garden.pace; easing.type: Easing.OutQuad }
                NumberAnimation { target: garden; property: "appleDrop"; to: garden.fallHeight; duration: 190 * garden.pace; easing.type: Easing.InQuad }
                NumberAnimation { target: garden; property: "appleDrop"; to: garden.fallHeight - 0.035; duration: 110 * garden.pace; easing.type: Easing.OutQuad }
                NumberAnimation { target: garden; property: "appleDrop"; to: garden.fallHeight; duration: 110 * garden.pace; easing.type: Easing.InQuad }
            }
            NumberAnimation { target: garden; property: "appleRoll"; to: 0.32; duration: 1100 * garden.pace; easing.type: Easing.OutCubic }
            NumberAnimation { target: garden; property: "appleSpin"; to: -170; duration: 1100 * garden.pace; easing.type: Easing.OutCubic }
        }
        PauseAnimation { duration: 800 * garden.pace }
        NumberAnimation { target: garden; property: "fade"; to: 1; duration: 650; easing.type: Easing.InOutCubic }
        ScriptAction { script: garden.finished() }
    }

    // -- what is happening ---------------------------------------------------------------------
    Rectangle {  // a light shade at the top of the sky: the header stays readable on the blue
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: 200
        opacity: 1 - garden.toApple * 0.6
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0.02, 0.04, 0.1, 0.55) }
            GradientStop { position: 1.0; color: Qt.rgba(0.02, 0.04, 0.1, 0) }
        }
    }
    Item {
        id: header
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 28 }
        height: 120
        opacity: 1 - garden.toApple * 0.6

        Row {
            id: brand
            spacing: 12
            Image { source: controller.logoUrl; width: 34; height: 34; smooth: true; mipmap: true }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                Text { text: "Eden"; color: Theme.text; font.family: Theme.displayFamily; font.pixelSize: 17; font.weight: Font.DemiBold; font.letterSpacing: 1.5 }
                Text { text: controller.projectName; color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 12 }
            }
        }

        Row {
            id: chips
            anchors { left: parent.left; top: brand.bottom; topMargin: 18 }
            spacing: 8
            Repeater {
                model: controller.journeyStages
                delegate: Rectangle {
                    required property var modelData
                    height: 28
                    width: chipText.implicitWidth + 34
                    radius: 14
                    color: modelData.status === "running" ? Qt.rgba(0.97, 0.77, 0.19, 0.16) : Qt.rgba(1, 1, 1, 0.05)
                    border.width: 1
                    border.color: modelData.status === "running" ? Qt.rgba(0.97, 0.77, 0.19, 0.55)
                                : modelData.status === "done" ? Qt.rgba(0.27, 0.84, 0.6, 0.35) : Qt.rgba(1, 1, 1, 0.08)
                    Behavior on color { ColorAnimation { duration: Theme.normal } }
                    Rectangle {
                        x: 11; anchors.verticalCenter: parent.verticalCenter
                        width: 7; height: 7; radius: 3.5
                        color: modelData.status === "done" ? Theme.success : modelData.status === "running" ? Theme.gold : Theme.textDim
                        SequentialAnimation on opacity {
                            running: modelData.status === "running"
                            loops: Animation.Infinite
                            NumberAnimation { to: 0.3; duration: 700; easing.type: Easing.InOutSine }
                            NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
                        }
                    }
                    Text {
                        id: chipText
                        x: 24; anchors.verticalCenter: parent.verticalCenter
                        text: modelData.label
                        color: modelData.status === "pending" ? Theme.textDim : Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: 12; font.weight: Font.Medium
                    }
                }
            }
        }

        Text {
            anchors { left: parent.left; right: percent.left; rightMargin: 24; top: chips.bottom; topMargin: 14 }
            text: controller.journeyStep
            elide: Text.ElideRight
            color: Theme.text
            font.family: Theme.fontFamily; font.pixelSize: 15
            style: Text.Outline; styleColor: Qt.rgba(0, 0, 0, 0.35)
        }

        Column {
            id: percent
            anchors { right: parent.right; top: parent.top }
            Text {
                anchors.right: parent.right
                text: Math.round(garden.shown * 100) + " %"
                color: Theme.gold
                font.family: Theme.displayFamily; font.pixelSize: 34; font.weight: Font.DemiBold
            }
            Text {
                anchors.right: parent.right
                text: controller.journeyFinished ? "Terminé" : "du travail d'Eden"
                color: Theme.textMuted
                font.family: Theme.fontFamily; font.pixelSize: 12
            }
        }
    }

    Text {
        anchors { right: parent.right; bottom: journal.top; margins: 18 }
        text: "Fais glisser pour tourner autour de l'arbre · molette pour zoomer"
        visible: garden.threeD
        opacity: garden.time < 12 && garden.toApple === 0 ? 0.7 : 0
        Behavior on opacity { NumberAnimation { duration: 900 } }
        color: Theme.textMuted
        font.family: Theme.fontFamily; font.pixelSize: 12
    }

    // the journal: every step, in French, as it happens, written on the garden itself (outlined to read
    // on the sky as on the grass)
    Item {
        id: journal
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 28 }
        height: Math.max(52, Math.min(100, parent.height * 0.11))  // the last few lines: what is happening now
        opacity: 1 - garden.toApple * 0.65

        // newest line first, laid out from the bottom: the latest is always on the bottom edge with
        // nothing to scroll (a scroll asked for later could reach a journal already closing and crash it)
        ListModel { id: lines }
        Connections {
            target: controller
            function onLogAdded(line) { lines.insert(0, line) }
            function onLogCleared() { lines.clear() }
        }
        Component.onCompleted: {
            const known = controller.journeyLines()
            for (let i = 0; i < known.length; i++)
                lines.insert(0, known[i])
        }

        ListView {
            id: logView
            objectName: "journal"
            anchors.fill: parent
            clip: true
            model: lines
            spacing: 3
            boundsBehavior: Flickable.StopAtBounds
            verticalLayoutDirection: ListView.BottomToTop
            delegate: Row {
                required property string time
                required property string text
                required property string kind
                width: logView.width
                spacing: 12
                opacity: Math.max(0, Math.min(1, (y - logView.contentY) / 28))  // older lines fade out at the top
                Text {
                    text: parent.time
                    color: Theme.textMuted
                    font.family: Theme.monoFamily; font.pixelSize: 12
                    style: Text.Outline; styleColor: Qt.rgba(0, 0, 0, 0.8)
                }
                Text {
                    width: parent.width - 60
                    wrapMode: Text.Wrap
                    text: (parent.kind === "stage" ? "▸ " : parent.kind === "done" ? "✓ " : parent.kind === "warn" ? "! "
                           : parent.kind === "error" ? "✕ " : parent.kind === "detail" ? "  · " : "› ") + parent.text
                    color: parent.kind === "stage" ? Theme.gold : parent.kind === "done" ? Theme.success
                         : parent.kind === "warn" ? Theme.warning : parent.kind === "error" ? Theme.danger
                         : parent.kind === "detail" ? Theme.textMuted : Theme.text
                    font.family: Theme.monoFamily; font.pixelSize: 12
                    font.weight: parent.kind === "stage" ? Font.DemiBold : Font.Normal
                    style: Text.Outline; styleColor: Qt.rgba(0, 0, 0, 0.8)
                }
            }
        }
    }

    Rectangle {  // the garden fades into the result
        anchors.fill: parent
        color: Theme.bg
        opacity: garden.fade
    }
}
