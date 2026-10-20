(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  var statusEl = $("status");
  var filterEl = $("route-filter");
  var listEl = $("list");
  var listSummary = $("list-summary");
  var listItems = $("list-items");
  var infoEl = $("info");
  var shareEl = $("share");
  var shareOpen = $("share-open");
  var routePick = $("route-pick");
  var routeOther = $("route-other");
  var shareSetup = $("share-setup");
  var shareLive = $("share-live");
  var shareStatus = $("share-status");
  var shareError = $("share-error");

  var useMph = /^en-US/i.test(navigator.language || "");
  var config = null;
  var map = null;
  var markers = {};
  var buses = [];
  var routes = [];
  var selectedId = null;
  var last = { serverTime: null, updated: null, mode: "demo", agency: "", notes: [], feedOk: true };

  // ---------------------------------------------------------------- wording

  function ago(seconds) {
    if (seconds === null || seconds === undefined) return "a while ago";
    if (seconds < 5) return "just now";
    if (seconds < 90) return Math.round(seconds) + " seconds ago";
    if (seconds < 5400) return Math.round(seconds / 60) + " minutes ago";
    return Math.round(seconds / 3600) + " hours ago";
  }

  function speedText(metersPerSecond) {
    if (metersPerSecond === null || metersPerSecond === undefined) return "";
    var value = useMph ? metersPerSecond * 2.23694 : metersPerSecond * 3.6;
    var unit = useMph ? "mph" : "km/h";
    return value < 1 ? "Stopped." : "Moving at " + Math.round(value) + " " + unit + ".";
  }

  function busName(b) {
    if (!b.route) return "Bus " + (b.label || "");
    var extra = b.label && b.label !== b.route ? " (bus " + b.label + ")" : "";
    return "Route " + b.route + extra;
  }

  function sourceText(b) {
    if (b.source === "riders") {
      return b.riders === 1 ? "Reported by 1 rider on this bus." : "Reported by " + b.riders + " riders on this bus.";
    }
    if (last.mode === "demo") return "Simulated bus.";
    return b.riders > 0
      ? "Position from the agency's feed, confirmed by " + b.riders + (b.riders === 1 ? " rider." : " riders.")
      : "Position from the agency's feed.";
  }

  // ---------------------------------------------------------------- header status

  function renderStatus() {
    var line;
    if (last.mode === "demo") {
      line = "Demo mode: simulated buses";
    } else if (!last.feedOk) {
      line = "The agency's feed is not responding";
    } else {
      var age = last.updated === null ? null : Math.max(0, last.serverTime - last.updated);
      line = (last.agency ? "Live from " + last.agency : "Live bus positions") + ", updated " + ago(age);
    }
    var visible = buses.filter(function (b) { return !filterEl.value || b.route === filterEl.value; });
    line += ". " + (visible.length === 1 ? "1 bus" : visible.length + " buses") + " on the map.";
    statusEl.textContent = line;
  }

  // ---------------------------------------------------------------- markers

  function makeMarker(id) {
    var button = el("button", "bus");
    button.type = "button";
    button.appendChild(el("span", "arrow"));
    button.appendChild(el("span", "name"));
    button.addEventListener("click", function () { select(id, true); });
    return button;
  }

  function updateMarker(b) {
    var m = markers[b.id];
    var fresh = !m;
    if (fresh) {
      var button = makeMarker(b.id);
      m = { el: button, handle: map.addMarker(button, b.lat, b.lon), timer: null };
      markers[b.id] = m;
    } else {
      m.el.classList.add("glide");
      clearTimeout(m.timer);
      m.timer = setTimeout(function () { m.el.classList.remove("glide"); }, 1200);
      m.handle.setLatLng(b.lat, b.lon);
    }
    var node = m.el;
    node.classList.toggle("riders", b.source === "riders");
    node.classList.toggle("stale", b.age > 60);
    node.classList.toggle("selected", b.id === selectedId);
    var label = (b.route || b.label || "?").slice(0, 4);
    node.querySelector(".name").textContent = label;
    node.classList.toggle("long", label.length > 2);
    var arrow = node.querySelector(".arrow");
    arrow.hidden = b.bearing === null;
    if (b.bearing !== null) arrow.style.transform = "rotate(" + b.bearing + "deg)";
    node.setAttribute("aria-label", busName(b) + ". " + sourceText(b) + " Updated " + ago(b.age) + ".");
    m.handle.setHidden(!!filterEl.value && b.route !== filterEl.value);
  }

  // ---------------------------------------------------------------- details and list

  function select(id, center) {
    selectedId = id;
    Object.keys(markers).forEach(function (key) {
      markers[key].el.classList.toggle("selected", key === id);
    });
    var b = buses.filter(function (x) { return x.id === id; })[0];
    if (!b) { infoEl.hidden = true; return; }
    shareEl.hidden = true;
    $("info-title").textContent = busName(b);
    $("info-source").textContent = sourceText(b);
    $("info-detail").textContent = ("Updated " + ago(b.age) + ". " + speedText(b.speed)).trim();
    infoEl.hidden = false;
    if (center) map.setView(b.lat, b.lon);
  }

  function renderList() {
    var shown = buses.filter(function (b) { return !filterEl.value || b.route === filterEl.value; });
    listSummary.textContent = "Bus list (" + shown.length + ")";
    listItems.textContent = "";
    if (!shown.length) {
      listItems.appendChild(el("li", "empty", "No buses reported right now."));
      return;
    }
    shown.forEach(function (b) {
      var item = el("li");
      var button = el("button", "plain", busName(b) + ", " + (b.source === "riders" ? "reported by riders" : "agency feed") + ", " + ago(b.age));
      button.type = "button";
      button.addEventListener("click", function () { select(b.id, true); });
      item.appendChild(button);
      listItems.appendChild(item);
    });
  }

  function renderRoutes() {
    var current = filterEl.value;
    filterEl.textContent = "";
    var all = el("option", "", "All routes");
    all.value = "";
    filterEl.appendChild(all);
    routes.forEach(function (r) {
      var o = el("option", "", r);
      o.value = r;
      filterEl.appendChild(o);
    });
    filterEl.value = routes.indexOf(current) >= 0 ? current : "";

    var pick = routePick.dataset.touched ? routePick.value : "";
    routePick.textContent = "";
    routes.forEach(function (r) {
      var o = el("option", "", "Route " + r);
      o.value = r;
      routePick.appendChild(o);
    });
    var other = el("option", "", routes.length ? "Another route" : "Type the route");
    other.value = "__other";
    routePick.appendChild(other);
    var known = routes.indexOf(pick) >= 0 || pick === "__other";
    routePick.value = known ? pick : (routes[0] || "__other");
    routeOther.hidden = routePick.value !== "__other";
  }

  function applyData(data) {
    last = {
      serverTime: data.serverTime,
      updated: data.updated,
      mode: data.mode,
      agency: data.agency,
      notes: data.notes || [],
      feedOk: data.feedOk,
    };
    buses = data.buses || [];
    var joined = (data.routes || []).join("\u0000");
    if (joined !== routes.join("\u0000")) { routes = data.routes || []; renderRoutes(); }
    var seen = {};
    buses.forEach(function (b) { seen[b.id] = true; updateMarker(b); });
    Object.keys(markers).forEach(function (id) {
      if (!seen[id]) {
        markers[id].handle.remove();
        delete markers[id];
        if (selectedId === id) { selectedId = null; infoEl.hidden = true; }
      }
    });
    renderStatus();
    renderList();
    if (selectedId) select(selectedId, false);
    if (last.notes.length && last.mode !== "demo") statusEl.textContent += " " + last.notes[0];
  }

  // ---------------------------------------------------------------- loading

  function poll() {
    fetch("/api/buses", { cache: "no-store" })
      .then(function (response) {
        if (response.status === 429) throw new Error("The map is refreshing too often. Retrying shortly.");
        if (!response.ok) throw new Error("Could not load buses. Retrying shortly.");
        return response.json();
      })
      .then(applyData)
      .catch(function (err) { statusEl.textContent = err.message || "Could not load buses. Retrying shortly."; });
  }

  filterEl.addEventListener("change", function () {
    buses.forEach(updateMarker);
    renderStatus();
    renderList();
  });

  $("info-close").addEventListener("click", function () {
    infoEl.hidden = true;
    selectedId = null;
    Object.keys(markers).forEach(function (key) { markers[key].el.classList.remove("selected"); });
  });

  // ---------------------------------------------------------------- sharing a ride

  var share = { session: null, watch: null, sent: 0, lastSent: 0, route: "", centered: false, wake: null };

  function showShareError(text) {
    shareError.textContent = text || "";
    shareError.hidden = !text;
  }

  function post(url, body, keepalive) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      keepalive: !!keepalive,
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        return { ok: response.ok, status: response.status, data: data };
      });
    });
  }

  function renderShare() {
    var sharing = !!share.session;
    shareSetup.hidden = sharing;
    shareLive.hidden = !sharing;
    shareOpen.textContent = sharing ? "Sharing route " + share.route : "Share my bus";
    shareOpen.classList.toggle("live", sharing);
    if (sharing) {
      shareStatus.textContent = share.sent
        ? "Sharing route " + share.route + ". " + share.sent + " position" + (share.sent === 1 ? "" : "s") + " sent."
        : "Sharing route " + share.route + ". Waiting for your phone's location.";
    }
  }

  function releaseWake() {
    if (share.wake && share.wake.release) { share.wake.release().catch(function () {}); }
    share.wake = null;
  }

  function keepScreenOn() {
    if (!("wakeLock" in navigator)) return;
    navigator.wakeLock.request("screen").then(function (lock) { share.wake = lock; }).catch(function () {});
  }

  function stopSharing(message) {
    if (share.watch !== null) navigator.geolocation.clearWatch(share.watch);
    if (share.session) post("/api/riders/stop", { session: share.session }, true).catch(function () {});
    share = { session: null, watch: null, sent: 0, lastSent: 0, route: "", centered: false, wake: share.wake };
    releaseWake();
    renderShare();
    showShareError(message || "");
  }

  function onPosition(position) {
    if (!share.session) return;
    var now = Date.now();
    if (now - share.lastSent < 5000) return;
    share.lastSent = now;
    var c = position.coords;
    if (!share.centered) { share.centered = true; map.setView(c.latitude, c.longitude); }
    post("/api/riders/report", {
      session: share.session,
      lat: c.latitude,
      lon: c.longitude,
      accuracy: c.accuracy,
    }).then(function (result) {
      if (!share.session) return;
      if (result.ok) {
        if (result.data.result === "ok") share.sent += 1;
        showShareError(result.data.result === "ignored" ? "Waiting for a stronger location signal." : "");
        renderShare();
      } else if (result.status === 404) {
        stopSharing(result.data.error || "Sharing has ended.");
      } else if (result.status !== 429) {
        showShareError(result.data.error || "Your position could not be sent.");
      }
    }).catch(function () { showShareError("Could not reach the server. Still trying."); });
  }

  function onPositionError(error) {
    if (error && error.code === 1) {
      stopSharing("Location is blocked for this site. Allow it in your browser settings, then try again.");
    } else {
      showShareError("Your phone could not find its location. Still trying.");
    }
  }

  routePick.addEventListener("change", function () {
    routePick.dataset.touched = "yes";
    routeOther.hidden = routePick.value !== "__other";
  });

  $("share-start").addEventListener("click", function () {
    showShareError("");
    var route = routePick.value === "__other" ? routeOther.value.trim() : routePick.value;
    if (!route) { showShareError("Choose or type the route you are on."); return; }
    if (!("geolocation" in navigator)) {
      showShareError("This browser cannot share location. Try again on your phone's own browser.");
      return;
    }
    post("/api/riders/start", { route: route }).then(function (result) {
      if (!result.ok) { showShareError(result.data.error || "Could not start sharing."); return; }
      share.session = result.data.session;
      share.route = route;
      share.watch = navigator.geolocation.watchPosition(onPosition, onPositionError, {
        enableHighAccuracy: true,
        maximumAge: 5000,
        timeout: 30000,
      });
      keepScreenOn();
      renderShare();
    }).catch(function () { showShareError("Could not reach the server. Try again."); });
  });

  $("share-stop").addEventListener("click", function () { stopSharing(""); shareEl.hidden = true; });
  $("share-cancel").addEventListener("click", function () { shareEl.hidden = true; showShareError(""); });

  shareOpen.addEventListener("click", function () {
    infoEl.hidden = true;
    shareEl.hidden = !shareEl.hidden;
    renderShare();
  });

  window.addEventListener("pagehide", function () {
    if (share.session) post("/api/riders/stop", { session: share.session }, true).catch(function () {});
  });

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      poll();
      if (share.session && !share.wake) keepScreenOn();
    }
  });

  // ---------------------------------------------------------------- start

  fetch("/api/config", { cache: "no-store" })
    .then(function (response) { return response.json(); })
    .then(function (data) {
      config = data;
      map = new window.SimpleMap($("map"), {
        center: data.center,
        zoom: data.zoom,
        tileUrl: data.tileUrl,
        attribution: data.attribution,
      });
      renderRoutes();
      poll();
      setInterval(function () {
        if (document.visibilityState === "visible") poll();
      }, Math.max(5, data.refreshSeconds) * 1000);
    })
    .catch(function () { statusEl.textContent = "Could not load the map. Check your connection and reload."; });
})();
