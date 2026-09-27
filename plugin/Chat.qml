import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui

Item {
  id: root

  property var shell: null
  property var manifest: null
  property bool opened: false
  property string phase: "idle"
  property string phaseLabel: "Idle"
  property string modelId: ""
  property var turns: []
  property string runtimeDir: Quickshell.env("XDG_RUNTIME_DIR") || ("/run/user/" + Quickshell.env("UID"))
  property string uiPath: root.runtimeDir + "/agavai/ui.json"

  readonly property color background: Color.menu.background
  readonly property color foreground: Color.menu.text
  readonly property color muted: Util.alpha(Color.menu.text, 0.62)
  readonly property color border: Color.menu.border
  readonly property color accent: Color.accent
  readonly property var borderSpec: Border.surfaceSpec("menu", "border", border, Math.max(1, Style.space(2)))
  readonly property int cornerRadius: Style.cornerRadius
  readonly property int pad: Style.spacing.panelPadding
  readonly property int cardWidth: Math.min(Style.space(560), panel.width - Style.gapsOut * 2)

  function open(payloadJson) {
    root.opened = true
    uiFile.reload()
  }

  function close() {
    root.opened = false
  }

  function dismiss() {
    root.opened = false
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide((root.manifest && root.manifest.id) || "janar.agavai")
  }

  function applySnapshot(raw) {
    try {
      var obj = JSON.parse(String(raw || "{}"))
    } catch (e) {
      return
    }
    root.phase = String(obj.phase || "idle")
    root.phaseLabel = String(obj.phase_label || root.phase)
    root.modelId = String(obj.model_id || "")
    root.turns = Array.isArray(obj.turns) ? obj.turns : []
    if (root.phase !== "idle" || root.turns.length > 0)
      root.opened = true
  }

  FileView {
    id: uiFile
    path: root.uiPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.applySnapshot(text())
  }

  Timer {
    interval: 12000
    running: root.opened && root.phase === "idle"
    onTriggered: root.dismiss()
  }

  IpcHandler {
    target: "janar.agavai"
    function open(payloadJson: string): string {
      root.open(payloadJson || "{}")
      return "ok"
    }
    function close(): string {
      root.close()
      return "ok"
    }
    function ping(): string { return "ok" }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "agavai-chat"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    mask: Region {}

    BorderSurface {
      id: card
      width: Math.min(root.cardWidth, parent.width - Style.gapsOut * 2)
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.top: parent.top
      anchors.topMargin: Style.space(52)
      color: Util.alpha(root.background, 0.97)
      borderSpec: root.borderSpec
      radius: root.cornerRadius

      ColumnLayout {
        id: col
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: card.borderLeft + root.pad
        width: card.width - (card.borderLeft + card.borderRight + root.pad * 2)
        spacing: Style.spacing.sm

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.spacing.sm
          Text {
            text: root.phase === "listening" ? "󰍬" : (root.phase === "thinking" || root.phase === "transcribing" ? "󰔟" : "󰚩")
            color: root.accent
            font.family: Style.font.family
            font.pixelSize: Style.font.title
          }
          Text {
            text: root.phaseLabel
            color: root.foreground
            font.family: Style.font.menuFamily
            font.pixelSize: Style.font.title
            font.bold: true
            Layout.fillWidth: true
          }
          Text {
            visible: root.modelId !== ""
            text: root.modelId
            color: root.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }
        }

        Repeater {
          model: root.turns
          delegate: ColumnLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: Style.space(4)

            Text {
              visible: String(modelData.user || "") !== ""
              Layout.fillWidth: true
              wrapMode: Text.Wrap
              text: "You  " + modelData.user
              color: root.foreground
              font.family: Style.font.menuFamily
              font.pixelSize: Style.font.body
            }

            Repeater {
              model: modelData.tools || []
              delegate: ColumnLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: 0
                Text {
                  Layout.fillWidth: true
                  wrapMode: Text.Wrap
                  text: (modelData.status === "running" ? "▶  " : "✓  ") + modelData.name
                        + (modelData.args ? "  " + modelData.args : "")
                  color: root.accent
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                }
                Text {
                  visible: String(modelData.result || "") !== ""
                  Layout.fillWidth: true
                  wrapMode: Text.Wrap
                  text: "    " + modelData.result
                  color: root.muted
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                }
              }
            }

            Text {
              visible: String(modelData.assistant || "") !== ""
              Layout.fillWidth: true
              wrapMode: Text.Wrap
              text: "Agavai  " + modelData.assistant
              color: root.foreground
              font.family: Style.font.menuFamily
              font.pixelSize: Style.font.body
            }
          }
        }

        Text {
          visible: root.turns.length === 0 && root.phase === "listening"
          Layout.fillWidth: true
          text: "Speak, then Super+Ctrl+M again to send."
          color: root.muted
          font.family: Style.font.menuFamily
          font.pixelSize: Style.font.caption
        }

        Item { Layout.preferredHeight: 1 }
      }

      height: card.borderTop + col.implicitHeight + root.pad + card.borderBottom
    }
  }
}
