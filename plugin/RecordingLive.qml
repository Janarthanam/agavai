import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Commons as Commons

// A recording in progress: the lines said so far, with their times, and the controls.
ColumnLayout {
    id: root
    property var recording: ({})
    property string elapsed: "00:00"
    readonly property var lines: recording.lines || []
    readonly property bool paused: !!recording.paused
    spacing: Style.space(10)

    RowLayout {
        Layout.fillWidth: true
        Text {
            objectName: "agavaiRecordingHeading"
            text: (root.paused ? "❚❚ Paused  " : "● Recording  ") + root.elapsed
            textFormat: Text.PlainText
            color: Commons.Color.urgent
            font.bold: true
            font.family: Style.font.family
            font.pixelSize: Style.font.body
        }
        Item {
            Layout.fillWidth: true
        }
        Text {
            visible: root.recording.transcribing === false
            text: "Live transcript stopped. The audio is still recording."
            textFormat: Text.PlainText
            color: Util.alpha(Commons.Color.foreground, 0.62)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
        }
    }
    ListView {
        id: list
        objectName: "agavaiRecordingLines"
        // Follows new lines unless the user has scrolled back to read.
        property bool following: true
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(Style.space(260), Math.max(Style.space(40), contentHeight))
        visible: root.lines.length > 0
        clip: true
        spacing: Style.space(4)
        model: root.lines
        onMovementEnded: following = atYEnd
        onCountChanged: if (following)
            positionViewAtEnd()
        delegate: RowLayout {
            required property var modelData
            width: list.width
            spacing: Style.space(10)
            Text {
                Layout.preferredWidth: Style.space(52)
                Layout.alignment: Qt.AlignTop
                text: modelData.time
                textFormat: Text.PlainText
                color: Util.alpha(Commons.Color.foreground, 0.62)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
            }
            Text {
                Layout.fillWidth: true
                text: modelData.mark ? "⚑ " + modelData.text : modelData.text
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: modelData.mark ? Commons.Color.accent : Commons.Color.foreground
                font.family: Style.font.family
                font.pixelSize: Style.font.body
            }
        }
    }
    Text {
        visible: root.lines.length === 0
        Layout.fillWidth: true
        text: root.paused ? "Paused. Nothing is kept until you resume." : "Lines appear here as they are spoken."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Util.alpha(Commons.Color.foreground, 0.62)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
    }
    RowLayout {
        Layout.alignment: Qt.AlignHCenter
        spacing: Style.space(6)
        NativeButton {
            objectName: "agavaiRecordingPause"
            text: root.paused ? "Resume" : "Pause"
            onClicked: Quickshell.execDetached(["agavai", "record", root.paused ? "resume" : "pause"])
        }
        NativeButton {
            objectName: "agavaiRecordingMark"
            text: "Mark"
            onClicked: Quickshell.execDetached(["agavai", "record", "mark"])
        }
        NativeButton {
            objectName: "agavaiRecordingStop"
            text: "Stop"
            onClicked: Quickshell.execDetached(["agavai", "record", "stop"])
        }
    }
}
