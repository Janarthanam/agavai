import QtQuick
import QtTest
import "Assistant"

Item {
    width: 80
    height: 80
    VoiceOrb { id: orb; anchors.fill: parent }

    TestCase {
        name: "ListeningOrb"
        when: windowShown

        function test_microphoneMotion() {
            orb.phase = "listening";
            orb.strength = 0;
            wait(250);
            var breath = orb.breath;
            var spin = orb.spin;
            wait(250);
            verify(orb.breath > breath, "The ring must breathe even with silent input");
            verify(orb.spin > spin, "Listening must keep the orb visibly active");

            var silentSpin = orb.spin;
            wait(250);
            var silentChange = orb.spin - silentSpin;
            orb.strength = 1;
            wait(150);
            var speechSpin = orb.spin;
            wait(250);
            verify(orb.spin - speechSpin > silentChange * 3, "Speech must strengthen motion");

            orb.phase = "thinking";
            verify(!orb.listening, "Processing must remove the listening ring");
            wait(150);
            compare(orb.breath, 0);

            orb.phase = "idle";
            orb.strength = 0;
            wait(150);
            var idleSpin = orb.spin;
            wait(250);
            compare(orb.spin, idleSpin, "Idle results must not look like microphone listening");
            compare(orb.breath, 0);

            orb.phase = "listening";
            wait(250);
            orb.visible = false;
            var hiddenSpin = orb.spin;
            var hiddenBreath = orb.breath;
            wait(250);
            compare(orb.spin, hiddenSpin);
            compare(orb.breath, hiddenBreath, "Hidden orbs must stop animating");
        }
    }
}
