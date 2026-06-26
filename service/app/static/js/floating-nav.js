// On-screen navigation bar (FoodAssistant-bzuu, -i181).
//
// A FIXED bar docked to a screen edge (bottom, left, or right), not a draggable
// floating overlay. The edge is the server default (data-position) unless the
// device has its own choice in localStorage (placement is per-device: a wall
// kiosk and a phone want different docking). The bar reserves layout space by
// padding the body on the docked side, so it never sits on top of content.
//
// On a touch kiosk it auto-docks to the bottom when nothing is set, so the
// large icon targets are always available without the hamburger.
//
// Auto-hides when a Stream Deck is connected if that option is set, since the
// deck already provides navigation.
(function () {
  var EDGES = ['bottom', 'left', 'right'];
  var STORE_KEY = 'floatNavPosition';

  // Map a legacy corner value (from the older draggable menu) to an edge so
  // existing saved settings keep working.
  function normalizeEdge(value) {
    if (EDGES.indexOf(value) !== -1) return value;
    if (value === 'top-left' || value === 'bottom-left') return 'left';
    if (value === 'top-right' || value === 'bottom-right') return 'right';
    return '';  // 'off', '', or unknown
  }

  function start() {
    var nav = document.getElementById('floatNav');
    if (!nav) return;

    var serverPos = nav.getAttribute('data-position') || 'off';
    var autohide = nav.getAttribute('data-autohide-streamdeck') === '1';
    var hasDeck = nav.getAttribute('data-has-streamdeck') === '1';

    // Per-device override beats the server default.
    var stored = '';
    try { stored = localStorage.getItem(STORE_KEY) || ''; } catch (e) { }
    var raw = stored || serverPos;
    var edge = normalizeEdge(raw);

    // On a touch kiosk, dock to the bottom by default when nothing is set, so
    // navigation is always one tap away. An explicit 'off' on this device wins.
    var kiosk = false;
    try { kiosk = localStorage.getItem('kioskMode') === 'true'; } catch (e) { }
    if (kiosk && !edge && raw !== 'off' && stored !== 'off') {
      edge = 'bottom';
    }

    if (!edge || (autohide && hasDeck)) {
      nav.classList.add('d-none');
      clearPadding();
      return;
    }

    applyDock(nav, edge);
    nav.classList.remove('d-none');
    reserveSpace(nav, edge);

    window.addEventListener('resize', function () {
      reserveSpace(nav, edge);
    });
  }

  function applyDock(nav, edge) {
    EDGES.forEach(function (e) { nav.classList.remove('float-nav-dock-' + e); });
    nav.classList.add('float-nav-dock-' + edge);
  }

  // Pad the body on the docked side so the fixed bar never overlaps content.
  // The body is the right target (its padding-top already offsets the navbar);
  // we only ever touch left/right/bottom here, never top.
  function reserveSpace(nav, edge) {
    clearPadding();
    var rect = nav.getBoundingClientRect();
    var body = document.body;
    if (edge === 'bottom') {
      body.style.setProperty('padding-bottom', Math.ceil(rect.height) + 'px', 'important');
    } else if (edge === 'left') {
      body.style.setProperty('padding-left', Math.ceil(rect.width) + 'px', 'important');
    } else if (edge === 'right') {
      body.style.setProperty('padding-right', Math.ceil(rect.width) + 'px', 'important');
    }
  }

  function clearPadding() {
    var body = document.body;
    ['padding-bottom', 'padding-left', 'padding-right'].forEach(function (p) {
      body.style.removeProperty(p);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
