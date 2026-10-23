import QtQuick
import QtQuick.Layouts
import QtMultimedia
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import "Clock.js" as Clock

// A saved recording: its audio with the transcript. Clicking a line plays from
// it; double-clicking corrects it. The folder's recording.json is the source,
// so a saved correction shows here once that file changes.
ColumnLayout {
    id: root
    property string path: ""
    property bool canGoBack: false
    signal backRequested
    property var meta: ({})
    property int editing: 0
    property bool showHeard: false
    property string problem: ""
    readonly property var segments: meta.segments || []
    readonly property var marks: meta.marks || []
    readonly property bool corrected: segments.some(function (s) {
        return !!s.corrected;
    })
    readonly property real length: player.duration > 0 ? player.duration : (meta.duration_ms || 0)
    readonly property int playingIndex: {
        if (player.playbackState === MediaPlayer.StoppedState && player.position === 0)
            return -1;
        var found = -1;
        for (var i = 0; i < segments.length; i++) {
            if (segments[i].start_ms <= player.position)
                found = i;
            else
                break;
        }
        return found;
    }
    spacing: Style.space(10)

    function playFrom(ms) {
        player.setPosition(Math.max(0, Math.min(ms, root.length)));
        player.play();
    }
    function lineText(segment) {
        var heard = segment.final || segment.live || "";
        return root.showHeard ? heard : segment.corrected || heard;
    }
    function correct(segment, text) {
        root.editing = 0;
        if (text.trim() === root.lineText(segment))
            return;
        root.problem = "";
        correction.command = ["agavai", "recording", "correct", root.path, String(segment.id), text.trim()];
        correction.running = true;
    }

    onPathChanged: {
        player.stop();
        root.editing = 0;
        root.showHeard = false;
        root.problem = "";
    }

    FileView {
        id: metaFile
        path: root.path ? root.path + "/recording.json" : ""
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            try {
                root.meta = JSON.parse(text());
            } catch (e) {
                root.problem = "This recording could not be read.";
            }
        }
        onLoadFailed: root.problem = "This recording could not be read."
    }
    MediaPlayer {
        id: player
        objectName: "agavaiRecordingPlayer"
        source: root.path && root.meta.audio ? Util.fileUrl(root.path + "/" + root.meta.audio) : ""
        audioOutput: AudioOutput {}
    }
    Process {
        id: correction
        onExited: exitCode => {
            if (exitCode !== 0)
                root.problem = "The correction could not be saved.";
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Style.space(10)
        NativeButton {
            visible: root.canGoBack
            quiet: true
            text: "‹ Recordings"
            onClicked: root.backRequested()
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            Text {
                Layout.fillWidth: true
                text: root.meta.title || "Recording"
                textFormat: Text.PlainText
                color: Commons.Color.foreground
                font.bold: true
                font.family: Style.font.family
                font.pixelSize: Style.font.body
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: (root.meta.started ? new Date(root.meta.started).toLocaleString(Qt.locale(), "ddd d MMM, HH:mm") + " · " : "") + Clock.clock(root.meta.duration_ms || 0) + (root.meta.recovered ? " · recovered after a crash" : "")
                textFormat: Text.PlainText
                color: Util.alpha(Commons.Color.foreground, 0.62)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
            }
        }
        NativeButton {
            quiet: true
            visible: root.corrected
            text: root.showHeard ? "Show corrections" : "Show heard words"
            onClicked: root.showHeard = !root.showHeard
        }
        NativeButton {
            quiet: true
            text: "Open folder"
            onClicked: Quickshell.execDetached(["xdg-open", root.path])
        }
    }
    Text {
        visible: root.problem !== "" || !!root.meta.audio_error || player.error !== MediaPlayer.NoError
        Layout.fillWidth: true
        text: root.problem || root.meta.audio_error || "The audio could not be played."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Commons.Color.urgent
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: Style.space(8)
        NativeButton {
            objectName: "agavaiRecordingPlay"
            text: player.playbackState === MediaPlayer.PlayingState ? "Pause" : "Play"
            onClicked: player.playbackState === MediaPlayer.PlayingState ? player.pause() : player.play()
        }
        NativeButton {
            text: "−10 s"
            onClicked: player.setPosition(Math.max(0, player.position - 10000))
        }
        Item {
            id: track
            objectName: "agavaiRecordingTrack"
            Layout.fillWidth: true
            Layout.preferredHeight: Style.space(24)
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                height: Style.space(6)
                radius: height / 2
                color: Util.alpha(Commons.Color.foreground, 0.14)
                Rectangle {
                    width: root.length > 0 ? parent.width * Math.min(1, player.position / root.length) : 0
                    height: parent.height
                    radius: height / 2
                    color: Commons.Color.accent
                }
            }
            Repeater {
                model: root.marks
                Rectangle {
                    required property var modelData
                    x: root.length > 0 ? track.width * modelData.at_ms / root.length : 0
                    width: 2
                    height: parent.height
                    color: Commons.Color.accent
                }
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onPressed: mouse => player.setPosition(root.length * Math.max(0, Math.min(1, mouse.x / width)))
                onPositionChanged: mouse => {
                    if (pressed)
                        player.setPosition(root.length * Math.max(0, Math.min(1, mouse.x / width)));
                }
            }
        }
        Text {
            text: Clock.clock(player.position) + " / " + Clock.clock(root.length)
            textFormat: Text.PlainText
            color: Util.alpha(Commons.Color.foreground, 0.62)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
        }
        NativeButton {
            objectName: "agavaiRecordingSpeed"
            text: player.playbackRate + "×"
            onClicked: player.playbackRate = player.playbackRate >= 2 ? 1 : player.playbackRate + 0.5
        }
    }
    ListView {
        id: lines
        objectName: "agavaiRecordingReview"
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(Style.space(300), Math.max(Style.space(40), contentHeight))
        clip: true
        spacing: Style.space(2)
        model: root.segments
        currentIndex: root.playingIndex
        onCurrentIndexChanged: if (currentIndex >= 0)
            positionViewAtIndex(currentIndex, ListView.Contain)
        delegate: Rectangle {
            id: line
            required property var modelData
            required property int index
            readonly property bool editingThis: root.editing === modelData.id
            width: lines.width
            height: Math.max(row.implicitHeight, Style.space(24)) + Style.space(8)
            radius: Style.space(6)
            color: index === root.playingIndex ? Util.alpha(Commons.Color.accent, 0.16) : "transparent"
            RowLayout {
                id: row
                anchors {
                    left: parent.left
                    right: parent.right
                    verticalCenter: parent.verticalCenter
                    leftMargin: Style.space(6)
                    rightMargin: Style.space(6)
                }
                spacing: Style.space(10)
                Text {
                    Layout.preferredWidth: Style.space(52)
                    Layout.alignment: Qt.AlignTop
                    text: Clock.clock(modelData.start_ms)
                    textFormat: Text.PlainText
                    color: index === root.playingIndex ? Commons.Color.accent : Util.alpha(Commons.Color.foreground, 0.62)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                }
                Text {
                    visible: !line.editingThis
                    Layout.fillWidth: true
                    text: root.lineText(modelData) + (modelData.corrected && !root.showHeard ? "  •" : "")
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: Commons.Color.foreground
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                }
                Rectangle {
                    visible: line.editingThis
                    Layout.fillWidth: true
                    Layout.preferredHeight: editor.implicitHeight + Style.space(8)
                    radius: Style.space(6)
                    color: Util.alpha(Commons.Color.foreground, 0.06)
                    border.width: 1
                    border.color: Commons.Color.accent
                    TextInput {
                        id: editor
                        objectName: "agavaiRecordingEditor"
                        anchors.fill: parent
                        anchors.margins: Style.space(4)
                        text: root.lineText(line.modelData)
                        color: Commons.Color.foreground
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                        selectByMouse: true
                        clip: true
                        onVisibleChanged: if (visible) {
                            text = root.lineText(line.modelData);
                            forceActiveFocus();
                            selectAll();
                        }
                        onAccepted: root.correct(line.modelData, text)
                        Keys.onEscapePressed: event => {
                            root.editing = 0;
                            event.accepted = true;
                        }
                    }
                }
            }
            MouseArea {
                visible: !line.editingThis
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.playFrom(line.modelData.start_ms)
                onDoubleClicked: {
                    player.pause();
                    root.editing = line.modelData.id;
                }
            }
        }
    }
    Text {
        visible: root.segments.length === 0 && !!root.meta.status
        Layout.fillWidth: true
        text: "No words were recognized. The audio is still here."
        textFormat: Text.PlainText
        color: Util.alpha(Commons.Color.foreground, 0.62)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
    }
}
