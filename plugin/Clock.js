.pragma library

// mm:ss, or h:mm:ss past an hour, the same as recording.clock() in Python.
function clock(ms) {
    var seconds = Math.max(0, Math.floor(ms / 1000));
    var hours = Math.floor(seconds / 3600);
    var minutes = Math.floor(seconds % 3600 / 60);
    var rest = seconds % 60;
    var two = function (n) {
        return (n < 10 ? "0" : "") + n;
    };
    return hours ? hours + ":" + two(minutes) + ":" + two(rest) : two(minutes) + ":" + two(rest);
}
