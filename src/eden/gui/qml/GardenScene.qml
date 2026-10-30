import QtQuick
import QtQuick3D
import Eden.Garden

// The garden in 3D: lawn, the tree growing from its seed (garden.py), the apple of the end.
// Units are metres. The parent drives everything through the properties below.
View3D {
    id: view
    property real growth: 0
    property real time: 0
    property real yaw: 30
    property real pitch: -16
    property real distance: 1.4
    property vector3d target: Qt.vector3d(0, 0.08, 0)
    property real appleScale: 0
    property vector3d applePosition: GardenInfo.appleCenter
    property vector3d appleRotation: Qt.vector3d(0, 0, 0)
    property real appleLight: 0  // a soft light on the apple while the camera looks at it
    readonly property color horizon: "#CFE6F7"  // the parent's sky meets the fog there: a pale blue haze

    camera: camera
    environment: SceneEnvironment {
        backgroundMode: SceneEnvironment.Transparent
        antialiasingMode: SceneEnvironment.MSAA
        antialiasingQuality: SceneEnvironment.High
        tonemapMode: SceneEnvironment.TonemapModeFilmic
        fog: Fog {
            enabled: true
            color: view.horizon
            depthEnabled: true
            // from just behind the tree to the lawn's far edge (18 m from its centre): the tree stays clear
            depthNear: view.distance + 2.5
            depthFar: view.distance + 18
        }
    }

    Node {
        position: view.target
        eulerRotation: Qt.vector3d(view.pitch, view.yaw, 0)
        PerspectiveCamera {
            id: camera
            z: view.distance
            fieldOfView: 38
            clipNear: 0.02
            clipFar: 120
        }
    }

    // a sunny day: the sun, the blue sky's light from everywhere, a warm glow from the crown as it fills
    DirectionalLight {
        eulerRotation: Qt.vector3d(-42, -38, 0)
        color: "#FFF3DC"
        brightness: 1.5
        ambientColor: "#4A5A72"
        castsShadow: true
        shadowMapQuality: Light.ShadowMapQualityHigh
        shadowMapFar: 30
        shadowFactor: 62
        pcfFactor: 3
        softShadowQuality: Light.PCF8
    }
    DirectionalLight {
        eulerRotation: Qt.vector3d(-18, 150, 0)
        color: "#A9C6EE"
        brightness: 0.55
    }
    PointLight {
        position: Qt.vector3d(0, 3.1, 0.4)
        color: "#FFC83A"
        brightness: 0.5 * Math.max(0, (view.growth - 0.35) / 0.65)
        quadraticFade: 0.6
    }

    Model {
        geometry: GardenMesh { kind: "ground" }
        castsShadows: false
        materials: PrincipledMaterial { vertexColorsEnabled: true; roughness: 0.95; specularAmount: 0.05 }
    }
    Model {
        geometry: GardenMesh { kind: "mound" }
        castsShadows: false
        materials: PrincipledMaterial { vertexColorsEnabled: true; roughness: 1.0; specularAmount: 0.05 }
    }
    Model {
        geometry: GardenMesh { kind: "seed" }
        scale: Qt.vector3d(s, s, s)
        readonly property real s: 1 - Math.min(1, Math.max(0, (view.growth - 0.035) / 0.045))
        visible: s > 0.01
        materials: PrincipledMaterial { vertexColorsEnabled: true; roughness: 0.6 }
    }

    Model {
        geometry: GardenMesh { kind: "branch" }
        instancing: GardenInstances { kind: "branches" }
        materials: CustomMaterial {
            property real growth: view.growth
            property real time: view.time
            property real roughness: 0.92
            property real shine: 0.08
            property real glow: 0.0
            vertexShader: "shaders/branch.vert"
            fragmentShader: "shaders/facet.frag"
        }
    }
    Model {
        geometry: GardenMesh { kind: "leaf" }
        instancing: GardenInstances { kind: "leaves" }
        materials: CustomMaterial {
            property real growth: view.growth
            property real time: view.time
            property real roughness: 0.7
            property real shine: 0.18
            property real glow: 0.14  // golden like the logo even in the crown's shade
            vertexShader: "shaders/leaf.vert"
            fragmentShader: "shaders/facet.frag"
        }
    }
    Model {
        geometry: GardenMesh { kind: "grass" }
        instancing: GardenInstances { kind: "grass" }
        castsShadows: false
        materials: CustomMaterial {
            property real time: view.time
            property real roughness: 0.9
            property real shine: 0.05
            property real glow: 0.0
            vertexShader: "shaders/plant.vert"
            fragmentShader: "shaders/facet.frag"
        }
    }
    Model {
        geometry: GardenMesh { kind: "flower" }
        instancing: GardenInstances { kind: "flowers" }
        castsShadows: false
        materials: CustomMaterial {
            property real time: view.time
            property real roughness: 0.8
            property real shine: 0.1
            property real glow: 0.05
            vertexShader: "shaders/plant.vert"
            fragmentShader: "shaders/facet.frag"
        }
    }
    Model {
        geometry: GardenMesh { kind: "stone" }
        instancing: GardenInstances { kind: "stones" }
        materials: PrincipledMaterial { vertexColorsEnabled: true; roughness: 0.85 }
    }

    PointLight {
        position: Qt.vector3d(view.applePosition.x * 1.45, view.applePosition.y + 0.5, view.applePosition.z * 1.45)
        color: "#FFE7C2"
        brightness: 1.6 * view.appleLight
        quadraticFade: 2.5
        visible: view.appleLight > 0
    }
    Model {
        id: apple
        geometry: GardenMesh { kind: "apple" }
        position: view.applePosition
        eulerRotation: view.appleRotation
        scale: Qt.vector3d(view.appleScale, view.appleScale, view.appleScale)
        visible: view.appleScale > 0.001
        materials: PrincipledMaterial { vertexColorsEnabled: true; roughness: 0.32; specularAmount: 0.6 }
    }
}
