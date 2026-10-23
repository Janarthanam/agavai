import QtQuick
import QtQuick.Window
import QtTest
import QtMultimedia
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
    readonly property var placements: ["top-left", "top-right", "bottom-left", "bottom-right"]
    readonly property string scenario: Quickshell.env("AGAVAI_UI_CHECK") || "compact"
    readonly property string recordingFolder: Quickshell.env("AGAVAI_UI_RECORDING") || ""
    property int waited: 0
    property var orbAt: null
    function orbOnScreen(orb, stage) {
        return orb.mapToItem(stage.parent, 0, 0);
    }
    // The orb holds its corner in both views; the sheet grows away from it inside the monitor.
    function checkPosition(stage, panel, orb) {
        var margin = Style.space(28);
        var top = chat.placement.indexOf("top") === 0;
        var right = chat.placement.slice(-5) === "right";
        var at = orbOnScreen(orb, stage);
        check(Math.abs(at.x - (right ? panel.width - margin - orb.width : margin)) < 1 && Math.abs(at.y - (top ? margin : panel.height - margin - orb.height)) < 1, chat.placement + ": the orb must sit in its corner, at " + at.x + "," + at.y);
        check(Math.abs(stage.x - (right ? panel.width - margin - stage.width : margin)) < 1 && Math.abs(stage.y - (top ? margin : panel.height - margin - stage.height)) < 1, chat.placement + ": the sheet must grow from the orb's corner");
        check(stage.x >= 0 && stage.y >= 0 && stage.x + stage.width <= panel.width && stage.y + stage.height <= panel.height, chat.placement + ": the sheet must remain inside the monitor");
    }
    // Hyprland focuses the overlay only when its layer maps with on-demand focus,
    // so opening and expanding share one tick, as in step 5 of the compact run.
    // That focus is given once per instance, hence a separate run.
    function canvasFocusStep(step, panel, details) {
        if (step === 0) {
            chat.applySnapshot(JSON.stringify({session_id: "focus", phase: "listening"}));
            input.mouseClick(find(chat, "agavaiOrbPointer"), 40, 40, Qt.LeftButton);
        } else if (step === 1) {
            check(!chat.compact && panel.contentItem.Window.active, "Expanded view must acquire focus when activated");
            chat.applySnapshot(JSON.stringify({session_id: "focus", phase: "speaking", turns: [{user: "list the planets", assistant: "Here are the planets."}], display: {id: "planets", kind: "answer", title: "Planets", html: "<p>Mercury</p>"}}));
            otherWindow.visible = true;
        } else if (step === 2) {
            otherWindow.contentItem.Window.window.requestActivate();
        } else if (step === 3) {
            check(otherWindow.contentItem.Window.active, "Another window must be able to take focus from a canvas");
            check(!chat.compact && details.visible && chat.display.title === "Planets", "A canvas must stay on screen when another window takes focus");
            input.keyClick(Qt.Key_A);
            check(otherInput.text === "a", "The other window must receive keyboard input while the canvas stays up");
            chat.applySnapshot(JSON.stringify({session_id: "focus", phase: "speaking", turns: [{user: "what time is it", assistant: "It is noon."}]}));
        } else if (step === 4) {
            check(chat.compact && chat.opened && !details.visible, "Once its canvas is cleared, the view must minimize while another window has focus");
            console.log("COMPACT_UI_PASS");
            Qt.quit();
        }
    }
    // Live recording, its review, and the Recordings list. Commands the overlay runs reach a stub agavai.
    // Returns false to repeat the step on the next tick.
    function recordingStep(step, panel, stage, details, orb) {
        var live = {path: recordingFolder, elapsed_ms: 64000, at: Date.now(), paused: false, lines: [{time: "00:58", text: "the canary ships"}], partial: "widen it on monday", transcribing: true};
        if (step === 0) {
            chat.applySnapshot(JSON.stringify({session_id: "rec", phase: "recording", recording: live}));
        } else if (step === 1) {
            var chip = find(chat, "agavaiRecordingChip");
            check(chat.opened && chat.compact && chip.visible, "A minimized recording must show its time beside the orb");
            check(chip.children[0].text.indexOf("01:0") > 0, "The chip must show the elapsed time: " + chip.children[0].text);
            check(stage.width === Style.space(80) && chip.x + chip.width <= stage.x, "The chip must stay outside the orb's input region");
            input.mouseClick(find(chat, "agavaiOrbPointer"), 40, 40, Qt.LeftButton);
        } else if (step === 2) {
            check(!chat.compact && details.visible && find(chat, "agavaiRecordingLines").count === 1, "Expanding a recording must show its lines");
            check(find(chat, "agavaiRecordingHeading").text.indexOf("Recording") >= 0 && !chat.showsActions, "The sheet must read as recording, without assistant actions");
            find(chat, "agavaiRecordingPause").clicked();
            find(chat, "agavaiRecordingMark").clicked();
            live.paused = true;
            chat.applySnapshot(JSON.stringify({session_id: "rec", phase: "recording", recording: live}));
        } else if (step === 3) {
            check(find(chat, "agavaiRecordingHeading").text.indexOf("Paused") >= 0 && find(chat, "agavaiRecordingPause").text === "Resume", "A paused recording must say so and offer Resume");
            chat.applySnapshot(JSON.stringify({session_id: "rec", phase: "idle", display: {id: "saved", kind: "recording", title: "Recording", path: recordingFolder, duration_ms: 2000}}));
        } else if (step === 4) {
            var view = find(chat, "agavaiRecordingView");
            check(view.visible && view.path === recordingFolder && !view.canGoBack, "A stopped recording must open for review");
        } else if (step === 5) {
            var review = find(chat, "agavaiRecordingReview");
            // The file loads asynchronously and rows appear once laid out; wait up to two seconds.
            if (!(review.itemAtIndex(0) && review.itemAtIndex(1)) && waited++ < 8)
                return false;
            check(review.count === 2 && review.itemAtIndex(0) && review.itemAtIndex(1), "The review must list the recording's lines: " + review.count);
            input.mouseClick(review.itemAtIndex(1), 20, 10, Qt.LeftButton);
        } else if (step === 6) {
            var player = find(chat, "agavaiRecordingPlayer");
            check(player.playbackState === MediaPlayer.PlayingState && player.position >= 900, "Clicking a line must play from its time: " + player.position);
            player.stop();
            input.mouseDoubleClickSequence(find(chat, "agavaiRecordingReview").itemAtIndex(0), 20, 10, Qt.LeftButton);
        } else if (step === 7) {
            var editor = find(chat, "agavaiRecordingEditor");
            check(editor.visible && editor.activeFocus, "Double-clicking a line must open it for correction");
            editor.text = "The canary ships on Thursday.";
            editor.accepted();
            check(find(chat, "agavaiRecordingView").editing === 0, "Enter must save the correction and close the editor");
            chat.applySnapshot(JSON.stringify({session_id: "rec", phase: "idle", display: {id: "list", kind: "recordings", title: "Recordings", items: [{id: "0", kind: "recording", title: "Recording", subtitle: "Fri 23 Oct, 20:17 · 00:02", path: recordingFolder, openable: false}]}}));
        } else if (step === 8) {
            check(!find(chat, "agavaiRecordingView").visible, "The Recordings list must show before one is opened");
            chat.openSelected();
            check(find(chat, "agavaiRecordingView").visible && find(chat, "agavaiRecordingView").canGoBack, "Opening a listed recording must review it with a way back");
            find(chat, "agavaiRecordingView").backRequested();
            check(!find(chat, "agavaiRecordingView").visible && chat.openedRecording === "", "Back must return to the Recordings list");
            console.log("COMPACT_UI_PASS");
            Qt.quit();
        }
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
                var orb = find(chat, "agavaiOrb");
                var closeButton = find(chat, "agavaiClose");
                if (scenario === "canvas-focus") {
                    canvasFocusStep(step, panel, details);
                } else if (scenario === "recording") {
                    if (recordingStep(step, panel, stage, details, orb) === false)
                        return;
                } else if (step === 0) {
                    chat.applySnapshot(JSON.stringify({session_id: "test", phase: "listening", transcript: {text: "find notes"}, level_db: -25}));
                } else if (step === 1 || step === 4) {
                    check(chat.opened && chat.compact && !chat.wantsKeyboardFocus, "Compact mode must keep the session open without keyboard focus");
                    check(panel.WlrLayershell.keyboardFocus === WlrKeyboardFocus.None, "Compact layer must release compositor keyboard focus");
                    check(orb.visible && !details.visible, "Compact mode must show only the orb");
                    check(closeButton.visible && closeButton.Accessible.name === "Dismiss assistant", "Compact mode must expose a named close button");
                    check(closeButton.x >= 0 && closeButton.y >= 0 && closeButton.x + closeButton.width <= orb.width && closeButton.y + closeButton.height <= orb.height, "Close button must stay inside the compact input region");
                    check(stage.width === Style.space(80) && stage.height === Style.space(80), "Compact input region must stay small: step " + step + ", " + stage.width + "x" + stage.height);
                    checkPosition(stage, panel, orb);
                    if (step === 1) {
                        check(chat.strength > 0 && chat.transcript === "find notes", "Compact mode must retain microphone level and transcription");
                        orbAt = orbOnScreen(orb, stage);
                        input.mouseClick(find(chat, "agavaiOrbPointer"), 40, 40, Qt.LeftButton);
                    } else {
                        check(chat.sessionId === "test" && chat.items.length === 1, "Minimizing must preserve session and results");
                        chat.applySnapshot(JSON.stringify({session_id: "test", phase: "speaking", error: "Retry needed", turns: [{assistant: "Your notes"}], display: {id: "canvas1", items: [{title: "Notes"}]}}));
                    }
                } else if (step === 2) {
                    check(!chat.compact && details.visible && orb.visible && chat.wantsKeyboardFocus, "Expanding must reveal the full view around the orb");
                    var expandedAt = orbOnScreen(orb, stage);
                    check(expandedAt.x === orbAt.x && expandedAt.y === orbAt.y, "Expanding must not move the orb");
                    checkPosition(stage, panel, orb);
                    check(panel.WlrLayershell.keyboardFocus === WlrKeyboardFocus.OnDemand, "Expanded view must let other windows receive input");
                    chat.applySnapshot(JSON.stringify({session_id: "test", phase: "listening", display: {id: "canvas1", items: [{title: "Notes"}]}}));
                } else if (step === 3) {
                    check(!chat.compact && chat.items.length === 1, "Snapshots must preserve the chosen expanded view");
                    checkPosition(stage, panel, orb);
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
                    input.mouseClick(find(chat, "agavaiOrbPointer"), 40, 40, Qt.LeftButton);
                } else if (step === 6) {
                    check(!chat.compact && panel.contentItem.Window.active, "Expanded view must acquire focus when activated");
                    checkPosition(stage, panel, orb);
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
                    checkPosition(stage, panel, orb);
                    find(chat, "agavaiMinimize").clicked();
                    chat.applySnapshot(JSON.stringify({session_id: "next", phase: "listening", level_db: -20, display: {id: "canvas2", items: [{title: "Budget"}]}}));
                } else if (step === 10) {
                    check(chat.compact && !chat.wantsKeyboardFocus, "Retained canvas and microphone updates must respect minimization");
                    checkPosition(stage, panel, orb);
                    chat.applySnapshot(JSON.stringify({session_id: "next", phase: "speaking", display: {id: "canvas3", items: [{title: "Budget"}]}}));
                } else if (step === 11) {
                    check(!chat.compact && chat.items[0].title === "Budget", "Reissuing the same results must reopen the canvas");
                    checkPosition(stage, panel, orb);
                    find(chat, "agavaiMinimize").clicked();
                    chat.applySnapshot(JSON.stringify({session_id: "next", phase: "error", error: "Retry needed"}));
                } else if (step === 12) {
                    check(chat.compact, "Errors without a new canvas must not expand the panel");
                    chat.phase = "idle";
                    input.mouseClick(find(chat, "agavaiOrbPointer"), 40, 40, Qt.RightButton);
                    chat.applySnapshot(JSON.stringify({session_id: "next", phase: "speaking", display: {id: "late", items: [{title: "Late"}]}}));
                    check(!chat.opened && chat.compact, "Late canvas results must not reopen a dismissed session");
                } else if (step < 13 + placements.length * 2) {
                    // Each placement: a canvas expands in that corner, then the orb minimizes it in place.
                    var placement = placements[Math.floor((step - 13) / 2)];
                    if ((step - 13) % 2 === 0) {
                        chat.applySnapshot(JSON.stringify({session_id: "corners", phase: "listening", placement: placement, turns: [{user: "list the planets", assistant: "Here are the planets."}], display: {id: placement, kind: "answer", title: "Planets", html: "<p>Mercury</p>"}}));
                    } else {
                        check(chat.placement === placement && !chat.compact, placement + ": a new canvas must expand");
                        checkPosition(stage, panel, orb);
                        var openAt = orbOnScreen(orb, stage);
                        input.mouseClick(find(chat, "agavaiOrbPointer"), 40, 40, Qt.LeftButton);
                        check(chat.compact && stage.width === Style.space(80) && stage.height === Style.space(80), placement + ": clicking the orb must minimize");
                        var closedAt = orbOnScreen(orb, stage);
                        check(closedAt.x === openAt.x && closedAt.y === openAt.y, placement + ": minimizing must not move the orb");
                        checkPosition(stage, panel, orb);
                    }
                } else {
                    console.log("COMPACT_UI_PASS");
                    Qt.quit();
                }
                step++;
            } catch (error) {
                console.error("COMPACT_UI_FAIL: step " + step + ": " + error.message);
                Qt.quit();
            }
        }
    }
}
