import QtQuick

Canvas {
    id: root
    property string phase: "idle"
    property real strength: 0
    property bool paused: false
    readonly property bool listening: phase === "listening"
    readonly property bool recording: phase === "recording"
    readonly property bool working: phase === "thinking" || phase === "speaking"
    property real spin: 0
    property real breath: 0

    onSpinChanged: requestPaint()
    onBreathChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onStrengthChanged: requestPaint()
    onPhaseChanged: requestPaint()
    onPausedChanged: requestPaint()
    onListeningChanged: {
        if (!listening)
            breath = 0;
    }
    Behavior on strength {
        NumberAnimation { duration: 100 }
    }
    SequentialAnimation on breath {
        running: root.visible && root.listening
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: 1100; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: 1100; easing.type: Easing.InOutSine }
    }
    Timer {
        interval: 32
        repeat: true
        running: root.visible && (root.listening || root.working || root.recording && !root.paused)
        onTriggered: {
            var step = root.listening || root.recording ? 0.006 + root.strength * 0.1 : 0.022;
            root.spin = (root.spin + step) % (Math.PI * 2);
        }
    }
    onPaint: {
        var ctx = getContext("2d");
        if (!ctx || width < 2 || height < 2)
            return;
        ctx.reset();
        var cx = width / 2;
        var cy = height / 2;
        var pulse = 0.78 + root.strength * 0.34;
        var radius = Math.min(width, height) * 0.31 * pulse;
        // A ring only while the mic is open, so listening is distinct from results.
        if (root.listening) {
            ctx.beginPath();
            ctx.lineWidth = Math.max(2, width * 0.02) + root.strength * 3;
            ctx.strokeStyle = Qt.rgba(0.55, 0.78, 1, 0.48 + root.breath * 0.18 + root.strength * 0.3);
            var ringRadius = Math.min(radius * (1.26 + root.breath * 0.08 + root.strength * 0.34), Math.min(width, height) / 2 - ctx.lineWidth / 2 - 1);
            ctx.arc(cx, cy, ringRadius, 0, Math.PI * 2);
            ctx.stroke();
        } else if (root.recording) {
            // Steady, not breathing: recording must read differently from listening at a glance.
            ctx.beginPath();
            ctx.lineWidth = Math.max(3, width * 0.035) + (root.paused ? 0 : root.strength * 3);
            ctx.strokeStyle = root.paused ? Qt.rgba(0.95, 0.7, 0.3, 0.8) : Qt.rgba(0.93, 0.27, 0.25, 0.92);
            ctx.arc(cx, cy, Math.min(radius * 1.3, Math.min(width, height) / 2 - ctx.lineWidth / 2 - 1), 0, Math.PI * 2);
            ctx.stroke();
        }
        var glow = ctx.createRadialGradient(cx, cy, radius * 0.15, cx, cy, radius * 1.85);
        glow.addColorStop(0, Qt.rgba(0.62, 0.45, 1, 0.34 + root.strength * 0.28));
        glow.addColorStop(1, Qt.rgba(0.62, 0.45, 1, 0));
        ctx.fillStyle = glow;
        ctx.fillRect(0, 0, width, height);
        ctx.save();
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.clip();
        var colors = ["#64d2ff", "#30d158", "#ffd60a", "#ff375f", "#bf5af2"];
        for (var i = 0; i < colors.length; i++) {
            var angle = spin + i * Math.PI * 2 / colors.length;
            var bx = cx + Math.cos(angle) * radius * 0.45;
            var by = cy + Math.sin(angle * 1.31) * radius * 0.45;
            var br = radius * (0.72 + 0.18 * Math.sin(spin * 1.4 + i));
            var blob = ctx.createRadialGradient(bx, by, 0, bx, by, br);
            blob.addColorStop(0, colors[i]);
            blob.addColorStop(1, Qt.rgba(1, 1, 1, 0));
            ctx.fillStyle = blob;
            ctx.fillRect(0, 0, width, height);
        }
        ctx.restore();
    }
}
