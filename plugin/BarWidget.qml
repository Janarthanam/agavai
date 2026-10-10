import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

BarWidget {
  id: root
  moduleName: "janar.agavai"

  property string phase: "idle"
  property var levelDb: null
  property real levelFrac: 0.0

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
    } catch (e) {
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    iconComponent: mark
    active: root.phase === "listening" || root.phase === "thinking" || root.phase === "speaking"
    tooltipText: root.phase === "idle" ? "Agavai · Click to speak · Super+M" : ("Agavai · " + root.phase + " · Right-click to cancel")
    onPressed: function(b) {
      if (!root.bar)
        return
      if (b === Qt.RightButton)
        root.bar.run("agavai cancel")
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
    }
  }
}
