/* Stash front end. No framework, no build step. Every URL is relative so it
   works behind Home Assistant's ingress path. */

(function () {
  "use strict";

  var S = {
    data: null,          // /api/state
    places: {},          // id -> place summary
    tab: "find",
    query: "",
    results: null,
    searchSeq: 0,
    nav: { place: null, cell: null },
    stack: []            // sheet frames: {title, build(body)}
  };
  var $ = function (id) { return document.getElementById(id); };

  // ================================================================ basics

  function api(path, options) {
    options = options || {};
    var init = { method: options.method || "GET", headers: {} };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    return fetch(path, init).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) { throw new Error(data.error || ("Request failed: " + res.status)); }
        return data;
      });
    });
  }

  function toast(message) {
    var node = $("toast");
    node.textContent = message;
    node.hidden = false;
    clearTimeout(node._timer);
    node._timer = setTimeout(function () { node.hidden = true; }, 2800);
  }
  function fail(err) { toast(err.message || String(err)); }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }
  function button(className, text, onClick) {
    var node = el("button", className, text);
    node.type = "button";
    if (onClick) { node.addEventListener("click", onClick); }
    return node;
  }
  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } return node; }
  function qs(params) {
    var parts = [];
    for (var key in params) {
      if (params[key] !== null && params[key] !== undefined && params[key] !== "") {
        parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(params[key]));
      }
    }
    return parts.length ? "?" + parts.join("&") : "";
  }

  var ICONS = {
    room: '<path d="M4 11 12 4l8 7v9H4z"/><path d="M10 20v-5h4v5"/>',
    grid: '<rect x="3.5" y="4" width="17" height="16" rx="1"/><path d="M3.5 9.3h17M3.5 14.6h17M9.2 4v16M14.8 4v16"/>',
    area: '<rect x="3.5" y="5" width="17" height="14" rx="2" stroke-dasharray="3 2.4"/>',
    container: '<path d="M4 8.5h16V19a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z"/><path d="M3 5h18v3.5H3z"/><path d="M10 12h4"/>',
    cell: '<rect x="5" y="5" width="14" height="14" rx="1.5"/>',
    pin: '<path d="M12 21s6-5.2 6-10.2A6 6 0 0 0 6 10.8C6 15.8 12 21 12 21z"/><circle cx="12" cy="10.5" r="2"/>'
  };
  function icon(kind, className) {
    var span = el("span", className || "kind");
    span.innerHTML = '<svg viewBox="0 0 24 24" width="100%" height="100%" fill="none" stroke="currentColor" ' +
      'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + (ICONS[kind] || ICONS.area) + "</svg>";
    return span;
  }

  var KIND_LABELS = { room: "Room", grid: "Shelf wall", area: "Area", container: "Box" };

  // ================================================================ storage (per viewer)

  function recentSpots() {
    try { return JSON.parse(localStorage.getItem("stash.recent") || "[]"); } catch (e) { return []; }
  }
  function rememberSpot(spot) {
    try {
      var list = recentSpots().filter(function (s) {
        return !(s.place === spot.place && sameCell(s.cell, spot.cell));
      });
      list.unshift({ place: spot.place, cell: spot.cell || null });
      localStorage.setItem("stash.recent", JSON.stringify(list.slice(0, 5)));
    } catch (e) { /* private mode: no recents, nothing else lost */ }
  }

  // ================================================================ places, paths, cells

  function sameCell(a, b) {
    if (!a && !b) { return true; }
    if (!a || !b) { return false; }
    return Number(a.col) === Number(b.col) && Number(a.row) === Number(b.row);
  }
  function ordinal(n) {
    n = Number(n);
    var mod100 = n % 100, suffix = "th";
    if (mod100 < 10 || mod100 > 20) { suffix = { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"; }
    return n + suffix;
  }
  function cellLabel(grid, cell) {
    if (!cell) { return ""; }
    return ordinal(cell.col) + " from the " + (grid.count_cols_from || "left") + ", " +
      ordinal(cell.row) + " from the " + (grid.count_rows_from || "top");
  }
  // "14th from the right, 2nd from the top" → "14th from right · 2nd from top"
  function compactLabel(label) { return label.replace(/ the /g, " ").replace(", ", " · "); }

  function segmentsFor(placeId, cell) {
    var chain = [], seen = {}, node = S.places[placeId];
    while (node && !seen[node.id]) {
      seen[node.id] = true;
      chain.unshift(node);
      node = node.parent ? S.places[node.parent] : null;
    }
    var out = [];
    chain.forEach(function (p) {
      var parent = p.parent && S.places[p.parent];
      if (p.cell && parent && parent.kind === "grid") {
        out.push({ kind: "cell", label: cellLabel(parent, p.cell), id: parent.id, cell: p.cell });
      }
      out.push({ kind: p.kind, label: p.name, id: p.id });
    });
    var place = S.places[placeId];
    if (cell && place && place.kind === "grid") {
      out.push({ kind: "cell", label: cellLabel(place, cell), id: place.id, cell: cell });
    }
    return out;
  }
  function roots() {
    return (S.data.places || []).filter(function (p) { return !p.parent || !S.places[p.parent]; })
      .sort(byName);
  }
  function byName(a, b) { return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1; }
  // With one room for everything, leading every line with it is noise.
  function trimmed(segments) {
    if (segments.length > 1 && roots().length === 1 && segments[0].id === roots()[0].id) {
      return segments.slice(1);
    }
    return segments;
  }
  function shortText(segments) {
    return trimmed(segments).map(function (s) {
      return s.kind === "cell" ? compactLabel(s.label) : s.label;
    }).join(" › ");
  }
  function childrenAt(placeId, cell, anyCell) {
    return (S.data.places || []).filter(function (p) {
      if ((p.parent || null) !== (placeId || null)) { return false; }
      return anyCell || sameCell(p.cell, cell);
    }).sort(function (a, b) {
      if ((a.kind === "container") !== (b.kind === "container")) { return a.kind === "container" ? 1 : -1; }
      return byName(a, b);
    });
  }
  function descendantsOf(placeId) {
    var out = {}, frontier = [placeId];
    while (frontier.length) {
      var current = frontier.pop();
      (S.data.places || []).forEach(function (p) {
        if (p.parent === current && !out[p.id]) { out[p.id] = true; frontier.push(p.id); }
      });
    }
    return out;
  }

  // ================================================================ data

  function refresh() {
    return api("api/state").then(function (data) {
      S.data = data;
      S.places = {};
      data.places.forEach(function (p) { S.places[p.id] = p; });
      if (S.nav.place && !S.places[S.nav.place]) { S.nav = { place: null, cell: null }; }
    });
  }

  function afterChange() {
    return refresh().then(function () {
      renderTab();
      renderSheet();
    }).catch(fail);
  }

  // ================================================================ tabs

  function switchTab(name) {
    S.tab = name;
    ["find", "places"].forEach(function (tab) { $("view-" + tab).hidden = tab !== name; });
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (b) {
      b.classList.toggle("is-active", b.dataset.tab === name);
      b.setAttribute("aria-selected", b.dataset.tab === name ? "true" : "false");
    });
    renderTab();
    window.scrollTo(0, 0);
  }

  function renderTab() {
    if (!S.data) { return; }
    if (S.tab === "find") { renderFind(); } else { renderPlaces(); }
  }

  function goTo(placeId, cell) {
    S.nav = { place: placeId || null, cell: cell || null };
    closeAll();
    switchTab("places");
  }

  // ================================================================ find

  function runSearch() {
    var query = S.query.trim();
    var seq = ++S.searchSeq;
    if (!query) { S.results = null; renderFind(); return; }
    api("api/search" + qs({ q: query })).then(function (res) {
      if (seq !== S.searchSeq) { return; }  // a newer keystroke won
      S.results = res;
      renderFind();
    }).catch(fail);
  }

  function itemRow(item) {
    var row = button("item-row", null, function () { openItem(item.id); });
    var head = el("div", "item-head");
    head.appendChild(el("span", "name", item.name));
    if (item.total !== null && item.total !== undefined) {
      head.appendChild(el("span", "total", "×" + item.total + (item.uncounted ? "+" : "")));
    }
    row.appendChild(head);
    var where = el("ul", "where");
    if (!item.locations.length) {
      where.appendChild(el("li", "unplaced", "Not put anywhere yet"));
    }
    item.locations.forEach(function (loc) {
      var li = el("li", loc.missing ? "missing" : "");
      li.appendChild(icon("pin", "pin"));
      li.appendChild(el("span", "text", shortText(loc.path)));
      if (loc.qty !== null && loc.qty !== undefined && item.locations.length > 1) {
        li.appendChild(el("span", "q", "×" + loc.qty));
      }
      where.appendChild(li);
    });
    row.appendChild(where);
    return row;
  }

  function placeRow(place, onClick, sub) {
    var row = button("place-row", null, onClick);
    row.appendChild(icon(place.kind));
    var grow = el("span", "grow");
    grow.appendChild(el("span", "name", place.name));
    var subText = sub !== undefined ? sub : (place.cell_label ? compactLabel(place.cell_label) : KIND_LABELS[place.kind]);
    if (subText) { grow.appendChild(el("span", "sub", subText)); }
    row.appendChild(grow);
    if (place.count) { row.appendChild(el("span", "count", String(place.count))); }
    row.appendChild(el("span", "chev", "›"));
    return row;
  }

  function renderFind() {
    var list = clear($("find-list")), placesBox = clear($("find-places")), meta = $("find-meta");
    var sum = S.data.summary;
    if (!S.results) {
      meta.textContent = sum.items
        ? sum.items + (sum.items === 1 ? " thing" : " things") + " in " + sum.locations +
          (sum.locations === 1 ? " spot" : " spots") + (sum.unplaced ? " · " + sum.unplaced + " not put anywhere" : "")
        : "";
      if (!S.data.items.length) {
        var empty = el("div", "empty");
        empty.appendChild(el("strong", null, "Nothing here yet"));
        empty.appendChild(document.createTextNode("Add your first thing, or open Places to set up your shelves first."));
        list.appendChild(empty);
        return;
      }
      var groups = {}, order = [];
      S.data.items.forEach(function (item) {
        var key = item.category || "";
        if (!groups[key]) { groups[key] = []; order.push(key); }
        groups[key].push(item);
      });
      order.sort(function (a, b) {
        if (!a) { return 1; }
        if (!b) { return -1; }
        return a.toLowerCase() < b.toLowerCase() ? -1 : 1;
      });
      order.forEach(function (key) {
        list.appendChild(el("div", "list-title", (key || "Uncategorised") + " · " + groups[key].length));
        var box = el("div", "list");
        groups[key].forEach(function (item) { box.appendChild(itemRow(item)); });
        list.appendChild(box);
      });
      return;
    }
    var res = S.results;
    meta.textContent = res.items.length
      ? res.items.length + (res.items.length === 1 ? " match" : " matches")
      : "";
    if (res.places.length) {
      placesBox.appendChild(el("div", "list-title", "Places"));
      var pbox = el("div", "list");
      res.places.forEach(function (p) {
        var sub = p.path.split(" › ").slice(0, -1).join(" › ");
        pbox.appendChild(placeRow(p, function () { goTo(p.id); }, sub || KIND_LABELS[p.kind]));
      });
      placesBox.appendChild(pbox);
    }
    if (!res.items.length) {
      var none = el("div", "empty");
      none.appendChild(el("strong", null, "Nothing called “" + S.query.trim() + "”"));
      var add = button("filled", "Add “" + S.query.trim() + "”", function () {
        openItemEditor({ name: S.query.trim() });
      });
      none.appendChild(el("div", null, ""));
      none.appendChild(add);
      list.appendChild(none);
      return;
    }
    if (res.places.length) { list.appendChild(el("div", "list-title", "Things")); }
    var box2 = el("div", "list");
    res.items.forEach(function (item) { box2.appendChild(itemRow(item)); });
    list.appendChild(box2);
  }

  // ================================================================ places tab

  function renderCrumbs(container, segments, onTap) {
    clear(container);
    var all = [{ kind: "root", label: "Everything", id: null }].concat(segments);
    all.forEach(function (seg, i) {
      if (i) { container.appendChild(el("span", "crumb-sep", "›")); }
      var last = i === all.length - 1;
      var label = seg.kind === "cell" ? compactLabel(seg.label) : seg.label;
      var crumb = button("crumb" + (last ? " is-here" : ""), label, last ? null : function () {
        onTap(seg.id, seg.kind === "cell" ? seg.cell : null);
      });
      container.appendChild(crumb);
    });
    // Keep the end of a long trail in view.
    container.scrollLeft = container.scrollWidth;
  }

  function renderPlaces() {
    var body = $("place-body");
    var nav = S.nav;
    if (!nav.place) {
      renderCrumbs($("crumbs"), [], navigate);
      clear(body);
      var list = roots();
      if (!list.length) {
        var empty = el("div", "empty");
        empty.appendChild(el("strong", null, "No places yet"));
        empty.appendChild(document.createTextNode("Start with a room — the man cave, the garage — then add the shelves in it."));
        body.appendChild(empty);
      } else {
        var box = el("div", "list");
        list.forEach(function (p) { box.appendChild(placeRow(p, function () { navigate(p.id); })); });
        body.appendChild(box);
      }
      var actions = el("div", "actions");
      actions.appendChild(button("outlined", "Add a room", function () {
        openPlaceEditor({ kind: "room", parent: null });
      }));
      body.appendChild(actions);
      var unplaced = S.data.items.filter(function (i) { return !i.locations.length; });
      if (unplaced.length) {
        body.appendChild(el("div", "list-title", "Not put anywhere · " + unplaced.length));
        var ubox = el("div", "list");
        unplaced.forEach(function (item) { ubox.appendChild(itemRow(item)); });
        body.appendChild(ubox);
      }
      return;
    }
    var requested = nav.place + JSON.stringify(nav.cell);
    api("api/places/" + encodeURIComponent(nav.place) + qs(nav.cell ? nav.cell : {})).then(function (view) {
      if (requested !== S.nav.place + JSON.stringify(S.nav.cell)) { return; }
      drawPlace(view);
    }).catch(function (err) {
      S.nav = { place: null, cell: null };
      fail(err);
      renderPlaces();
    });
  }

  function navigate(placeId, cell) {
    S.nav = { place: placeId || null, cell: cell || null };
    renderPlaces();
    window.scrollTo(0, 0);
  }

  function drawPlace(view) {
    var body = clear($("place-body"));
    var place = view.place;
    renderCrumbs($("crumbs"), view.path, navigate);

    var card = el("div", "card");
    var head = el("div", "place-head");
    head.appendChild(icon(view.cell ? "cell" : place.kind));
    var grow = el("div", "grow");
    if (view.cell) {
      grow.appendChild(el("h1", null, view.cell_label.charAt(0).toUpperCase() + view.cell_label.slice(1)));
      grow.appendChild(el("div", "sub", "Compartment in " + place.name));
    } else {
      grow.appendChild(el("h1", null, place.name));
      var sub = KIND_LABELS[place.kind];
      if (place.kind === "grid") { sub += " · " + place.cols + " × " + place.rows; }
      if (place.cell_label) { sub += " · " + compactLabel(place.cell_label); }
      grow.appendChild(el("div", "sub", sub));
      if (place.notes) { grow.appendChild(el("div", "notes", place.notes)); }
    }
    head.appendChild(grow);
    card.appendChild(head);

    var actions = el("div", "place-actions");
    var spot = { place: place.id, cell: view.cell };
    actions.appendChild(button("filled", "Add thing here", function () {
      openItemEditor({ spot: spot });
    }));
    var isGridTop = place.kind === "grid" && !view.cell;
    if (!isGridTop) {
      actions.appendChild(button("outlined", place.kind === "room" ? "Add place" : "Add box", function () {
        openPlaceEditor({
          kind: place.kind === "room" ? "grid" : "container",
          parent: place.id,
          cell: view.cell
        });
      }));
    }
    if (!view.cell) {
      actions.appendChild(button("outlined", "Edit", function () { openPlaceEditor(S.places[place.id]); }));
    }
    card.appendChild(actions);

    if (view.grid) {
      card.appendChild(drawWall(place, view.grid.cells, {
        onTap: function (cell) { navigate(place.id, cell); }
      }));
    }
    body.appendChild(card);

    if (view.children.length) {
      body.appendChild(el("div", "list-title", view.cell ? "In this compartment" : (isGridTop ? "On the wall, no compartment" : "Inside")));
      var box = el("div", "list");
      view.children.forEach(function (c) {
        box.appendChild(placeRow(c, function () { navigate(c.id); }, view.cell ? KIND_LABELS[c.kind] : undefined));
      });
      body.appendChild(box);
    }
    if (view.items.length) {
      body.appendChild(el("div", "list-title", (view.children.length ? "Loose · " : "Things · ") + view.items.length));
      var list = el("div", "list");
      view.items.forEach(function (row) {
        var line = el("div", "thing-row");
        var main = button("main", null, function () { openItem(row.item_id); });
        main.appendChild(el("span", "name", row.name));
        var bits = [];
        if (row.note) { bits.push(row.note); }
        if (row.elsewhere) { bits.push("also in " + row.elsewhere + (row.elsewhere === 1 ? " other place" : " other places")); }
        if (bits.length) { main.appendChild(el("span", "sub", bits.join(" · "))); }
        line.appendChild(main);
        line.appendChild(stepper(row.item_id, row.location_id, row.qty));
        list.appendChild(line);
      });
      body.appendChild(list);
    }
    if (!view.children.length && !view.items.length && !view.grid) {
      var empty = el("div", "empty");
      empty.appendChild(el("strong", null, "Empty"));
      empty.appendChild(document.createTextNode("Nothing has been put here yet."));
      body.appendChild(empty);
    }
  }

  // ================================================================ the wall

  function drawWall(grid, cells, opts) {
    opts = opts || {};
    var cols = Number(grid.cols), rows = Number(grid.rows);
    var fromRight = grid.count_cols_from === "right", fromBottom = grid.count_rows_from === "bottom";
    var scroll = el("div", "wall-scroll");
    var wall = el("div", "wall");
    wall.style.gridTemplateColumns = "18px repeat(" + cols + ", minmax(0, 1fr))";
    wall.style.minWidth = (22 + cols * 42) + "px";
    wall.style.maxWidth = (22 + cols * 76) + "px";

    wall.appendChild(el("span", "corner", ""));
    for (var x = 1; x <= cols; x++) {
      wall.appendChild(el("span", "axis", String(fromRight ? cols - x + 1 : x)));
    }
    for (var y = 1; y <= rows; y++) {
      wall.appendChild(el("span", "axis row", String(fromBottom ? rows - y + 1 : y)));
      for (var x2 = 1; x2 <= cols; x2++) {
        var cell = { col: fromRight ? cols - x2 + 1 : x2, row: fromBottom ? rows - y + 1 : y };
        wall.appendChild(cellBox(grid, cell, (cells || {})[cell.col + "," + cell.row], opts));
      }
    }
    scroll.appendChild(wall);
    var holder = el("div");
    holder.appendChild(scroll);
    holder.appendChild(el("div", "wall-legend",
      "Numbered from the " + (grid.count_cols_from || "left") + " and from the " +
      (grid.count_rows_from || "top") + ". Tap a compartment."));
    if (fromRight) {
      requestAnimationFrame(function () { scroll.scrollLeft = scroll.scrollWidth; });
    }
    return holder;
  }

  function cellBox(grid, cell, entry, opts) {
    var box = button("cellbox", null, function () { opts.onTap(cell); });
    var count = entry ? entry.items : 0;
    if (count || (entry && entry.containers.length)) { box.classList.add("has-stuff"); }
    if (opts.selected && sameCell(opts.selected, cell)) { box.classList.add("is-selected"); }
    box.appendChild(el("span", "n", count ? String(count) : ""));
    var names = [];
    if (entry) {
      entry.containers.forEach(function (c) { names.push(c.name); });
      if (!names.length) { names = entry.names.slice(0, 2); }
    }
    box.appendChild(el("span", "box-name", names.join(", ")));
    var label = cellLabel(grid, cell) + (count ? ": " + count + " things" : ": empty") +
      (names.length ? " (" + names.join(", ") + ")" : "");
    box.setAttribute("aria-label", label);
    box.title = label;
    return box;
  }

  // ================================================================ quantity stepper

  function stepper(itemId, locationId, qty) {
    var wrap = el("div", "qty" + (qty === null || qty === undefined ? " is-unknown" : (qty === 0 ? " is-zero" : "")));
    var minus = button("step", "−", function () { step(itemId, locationId, -1); });
    minus.setAttribute("aria-label", "One less");
    minus.disabled = qty === null || qty === undefined || qty === 0;
    var plus = button("step", "+", function () { step(itemId, locationId, 1); });
    plus.setAttribute("aria-label", "One more");
    var value = el("span", "qty-value", qty === null || qty === undefined ? "?" : String(qty));
    value.title = qty === null || qty === undefined ? "Not counted" : qty + " here";
    wrap.appendChild(minus);
    wrap.appendChild(value);
    wrap.appendChild(plus);
    return wrap;
  }
  function step(itemId, locationId, delta) {
    api("api/items/" + encodeURIComponent(itemId) + "/locations/" + encodeURIComponent(locationId) + "/step",
      { method: "POST", body: { delta: delta } }).then(afterChange).catch(fail);
  }

  // ================================================================ sheet stack

  function openSheet(frame) {
    S.stack.push(frame);
    $("sheet").hidden = false;
    renderSheet(true);
  }
  function replaceSheet(frame) {
    S.stack.pop();
    openSheet(frame);
  }
  function closeTop() {
    S.stack.pop();
    if (!S.stack.length) { $("sheet").hidden = true; return; }
    renderSheet(true);
  }
  function closeAll() {
    S.stack = [];
    $("sheet").hidden = true;
  }
  function renderSheet(scrollTop) {
    if (!S.stack.length) { return; }
    var frame = S.stack[S.stack.length - 1];
    $("sheet-title").textContent = frame.title || "";
    $("sheet-back").hidden = S.stack.length < 2;
    var body = clear($("sheet-body"));
    frame.build(body, frame);
    if (scrollTop) { document.querySelector(".sheet-panel").scrollTop = 0; }
  }

  // ================================================================ item detail

  function openItem(itemId) {
    var frame = { title: "", build: null };
    frame.build = function (body) {
      api("api/items/" + encodeURIComponent(itemId)).then(function (item) {
        if (S.stack[S.stack.length - 1] !== frame) { return; }
        frame.title = item.name;
        $("sheet-title").textContent = item.name;
        drawItem(clear(body), item);
      }).catch(function (err) { fail(err); closeTop(); });
    };
    openSheet(frame);
  }

  function pathNode(segments) {
    var node = el("div", "path");
    trimmed(segments).forEach(function (seg, i) {
      if (i) { node.appendChild(el("span", "sep", "›")); }
      if (seg.kind === "missing") {
        node.appendChild(el("span", "seg danger", seg.label));
        return;
      }
      // A span, not a <button>: buttons will not wrap mid-label, and
      // "14th from the right, 2nd from the top" needs to.
      var link = el("span", "seg link" + (seg.kind === "cell" ? " cell" : ""), seg.label);
      link.setAttribute("role", "link");
      link.tabIndex = 0;
      var open = function () { goTo(seg.id, seg.kind === "cell" ? seg.cell : null); };
      link.addEventListener("click", open);
      link.addEventListener("keydown", function (e) { if (e.key === "Enter") { open(); } });
      node.appendChild(link);
    });
    return node;
  }

  function drawItem(body, item) {
    var meta = el("div", "detail-meta");
    if (item.category) { meta.appendChild(el("span", "tag", item.category)); }
    item.tags.forEach(function (t) { meta.appendChild(el("span", "tag", "#" + t)); });
    if (meta.childNodes.length) { body.appendChild(meta); }
    if (item.notes) { body.appendChild(el("p", "detail-notes", item.notes)); }

    var total = item.total !== null ? " · " + item.total + (item.uncounted ? "+" : "") + " in total" : "";
    body.appendChild(el("h3", null, (item.locations.length === 1 ? "1 place" : item.locations.length + " places") + total));
    if (!item.locations.length) {
      body.appendChild(el("p", "detail-notes", "Not put anywhere yet."));
    }
    item.locations.forEach(function (loc) {
      var card = el("div", "loc-card");
      var grow = el("div", "grow");
      grow.appendChild(pathNode(loc.path));
      if (loc.note) { grow.appendChild(el("div", "note", loc.note)); }
      card.appendChild(grow);
      var controls = el("div", "controls");
      controls.appendChild(stepper(item.id, loc.id, loc.qty));
      var more = button("more", "⋯", function () { openLocationMenu(item, loc); });
      more.setAttribute("aria-label", "Move, note or remove");
      controls.appendChild(more);
      card.appendChild(controls);
      body.appendChild(card);
    });

    var actions = el("div", "actions");
    actions.appendChild(button("filled", "Also somewhere else", function () {
      pickSpot({
        title: "Where else?",
        onPick: function (spot) {
          api("api/items/" + encodeURIComponent(item.id) + "/locations",
            { method: "POST", body: { place: spot.place, cell: spot.cell, qty: 1 } })
            .then(function () { toast("Added"); return afterChange(); }).catch(fail);
        }
      });
    }));
    actions.appendChild(button("outlined", "Edit", function () {
      openItemEditor({ id: item.id, name: item.name, category: item.category,
                       tags: item.tags.join(", "), notes: item.notes });
    }));
    body.appendChild(actions);
    var danger = el("div", "actions");
    danger.appendChild(confirmButton("text-button danger", "Delete " + item.name, function () {
      api("api/items/" + encodeURIComponent(item.id), { method: "DELETE" }).then(function () {
        toast("Deleted " + item.name);
        closeAll();
        S.results = null;
        return afterChange().then(runSearch);
      }).catch(fail);
    }));
    body.appendChild(danger);
  }

  /* No window.confirm(): it blocks the panel and looks foreign inside HA. A
     second tap within a few seconds confirms instead. */
  function confirmButton(className, label, onConfirm) {
    var armed = false, timer = null;
    var node = button(className, label, function () {
      if (armed) { clearTimeout(timer); onConfirm(); return; }
      armed = true;
      node.textContent = "Tap again to confirm";
      timer = setTimeout(function () { armed = false; node.textContent = label; }, 3500);
    });
    return node;
  }

  function openLocationMenu(item, loc) {
    openSheet({
      title: item.name,
      build: function (body) {
        body.appendChild(pathNode(loc.path));
        var form = el("div");
        form.style.marginTop = "12px";
        var two = el("div", "two");
        var qtyLabel = el("label", null, "How many here");
        var qtyInput = el("input");
        qtyInput.type = "number"; qtyInput.min = "0"; qtyInput.inputMode = "numeric";
        qtyInput.placeholder = "Not counted";
        qtyInput.value = loc.qty === null || loc.qty === undefined ? "" : String(loc.qty);
        qtyLabel.appendChild(qtyInput);
        two.appendChild(qtyLabel);
        form.appendChild(two);
        var noteLabel = el("label", null, "Note for this spot");
        var noteInput = el("input");
        noteInput.type = "text"; noteInput.value = loc.note || ""; noteInput.placeholder = "2 m, braided";
        noteLabel.appendChild(noteInput);
        form.appendChild(noteLabel);
        body.appendChild(form);

        var url = "api/items/" + encodeURIComponent(item.id) + "/locations/" + encodeURIComponent(loc.id);
        var actions = el("div", "actions");
        actions.appendChild(button("filled", "Save", function () {
          api(url, { method: "POST", body: { qty: qtyInput.value, note: noteInput.value } })
            .then(function () { closeTop(); return afterChange(); }).catch(fail);
        }));
        actions.appendChild(button("outlined", "Move…", function () {
          pickSpot({
            title: "Move to",
            initial: { place: loc.place, cell: loc.cell },
            onPick: function (spot) {
              api(url, { method: "POST", body: { place: spot.place, cell: spot.cell } })
                .then(function () { toast("Moved"); closeTop(); return afterChange(); }).catch(fail);
            }
          });
        }));
        body.appendChild(actions);
        var danger = el("div", "actions");
        danger.appendChild(confirmButton("text-button danger", "Not here any more", function () {
          api(url, { method: "DELETE" }).then(function () { closeTop(); return afterChange(); }).catch(fail);
        }));
        body.appendChild(danger);
      }
    });
  }

  // ================================================================ item editor

  function field(labelText, input) {
    var label = el("label", null, labelText);
    label.appendChild(input);
    return label;
  }
  function textInput(value, placeholder, onInput) {
    var input = el("input");
    input.type = "text";
    input.value = value || "";
    if (placeholder) { input.placeholder = placeholder; }
    input.addEventListener("input", function () { onInput(input.value); });
    return input;
  }

  function spotButton(spot, onTap, emptyText) {
    var b = button("spot-button", null, onTap);
    b.appendChild(icon("pin", "kind"));
    var grow = el("span", "grow");
    if (spot && spot.place) {
      grow.textContent = shortText(segmentsFor(spot.place, spot.cell));
    } else {
      grow.appendChild(el("span", "placeholder", emptyText || "Choose where it is"));
    }
    b.appendChild(grow);
    b.appendChild(el("span", "cue", spot && spot.place ? "Change" : "Choose"));
    return b;
  }

  function openItemEditor(seed) {
    var isNew = !seed.id;
    var draft = {
      id: seed.id || null,
      name: seed.name || "",
      category: seed.category || "",
      tags: seed.tags || "",
      notes: seed.notes || "",
      spot: seed.spot || null,
      qty: seed.qty === undefined ? "1" : seed.qty
    };
    var frame = { title: isNew ? "New thing" : "Edit " + draft.name };
    frame.build = function (body) {
      var name = textInput(draft.name, "USB-C cable", function (v) { draft.name = v; });
      body.appendChild(field("Name", name));

      var category = textInput(draft.category, "Cables", function (v) { draft.category = v; drawChips(); });
      category.setAttribute("list", "stash-categories");
      var datalist = el("datalist");
      datalist.id = "stash-categories";
      S.data.categories.forEach(function (c) { var o = el("option"); o.value = c; datalist.appendChild(o); });
      var catLabel = field("Category", category);
      catLabel.appendChild(datalist);
      body.appendChild(catLabel);
      var chips = el("div", "chips");
      function drawChips() {
        clear(chips);
        S.data.categories.slice(0, 14).forEach(function (c) {
          chips.appendChild(button("chip" + (c === draft.category ? " is-on" : ""), c, function () {
            draft.category = c; category.value = c; drawChips();
          }));
        });
      }
      drawChips();
      if (S.data.categories.length) { body.appendChild(chips); }

      if (isNew) {
        body.appendChild(el("div", "field-label", "Where is it"));
        body.appendChild(spotButton(draft.spot, function () {
          pickSpot({
            title: "Where is it?",
            initial: draft.spot,
            onPick: function (spot) { draft.spot = spot; }
          });
        }, "Choose where it is (or leave for later)"));
        var qty = el("input");
        qty.type = "number"; qty.min = "0"; qty.inputMode = "numeric";
        qty.placeholder = "Not counted";
        qty.value = draft.qty;
        qty.addEventListener("input", function () { draft.qty = qty.value; });
        var two = el("div", "two");
        two.appendChild(field("How many there", qty));
        var tagsInput = textInput(draft.tags, "usb, charging", function (v) { draft.tags = v; });
        two.appendChild(field("Tags", tagsInput));
        body.appendChild(two);
      } else {
        body.appendChild(field("Tags", textInput(draft.tags, "usb, charging", function (v) { draft.tags = v; })));
      }
      var notes = el("textarea");
      notes.value = draft.notes;
      notes.placeholder = "Anything worth knowing";
      notes.addEventListener("input", function () { draft.notes = notes.value; });
      body.appendChild(field("Notes", notes));

      function save(again) {
        if (!draft.name.trim()) { toast("Give it a name"); name.focus(); return; }
        var payload = { name: draft.name, category: draft.category, tags: draft.tags, notes: draft.notes };
        if (draft.id) { payload.id = draft.id; }
        if (isNew && draft.spot) {
          payload.locations = [{ place: draft.spot.place, cell: draft.spot.cell, qty: draft.qty }];
        }
        api("api/items", { method: "POST", body: payload }).then(function (item) {
          toast((isNew ? "Saved " : "Updated ") + item.name);
          if (again) {
            draft.name = ""; draft.notes = ""; draft.tags = ""; draft.qty = "1";
            return afterChange().then(function () {
              var first = document.querySelector("#sheet-body input");
              if (first) { first.focus(); }
            });
          }
          closeTop();
          return afterChange().then(function () { if (S.query) { runSearch(); } });
        }).catch(fail);
      }
      var actions = el("div", "actions");
      actions.appendChild(button("filled", "Save", function () { save(false); }));
      if (isNew) { actions.appendChild(button("outlined", "Save & add another", function () { save(true); })); }
      body.appendChild(actions);
      if (isNew && !draft.name) { setTimeout(function () { name.focus(); }, 60); }
    };
    openSheet(frame);
  }

  // ================================================================ spot picker

  /* Walks the tree inside the sheet: rooms → walls → a compartment → a box.
     "Put it here" is offered at every level, so "somewhere behind the left
     Kallax" is as valid an answer as a specific box. */
  function pickSpot(opts) {
    var at = { place: null, cell: null };
    if (opts.initial && opts.initial.place && S.places[opts.initial.place]) {
      at = { place: opts.initial.place, cell: opts.initial.cell || null };
    }
    var exclude = opts.exclude || {};
    var frame = { title: opts.title || "Where?" };
    var gridCache = {};

    function go(placeId, cell) { at = { place: placeId || null, cell: cell || null }; renderSheet(true); }
    function pick() {
      var spot = { place: at.place, cell: at.cell };
      rememberSpot(spot);
      // Hand the answer over before the frame below re-renders, so it shows it.
      S.stack.pop();
      opts.onPick(spot);
      if (S.stack.length) { renderSheet(true); } else { $("sheet").hidden = true; }
    }

    frame.build = function (body) {
      var crumbs = el("nav", "crumbs");
      crumbs.style.position = "static";
      crumbs.style.margin = "0 -16px 12px";
      body.appendChild(crumbs);
      renderCrumbs(crumbs, at.place ? segmentsFor(at.place, at.cell) : [], go);

      var place = at.place ? S.places[at.place] : null;

      if (!place) {
        var recents = recentSpots().filter(function (s) {
          return S.places[s.place] && !exclude[s.place];
        });
        if (recents.length && !opts.placesOnly) {
          body.appendChild(el("h3", null, "Recent"));
          var rbox = el("div", "recent");
          recents.forEach(function (s) {
            rbox.appendChild(button(null, shortText(segmentsFor(s.place, s.cell)), function () {
              at = { place: s.place, cell: s.cell }; pick();
            }));
          });
          body.appendChild(rbox);
          body.appendChild(el("h3", null, "Or browse"));
        }
        if (opts.allowTop) {
          body.appendChild(button("outlined wide", "At the top level, inside nothing", pick));
        }
      } else {
        var label;
        if (at.cell) { label = "Put it in this compartment"; }
        else if (place.kind === "grid") { label = "Somewhere on " + place.name; }
        else { label = "Put it in " + place.name; }
        var target = button(place.kind === "grid" && !at.cell ? "outlined wide" : "filled wide", label, pick);
        body.appendChild(target);
      }

      if (place && place.kind === "grid" && !at.cell) {
        var wallHolder = el("div");
        body.appendChild(wallHolder);
        var drawIt = function (cells) {
          clear(wallHolder).appendChild(drawWall(place, cells, {
            onTap: function (cell) { go(place.id, cell); },
            selected: opts.initial && opts.initial.place === place.id ? opts.initial.cell : null
          }));
        };
        if (gridCache[place.id]) { drawIt(gridCache[place.id]); }
        else {
          drawIt({});
          api("api/places/" + encodeURIComponent(place.id)).then(function (view) {
            gridCache[place.id] = view.grid.cells;
            if (at.place === place.id && !at.cell) { drawIt(view.grid.cells); }
          }).catch(fail);
        }
      }

      var kids = childrenAt(at.place, at.cell).filter(function (p) { return !exclude[p.id]; });
      if (kids.length) {
        if (place) { body.appendChild(el("h3", null, at.cell ? "Or in…" : "Or inside…")); }
        var box = el("div", "list");
        kids.forEach(function (p) {
          var row = placeRow(p, function () { go(p.id); }, at.cell ? KIND_LABELS[p.kind] : undefined);
          if (opts.initial && opts.initial.place === p.id) { row.classList.add("is-target"); }
          box.appendChild(row);
        });
        body.appendChild(box);
      }

      // A new box, right here, without leaving the picker.
      var kind = !place ? "room" : "container";
      var noun = !place ? "room" : "box";
      var inline = el("div", "inline-new");
      var input = el("input");
      input.type = "text";
      input.placeholder = !place ? "New room…" : "New box here… e.g. Black box with lid";
      inline.appendChild(input);
      var create = function () {
        var nameValue = input.value.trim();
        if (!nameValue) { input.focus(); return; }
        api("api/places", { method: "POST", body: {
          name: nameValue, kind: kind, parent: at.place, cell: at.cell
        } }).then(function (created) {
          return refresh().then(function () {
            delete gridCache[at.place];
            toast("Made " + noun + " " + created.name);
            go(created.id);
          });
        }).catch(fail);
      };
      input.addEventListener("keydown", function (e) { if (e.key === "Enter") { create(); } });
      inline.appendChild(button("outlined", "Add " + noun, create));
      body.appendChild(inline);
    };
    openSheet(frame);
  }

  // ================================================================ place editor

  function openPlaceEditor(seed) {
    var isNew = !seed.id;
    var draft = {
      id: seed.id || null,
      name: seed.name || "",
      kind: seed.kind || "container",
      parent: seed.parent === undefined ? null : seed.parent,
      cell: seed.cell || null,
      notes: seed.notes || "",
      cols: seed.cols || 4,
      rows: seed.rows || 4,
      count_cols_from: seed.count_cols_from || "left",
      count_rows_from: seed.count_rows_from || "top"
    };
    var frame = { title: isNew ? "New place" : "Edit " + draft.name };
    frame.build = function (body) {
      var name = textInput(draft.name, draft.kind === "grid" ? "Left Kallax" : "Black box with lid",
        function (v) { draft.name = v; });
      body.appendChild(field("Name", name));

      body.appendChild(el("div", "field-label", "What is it"));
      var kinds = el("div", "chips");
      ["room", "grid", "area", "container"].forEach(function (k) {
        kinds.appendChild(button("chip" + (draft.kind === k ? " is-on" : ""), KIND_LABELS[k], function () {
          draft.kind = k; renderSheet();
        }));
      });
      body.appendChild(kinds);

      if (draft.kind === "grid") {
        var two = el("div", "two");
        var cols = el("input"); cols.type = "number"; cols.min = "1"; cols.max = "60"; cols.value = draft.cols;
        cols.inputMode = "numeric";
        cols.addEventListener("input", function () { draft.cols = cols.value; });
        var rows = el("input"); rows.type = "number"; rows.min = "1"; rows.max = "20"; rows.value = draft.rows;
        rows.inputMode = "numeric";
        rows.addEventListener("input", function () { draft.rows = rows.value; });
        two.appendChild(field("Compartments across", cols));
        two.appendChild(field("Compartments high", rows));
        body.appendChild(two);
        body.appendChild(el("div", "field-label", "Count columns from the"));
        var cc = el("div", "chips");
        ["left", "right"].forEach(function (side) {
          cc.appendChild(button("chip" + (draft.count_cols_from === side ? " is-on" : ""), side, function () {
            draft.count_cols_from = side; renderSheet();
          }));
        });
        body.appendChild(cc);
        body.appendChild(el("div", "field-label", "Count rows from the"));
        var rc = el("div", "chips");
        ["top", "bottom"].forEach(function (side) {
          rc.appendChild(button("chip" + (draft.count_rows_from === side ? " is-on" : ""), side, function () {
            draft.count_rows_from = side; renderSheet();
          }));
        });
        body.appendChild(rc);
      }

      body.appendChild(el("div", "field-label", "Inside"));
      var exclude = {};
      if (draft.id) { exclude = descendantsOf(draft.id); exclude[draft.id] = true; }
      body.appendChild(spotButton(draft.parent ? { place: draft.parent, cell: draft.cell } : null, function () {
        pickSpot({
          title: "Where is it?",
          initial: draft.parent ? { place: draft.parent, cell: draft.cell } : null,
          exclude: exclude,
          allowTop: true,
          placesOnly: true,
          onPick: function (spot) { draft.parent = spot.place; draft.cell = spot.cell; }
        });
      }, "Nothing — it is a top-level place"));

      var notes = el("textarea");
      notes.value = draft.notes;
      notes.placeholder = draft.kind === "grid" ? "Two Kallax 4×4 units side by side" : "";
      notes.addEventListener("input", function () { draft.notes = notes.value; });
      body.appendChild(field("Notes", notes));

      var actions = el("div", "actions");
      actions.appendChild(button("filled", "Save", function () {
        if (!draft.name.trim()) { toast("Give it a name"); name.focus(); return; }
        var payload = {
          name: draft.name, kind: draft.kind, parent: draft.parent, cell: draft.cell, notes: draft.notes
        };
        if (draft.id) { payload.id = draft.id; }
        if (draft.kind === "grid") {
          payload.cols = draft.cols; payload.rows = draft.rows;
          payload.count_cols_from = draft.count_cols_from; payload.count_rows_from = draft.count_rows_from;
        }
        api("api/places", { method: "POST", body: payload }).then(function (saved) {
          toast("Saved " + saved.name);
          closeTop();
          if (isNew && S.tab === "places") { S.nav = { place: saved.id, cell: null }; }
          return afterChange();
        }).catch(fail);
      }));
      body.appendChild(actions);

      if (!isNew) {
        var parent = draft.parent && S.places[draft.parent];
        var hint = parent
          ? "Anything inside moves to " + parent.name + "."
          : "Only possible once it is empty.";
        var danger = el("div", "actions");
        danger.appendChild(confirmButton("text-button danger", "Delete " + draft.name, function () {
          api("api/places/" + encodeURIComponent(draft.id), { method: "DELETE" }).then(function (res) {
            var moved = res.moved_items + res.moved_places;
            toast(moved ? "Deleted; " + moved + " moved up to " + (parent ? parent.name : "the top") : "Deleted");
            closeAll();
            S.nav = { place: draft.parent || null, cell: draft.cell || null };
            return afterChange();
          }).catch(fail);
        }));
        body.appendChild(danger);
        body.appendChild(el("div", "meta-line", hint));
      }
    };
    openSheet(frame);
  }

  // ================================================================ wiring

  function init() {
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (b) {
      b.addEventListener("click", function () { switchTab(b.dataset.tab); });
    });
    var timer = null;
    $("search").addEventListener("input", function () {
      S.query = $("search").value;
      clearTimeout(timer);
      timer = setTimeout(runSearch, 120);
    });
    $("search").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && S.results && S.results.items.length === 1) {
        openItem(S.results.items[0].id);
      }
    });
    $("new-item").addEventListener("click", function () {
      openItemEditor({ name: S.results && !S.results.items.length ? S.query.trim() : "" });
    });
    $("sheet-close").addEventListener("click", closeAll);
    $("sheet-back").addEventListener("click", closeTop);
    $("sheet").addEventListener("click", function (e) { if (e.target === $("sheet")) { closeAll(); } });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && S.stack.length) { closeTop(); }
    });
    refresh().then(renderTab).catch(fail);
  }

  init();
})();
