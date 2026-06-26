// On-screen floating timer window (FoodAssistant-8uqy, Current Recipe epic).
//
// Shows the server-side running timers (GET /timers) in a small floating window
// so any browser surface can watch the same countdowns the Stream Deck and
// satellites see. The window only appears when at least one timer is running and
// hides itself when none remain.
//
// Two clocks, like the server: we POLL /timers every few seconds to learn which
// timers exist and to pick up new/cancelled ones, but between polls we TICK each
// visible countdown locally once a second from deadline_epoch minus the browser's
// own time.time() (Date.now()). That keeps the mm:ss display smooth without
// hammering the server, and matches the server's shareable-countdown contract:
// remaining = deadline_epoch - now, clamped at zero, expired once it hits zero.
//
// Per-device toggle: a small close control hides the window and persists the
// choice in localStorage ('timerWindow' = 'on'|'off', default 'on'), since a
// wall kiosk and a phone may each want it on or off independently.
//
// Defers to the Stream Deck: when a deck is present (data-has-streamdeck="1"),
// the deck already displays timers, so the on-screen window stays hidden unless
// the user has explicitly turned it 'on' on this device.
(function () {
  var STORE_KEY = 'timerWindow';
  var POLL_MS = 5000;   // how often we re-ask the server which timers exist
  var TICK_MS = 1000;   // how often we redraw the local countdown

  function start() {
    var win = document.getElementById('timerWindow');
    if (!win) return;

    var hasDeck = win.getAttribute('data-has-streamdeck') === '1';

    var stored = '';
    try { stored = localStorage.getItem(STORE_KEY) || ''; } catch (e) { }

    // 'off' always wins. With a deck present we default to hidden (the deck
    // shows timers); only an explicit 'on' brings the window back. Without a
    // deck the default is 'on'.
    if (stored === 'off') return;
    if (hasDeck && stored !== 'on') return;

    var list = win.querySelector('.timer-window-list');
    var closeBtn = win.querySelector('.timer-window-close');
    var timers = [];

    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        try { localStorage.setItem(STORE_KEY, 'off'); } catch (e) { }
        win.classList.add('d-none');
      });
    }

    function fmt(remaining) {
      var total = Math.max(0, Math.floor(remaining));
      var m = Math.floor(total / 60);
      var s = total % 60;
      return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    }

    // Compute remaining from the absolute epoch deadline and the browser clock,
    // falling back to the server-provided remaining_seconds if no deadline.
    function remainingOf(t) {
      if (typeof t.deadline_epoch === 'number') {
        return t.deadline_epoch - (Date.now() / 1000);
      }
      var rs = (typeof t.remaining_seconds === 'number') ? t.remaining_seconds
             : (typeof t.seconds === 'number') ? t.seconds : 0;
      return rs;
    }

    function render() {
      if (!timers.length) {
        win.classList.add('d-none');
        if (list) list.innerHTML = '';
        return;
      }
      win.classList.remove('d-none');
      if (!list) return;
      list.innerHTML = '';
      for (var i = 0; i < timers.length; i++) {
        var t = timers[i];
        var remaining = remainingOf(t);
        var expired = remaining <= 0;

        var row = document.createElement('div');
        row.className = 'timer-window-row' + (expired ? ' timer-window-expired' : '');

        var label = document.createElement('span');
        label.className = 'timer-window-label';
        label.textContent = t.label || ('Timer ' + (t.id != null ? t.id : (i + 1)));

        var clock = document.createElement('span');
        clock.className = 'timer-window-clock';
        clock.textContent = expired ? 'done' : fmt(remaining);

        row.appendChild(label);
        row.appendChild(clock);
        list.appendChild(row);
      }
    }

    function poll() {
      fetch('timers', { cache: 'no-store', headers: { 'Accept': 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          var rows = (data && Array.isArray(data.timers)) ? data.timers : [];
          // Only display running timers; an expired one is shown highlighted
          // until the server drops it, but a cancelled timer just disappears.
          timers = rows.filter(function (t) {
            return t && (t.running || t.expired);
          });
          render();
        })
        .catch(function () { /* empty or unreachable: leave last state */ });
    }

    poll();
    setInterval(poll, POLL_MS);
    setInterval(render, TICK_MS);  // smooth local countdown between polls
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
