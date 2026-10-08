import QtQuick
import QtQuick.Window
import QtTest
import Quickshell
import Quickshell.Wayland
import qs.Commons
import "Assistant"

ShellRoot {
    TestCase { id: input; when: false }
    Chat { id: chat; runtimeDir: Quickshell.env("XDG_RUNTIME_DIR") }
    FloatingWindow {
        id: otherWindow
        visible: false
        title: "Agavai input regression"
        implicitWidth: 240
        implicitHeight: 100
        TextInput { id: otherInput; anchors.fill: parent; focus: true }
    }

    function find(object, name) {
        if (object.objectName === name)
            return object;
        var children = object.data || object.children || [];
        for (var i = 0; i < children.length; i++) {
            var match = find(children[i], name);
            if (match)
                return match;
        }
        return object.contentItem ? find(object.contentItem, name) : null;
    }
    function check(condition, message) {
        if (!condition)
            throw new Error(message);
    }
    function checkPosition(stage, panel) {
        check(Math.abs(stage.x + stage.width + Style.space(28) - panel.width) < 1 && Math.abs(stage.y + stage.height + Style.space(28) - panel.height) < 1, "Both orb and expanded panel must stay at the bottom right");
        check(stage.x >= 0, "The expanded panel must remain inside the monitor");
    }
    Timer {
        interval: 250
        running: true
        repeat: true
        property int step: 0
        onTriggered: {
            try {
                var panel = find(chat, "agavaiPanel");
                var stage = find(chat, "agavaiStage");
                var details = find(chat, "agavaiDetails");
                var orb = find(chat, "agavaiCompactOrb");
                if (step === 0) {
                    chat.applySnapshot(JSON.stringify({session_id: "test", phase: "listening", transcript: {text: "find notes"}, level_db: -25}));
                } else if (step === 1 || step === 4) {
                    check(chat.opened && chat.compact && !chat.wantsKeyboardFocus, "Compact mode must keep the session open without keyboard focus");
                    check(panel.WlrLayershell.keyboardFocus === WlrKeyboardFocus.None, "Compact layer must release compositor keyboard focus");
                    check(orb.visible && !details.visible, "Compact mode must show only the orb");
                    check(stage.width === Style.space(80) && stage.height === Style.space(80), "Compact input region must stay small: step " + step + ", " + stage.width + "x" + stage.height);
                    checkPosition(stage, panel);
                    if (step === 1) {
                        check(chat.strength > 0 && chat.transcript === "find notes", "Compact mode must retain microphone level and transcription");
                        input.mouseClick(find(chat, "agavaiCompactPointer"), 40, 40, Qt.LeftButton);
                    } else {
                        check(chat.sessionId === "test" && chat.items.length === 1, "Minimizing must preserve session and results");
                        chat.applySnapshot(JSON.stringify({session_id: "test", phase: "speaking", error: "Retry needed", turns: [{assistant: "Your notes"}], display: {items: [{title: "Notes"}]}}));
                    }
                } else if (step === 2) {
                    check(!chat.compact && details.visible && !orb.visible && chat.wantsKeyboardFocus, "Expanding must reveal the full view");
                    checkPosition(stage, panel);
                    check(panel.WlrLayershell.keyboardFocus === WlrKeyboardFocus.OnDemand, "Expanded view must let other windows receive input");
                    chat.applySnapshot(JSON.stringify({session_id: "test", phase: "listening", display: {items: [{title: "Notes"}]}}));
                } else if (step === 3) {
                    check(!chat.compact && chat.items.length === 1, "Snapshots must preserve the chosen expanded view");
                    checkPosition(stage, panel);
                    find(chat, "agavaiMinimize").clicked();
                } else if (step === 5) {
                    check(chat.compact && !chat.wantsKeyboardFocus && !details.visible, "Replies and errors must not expand or steal focus");
                    // Idle dismissal avoids launching the real capture cancellation command.
                    chat.phase = "idle";
                    input.mouseClick(find(chat, "agavaiCompactPointer"), 40, 40, Qt.RightButton);
                    check(!chat.opened && chat.compact, "Dismissal must reset the default mode");
                    chat.applySnapshot(JSON.stringify({session_id: "test", phase: "speaking"}));
                    check(!chat.opened, "Late snapshots must not reopen a dismissed session");
                    chat.applySnapshot(JSON.stringify({session_id: "next", phase: "listening"}));
                    check(chat.opened && chat.compact && !chat.wantsKeyboardFocus, "A new session must start compact");
                    input.mouseClick(find(chat, "agavaiCompactPointer"), 40, 40, Qt.LeftButton);
                } else if (step === 6) {
                    check(!chat.compact && panel.contentItem.Window.active, "Expanded view must acquire focus when activated");
                    checkPosition(stage, panel);
                    otherWindow.visible = true;
                } else if (step === 7) {
                    otherWindow.contentItem.Window.window.requestActivate();
                } else if (step === 8) {
                    check(otherWindow.contentItem.Window.active, "Another window must be able to take focus");
                    check(chat.compact && chat.opened && chat.phase === "listening" && chat.sessionId === "next", "Focus loss must minimize without stopping or replacing the listening session");
                    input.keyClick(Qt.Key_A);
                    check(otherInput.text === "a", "The other window must receive keyboard input");
                    console.log("COMPACT_UI_PASS");
                    Qt.quit();
                }
                step++;
            } catch (error) {
                console.error("COMPACT_UI_FAIL: " + error.message);
                Qt.quit();
            }
        }
    }
}
