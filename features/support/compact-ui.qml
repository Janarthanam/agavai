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
                var closeButton = find(chat, "agavaiCompactClose");
                if (step === 0) {
                    chat.applySnapshot(JSON.stringify({session_id: "test", phase: "listening", transcript: {text: "find notes"}, level_db: -25}));
                } else if (step === 1 || step === 4) {
                    check(chat.opened && chat.compact && !chat.wantsKeyboardFocus, "Compact mode must keep the session open without keyboard focus");
                    check(panel.WlrLayershell.keyboardFocus === WlrKeyboardFocus.None, "Compact layer must release compositor keyboard focus");
                    check(orb.visible && !details.visible, "Compact mode must show only the orb");
                    check(closeButton.visible && closeButton.Accessible.name === "Dismiss assistant", "Compact mode must expose a named close button");
                    check(closeButton.x >= 0 && closeButton.y >= 0 && closeButton.x + closeButton.width <= orb.width && closeButton.y + closeButton.height <= orb.height, "Close button must stay inside the compact input region");
                    check(stage.width === Style.space(80) && stage.height === Style.space(80), "Compact input region must stay small: step " + step + ", " + stage.width + "x" + stage.height);
                    checkPosition(stage, panel);
                    if (step === 1) {
                        check(chat.strength > 0 && chat.transcript === "find notes", "Compact mode must retain microphone level and transcription");
                        input.mouseClick(find(chat, "agavaiCompactPointer"), 40, 40, Qt.LeftButton);
                    } else {
                        check(chat.sessionId === "test" && chat.items.length === 1, "Minimizing must preserve session and results");
                        chat.applySnapshot(JSON.stringify({session_id: "test", phase: "speaking", error: "Retry needed", turns: [{assistant: "Your notes"}], display: {id: "canvas1", items: [{title: "Notes"}]}}));
                    }
                } else if (step === 2) {
                    check(!chat.compact && details.visible && !orb.visible && chat.wantsKeyboardFocus, "Expanding must reveal the full view");
                    checkPosition(stage, panel);
                    check(panel.WlrLayershell.keyboardFocus === WlrKeyboardFocus.OnDemand, "Expanded view must let other windows receive input");
                    chat.applySnapshot(JSON.stringify({session_id: "test", phase: "listening", display: {id: "canvas1", items: [{title: "Notes"}]}}));
                } else if (step === 3) {
                    check(!chat.compact && chat.items.length === 1, "Snapshots must preserve the chosen expanded view");
                    checkPosition(stage, panel);
                    find(chat, "agavaiMinimize").clicked();
                } else if (step === 5) {
                    check(chat.compact && !chat.wantsKeyboardFocus && !details.visible, "Replies and errors must not expand or steal focus");
                    // Idle dismissal avoids launching the real capture cancellation command.
                    chat.phase = "idle";
                    input.mouseClick(closeButton, closeButton.width / 2, closeButton.height / 2, Qt.LeftButton);
                    check(!chat.opened && chat.compact && !chat.wantsKeyboardFocus, "Close button must dismiss directly without expanding or taking keyboard focus");
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
                    chat.applySnapshot(JSON.stringify({session_id: "next", phase: "speaking", display: {id: "canvas2", items: [{title: "Budget"}]}}));
                } else if (step === 9) {
                    check(!chat.compact && chat.items[0].title === "Budget", "New canvas results must expand automatically");
                    checkPosition(stage, panel);
                    find(chat, "agavaiMinimize").clicked();
                    chat.applySnapshot(JSON.stringify({session_id: "next", phase: "listening", level_db: -20, display: {id: "canvas2", items: [{title: "Budget"}]}}));
                } else if (step === 10) {
                    check(chat.compact && !chat.wantsKeyboardFocus, "Retained canvas and microphone updates must respect minimization");
                    checkPosition(stage, panel);
                    chat.applySnapshot(JSON.stringify({session_id: "next", phase: "speaking", display: {id: "canvas3", items: [{title: "Budget"}]}}));
                } else if (step === 11) {
                    check(!chat.compact && chat.items[0].title === "Budget", "Reissuing the same results must reopen the canvas");
                    checkPosition(stage, panel);
                    find(chat, "agavaiMinimize").clicked();
                    chat.applySnapshot(JSON.stringify({session_id: "next", phase: "error", error: "Retry needed"}));
                } else if (step === 12) {
                    check(chat.compact, "Errors without a new canvas must not expand the panel");
                    chat.phase = "idle";
                    input.mouseClick(find(chat, "agavaiCompactPointer"), 40, 40, Qt.RightButton);
                    chat.applySnapshot(JSON.stringify({session_id: "next", phase: "speaking", display: {id: "late", items: [{title: "Late"}]}}));
                    check(!chat.opened && chat.compact, "Late canvas results must not reopen a dismissed session");
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
