import QtQuick
import qs.Commons
import qs.Commons as Commons

Rectangle {
    id: root
    property string text: ""
    property string accessibleName: text
    property bool quiet: false
    property int textSize: Style.font.caption
    signal clicked
    implicitWidth: label.implicitWidth + Style.space(20)
    implicitHeight: Math.max(Style.space(32), label.implicitHeight + Style.space(12))
    radius: height / 2
    color: pointer.containsMouse ? Util.alpha(Commons.Color.accent, 0.18) : quiet ? "transparent" : Util.alpha(Commons.Color.foreground, 0.06)
    border.width: activeFocus ? 2 : 0
    border.color: Commons.Color.accent
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: accessibleName
    Accessible.onPressAction: clicked()
    Keys.onSpacePressed: clicked()
    Keys.onReturnPressed: clicked()
    Text {
        id: label
        anchors.centerIn: parent
        text: root.text
        textFormat: Text.PlainText
        color: root.enabled ? Commons.Color.foreground : Util.alpha(Commons.Color.foreground, 0.4)
        font.family: Style.font.family
        font.pixelSize: root.textSize
    }
    MouseArea {
        id: pointer
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
