/** Local host adapter for the original Gladeye scene. No geometry or shader replacement. */
(() => {
  'use strict';
  const channel = 'yingxu:original-flower-valley';
  let valley;
  let ready = false;
  let disposed = false;
  let lost = false;
  let failed = false;
  let active = !document.hidden;
  let reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let resizeTimer;
  let running = false;

  const report = (state, message) => {
    if (disposed) return;
    document.documentElement.dataset.state = state;
    parent.postMessage({ channel, state, message }, location.origin);
  };
  const stop = () => {
    if (!valley) return;
    cancelAnimationFrame(valley.rafID);
    valley.rafID = 0;
    // Before animateIn(), the original virtual scroller has not started yet.
    // Marking it paused here would make resume start it before animateIn()
    // starts it a second time, leaving an extra scrolling RAF alive.
    if (valley.valleyScene.hasStartedAnimatingIn) valley.valleyScene.onFramePause();
    running = false;
  };
  const renderStill = () => {
    if (!valley?.valleyReady || lost || failed || disposed) return;
    valley.render();
  };
  const updateRunning = () => {
    // Assets being ready is sufficient to resume the official intro. Waiting
    // for its completion here can deadlock a scene loaded in a hidden iframe.
    if (!valley?.valleyReady || lost || failed || disposed) return;
    if (reduced) {
      stop();
      if (!ready) {
        // Skip only the introductory camera turn, including when the motion
        // preference changes after assets load but before the intro finishes.
        const scene = valley.valleyScene;
        if (!scene.hasStartedAnimatingIn) scene.animateIn();
        scene.introCameraAngle = 0;
        scene.breathContainer.rotation.x = 0;
        scene.isAnimatedIn = true;
        scene.onFrameAlwaysRun();
        scene.onFrame();
        valley.render();
        ready = true;
        stop();
        report('ready');
      } else {
        renderStill();
      }
    } else if (active && !document.hidden) {
      if (!running) {
        valley.valleyScene.clock.getDelta();
        if (valley.valleyScene.hasStartedAnimatingIn) valley.valleyScene.onFrameStart();
        valley.startRender();
        running = true;
      }
    } else {
      stop();
    }
  };
  const onReady = () => {
    if (ready || disposed) return;
    ready = true;
    // The original intro callback can fire every frame. Only announce it once,
    // and pause after its enclosing official frame has finished scheduling RAF.
    queueMicrotask(() => {
      if (disposed || failed || lost) return;
      running = true;
      updateRunning();
      report('ready');
    });
  };
  const onLoaded = () => {
    queueMicrotask(() => {
      if (!valley) return;
      if (disposed || failed || lost) {
        stop();
        return;
      }
      running = true;
      updateRunning();
    });
  };
  const onResize = () => {
    clearTimeout(resizeTimer);
    // The original resize handler makes a second update after 50 ms.
    // Redraw a paused scene after both, so resizing cannot leave a blank canvas.
    resizeTimer = setTimeout(() => {
      if (ready && !running) renderStill();
    }, 100);
  };
  const fail = (message) => {
    failed = true;
    stop();
    report('error', String(message || 'Unable to render the flower valley'));
  };
  window.addEventListener('error', (event) => fail(event.message));
  window.addEventListener('unhandledrejection', (event) => fail(event.reason?.message || event.reason));
  window.addEventListener('resize', onResize, { passive: true });
  document.addEventListener('visibilitychange', updateRunning);
  window.addEventListener('message', (event) => {
    if (event.source !== parent || event.origin !== location.origin || event.data?.channel !== channel) return;
    const data = event.data;
    if (data.action === 'state') {
      active = data.active !== false;
      reduced = data.reduced === true;
      updateRunning();
    } else if (data.action === 'pointer' && valley && ready && active && !reduced) {
      const x = Math.max(0, Math.min(1, Number(data.x))) * innerWidth;
      const y = Math.max(0, Math.min(1, Number(data.y))) * innerHeight;
      if (Number.isFinite(x) && Number.isFinite(y)) valley.onMouseMove({ pageX: x, pageY: y });
    } else if (data.action === 'wheel' && valley && ready && active && !reduced) {
      document.getElementById('valley').dispatchEvent(new WheelEvent('wheel', {
        deltaX: Number(data.deltaX) || 0,
        deltaY: Number(data.deltaY) || 0,
        deltaMode: Number(data.deltaMode) || 0,
        bubbles: true,
        cancelable: false,
      }));
    } else if (data.action === 'resize') {
      onResize();
    } else if (data.action === 'status') {
      report(failed || lost ? 'error' : ready ? 'ready' : 'loading');
    }
  });
  window.addEventListener('pagehide', (event) => {
    if (event.persisted) {
      stop();
      return;
    }
    disposed = true;
    clearTimeout(resizeTimer);
    stop();
    clearTimeout(valley?.resizeTimeout);
    // The original inner destroy checks a misspelled `vignetter` property.
    // Release its resize listener explicitly before destroying the scene.
    try { valley?.valleyScene.vignette?.destroy(); } catch { /* Continue teardown. */ }
    try { valley?.destroy(); } catch { /* The document also releases its own GL context. */ }
  });
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) updateRunning();
  });

  try {
    report('loading');
    let requireOriginal;
    self.webpackChunk_N_E.push([[90003], {}, (require) => { requireOriginal = require; }]);
    requireOriginal(889);
    valley = new window.__GE.Valley(document.getElementById('valley'), onLoaded, onReady);
    // No audio manager is initialised and no media permissions are requested.
    const canvas = valley.canvas;
    canvas.addEventListener('webglcontextlost', (event) => {
      event.preventDefault();
      lost = true;
      stop();
      report('error', 'context-lost');
    });
    canvas.addEventListener('webglcontextrestored', () => {
      lost = false;
      queueMicrotask(() => {
        if (disposed || failed) return;
        updateRunning();
        if (!running) renderStill();
        report(ready ? 'ready' : 'loading');
      });
    });
  } catch (error) {
    fail(error.message);
  }
})();
