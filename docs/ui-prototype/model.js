/* Shared interaction model for the browser design prototype. No desktop actions. */
(function (scope) {
  function initial() {
    return { phase: 'idle', open: false, transcript: '', level: 0, items: [], selected: 0, pinned: false, error: '' };
  }
  function update(state, event) {
    switch (event.type) {
      case 'start': return { ...initial(), open: true, phase: 'listening' };
      case 'partial': return state.phase === 'listening' ? { ...state, transcript: event.text } : state;
      case 'level': return { ...state, level: state.phase === 'listening' && Number.isFinite(event.db) ? Math.max(0, Math.min(1, (event.db + 70) / 65)) : 0 };
      case 'submit': return state.phase === 'listening' ? { ...state, phase: 'thinking', level: 0 } : state;
      case 'results': return state.phase === 'thinking' ? { ...state, phase: 'results', items: event.items, selected: 0 } : state;
      case 'select': return { ...state, selected: Math.max(0, Math.min(Math.max(0, state.items.length - 1), event.index)) };
      case 'pin': return { ...state, pinned: !state.pinned };
      case 'error': return { ...state, open: true, phase: 'error', level: 0, error: event.message };
      case 'dismiss': return { ...state, open: false, phase: 'idle', level: 0 };
      default: return state;
    }
  }
  const api = { initial, update };
  if (typeof module !== 'undefined') module.exports = api;
  else scope.AgavaiDesign = api;
})(globalThis);
