import QtQuick
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
        if (phase === "listening" || phase === "transcribing" || phase === "thinking" || phase === "speaking")
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
        if (sessionId !== dismissedSession && (phase !== "idle" || expanded))
            opened = true;
    }
    function acquireFocus() {
        if (!opened)
            return;
        Qt.callLater(function () {
            keyTarget.forceActiveFocus();
        });
    }
    onExpandedChanged: acquireFocus()
    onOpenedChanged: acquireFocus()
    Timer {
        interval: 32
        repeat: true
        running: root.opened
        onTriggered: {
            var working = root.phase === "thinking" || root.phase === "speaking" || root.phase === "transcribing";
            // Silence settles the orb. Speech is what speeds it up.
            var step = root.listening ? 0.006 + root.strength * 0.1 : working ? 0.022 : 0.004;
            orb.spin = (orb.spin + step) % (Math.PI * 2);
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
        WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore
        mask: Region {
            item: stage
        }

        Item {
            id: stage
            readonly property int sheetWidth: Math.max(1, Math.min(Style.space(680), panel.width - Style.gapsOut * 2))
            readonly property int voiceWidth: Math.max(1, Math.min(Style.space(440), panel.width - Style.gapsOut * 2))
            width: root.expanded ? sheetWidth : voiceWidth
            readonly property int inset: Style.space(18)
            height: Math.min(Math.max(col.implicitHeight + inset * 2, Style.space(220)), Math.max(Style.space(280), panel.height - Style.space(40)))
            clip: true
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: Style.space(28)

            Rectangle {
                anchors.fill: parent
                radius: Style.space(28)
                color: Util.alpha(Color.background, 0.94)
            }

            FocusScope {
                id: keyTarget
                anchors.fill: parent
                focus: true
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
                ColumnLayout {
                    id: col
                    width: Math.max(1, parent.width - stage.inset * 2)
                    x: stage.inset
                    y: Math.max(stage.inset, parent.height - implicitHeight - stage.inset)
                    spacing: Style.space(12)

                    Item {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(dismissMark.implicitHeight, phaseText.implicitHeight)
                        Text {
                            id: phaseText
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: Math.max(1, parent.width - dismissMark.width - Style.space(12))
                            horizontalAlignment: Text.AlignHCenter
                            text: root.snapshot.error ? "Something went wrong" : root.phase === "idle" && root.expanded ? "Here’s what I found" : root.phaseLabel
                            textFormat: Text.PlainText
                            color: root.statusColor
                            font.family: Style.font.family
                            font.pixelSize: Style.font.caption
                            elide: Text.ElideRight
                        }
                        Text {
                            id: dismissMark
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            text: "×"
                            textFormat: Text.PlainText
                            color: root.inkMuted
                            font.family: Style.font.family
                            font.pixelSize: Style.space(18)
                            Accessible.role: Accessible.Button
                            Accessible.name: "Dismiss assistant"
                            Accessible.onPressAction: root.dismiss()
                            MouseArea {
                                anchors.fill: parent
                                anchors.margins: -Style.space(6)
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.dismiss()
                            }
                        }
                    }
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
                        visible: !root.listening && (root.expanded || root.phase === "idle" || root.phase === "error")
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
                            visible: !root.listening && root.phase !== "thinking" && root.phase !== "transcribing" && root.phase !== "speaking"
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
                    Text {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
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
                        horizontalAlignment: Text.AlignHCenter
                        text: root.listening ? (root.completion ? "Still listening. Escape dismisses." : (root.expanded ? "Listening for your answer. It sends when you finish, or press Enter." : "Speak naturally. It sends when you finish, or press Enter.")) : root.phase === "transcribing" ? "Turning your speech into words…" : root.phase === "thinking" ? "Working on your request…" : root.transcript ? "Voice request" : "Press Super+M or click Listen."
                        textFormat: Text.PlainText
                        color: root.inkMuted
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                        wrapMode: Text.Wrap
                    }
                    Text {
                        visible: !!root.completion
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
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
                        horizontalAlignment: Text.AlignHCenter
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
                        Layout.alignment: Qt.AlignHCenter
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
                    Item {
                        id: orbBox
                        Layout.alignment: Qt.AlignHCenter
                        Layout.preferredWidth: root.listening && root.expanded ? Style.space(96) : Style.space(132)
                        Layout.preferredHeight: root.listening && root.expanded ? Style.space(96) : Style.space(132)
                        Canvas {
                            id: orb
                            anchors.fill: parent
                            property real spin: 0
                            onSpinChanged: requestPaint()
                            onWidthChanged: requestPaint()
                            onHeightChanged: requestPaint()
                            Connections {
                                target: root
                                function onStrengthChanged() { orb.requestPaint() }
                            }
                            onPaint: {
                                var ctx = getContext("2d");
                                if (!ctx || width < 2 || height < 2)
                                    return;
                                ctx.reset();
                                var cx = width / 2;
                                var cy = height / 2;
                                var pulse = 0.78 + root.strength * 0.34;
                                var radius = Math.min(width, height) * 0.31 * pulse;
                                // A ring only while the mic is open, so listening is distinct from results.
                                if (root.listening) {
                                    ctx.beginPath();
                                    ctx.lineWidth = Math.max(2, width * 0.02) + root.strength * 3;
                                    ctx.strokeStyle = Qt.rgba(0.55, 0.78, 1, 0.38 + root.strength * 0.5);
                                    ctx.arc(cx, cy, radius * (1.22 + root.strength * 0.38), 0, Math.PI * 2);
                                    ctx.stroke();
                                }
                                var glow = ctx.createRadialGradient(cx, cy, radius * 0.15, cx, cy, radius * 1.85);
                                glow.addColorStop(0, Qt.rgba(0.62, 0.45, 1, 0.34 + root.strength * 0.28));
                                glow.addColorStop(1, Qt.rgba(0.62, 0.45, 1, 0));
                                ctx.fillStyle = glow;
                                ctx.fillRect(0, 0, width, height);
                                ctx.save();
                                ctx.beginPath();
                                ctx.arc(cx, cy, radius, 0, Math.PI * 2);
                                ctx.clip();
                                var colors = ["#64d2ff", "#30d158", "#ffd60a", "#ff375f", "#bf5af2"];
                                for (var i = 0; i < colors.length; i++) {
                                    var angle = spin + i * Math.PI * 2 / colors.length;
                                    var bx = cx + Math.cos(angle) * radius * 0.45;
                                    var by = cy + Math.sin(angle * 1.31) * radius * 0.45;
                                    var br = radius * (0.72 + 0.18 * Math.sin(spin * 1.4 + i));
                                    var blob = ctx.createRadialGradient(bx, by, 0, bx, by, br);
                                    blob.addColorStop(0, colors[i]);
                                    blob.addColorStop(1, Qt.rgba(1, 1, 1, 0));
                                    ctx.fillStyle = blob;
                                    ctx.fillRect(0, 0, width, height);
                                }
                                ctx.restore();
                            }
                        }
                    }
                }
            }
        }
    }
}
