// Kiosk screensaver (FoodAssistant-y65x).
//
// Runs only in kiosk mode. After the configured idle minutes the page fades to
// a near-black overlay with the Pantry Raider logo bouncing slowly around the
// screen (clock and date riding under it), and any touch or key press
// dismisses it instantly. This is the SOFT layer for panels where full display
// blanking is unwanted: the separate "Display sleep" setting powers the panel
// itself off via the host bridge, while this one keeps the display lit and
// just covers the page. The constant motion is the burn-in guard.
//
// The timeout comes from #screensaver-config (data-minutes, rendered from the
// per-device saved setting); 0 or a missing config leaves this a no-op.
//
// Planned phases (separate beads): slideshow of images from an attached USB
// drive, and a mode that spans the Stream Deck keys and the panel as one large
// canvas.
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
  var SPEED = 30; // pixels per second: a slow, calm glide
  var lastActivity = Date.now();
  var overlay = null;
  var clockTimer = null;
  var rafId = null;

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

  // DVD-style bounce: the block glides at constant speed and reflects off the
  // viewport edges. Frame-time based so the speed is the same on a slow Pi
  // and a fast desktop; transform keeps the motion on the compositor.
  function startBounce(block) {
    var x = null, y = null, dx = 1, dy = 1, last = null;
    function step(ts) {
      if (!overlay) return;
      var w = window.innerWidth, h = window.innerHeight;
      var r = block.getBoundingClientRect();
      var maxX = Math.max(0, w - r.width);
      var maxY = Math.max(0, h - r.height);
      if (x === null) {
        x = Math.random() * maxX;
        y = Math.random() * maxY;
        var a = (Math.random() * 0.5 + 0.4); // avoid near-flat angles
        dx = (Math.random() < 0.5 ? -1 : 1) * a;
        dy = (Math.random() < 0.5 ? -1 : 1) * Math.sqrt(1 - a * a || 0.5);
      }
      if (last !== null) {
        var dt = Math.min(100, ts - last) / 1000;
        x += dx * SPEED * dt;
        y += dy * SPEED * dt;
        if (x <= 0) { x = 0; dx = Math.abs(dx); }
        if (x >= maxX) { x = maxX; dx = -Math.abs(dx); }
        if (y <= 0) { y = 0; dy = Math.abs(dy); }
        if (y >= maxY) { y = maxY; dy = -Math.abs(dy); }
      }
      last = ts;
      block.style.transform = 'translate(' + x + 'px,' + y + 'px)';
      rafId = requestAnimationFrame(step);
    }
    rafId = requestAnimationFrame(step);
  }

  function show() {
    if (overlay) return;
    overlay = document.createElement('div');
    overlay.id = 'kiosk-screensaver';
    overlay.style.cssText =
      'position:fixed;inset:0;z-index:2147483000;background:#000;' +
      'opacity:0;transition:opacity 1.2s ease;cursor:none;overflow:hidden;';
    var block = document.createElement('div');
    block.className = 'ss-block';
    block.style.cssText =
      'position:absolute;left:0;top:0;text-align:center;color:#9aa0a6;' +
      'font-family:inherit;will-change:transform;';
    var mark = document.createElement('img');
    mark.src = 'static/icons/logo-mark.png';
    mark.alt = '';
    mark.style.cssText = 'width:18vmin;height:18vmin;opacity:0.85;display:block;margin:0 auto 1.5vmin;';
    var time = document.createElement('div');
    time.className = 'ss-time';
    time.style.cssText = 'font-size:6vmin;font-weight:600;line-height:1;color:#cfd3d8;';
    var date = document.createElement('div');
    date.className = 'ss-date';
    date.style.cssText = 'font-size:2.4vmin;margin-top:0.8vmin;opacity:0.7;';
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
    startBounce(block);
  }

  function hide() {
    if (!overlay) return;
    var el = overlay;
    overlay = null;
    clearInterval(clockTimer);
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
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
