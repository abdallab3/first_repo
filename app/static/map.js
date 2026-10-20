/* A small map: pan, zoom, map tiles and markers. It has no outside dependencies. */
(function () {
  "use strict";

  var TILE = 256;
  var MAX_LAT = 85.0511;

  function project(lat, lon, zoom) {
    var size = TILE * Math.pow(2, zoom);
    var s = Math.sin((Math.max(-MAX_LAT, Math.min(MAX_LAT, lat)) * Math.PI) / 180);
    return {
      x: ((lon + 180) / 360) * size,
      y: (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * size,
    };
  }

  function unproject(x, y, zoom) {
    var size = TILE * Math.pow(2, zoom);
    var n = Math.PI - (2 * Math.PI * y) / size;
    return {
      lat: (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n))),
      lon: (x / size) * 360 - 180,
    };
  }

  function SimpleMap(container, options) {
    this.container = container;
    this.tileUrl = options.tileUrl;
    this.minZoom = options.minZoom || 3;
    this.maxZoom = options.maxZoom || 18;
    this.lat = options.center[0];
    this.lon = options.center[1];
    this.zoom = Math.max(this.minZoom, Math.min(this.maxZoom, options.zoom));
    this.tiles = {};
    this.markers = [];
    this.pointers = {};
    this.pinch = null;
    this.scheduled = false;

    container.classList.add("sm-map");
    this.tilePane = document.createElement("div");
    this.tilePane.className = "sm-tiles";
    this.markerPane = document.createElement("div");
    this.markerPane.className = "sm-markers";
    container.appendChild(this.tilePane);
    container.appendChild(this.markerPane);

    var credit = document.createElement("p");
    credit.className = "sm-credit";
    credit.textContent = options.attribution || "";
    container.appendChild(credit);

    var controls = document.createElement("div");
    controls.className = "sm-zoom";
    var self = this;
    [["+", "Zoom in", 1], ["−", "Zoom out", -1]].forEach(function (spec) {
      var button = document.createElement("button");
      button.type = "button";
      button.textContent = spec[0];
      button.setAttribute("aria-label", spec[1]);
      button.addEventListener("click", function () {
        self.zoomAbout(self.zoom + spec[2], self.width() / 2, self.height() / 2);
      });
      controls.appendChild(button);
    });
    container.appendChild(controls);

    container.tabIndex = 0;
    container.setAttribute("role", "application");
    container.setAttribute("aria-label", "Map of buses. Use the arrow keys to move and plus or minus to zoom.");
    this.bind();
    this.schedule();
  }

  SimpleMap.prototype.width = function () { return this.container.clientWidth || 1; };
  SimpleMap.prototype.height = function () { return this.container.clientHeight || 1; };

  SimpleMap.prototype.schedule = function () {
    var self = this;
    if (this.scheduled) return;
    this.scheduled = true;
    requestAnimationFrame(function () {
      self.scheduled = false;
      self.render();
    });
  };

  SimpleMap.prototype.setView = function (lat, lon, zoom) {
    this.lat = Math.max(-MAX_LAT, Math.min(MAX_LAT, lat));
    this.lon = lon;
    if (zoom !== undefined) this.zoom = Math.max(this.minZoom, Math.min(this.maxZoom, zoom));
    this.schedule();
  };

  SimpleMap.prototype.panBy = function (dx, dy) {
    var c = project(this.lat, this.lon, this.zoom);
    var p = unproject(c.x - dx, c.y - dy, this.zoom);
    this.setView(p.lat, p.lon);
  };

  // Zoom while keeping the point under (sx, sy) in place.
  SimpleMap.prototype.zoomAbout = function (zoom, sx, sy) {
    zoom = Math.max(this.minZoom, Math.min(this.maxZoom, zoom));
    var c = project(this.lat, this.lon, this.zoom);
    var under = unproject(c.x - this.width() / 2 + sx, c.y - this.height() / 2 + sy, this.zoom);
    var u = project(under.lat, under.lon, zoom);
    var center = unproject(u.x - (sx - this.width() / 2), u.y - (sy - this.height() / 2), zoom);
    this.zoom = zoom;
    this.setView(center.lat, center.lon);
  };

  SimpleMap.prototype.addMarker = function (element, lat, lon) {
    var marker = { el: element, lat: lat, lon: lon, hidden: false };
    element.classList.add("sm-marker");
    this.markerPane.appendChild(element);
    this.markers.push(marker);
    this.schedule();
    var map = this;
    return {
      el: element,
      setLatLng: function (a, b) { marker.lat = a; marker.lon = b; map.schedule(); },
      setHidden: function (hidden) { marker.hidden = hidden; element.hidden = hidden; },
      remove: function () {
        map.markers = map.markers.filter(function (m) { return m !== marker; });
        element.remove();
      },
    };
  };

  SimpleMap.prototype.render = function () {
    var w = this.width();
    var h = this.height();
    var z0 = Math.max(0, Math.min(19, Math.round(this.zoom)));
    var scale = Math.pow(2, this.zoom - z0);
    var shown = TILE * scale;
    var c0 = project(this.lat, this.lon, z0);
    var count = Math.pow(2, z0);
    var x1 = Math.floor((c0.x - w / 2 / scale) / TILE);
    var x2 = Math.floor((c0.x + w / 2 / scale) / TILE);
    var y1 = Math.floor((c0.y - h / 2 / scale) / TILE);
    var y2 = Math.floor((c0.y + h / 2 / scale) / TILE);
    var keep = {};
    for (var tx = x1; tx <= x2; tx++) {
      for (var ty = y1; ty <= y2; ty++) {
        if (ty < 0 || ty >= count) continue;
        var wrapped = ((tx % count) + count) % count;
        var key = z0 + "/" + tx + "/" + ty;
        keep[key] = true;
        var img = this.tiles[key];
        if (!img) {
          img = document.createElement("img");
          img.alt = "";
          img.draggable = false;
          img.className = "sm-tile";
          img.addEventListener("error", function () { this.style.visibility = "hidden"; });
          img.src = this.tileUrl
            .replace("{z}", z0)
            .replace("{x}", wrapped)
            .replace("{y}", ty)
            .replace("{s}", "a");
          this.tilePane.appendChild(img);
          this.tiles[key] = img;
        }
        img.style.width = shown + "px";
        img.style.height = shown + "px";
        img.style.transform =
          "translate(" + ((tx * TILE - c0.x) * scale + w / 2) + "px," + ((ty * TILE - c0.y) * scale + h / 2) + "px)";
      }
    }
    for (var k in this.tiles) {
      if (!keep[k]) {
        this.tiles[k].remove();
        delete this.tiles[k];
      }
    }
    var c = project(this.lat, this.lon, this.zoom);
    for (var i = 0; i < this.markers.length; i++) {
      var m = this.markers[i];
      var p = project(m.lat, m.lon, this.zoom);
      m.el.style.transform = "translate(" + (p.x - c.x + w / 2) + "px," + (p.y - c.y + h / 2) + "px)";
    }
  };

  SimpleMap.prototype.bind = function () {
    var self = this;
    var el = this.container;

    el.addEventListener("pointerdown", function (e) {
      if (e.target.closest && e.target.closest(".sm-zoom")) return;
      self.pointers[e.pointerId] = { x: e.clientX, y: e.clientY, moved: 0 };
      if (Object.keys(self.pointers).length === 2) {
        var ids = Object.keys(self.pointers);
        var a = self.pointers[ids[0]];
        var b = self.pointers[ids[1]];
        self.pinch = { dist: Math.hypot(a.x - b.x, a.y - b.y), zoom: self.zoom };
      }
    });

    el.addEventListener("pointermove", function (e) {
      var p = self.pointers[e.pointerId];
      if (!p) return;
      var dx = e.clientX - p.x;
      var dy = e.clientY - p.y;
      var ids = Object.keys(self.pointers);
      if (ids.length >= 2 && self.pinch) {
        var a = self.pointers[ids[0]];
        var b = self.pointers[ids[1]];
        p.x = e.clientX;
        p.y = e.clientY;
        var dist = Math.hypot(a.x - b.x, a.y - b.y);
        var rect = el.getBoundingClientRect();
        var midX = (a.x + b.x) / 2 - rect.left;
        var midY = (a.y + b.y) / 2 - rect.top;
        if (self.pinch.dist > 0 && dist > 0) {
          self.zoomAbout(self.pinch.zoom + Math.log(dist / self.pinch.dist) / Math.LN2, midX, midY);
        }
        return;
      }
      p.moved += Math.abs(dx) + Math.abs(dy);
      if (p.moved > 6 && !el.hasPointerCapture(e.pointerId)) {
        try { el.setPointerCapture(e.pointerId); } catch (err) { /* the pointer is already gone */ }
        el.classList.add("sm-dragging");
      }
      if (p.moved > 6) {
        self.panBy(dx, dy);
        p.x = e.clientX;
        p.y = e.clientY;
      }
    });

    function end(e) {
      delete self.pointers[e.pointerId];
      if (Object.keys(self.pointers).length < 2) self.pinch = null;
      if (!Object.keys(self.pointers).length) el.classList.remove("sm-dragging");
    }
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);

    el.addEventListener("wheel", function (e) {
      e.preventDefault();
      var rect = el.getBoundingClientRect();
      var step = e.deltaMode === 1 ? e.deltaY * 0.05 : e.deltaY * 0.0025;
      self.zoomAbout(self.zoom - step, e.clientX - rect.left, e.clientY - rect.top);
    }, { passive: false });

    el.addEventListener("dblclick", function (e) {
      if (e.target.closest && e.target.closest(".sm-marker, .sm-zoom")) return;
      var rect = el.getBoundingClientRect();
      self.zoomAbout(self.zoom + 1, e.clientX - rect.left, e.clientY - rect.top);
    });

    el.addEventListener("keydown", function (e) {
      if (e.target !== el) return;
      var step = 80;
      var handled = true;
      if (e.key === "ArrowLeft") self.panBy(step, 0);
      else if (e.key === "ArrowRight") self.panBy(-step, 0);
      else if (e.key === "ArrowUp") self.panBy(0, step);
      else if (e.key === "ArrowDown") self.panBy(0, -step);
      else if (e.key === "+" || e.key === "=") self.zoomAbout(self.zoom + 1, self.width() / 2, self.height() / 2);
      else if (e.key === "-") self.zoomAbout(self.zoom - 1, self.width() / 2, self.height() / 2);
      else handled = false;
      if (handled) e.preventDefault();
    });

    window.addEventListener("resize", function () { self.schedule(); });
  };

  window.SimpleMap = SimpleMap;
})();
