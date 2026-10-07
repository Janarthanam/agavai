import QtQuick

Canvas {
    id: root
    property string phase: "idle"
    property real strength: 0
    readonly property bool listening: phase === "listening"
    property real spin: 0

    onSpinChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onStrengthChanged: requestPaint()
    onPhaseChanged: requestPaint()
    Timer {
        interval: 32
        repeat: true
        running: root.visible
        onTriggered: {
            var working = root.phase === "thinking" || root.phase === "speaking" || root.phase === "transcribing";
            var step = root.listening ? 0.006 + root.strength * 0.1 : working ? 0.022 : 0.004;
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
            ctx.strokeStyle = Qt.rgba(0.55, 0.78, 1, 0.38 + root.strength * 0.5);
            ctx.arc(cx, cy, radius * (1.22 + root.strength * 0.38), 0, Math.PI * 2);
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
