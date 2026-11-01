/*
    SPDX-License-Identifier: GPL-3.0-or-later

    Nitro Panel widget for the Plasma system tray. All hardware access goes
    through the nitro-panel command: this file reads `nitro-panel --status`
    and runs its other options.
*/

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.extras as PlasmaExtras
import org.kde.plasma.plasma5support as P5Support
import org.kde.plasma.plasmoid

PlasmoidItem {
    id: root

    readonly property string command: "nitro-panel"
    readonly property string statusCommand: command + " --status"

    property var info: null      // the last --status output
    property string error: ""

    readonly property var modes: info ? info.modes : []
    readonly property int modeIndex: modes.findIndex(m => m.id === info.mode)
    readonly property string modeLabel: modeIndex >= 0 ? modes[modeIndex].label : ""

    Plasmoid.status: PlasmaCore.Types.ActiveStatus
    Plasmoid.icon: {
        const mode = info ? info.mode : "";
        if (mode === "low-power" || mode === "quiet")
            return "battery-profile-powersave-symbolic";
        if (mode === "balanced-performance" || mode === "performance")
            return "battery-profile-performance-symbolic";
        return "battery-profile-balanced-symbolic";
    }

    toolTipMainText: "Nitro Panel"
    toolTipSubText: {
        if (!info)
            return error;
        const lines = ["Power mode: " + modeLabel];
        const s = info.sensors;
        if (s.cpu_temp !== null && s.gpu_temp !== null)
            lines.push("CPU " + s.cpu_temp + "°C · GPU " + s.gpu_temp + "°C");
        return lines.join("\n");
    }

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: "Open Nitro Panel"
            icon.name: "configure"
            onTriggered: root.openPanel()
        }
    ]

    function quote(text) {
        return "'" + text.replace(/'/g, "'\\''") + "'";
    }

    function run(args) {
        error = "";
        executable.connectSource(command + " " + args);
    }

    function refresh() {
        executable.connectSource(statusCommand);
    }

    function openPanel() {
        // Detach it, or the data engine would wait until the window closes
        executable.connectSource(command + " >/dev/null 2>&1 &");
        expanded = false;
    }

    P5Support.DataSource {
        id: executable
        engine: "executable"
        connectedSources: []

        onNewData: (source, data) => {
            disconnectSource(source);
            const failed = data["exit code"] !== 0;
            if (source === root.statusCommand) {
                if (failed) {
                    root.error = data.stderr.trim() || "The nitro-panel command was not found.";
                    return;
                }
                try {
                    root.info = JSON.parse(data.stdout);
                } catch (e) {
                    root.error = "nitro-panel --status gave unexpected output.";
                }
                return;
            }
            if (failed)
                root.error = data.stderr.replace(/^nitro-panel: /, "").trim();
            root.refresh();
        }
    }

    // Quick while the popup is open, slow otherwise (only the icon and tooltip need it)
    Timer {
        interval: root.expanded ? 2000 : 10000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.refresh()
    }

    onExpandedChanged: {
        if (root.expanded)
            refresh();
    }

    fullRepresentation: PlasmaExtras.Representation {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 18
        Layout.preferredWidth: Kirigami.Units.gridUnit * 21
        Layout.preferredHeight: content.implicitHeight + Kirigami.Units.largeSpacing * 2

        contentItem: ColumnLayout {
            id: content
            spacing: Kirigami.Units.largeSpacing * 2

            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: root.error !== ""
                type: Kirigami.MessageType.Error
                text: root.error
            }

            PlasmaExtras.PlaceholderMessage {
                Layout.fillWidth: true
                visible: root.info !== null && !root.info.available
                iconName: "dialog-warning"
                text: "Linuwu-Sense is not loaded"
                explanation: "Nitro Panel needs the linuwu_sense kernel module."
            }

            // Power mode, laid out like the power profile slider in Power and Battery
            Section {
                visible: root.info !== null && root.info.available
                iconName: "speedometer"

                RowLayout {
                    Layout.fillWidth: true
                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        text: "Power mode"
                    }
                    PlasmaComponents3.Label {
                        text: root.modes.length ? root.modes[Math.round(modeSlider.value)].label : ""
                    }
                }

                PlasmaComponents3.Slider {
                    id: modeSlider
                    Layout.fillWidth: true
                    from: 0
                    to: Math.max(root.modes.length - 1, 1)
                    stepSize: 1
                    snapMode: QQC2.Slider.SnapAlways
                    value: Math.max(root.modeIndex, 0)

                    function commit() {
                        const mode = root.modes[Math.round(value)];
                        if (!mode || mode.id === root.info.mode)
                            return;
                        if (!mode.available) {
                            root.error = mode.label + " is not available right now.";
                            value = Qt.binding(() => Math.max(root.modeIndex, 0));
                            return;
                        }
                        root.run("--mode " + mode.id);
                    }

                    onPressedChanged: if (!pressed) commit()
                    onMoved: if (!pressed) commit()
                }

                RowLayout {
                    Layout.fillWidth: true
                    Kirigami.Icon {
                        source: "battery-profile-powersave-symbolic"
                        implicitWidth: Kirigami.Units.iconSizes.small
                        implicitHeight: Kirigami.Units.iconSizes.small
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    Kirigami.Icon {
                        source: "battery-profile-performance-symbolic"
                        implicitWidth: Kirigami.Units.iconSizes.small
                        implicitHeight: Kirigami.Units.iconSizes.small
                    }
                }
            }

            Section {
                visible: root.info !== null && root.info.profiles.length > 0
                iconName: "bookmarks"

                PlasmaComponents3.Label {
                    text: "Profiles"
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing

                    Repeater {
                        model: root.info ? root.info.profiles : []
                        PlasmaComponents3.Button {
                            required property string modelData
                            text: modelData
                            onClicked: root.run("--profile " + root.quote(modelData))
                        }
                    }
                }
            }

            Section {
                visible: root.info !== null && root.info.keyboard_brightness !== null
                iconName: "input-keyboard-brightness"

                RowLayout {
                    Layout.fillWidth: true
                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        text: "Keyboard light"
                    }

                    // Steps like NitroSense (off, 25, 50, 75, 100%) or every percent
                    RowLayout {
                        spacing: 0
                        PlasmaComponents3.ToolButton {
                            text: "Steps"
                            checkable: true
                            autoExclusive: true
                            checked: root.info !== null && !root.info.keyboard_fine
                            onClicked: root.run("--kb-fine off")
                        }
                        PlasmaComponents3.ToolButton {
                            text: "Fine"
                            checkable: true
                            autoExclusive: true
                            checked: root.info !== null && root.info.keyboard_fine
                            onClicked: root.run("--kb-fine on")
                        }
                    }

                    PlasmaComponents3.Label {
                        Layout.minimumWidth: percentMetrics.width
                        horizontalAlignment: Text.AlignRight
                        text: Math.round(kbSlider.value) === 0 ? "Off" : Math.round(kbSlider.value) + "%"

                        TextMetrics {
                            id: percentMetrics
                            text: "100%"
                        }
                    }
                }

                PlasmaComponents3.Slider {
                    id: kbSlider
                    Layout.fillWidth: true
                    from: 0
                    to: 100
                    stepSize: root.info && root.info.keyboard_fine ? 1 : 25
                    snapMode: QQC2.Slider.SnapAlways
                    value: root.info && root.info.keyboard_brightness !== null ? root.info.keyboard_brightness : 0

                    function commit() {
                        if (Math.round(value) !== root.info.keyboard_brightness)
                            root.run("--kb-brightness " + Math.round(value));
                    }

                    onPressedChanged: if (!pressed) commit()
                    onMoved: if (!pressed) commit()
                }
            }

            Section {
                visible: root.info !== null && root.info.battery_limit !== null
                iconName: "battery-good-symbolic"

                PlasmaComponents3.Switch {
                    Layout.fillWidth: true
                    text: "Stop charging at 80%"
                    checked: root.info !== null && root.info.battery_limit === true
                    onToggled: root.run("--battery-limit " + (checked ? "on" : "off"))
                }
            }

            Section {
                visible: root.info !== null && root.info.sensors.cpu_temp !== null
                iconName: "temperature-normal"

                Repeater {
                    model: [["CPU", "cpu_temp", "cpu_fan"], ["GPU", "gpu_temp", "gpu_fan"]]

                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.gridUnit

                        PlasmaComponents3.Label {
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 2
                            text: modelData[0]
                        }
                        PlasmaComponents3.Label {
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 3
                            text: root.info ? root.info.sensors[modelData[1]] + "°C" : ""
                        }
                        PlasmaComponents3.Label {
                            Layout.fillWidth: true
                            opacity: 0.7
                            text: root.info ? root.info.sensors[modelData[2]] + " RPM" : ""
                        }
                    }
                }
            }

            // Keeps the sections together at the top when the popup is taller
            Item {
                Layout.fillHeight: true
            }

            PlasmaComponents3.Button {
                Layout.alignment: Qt.AlignRight
                icon.name: "configure"
                text: "Open Nitro Panel…"
                onClicked: root.openPanel()
            }
        }
    }

    // A row with a large icon on the left, like the sections in Power and Battery
    component Section: RowLayout {
        id: section
        property string iconName
        default property alias items: column.data

        Layout.fillWidth: true
        spacing: Kirigami.Units.gridUnit

        Kirigami.Icon {
            Layout.alignment: Qt.AlignTop
            source: section.iconName
            implicitWidth: Kirigami.Units.iconSizes.medium
            implicitHeight: Kirigami.Units.iconSizes.medium
        }

        ColumnLayout {
            id: column
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
        }
    }
}
