import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Clock.js" as Clock

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
    property bool helpOpen: false
    property bool historyOpen: false
    property var sessionHistory: []
    onCompactChanged: { if (compact) { helpOpen = false; historyOpen = false; } }
    readonly property bool listening: phase === "listening"
    readonly property bool recording: phase === "recording"
    readonly property var rec: snapshot.recording || null
    readonly property bool recPaused: !!(rec && rec.paused)
    property double nowMs: Date.now()
    readonly property string recordingClock: rec ? Clock.clock(rec.elapsed_ms + (recPaused ? 0 : Math.max(0, nowMs - rec.at))) : "00:00"
    // A recording opened from the Recordings list; a stopped recording is reviewed from its canvas.
    property string openedRecording: ""
    readonly property var display: snapshot.display || null
    readonly property var items: display && Array.isArray(display.items) ? display.items : []
    readonly property var selectedItem: items.length ? items[Math.min(selected, items.length - 1)] : ({})
    readonly property var turn: (snapshot.turns || []).length ? snapshot.turns[snapshot.turns.length - 1] : ({})
    readonly property var tools: turn.tools || []
    readonly property var latestTool: tools.length ? tools[tools.length - 1] : null
    readonly property bool expanded: !!display || !!turn.assistant || !!snapshot.error || typing || recording || helpOpen || historyOpen
    readonly property string reviewPath: recording ? "" : openedRecording || (display && display.kind === "recording" ? String(display.path || "") : "")
    readonly property string heard: (snapshot.transcript && snapshot.transcript.text) ? String(snapshot.transcript.text) : ""
    readonly property string transcript: heard || (listening ? "" : (turn.user || ""))
    // Listening for a follow-up gives the main line to the next utterance; the
    // finished request stays visible beside its answer.
    readonly property string previousRequest: turn.user && turn.user !== transcript ? String(turn.user) : ""
    readonly property var completion: snapshot.completion || null
    readonly property real strength: (listening || recording && !recPaused) && snapshot.level_db !== null && snapshot.level_db !== undefined && isFinite(Number(snapshot.level_db)) ? Math.max(0, Math.min(1, (Number(snapshot.level_db) + 70) / 65)) : 0
    readonly property color ink: Commons.Color.foreground
    readonly property color inkMuted: Util.alpha(Commons.Color.foreground, 0.62)
    readonly property color statusColor: Commons.Color.accent
    readonly property bool showsActions: !listening && !recording && (expanded || phase === "idle" || phase === "error")
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
        // During a recording, cancel stops and saves it.
        if (phase === "listening" || phase === "thinking" || phase === "speaking" || phase === "recording" || phase === "transcribing")
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
        askProc.command = root.snapshot.session && root.snapshot.session.persistent
            ? ["agavai", "ask", "--session", sessionId, text] : ["agavai", "ask", text];
        askProc.running = true;
    }
    function send() {
        if (listening)
            Quickshell.execDetached(["agavai", "stop"]);
    }
    function openSelected() {
        if (selectedItem.kind === "recording") {
            openedRecording = String(selectedItem.path || "");
            return;
        }
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
        var canvasCleared = !obj.display && !!snapshot.display;
        if (nextSession !== sessionId) {
            helpOpen = false;
            historyOpen = false;
            selected = 0;
            actionError = "";
            openedRecording = "";
            chooseScreen();
        } else if (nextDisplay !== JSON.stringify(snapshot.display || null)) {
            selected = 0;
            openedRecording = "";
        }
        sessionId = nextSession;
        snapshot = obj;
        nowMs = Date.now();
        phase = String(obj.phase || "idle");
        phaseLabel = String(obj.phase_label || phase);
        if (sessionId !== dismissedSession && (phase !== "idle" || expanded)) {
            opened = true;
            if (canvasChanged)
                compact = false;
        }
        if (canvasCleared)
            minimizeIfUnfocused();
    }
    function pipelineText() {
        var lines = ["Agavai · " + (snapshot.version || "session version unavailable"),
            "Current stage: " + phaseLabel, "", "SESSION CONFIGURATION",
            "Loaded when this session started. Changes require a new session."];
        var stages = snapshot.pipeline || [];
        if (!stages.length)
            lines.push("Pipeline details unavailable from this session. Restart Agavai to refresh.");
        for (var i = 0; i < stages.length; i++)
            lines.push(stages[i].stage + ": " + stages[i].detail);
        lines.push("", recording ? "RECORDING" : "LATEST TURN EXECUTION");
        if (recording) {
            lines.push("Speech is recording content. Router, brain, assistant tools and spoken replies are bypassed; only isolated recording controls run. An offline transcription pass may follow stopping.");
        } else {
            if (snapshot.input_mode === "typed")
                lines.push("Typed input · microphone, ASR and speech endpointing bypassed.");
            var events = snapshot.execution || [];
            if (!events.length)
                lines.push("No model or tool stage reported for this turn yet.");
            for (var j = 0; j < events.length; j++)
                lines.push(events[j].stage + ": " + events[j].detail);
        }
        return lines.join("\n");
    }
    // Focus elsewhere minimizes the expanded view, but not while a canvas is on
    // screen: with follow_mouse, merely moving the pointer would hide the answer.
    function minimizeIfUnfocused() {
        if (wantsKeyboardFocus && !display && !helpOpen && !historyOpen && !panel.contentItem.Window.window.active)
            compact = true;
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
            root.minimizeIfUnfocused();
        }
    }

    Timer {
        interval: 500
        repeat: true
        running: root.opened && root.recording && !root.recPaused
        onTriggered: root.nowMs = Date.now()
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
        stderr: StdioCollector {
            onStreamFinished: { if (text.trim()) root.actionError = text.trim(); }
        }
    }
    Process {
        id: historyProc
        command: ["agavai", "session", "list"]
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.sessionHistory = JSON.parse(text); }
                catch (e) { root.actionError = "Could not read saved sessions."; }
            }
        }
    }
    Process {
        id: sessionProc
        stderr: StdioCollector {
            onStreamFinished: { if (text.trim()) root.actionError = text.trim(); }
        }
        onExited: exitCode => {
            if (exitCode === 0) root.historyOpen = false;
        }
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
                color: Util.alpha(Commons.Color.background, 0.94)
            }

            FocusScope {
                id: keyTarget
                objectName: "agavaiDetails"
                visible: !root.compact
                anchors.fill: parent
                focus: root.wantsKeyboardFocus
                Keys.onPressed: event => {
                    if (event.key === Qt.Key_Escape) {
                        if (root.helpOpen) root.helpOpen = false;
                        else if (root.historyOpen) root.historyOpen = false;
                        else root.dismiss();
                        event.accepted = true;
                    } else if (root.historyOpen) {
                        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) event.accepted = true;
                    } else if (root.helpOpen) {
                        if ([Qt.Key_Down, Qt.Key_PageDown, Qt.Key_Up, Qt.Key_PageUp].indexOf(event.key) >= 0) {
                            var direction = event.key === Qt.Key_Up || event.key === Qt.Key_PageUp ? -1 : 1;
                            helpView.contentY = Math.max(0, Math.min(helpView.contentHeight - helpView.height, helpView.contentY + direction * helpView.height / 2));
                            event.accepted = true;
                        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                            event.accepted = true;
                        }
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

                    Flickable {
                        id: historyView
                        objectName: "agavaiSessionHistory"
                        Layout.row: root.atTop ? 1 : 0
                        Layout.column: 0
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(Style.space(300), panel.height * 0.4)
                        visible: root.historyOpen
                        clip: true
                        contentWidth: width
                        contentHeight: historyItems.implicitHeight
                        ColumnLayout {
                            id: historyItems
                            width: parent.width
                            spacing: Style.space(8)
                            NativeButton {
                                objectName: "agavaiNewSession"
                                text: "New session"
                                enabled: !sessionProc.running
                                onClicked: {
                                    sessionProc.command = ["agavai", "session", "new", "--listen"];
                                    sessionProc.running = true;
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: !!root.actionError
                                text: root.actionError
                                wrapMode: Text.Wrap
                                color: root.ink
                                font.pixelSize: Style.font.caption
                            }
                            Repeater {
                                model: root.sessionHistory
                                NativeButton {
                                    required property var modelData
                                    objectName: "agavaiHistorySession" + modelData.id
                                    Layout.fillWidth: true
                                    text: String(modelData.title).slice(0, 42) + " · " + String(modelData.id).slice(0, 8)
                                    accessibleName: "Resume session " + modelData.title + " " + modelData.id
                                    enabled: !sessionProc.running
                                    onClicked: {
                                        sessionProc.command = ["agavai", "session", "resume", modelData.id];
                                        sessionProc.running = true;
                                    }
                                }
                            }
                        }
                    }
                    Flickable {
                        id: helpView
                        objectName: "agavaiPipelineHelp"
                        Layout.row: root.atTop ? 1 : 0
                        Layout.column: 0
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(Style.space(300), panel.height * 0.4)
                        visible: root.helpOpen
                        clip: true
                        contentWidth: width
                        contentHeight: helpText.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds
                        activeFocusOnTab: true
                        onVisibleChanged: { if (visible) contentY = 0; }
                        Text {
                            id: helpText
                            objectName: "agavaiPipelineText"
                            width: parent.width - Style.space(10)
                            text: root.pipelineText()
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            color: root.ink
                            font.family: Style.font.family
                            font.pixelSize: Style.font.caption
                        }
                        Rectangle {
                            visible: helpView.contentHeight > helpView.height
                            x: helpView.width - width
                            y: helpView.contentY + (helpView.contentY / Math.max(1, helpView.contentHeight - helpView.height)) * (helpView.height - height)
                            width: Style.space(3)
                            height: Math.max(Style.space(20), helpView.height * helpView.height / helpView.contentHeight)
                            radius: width / 2
                            color: root.inkMuted
                        }
                    }
                    ColumnLayout {
                        Layout.row: root.atTop ? 1 : 0
                        Layout.column: 0
                        Layout.fillWidth: true
                        visible: !root.helpOpen && !root.historyOpen && (!!root.display || root.actionError !== "" || root.typing || root.showsActions || !!root.latestTool || root.recording)
                        spacing: Style.space(12)

                        RecordingLive {
                            visible: root.recording
                            Layout.fillWidth: true
                            recording: root.rec || ({})
                            elapsed: root.recordingClock
                        }
                        RecordingView {
                            objectName: "agavaiRecordingView"
                            visible: root.reviewPath !== ""
                            Layout.fillWidth: true
                            path: root.reviewPath
                            canGoBack: root.openedRecording !== "" && !!root.display && root.display.kind === "recordings"
                            onBackRequested: root.openedRecording = ""
                        }
                        ResultBrowser {
                            visible: !!root.display && root.reviewPath === "" && !root.recording
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
                                color: Util.alpha(Commons.Color.foreground, 0.06)
                                TextInput {
                                    id: typedInput
                                    objectName: "agavaiTypedInput"
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
                            visible: !!root.latestTool && !root.recording
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
                                    text: root.snapshot.error ? "Something went wrong" : root.phase === "idle" && root.reviewPath !== "" ? "Saved recording" : root.phase === "idle" && root.expanded ? "Here’s what I found" : root.phaseLabel
                                    textFormat: Text.PlainText
                                    color: root.statusColor
                                    font.family: Style.font.family
                                    font.pixelSize: Style.font.caption
                                    elide: Text.ElideRight
                                }
                                NativeButton {
                                    objectName: "agavaiSessions"
                                    quiet: true
                                    text: root.sessionId.slice(0, 8) + (root.snapshot.session && root.snapshot.session.persistent ? " · saved" : " · temporary")
                                    accessibleName: "Session history " + root.sessionId
                                    enabled: !!(root.snapshot.session && root.snapshot.session.persistent)
                                    onClicked: {
                                        root.helpOpen = false;
                                        root.historyOpen = !root.historyOpen;
                                        root.actionError = "";
                                        if (root.historyOpen && !historyProc.running) historyProc.running = true;
                                    }
                                }
                                NativeButton {
                                    objectName: "agavaiHelp"
                                    quiet: true
                                    text: "?"
                                    accessibleName: root.helpOpen ? "Close version and pipeline help" : "Version and pipeline help"
                                    onClicked: { root.historyOpen = false; root.helpOpen = !root.helpOpen; }
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
                                objectName: "agavaiAudioStatus"
                                Layout.fillWidth: true
                                horizontalAlignment: root.textTowardOrb
                                visible: !!root.snapshot.audio_status && (root.snapshot.audio_status.status !== "ready" || !!root.snapshot.audio_status.warning)
                                text: root.snapshot.audio_status ? String(root.snapshot.audio_status.warning || root.snapshot.audio_status.status) : ""
                                textFormat: Text.PlainText
                                color: root.inkMuted
                                font.pixelSize: Style.font.caption
                                wrapMode: Text.Wrap
                            }
                            Text {
                                Layout.fillWidth: true
                                horizontalAlignment: root.textTowardOrb
                                readonly property string heardNow: root.recording ? (root.rec && root.rec.partial ? String(root.rec.partial) : "") : root.transcript
                                text: heardNow || (root.recording ? (root.recPaused ? "Paused" : "Recording…") : root.listening ? "Listening…" : "What can I help you find?")
                                textFormat: Text.PlainText
                                color: heardNow ? root.ink : root.inkMuted
                                font.family: Style.font.family
                                font.pixelSize: root.expanded ? Style.font.heading : Style.font.display
                                wrapMode: Text.Wrap
                                maximumLineCount: 3
                                elide: Text.ElideRight
                            }
                            Text {
                                objectName: "agavaiListeningHint"
                                visible: root.listening || root.recording || !(root.turn.assistant || root.snapshot.error)
                                Layout.fillWidth: true
                                horizontalAlignment: root.textTowardOrb
                                text: root.recording ? (root.recPaused ? "Nothing is kept until you resume. Say “Agavai resume”." : "Say “Agavai stop” or press Super+Ctrl+M to stop.") : root.listening ? (root.snapshot.asr_endpoint === "manual" ? "Press Enter to send. Escape cancels." : (root.completion ? "Still listening. Escape dismisses." : (root.expanded ? "Listening for your answer. It sends when you finish, or press Enter." : "Speak naturally. It sends when you finish, or press Enter."))) : root.phase === "transcribing" ? "Turning your speech into words…" : root.phase === "thinking" ? "Working on your request…" : root.transcript ? "Voice request" : "Press Super+M or click Listen."
                                textFormat: Text.PlainText
                                color: root.inkMuted
                                font.family: Style.font.family
                                font.pixelSize: Style.font.caption
                                wrapMode: Text.Wrap
                            }
                            Text {
                                objectName: "agavaiPreviousRequest"
                                visible: root.previousRequest !== ""
                                Layout.fillWidth: true
                                horizontalAlignment: root.textTowardOrb
                                text: "You said “" + root.previousRequest + "”"
                                textFormat: Text.PlainText
                                color: root.inkMuted
                                font.family: Style.font.family
                                font.pixelSize: Style.font.body
                                wrapMode: Text.Wrap
                                maximumLineCount: 3
                                elide: Text.ElideRight
                            }
                            Text {
                                visible: !!root.completion && !root.recording
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
                                visible: (!!root.turn.assistant || !!root.snapshot.error) && !root.recording
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
                    paused: root.recPaused
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
        // Recording must never be invisible, so the time stays beside the minimized orb.
        // It sits outside the input mask, so it never takes a click.
        Rectangle {
            objectName: "agavaiRecordingChip"
            visible: root.recording && root.compact
            width: chipText.implicitWidth + Style.space(24)
            height: Style.space(28)
            radius: height / 2
            x: root.atRight ? stage.x - width - Style.space(10) : stage.x + stage.width + Style.space(10)
            y: stage.y + (stage.orbSize - height) / 2
            color: Util.alpha(Commons.Color.background, 0.94)
            Text {
                id: chipText
                anchors.centerIn: parent
                text: (root.recPaused ? "❚❚ " : "● ") + root.recordingClock
                textFormat: Text.PlainText
                color: root.recPaused ? root.inkMuted : Commons.Color.urgent
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
            }
        }
    }
}
