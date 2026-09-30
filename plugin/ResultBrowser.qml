import QtQuick
import QtQuick.Layouts
import QtMultimedia
import qs.Commons

ColumnLayout {
    id: root
    property var display: ({})
    property int selected: 0
    readonly property var items: display.items || []
    readonly property var current: items.length ? items[Math.min(selected, items.length - 1)] : ({})
    signal selectRequested(int index)
    signal openRequested
    spacing: Style.space(8)
    RowLayout {
        Layout.fillWidth: true
        Text {
            Layout.fillWidth: true
            text: root.display.title || "Results"
            textFormat: Text.PlainText
            color: Color.foreground
            font.bold: true
            font.family: Style.font.family
            font.pixelSize: Style.font.body
        }
        Text {
            text: root.items.length + " items"
            visible: root.display.kind !== "answer"
            color: Util.alpha(Color.foreground, 0.62)
            font.pixelSize: Style.font.caption
        }
    }
    Text {
        visible: root.display.kind !== "answer" && root.items.length === 0
        text: "No matches found. Try a different request."
        color: Color.foreground
        wrapMode: Text.Wrap
        Layout.fillWidth: true
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: root.items.length > 0 || root.display.kind === "answer"
        spacing: Style.space(12)
        ListView {
            id: list
            visible: root.items.length > 0
            Layout.preferredWidth: Math.min(Style.space(235), root.width * 0.44)
            Layout.fillHeight: true
            model: root.items
            clip: true
            spacing: Style.space(4)
            currentIndex: root.selected
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
            delegate: Rectangle {
                required property var modelData
                required property int index
                width: list.width
                height: Math.max(Style.space(62), row.implicitHeight + Style.space(16))
                radius: Style.space(8)
                color: index === root.selected ? Util.alpha(Color.accent, 0.14) : "transparent"
                border.width: index === root.selected ? 1 : 0
                border.color: Util.alpha(Color.accent, 0.4)
                RowLayout {
                    id: row
                    anchors {
                        left: parent.left
                        right: parent.right
                        verticalCenter: parent.verticalCenter
                        margins: Style.space(10)
                    }
                    Text {
                        text: modelData.extension || "•"
                        textFormat: Text.PlainText
                        color: Color.accent
                        font.pixelSize: Style.font.caption
                        Layout.preferredWidth: Style.space(30)
                        elide: Text.ElideRight
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: modelData.title || "Item"
                            textFormat: Text.PlainText
                            color: Color.foreground
                            font.family: Style.font.family
                            font.pixelSize: Style.font.body
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            text: modelData.subtitle || ""
                            textFormat: Text.PlainText
                            color: Util.alpha(Color.foreground, 0.62)
                            font.pixelSize: Style.font.caption
                            elide: Text.ElideMiddle
                        }
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: root.selectRequested(index)
                    onDoubleClicked: {
                        root.selectRequested(index);
                        root.openRequested();
                    }
                }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Style.space(8)
            Image {
                id: image
                visible: root.current.kind === "image"
                Layout.fillWidth: true
                Layout.fillHeight: true
                source: visible ? root.current.uri || "" : ""
                sourceSize.width: 1200
                asynchronous: true
                fillMode: Image.PreserveAspectFit
            }
            Text {
                visible: image.visible && image.status === Image.Error
                text: "Image preview unavailable"
                color: Color.foreground
            }
            Video {
                id: video
                visible: root.current.kind === "video"
                Layout.fillWidth: true
                Layout.fillHeight: true
                source: visible ? root.current.uri || "" : ""
                autoPlay: false
                onSourceChanged: stop()
                onVisibleChanged: if (!visible)
                    stop()
            }
            RowLayout {
                visible: video.visible
                NativeButton {
                    text: video.playbackState === MediaPlayer.PlayingState ? "Pause" : "Play"
                    onClicked: video.playbackState === MediaPlayer.PlayingState ? video.pause() : video.play()
                }
                NativeButton {
                    text: "Stop"
                    onClicked: video.stop()
                }
                Text {
                    text: video.error !== MediaPlayer.NoError ? "Playback unavailable" : Math.floor(video.position / 1000) + " / " + Math.floor(video.duration / 1000) + " s"
                    color: Color.foreground
                    font.pixelSize: Style.font.caption
                }
            }
            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: root.current.kind !== "image" && root.current.kind !== "video"
                contentHeight: preview.contentHeight
                clip: true
                TextEdit {
                    id: preview
                    width: parent.width
                    readOnly: true
                    selectByMouse: true
                    textFormat: TextEdit.RichText
                    wrapMode: TextEdit.Wrap
                    color: Color.foreground
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                    text: root.display.kind === "answer" ? root.display.html || "" : root.current.preview_html || "<b>" + String(root.current.title || "").replace(/&/g, "&amp;").replace(/</g, "&lt;") + "</b><p>" + String(root.current.subtitle || "").replace(/&/g, "&amp;").replace(/</g, "&lt;") + "</p>"
                    onLinkActivated: link => {
                        if (/^https?:\/\//.test(link))
                            Qt.openUrlExternally(link);
                    }
                }
            }
        }
    }
}
