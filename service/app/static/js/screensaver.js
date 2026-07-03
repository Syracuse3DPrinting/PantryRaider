// Kiosk screensaver (FoodAssistant-y65x).
//
// Runs only in kiosk mode. After the configured idle minutes the page fades to
// a near-black overlay with a floating clock (and the brand mark), and any
// touch or key press dismisses it instantly. This is the SOFT layer for panels
// where full display blanking is unwanted: the separate "Display sleep"
// setting powers the panel itself off via the host bridge, while this one
// keeps the display lit and just covers the page. The clock drifts to a new
// spot every minute so a static image never burns into the panel.
//
// The timeout comes from #screensaver-config (data-minutes, rendered from the
// per-device saved setting); 0 or a missing config leaves this a no-op.
(function () {
  try {
    if (localStorage.getItem('kioskMode') !== 'true') return;
  } catch (e) {
    return; // no storage / private mode: never run
  }

  var cfg = document.getElementById('screensaver-config');
  var minutes = parseInt(cfg ? cfg.getAttribute('data-minutes') : '0', 10);
  if (!minutes || minutes <= 0) return;

  var IDLE_MS = minutes * 60 * 1000;
  var DRIFT_MS = 60 * 1000; // move the clock once a minute (burn-in guard)
  var lastActivity = Date.now();
  var overlay = null;
  var clockTimer = null;
  var driftTimer = null;

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function updateClock() {
    if (!overlay) return;
    var now = new Date();
    var t = overlay.querySelector('.ss-time');
    var d = overlay.querySelector('.ss-date');
    if (t) t.textContent = pad(now.getHours()) + ':' + pad(now.getMinutes());
    if (d) d.textContent = now.toLocaleDateString(undefined, {
      weekday: 'long', month: 'long', day: 'numeric',
    });
  }

  function drift() {
    if (!overlay) return;
    var block = overlay.querySelector('.ss-block');
    if (!block) return;
    // Keep the block fully on screen: pick a spot in the middle 60% band.
    var x = 10 + Math.random() * 60;
    var y = 15 + Math.random() * 55;
    block.style.left = x + '%';
    block.style.top = y + '%';
  }

  function show() {
    if (overlay) return;
    overlay = document.createElement('div');
    overlay.id = 'kiosk-screensaver';
    overlay.style.cssText =
      'position:fixed;inset:0;z-index:2147483000;background:#000;' +
      'opacity:0;transition:opacity 1.2s ease;cursor:none;';
    var block = document.createElement('div');
    block.className = 'ss-block';
    block.style.cssText =
      'position:absolute;left:50%;top:40%;transform:translate(-50%,-50%);' +
      'text-align:center;color:#9aa0a6;font-family:inherit;' +
      'transition:left 2s ease, top 2s ease;';
    var mark = document.createElement('img');
    mark.src = 'static/icons/logo-mark.png';
    mark.alt = '';
    mark.style.cssText = 'width:56px;height:56px;opacity:0.35;display:block;margin:0 auto 10px;';
    var time = document.createElement('div');
    time.className = 'ss-time';
    time.style.cssText = 'font-size:14vmin;font-weight:600;line-height:1;color:#cfd3d8;';
    var date = document.createElement('div');
    date.className = 'ss-date';
    date.style.cssText = 'font-size:3.5vmin;margin-top:1vmin;opacity:0.7;';
    block.appendChild(mark);
    block.appendChild(time);
    block.appendChild(date);
    overlay.appendChild(block);
    document.body.appendChild(overlay);
    updateClock();
    // Fade in on the next frame so the transition runs.
    requestAnimationFrame(function () {
      if (overlay) overlay.style.opacity = '1';
    });
    clockTimer = setInterval(updateClock, 5000);
    driftTimer = setInterval(drift, DRIFT_MS);
  }

  function hide() {
    if (!overlay) return;
    var el = overlay;
    overlay = null;
    clearInterval(clockTimer);
    clearInterval(driftTimer);
    if (el.parentNode) el.parentNode.removeChild(el);
  }

  // After a dismissing tap, keep swallowing the rest of its gesture (the
  // pointerup/touchend/click that follow) so the tap never presses whatever
  // sits under the overlay.
  var suppressUntil = 0;
  var SWALLOW = ['pointerdown', 'pointerup', 'touchstart', 'touchend',
                 'mousedown', 'mouseup', 'click', 'keydown'];

  function onActivity(ev) {
    lastActivity = Date.now();
    var swallow = ev && SWALLOW.indexOf(ev.type) !== -1;
    if (overlay) {
      // Any input wakes the screen; a tap/key that did it is swallowed so it
      // only dismisses the screensaver. Mouse motion just dismisses.
      if (swallow) {
        suppressUntil = Date.now() + 700;
        if (ev.cancelable) ev.preventDefault();
        ev.stopPropagation();
      }
      hide();
      return;
    }
    if (swallow && Date.now() < suppressUntil) {
      if (ev.cancelable) ev.preventDefault();
      ev.stopPropagation();
    }
  }

  var events = SWALLOW.concat(['mousemove', 'wheel']);
  for (var i = 0; i < events.length; i++) {
    // Capture phase so a dismissing tap is seen (and swallowed) before the
    // page's own handlers. passive:false lets preventDefault work on touch.
    window.addEventListener(events[i], onActivity, { capture: true, passive: false });
  }

  setInterval(function () {
    if (!overlay && Date.now() - lastActivity >= IDLE_MS) show();
  }, 10000);
})();
