import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "."

ApplicationWindow {
    id: win
    width: 1320
    height: 840
    minimumWidth: 1060
    minimumHeight: 680
    visible: true
    title: controller.projectName !== "" ? controller.projectName + " — Eden" : "Eden"
    color: Theme.bg
    font.family: Theme.fontFamily

    property bool playSplash: true
    property bool splashDone: false

    Backdrop { anchors.fill: parent }

    Item {
        id: shell
        anchors.fill: parent
        opacity: win.splashDone ? 1 : 0
        scale: win.splashDone ? 1 : 0.985
        Behavior on opacity { NumberAnimation { duration: 800; easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: 1000; easing.type: Easing.OutCubic } }

        Sidebar {
            id: sidebar
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: 268
        }

        ColumnLayout {
            anchors { left: sidebar.right; right: parent.right; top: parent.top; bottom: parent.bottom; margins: 34 }
            spacing: 16

            Banner {
                Layout.fillWidth: true
                kind: "update"
                title: "Mise à jour"
                message: controller.updateMessage
                onClosed: shown = false
            }

            Banner {
                Layout.fillWidth: true
                kind: "error"
                title: controller.errorStep !== "" ? "Échec à l'étape « " + controller.errorStep + " »" : ""
                message: controller.errorMessage
                onClosed: controller.clearError()
                actions: [
                    EdenButton {
                        visible: controller.needsFlPath
                        compact: true
                        primary: true
                        text: "Indiquer où est FL Studio"
                        onClicked: flDialog.open()
                    }
                ]
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                HomePage {
                    anchors.fill: parent
                    active: controller.stage === "home"
                    onPickProject: projectDialog.open()
                }
                AnalysisPage {
                    anchors.fill: parent
                    active: controller.stage === "analyzing" || controller.stage === "analyzed"
                }
                RenderPage {
                    anchors.fill: parent
                    active: controller.stage === "rendering" || controller.stage === "rendered"
                }
                MixPage {
                    anchors.fill: parent
                    active: controller.stage === "mixing" || controller.stage === "mixed"
                    onChooseFolder: exportDialog.open()
                }
            }
        }
    }

    Splash {
        anchors.fill: parent
        play: win.playSplash
        onFinished: win.splashDone = true
    }

    FileDialog {
        id: projectDialog
        title: "Choisir un projet FL Studio"
        nameFilters: ["Projets FL Studio (*.flp)"]
        onAccepted: controller.openProject(selectedFile.toString())
    }

    FolderDialog {
        id: exportDialog
        title: "Dossier où enregistrer le WAV"
        onAccepted: controller.setExportFolder(selectedFolder.toString())
    }

    FileDialog {
        id: flDialog
        title: "Où est FL Studio ? (FL64.exe)"
        nameFilters: ["FL Studio (FL64.exe FL.exe)", "Programmes (*.exe)"]
        onAccepted: {
            controller.setFlStudioPath(selectedFile.toString())
            controller.renderFromFl()
        }
    }
}
