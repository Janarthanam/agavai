import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import qs.Commons as Commons
import "Clock.js" as Clock

BarWidget {
  id: root
  moduleName: "janar.agavai"

  property string phase: "idle"
  property var levelDb: null
  property real levelFrac: 0.0
  property var recording: null
  property double nowMs: Date.now()
  readonly property bool recordingActive: root.phase === "recording" && !!root.recording
  readonly property string recordingClock: root.recordingActive ? Clock.clock(root.recording.elapsed_ms + (root.recording.paused ? 0 : Math.max(0, root.nowMs - root.recording.at))) : ""

  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  FileView {
    id: uiFile
    path: (Quickshell.env("XDG_RUNTIME_DIR") || ("/run/user/" + Quickshell.env("UID"))) + "/agavai/ui.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.applySnapshot(text())
  }

  function applySnapshot(raw) {
    try {
      var obj = JSON.parse(String(raw || "{}"))
      root.phase = String(obj.phase || "idle")
      root.levelDb = (obj.level_db === undefined || obj.level_db === null) ? null : Number(obj.level_db)
      root.levelFrac = root.levelDb === null ? 0.0 : Math.max(0.0, Math.min(1.0, (root.levelDb + 70.0) / 65.0))
      root.recording = obj.recording || null
      root.nowMs = Date.now()
    } catch (e) {
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    iconComponent: mark
    active: root.phase === "listening" || root.phase === "thinking" || root.phase === "speaking" || root.recordingActive
    tooltipText: root.recordingActive ? ("Agavai · " + (root.recording.paused ? "Paused " : "Recording ") + root.recordingClock + " · Click to stop and save")
      : root.phase === "idle" ? "Agavai · Click to speak · Super+M" : ("Agavai · " + root.phase + " · Right-click to cancel")
    onPressed: function(b) {
      if (!root.bar)
        return
      // Like Omarchy's screen recording indicator, a click stops the recording; it is saved either way.
      if (b === Qt.RightButton)
        root.bar.run("agavai cancel")
      else if (root.recordingActive)
        root.bar.run("agavai record stop")
      else
        root.bar.run("agavai invoke")
    }
  }

  Timer {
    interval: 100
    running: root.phase === "listening"
    repeat: true
    onTriggered: uiFile.reload()
  }

  Timer {
    interval: 1000
    running: root.recordingActive && !root.recording.paused
    repeat: true
    onTriggered: root.nowMs = Date.now()
  }

  Component {
    id: mark
    Item {
      anchors.fill: parent
      Image {
        anchors.fill: parent
        opacity: root.phase === "listening" ? 0.55 + 0.45 * root.levelFrac : 1.0
        source: Qt.resolvedUrl("agavai.png")
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
      }
      Rectangle {
        visible: root.recordingActive
        width: Math.max(4, parent.width * 0.34)
        height: width
        radius: width / 2
        anchors.top: parent.top
        anchors.right: parent.right
        color: root.recordingActive && root.recording.paused ? Commons.Color.muted : Commons.Color.urgent
      }
    }
  }
}
