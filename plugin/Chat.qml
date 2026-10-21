import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.Commons
import qs.Ui

Item {
    id: root
    property var shell: null
    property var manifest: null
    property bool opened: false
    property bool compact: true
    readonly property bool wantsKeyboardFocus: opened && !compact
    property string phase: "idle"
    property string phaseLabel: "Ready"
    property string sessionId: ""
    property string dismissedSession: ""
    property var targetScreen: null
    property var snapshot: ({})
    property int selected: 0
    property string actionError: ""
    property bool typing: false
    readonly property bool listening: phase === "listening"
    readonly property var display: snapshot.display || null
    readonly property var items: display && Array.isArray(display.items) ? display.items : []
    readonly property var selectedItem: items.length ? items[Math.min(selected, items.length - 1)] : ({})
    readonly property var turn: (snapshot.turns || []).length ? snapshot.turns[snapshot.turns.length - 1] : ({})
    readonly property var tools: turn.tools || []
    readonly property var latestTool: tools.length ? tools[tools.length - 1] : null
    readonly property bool expanded: !!display || !!turn.assistant || !!snapshot.error || typing
    readonly property string heard: (snapshot.transcript && snapshot.transcript.text) ? String(snapshot.transcript.text) : ""
    readonly property string transcript: heard || (listening ? "" : (turn.user || ""))
    readonly property var completion: snapshot.completion || null
    readonly property real strength: listening && snapshot.level_db !== null && snapshot.level_db !== undefined && isFinite(Number(snapshot.level_db)) ? Math.max(0, Math.min(1, (Number(snapshot.level_db) + 70) / 65)) : 0
    readonly property color ink: Color.foreground
    readonly property color inkMuted: Util.alpha(Color.foreground, 0.62)
    readonly property color statusColor: Color.accent
    readonly property bool showsActions: !listening && (expanded || phase === "idle" || phase === "error")
    readonly property string placement: String(snapshot.placement || "bottom-right")
    readonly property bool atTop: placement.startsWith("top")
    readonly property bool atRight: placement.endsWith("right")
    readonly property int textTowardOrb: atRight ? Text.AlignRight : Text.AlignLeft
    property string runtimeDir: Quickshell.env("XDG_RUNTIME_DIR") || ("/run/user/" + Quickshell.env("UID"))

    function chooseScreen() {
        var name = Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : "";
        for (var i = 0; i < Quickshell.screens.length; i++) {
            if (Quickshell.screens[i].name === name) {
                targetScreen = Quickshell.screens[i];
                return;
            }
        }
        targetScreen = Quickshell.screens.length ? Quickshell.screens[0] : null;
    }
    function open(payloadJson) {
        dismissedSession = "";
        chooseScreen();
        opened = true;
        uiFile.reload();
    }
    function close() {
        dismiss();
    }
    function dismiss() {
        if (!opened)
            return;
        dismissedSession = sessionId;
        opened = false;
        compact = true;
        if (phase === "listening" || phase === "thinking" || phase === "speaking")
            Quickshell.execDetached(["agavai", "cancel"]);
        if (shell && typeof shell.hide === "function")
            shell.hide((manifest && manifest.id) || "janar.agavai");
    }
    function start() {
        typing = false;
        Quickshell.execDetached(["agavai", "invoke"]);
    }
    function ask() {
        var text = typedInput.text.trim();
        if (!text || askProc.running)
            return;
        typing = false;
        typedInput.text = "";
        askProc.command = ["agavai", "ask", text];
        askProc.running = true;
    }
    function send() {
        if (listening)
            Quickshell.execDetached(["agavai", "stop"]);
    }
    function openSelected() {
        if (!selectedItem.openable || openProc.running)
            return;
        actionError = "";
        openProc.command = ["agavai", "ui-open", String(selected), "--session", sessionId];
        openProc.running = true;
    }
    function applySnapshot(raw) {
        var obj;
        try {
            obj = JSON.parse(String(raw || "{}"));
        } catch (e) {
            return;
        }
        if (!obj || typeof obj !== "object" || Array.isArray(obj))
            return;
        var nextSession = String(obj.session_id || "");
        var nextDisplay = JSON.stringify(obj.display || null);
        var canvasChanged = !!obj.display && nextDisplay !== JSON.stringify(snapshot.display || null);
        if (nextSession !== sessionId) {
            selected = 0;
            actionError = "";
            chooseScreen();
        } else if (nextDisplay !== JSON.stringify(snapshot.display || null))
            selected = 0;
        sessionId = nextSession;
        snapshot = obj;
        phase = String(obj.phase || "idle");
        phaseLabel = String(obj.phase_label || phase);
        if (sessionId !== dismissedSession && (phase !== "idle" || expanded)) {
            opened = true;
            if (canvasChanged)
                compact = false;
        }
    }
    function acquireFocus() {
        if (!wantsKeyboardFocus)
            return;
        Qt.callLater(function () {
            if (root.wantsKeyboardFocus) {
                keyTarget.forceActiveFocus();
                panel.contentItem.Window.window.requestActivate();
            }
        });
    }
    onExpandedChanged: acquireFocus()
    onWantsKeyboardFocusChanged: acquireFocus()

    Connections {
        target: panel.contentItem.Window.window
        function onActiveChanged() {
            if (root.wantsKeyboardFocus && !target.active)
                root.compact = true;
        }
    }

    FileView {
        id: uiFile
        path: root.runtimeDir + "/agavai/ui.json"
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: root.applySnapshot(text())
    }
    Process {
        id: askProc
    }
    Process {
        id: openProc
        onExited: exitCode => {
            if (exitCode !== 0)
                root.actionError = "This item could not be opened. Try searching again.";
        }
    }
    IpcHandler {
        target: "janar.agavai"
        function open(payloadJson: string): string {
            root.open(payloadJson);
            return "ok";
        }
        function close(): string {
            root.dismiss();
            return "ok";
        }
        function ping(): string {
            return "ok";
        }
    }

    // The menu surface is what made this read as an Omarchy popup. Listening
    // stays an unbordered orb; results grow a sheet from that same orb.
    PanelWindow {
        id: panel
        objectName: "agavaiPanel"
        screen: root.targetScreen
        visible: root.opened
        anchors {
            top: true
            bottom: true
            left: true
            right: true
        }
        color: "transparent"
        WlrLayershell.namespace: "agavai-chat"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: root.wantsKeyboardFocus ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore
        mask: Region {
            item: stage
        }

        Item {
            id: stage
            objectName: "agavaiStage"
            readonly property int edgeMargin: Style.space(28)
            readonly property int orbSize: Style.space(80)
            readonly property int sheetWidth: Math.max(1, Math.min(Style.space(680), panel.width - edgeMargin * 2))
            readonly property int voiceWidth: Math.max(1, Math.min(Style.space(440), panel.width - edgeMargin * 2))
            readonly property int inset: Style.space(18)
            width: root.compact ? orbSize : root.expanded ? sheetWidth : voiceWidth
            height: root.compact ? orbSize : Math.min(Math.max(col.implicitHeight + inset * 2, orbSize), panel.height - edgeMargin * 2)
            clip: true
            // The orb's corner is fixed, so expanding grows the sheet away from it.
            x: root.atRight ? parent.width - width - edgeMargin : edgeMargin
            y: root.atTop ? edgeMargin : parent.height - height - edgeMargin

            Rectangle {
                visible: !root.compact
                anchors.fill: parent
                radius: Style.space(28)
                color: Util.alpha(Color.background, 0.94)
            }

            FocusScope {
                id: keyTarget
                objectName: "agavaiDetails"
                visible: !root.compact
                anchors.fill: parent
                focus: root.wantsKeyboardFocus
                Keys.onPressed: event => {
                    if (event.key === Qt.Key_Escape) {
                        root.dismiss();
                        event.accepted = true;
                    } else if (event.key === Qt.Key_Down && root.items.length) {
                        root.selected = Math.min(root.items.length - 1, root.selected + 1);
                        event.accepted = true;
                    } else if (event.key === Qt.Key_Up && root.items.length) {
                        root.selected = Math.max(0, root.selected - 1);
                        event.accepted = true;
                    } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                        root.listening ? root.send() : root.openSelected();
                        event.accepted = true;
                    }
                }
                // The voice row sits against the orb; results and actions are on its far side.
                GridLayout {
                    id: col
                    columns: 1
                    width: Math.max(1, parent.width - stage.inset * 2)
                    x: stage.inset
                    y: root.atTop ? stage.inset : parent.height - implicitHeight - stage.inset
                    rowSpacing: Style.space(12)

                    ColumnLayout {
                        Layout.row: root.atTop ? 1 : 0
                        Layout.column: 0
                        Layout.fillWidth: true
                        visible: !!root.display || root.actionError !== "" || root.typing || root.showsActions || !!root.latestTool
                        spacing: Style.space(12)

                        ResultBrowser {
                            visible: !!root.display
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(Style.space(320), Math.max(Style.space(120), panel.height * 0.42))
                            display: root.display || ({})
                            selected: root.selected
                            onSelectRequested: index => {
                                root.selected = index;
                                keyTarget.forceActiveFocus();
                            }
                            onOpenRequested: root.openSelected()
                        }
                        Text {
                            visible: root.actionError !== ""
                            Layout.fillWidth: true
                            text: root.actionError
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            horizontalAlignment: Text.AlignHCenter
                            color: root.statusColor
                            font.family: Style.font.family
                            font.pixelSize: Style.font.caption
                        }
                        RowLayout {
                            visible: root.typing
                            Layout.fillWidth: true
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: Style.space(40)
                                radius: Style.space(20)
                                color: Util.alpha(Color.foreground, 0.06)
                                TextInput {
                                    id: typedInput
                                    anchors.fill: parent
                                    anchors.margins: Style.space(10)
                                    color: root.ink
                                    font.family: Style.font.family
                                    font.pixelSize: Style.font.body
                                    clip: true
                                    horizontalAlignment: Text.AlignHCenter
                                    selectByMouse: true
                                    onAccepted: root.ask()
                                }
                                Text {
                                    visible: typedInput.text === ""
                                    anchors.fill: typedInput
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    text: "Type a request…"
                                    color: root.inkMuted
                                    font.family: Style.font.family
                                    font.pixelSize: Style.font.body
                                }
                            }
                            NativeButton {
                                text: "Ask"
                                enabled: typedInput.text.trim() !== "" && !askProc.running
                                onClicked: root.ask()
                            }
                        }
                        RowLayout {
                            visible: root.showsActions
                            Layout.alignment: Qt.AlignHCenter
                            spacing: Style.space(4)
                            NativeButton {
                                quiet: true
                                visible: root.phase === "idle" || root.phase === "error"
                                text: root.typing ? "Voice" : "Type instead"
                                onClicked: {
                                    root.typing = !root.typing;
                                    if (root.typing)
                                        Qt.callLater(function () {
                                            typedInput.forceActiveFocus();
                                        });
                                }
                            }
                            NativeButton {
                                quiet: true
                                visible: !root.listening && root.phase !== "thinking" && root.phase !== "speaking"
                                text: root.transcript ? "Ask again" : "Listen"
                                onClicked: root.start()
                            }
                            NativeButton {
                                quiet: true
                                visible: !!root.selectedItem.openable
                                text: "Open"
                                onClicked: root.openSelected()
                            }
                        }
                        Text {
                            visible: !!root.latestTool
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignHCenter
                            text: root.latestTool ? root.latestTool.name.replace(/_/g, " ") : ""
                            textFormat: Text.PlainText
                            color: root.inkMuted
                            font.family: Style.font.family
                            font.pixelSize: Style.font.caption
                            elide: Text.ElideRight
                        }
                    }

                    RowLayout {
                        Layout.row: root.atTop ? 0 : 1
                        Layout.column: 0
                        Layout.fillWidth: true
                        layoutDirection: root.atRight ? Qt.LeftToRight : Qt.RightToLeft
                        spacing: Style.space(12)

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                            spacing: Style.space(6)

                            RowLayout {
                                Layout.fillWidth: true
                                layoutDirection: root.atRight ? Qt.LeftToRight : Qt.RightToLeft
                                Text {
                                    Layout.fillWidth: true
                                    horizontalAlignment: root.textTowardOrb
                                    text: root.snapshot.error ? "Something went wrong" : root.phase === "idle" && root.expanded ? "Here’s what I found" : root.phaseLabel
                                    textFormat: Text.PlainText
                                    color: root.statusColor
                                    font.family: Style.font.family
                                    font.pixelSize: Style.font.caption
                                    elide: Text.ElideRight
                                }
                                NativeButton {
                                    objectName: "agavaiMinimize"
                                    quiet: true
                                    text: "−"
                                    accessibleName: "Minimize assistant"
                                    onClicked: root.compact = true
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                horizontalAlignment: root.textTowardOrb
                                text: root.transcript || (root.listening ? "Listening…" : "What can I help you find?")
                                textFormat: Text.PlainText
                                color: root.transcript ? root.ink : root.inkMuted
                                font.family: Style.font.family
                                font.pixelSize: root.expanded ? Style.font.heading : Style.font.display
                                wrapMode: Text.Wrap
                                maximumLineCount: 3
                                elide: Text.ElideRight
                            }
                            Text {
                                visible: root.listening || !(root.turn.assistant || root.snapshot.error)
                                Layout.fillWidth: true
                                horizontalAlignment: root.textTowardOrb
                                text: root.listening ? (root.completion ? "Still listening. Escape dismisses." : (root.expanded ? "Listening for your answer. It sends when you finish, or press Enter." : "Speak naturally. It sends when you finish, or press Enter.")) : root.phase === "thinking" ? "Working on your request…" : root.transcript ? "Voice request" : "Press Super+M or click Listen."
                                textFormat: Text.PlainText
                                color: root.inkMuted
                                font.family: Style.font.family
                                font.pixelSize: Style.font.caption
                                wrapMode: Text.Wrap
                            }
                            Text {
                                visible: !!root.completion
                                Layout.fillWidth: true
                                horizontalAlignment: root.textTowardOrb
                                wrapMode: Text.Wrap
                                text: root.completion ? ((root.completion.ok ? "✓ " : "") + root.completion.title + (root.completion.detail ? " · " + root.completion.detail : "")) : ""
                                textFormat: Text.PlainText
                                color: root.statusColor
                                font.family: Style.font.family
                                font.pixelSize: Style.font.heading
                            }
                            Text {
                                id: answer
                                visible: !!root.turn.assistant || !!root.snapshot.error
                                Layout.fillWidth: true
                                horizontalAlignment: root.textTowardOrb
                                wrapMode: Text.Wrap
                                maximumLineCount: 6
                                elide: Text.ElideRight
                                text: root.snapshot.error ? String(root.snapshot.error) : root.turn.assistant || ""
                                textFormat: Text.PlainText
                                color: root.ink
                                font.family: Style.font.family
                                font.pixelSize: Style.font.heading
                            }
                            Text {
                                visible: root.listening
                                Layout.alignment: root.atRight ? Qt.AlignRight : Qt.AlignLeft
                                text: "Send now"
                                textFormat: Text.PlainText
                                color: root.ink
                                font.family: Style.font.family
                                font.pixelSize: Style.font.caption
                                Accessible.role: Accessible.Button
                                Accessible.name: "Send now"
                                Accessible.onPressAction: root.send()
                                MouseArea {
                                    anchors.fill: parent
                                    anchors.margins: -Style.space(6)
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.send()
                                }
                            }
                        }
                        // Keeps the words clear of the orb, which is placed outside the layout.
                        Item {
                            Layout.preferredWidth: stage.orbSize - stage.inset
                            Layout.preferredHeight: stage.orbSize - stage.inset
                            Layout.alignment: root.atTop ? Qt.AlignTop : Qt.AlignBottom
                        }
                    }
                }
            }
            Item {
                id: orb
                objectName: "agavaiOrb"
                width: stage.orbSize
                height: stage.orbSize
                x: root.atRight ? stage.width - width : 0
                y: root.atTop ? 0 : stage.height - height
                Accessible.role: Accessible.Button
                Accessible.name: root.compact ? "Expand Agavai" : "Minimize Agavai"
                Accessible.onPressAction: root.compact = !root.compact
                VoiceOrb {
                    anchors.fill: parent
                    phase: root.phase
                    strength: root.strength
                }
                MouseArea {
                    objectName: "agavaiOrbPointer"
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    cursorShape: Qt.PointingHandCursor
                    onClicked: mouse => {
                        if (mouse.button === Qt.RightButton)
                            root.dismiss();
                        else
                            root.compact = !root.compact;
                    }
                }
                NativeButton {
                    objectName: "agavaiClose"
                    x: root.atRight ? parent.width - width : 0
                    width: Style.space(32)
                    height: Style.space(32)
                    text: "×"
                    accessibleName: "Dismiss assistant"
                    onClicked: root.dismiss()
                }
            }
        }
    }
}
