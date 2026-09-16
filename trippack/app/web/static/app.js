/* TripPack front end. No framework, no build step, works offline once loaded. */

(function () {
  "use strict";

  var state = { data: null, tray: [], trayTitle: null, trayPull: null, showSkipped: false, filter: "" };
  var $ = function (id) { return document.getElementById(id); };

  // ---------------------------------------------------------------- api

  function api(path, options) {
    options = options || {};
    var init = { method: options.method || "GET", headers: {} };
    if (options.body) {
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
    var el = $("toast");
    el.textContent = message;
    el.hidden = false;
    clearTimeout(el._timer);
    el._timer = setTimeout(function () { el.hidden = true; }, 2600);
  }

  function refresh() {
    return api("api/state").then(function (data) {
      state.data = data;
      render();
    }).catch(function (err) { toast(err.message); });
  }

  // ---------------------------------------------------------------- helpers

  function trip() { return state.data && state.data.active_trip; }
  function catalog() { return (state.data && state.data.catalog) || []; }
  function itemById(id) {
    var list = catalog();
    for (var i = 0; i < list.length; i++) { if (list[i].id === id) { return list[i]; } }
    return null;
  }
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }
  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }
  function humanDate(iso) {
    if (!iso) { return ""; }
    var parts = iso.split("-");
    var date = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    return date.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  }

  // ---------------------------------------------------------------- header

  function renderHeader() {
    var active = trip();
    if (!active) {
      $("trip-name").textContent = "TripPack";
      $("progress-text").textContent = "No trip";
      $("rail-done").style.width = "0%";
      return;
    }
    var p = active.progress;
    $("trip-name").textContent = active.name;
    $("rail-done").style.width = p.pct + "%";
    $("progress-text").textContent = p.total
      ? p.packed + "/" + (p.packed + p.todo)
      : "empty";
  }

  // ---------------------------------------------------------------- pack view

  function renderPack() {
    var host = $("pack-list");
    clear(host);
    var active = trip();
    if (!active) { return; }

    var waiting = $("waiting");
    if (active.waiting > 0 && !state.tray.length) {
      waiting.hidden = false;
      $("waiting-text").textContent = active.waiting === 1
        ? "One item your itinerary suggests"
        : active.waiting + " items your itinerary suggests";
    } else {
      waiting.hidden = true;
    }

    var rows = active.packing.filter(function (row) {
      return state.showSkipped ? row.state === "skipped" : row.state !== "skipped";
    });

    $("show-skipped").textContent = state.showSkipped
      ? "Back to the packing list"
      : "Show what you left behind (" + active.progress.skipped + ")";
    $("show-skipped").hidden = !active.progress.skipped && !state.showSkipped;

    if (!rows.length) {
      var empty = el("div", "empty");
      empty.appendChild(el("strong", null, state.showSkipped
        ? "Nothing left behind."
        : "The list is empty."));
      empty.appendChild(el("span", null, state.showSkipped
        ? "Items you decide against will collect here."
        : "Search above, or let the itinerary fill it in from the Days tab."));
      host.appendChild(empty);
      return;
    }

    var groups = {};
    var order = [];
    rows.forEach(function (row) {
      if (!groups[row.category]) { groups[row.category] = []; order.push(row.category); }
      groups[row.category].push(row);
    });

    var group = el("div", "group");
    order.forEach(function (category) {
      var items = groups[category];
      var head = el("div", "group-head");
      head.appendChild(el("h3", null, category.charAt(0).toUpperCase() + category.slice(1)));
      var packed = items.filter(function (r) { return r.state === "packed"; }).length;
      head.appendChild(el("span", "count", packed + "/" + items.length));
      group.appendChild(head);
      items.forEach(function (row) { group.appendChild(packRow(row)); });
    });
    host.appendChild(group);
  }

  function packRow(row) {
    var wrap = el("div", "row" + (row.state === "packed" ? " is-packed" : ""));
    var main = el("button", "row-main");
    main.appendChild(el("span", "box"));
    var label = el("span", "label");
    label.appendChild(el("span", "name", row.name));
    main.appendChild(label);
    // A counted item shows its number instead of the why-hint: on a phone
    // there is room for one of them, and the number is the one you act on.
    if (row.qty === null || row.qty === undefined) {
      if (row.hint) { main.appendChild(el("span", "hint", row.hint)); }
    }
    main.addEventListener("click", function () {
      api("api/pack/" + row.item_id + "/state", { method: "POST", body: {} })
        .then(refresh).catch(function (err) { toast(err.message); });
    });
    wrap.appendChild(main);

    if (row.qty !== null && row.qty !== undefined) {
      wrap.appendChild(stepper(row));
    }

    var more = el("button", "more", "\u22EF");
    more.setAttribute("aria-label", "Details for " + row.name);
    more.addEventListener("click", function () { openItemSheet(row); });
    wrap.appendChild(more);
    return wrap;
  }

  function setQty(row, next) {
    if (next < 1) { return; }
    return api("api/pack/" + row.item_id + "/qty", {
      method: "POST",
      body: { qty: next }
    }).then(refresh).catch(function (err) { toast(err.message); });
  }

  function stepper(row) {
    var group = el("div", "qty" + (row.qty_auto ? " is-auto" : ""));
    var less = el("button", "step", "\u2212");
    less.setAttribute("aria-label", "One fewer " + row.name);
    less.addEventListener("click", function () { setQty(row, row.qty - 1); });

    var value = el("span", "qty-value", String(row.qty));
    value.title = row.qty_auto
      ? "Worked out from the length of the trip"
      : "You chose this number";

    var more = el("button", "step", "+");
    more.setAttribute("aria-label", "One more " + row.name);
    more.addEventListener("click", function () { setQty(row, row.qty + 1); });

    group.appendChild(less);
    group.appendChild(value);
    group.appendChild(more);
    return group;
  }

  // ---------------------------------------------------------------- add box

  function renderSearch() {
    var query = ($("add-input").value || "").trim().toLowerCase();
    var results = $("add-results");
    clear(results);
    if (!query) { results.hidden = true; $("add-new").hidden = true; return; }

    var active = trip();
    var onList = {};
    if (active) { active.packing.forEach(function (r) { onList[r.item_id] = r.state; }); }

    var matches = catalog().filter(function (item) {
      return item.name.toLowerCase().indexOf(query) >= 0 ||
        (item.tags || []).join(" ").indexOf(query) >= 0;
    }).slice(0, 8);

    matches.forEach(function (item) {
      var li = el("li");
      var button = el("button");
      button.appendChild(el("span", null, item.name));
      button.appendChild(el("span", "meta", onList[item.id] ? "already on the list" : item.category));
      button.addEventListener("click", function () {
        $("add-input").value = "";
        renderSearch();
        addItem(item.id, { kind: "manual" });
      });
      li.appendChild(button);
      results.appendChild(li);
    });

    results.hidden = !matches.length;
    $("add-new").hidden = matches.length > 0;
  }

  function addItem(itemId, reason, parentName, depth) {
    return api("api/pack", { method: "POST", body: { item_id: itemId, reason: reason } })
      .then(function (res) {
        var item = itemById(itemId);
        if (res.added) { toast((item ? item.name : itemId) + " added"); }
        if (res.suggestions && res.suggestions.length) {
          pushSuggestions(res.suggestions, item ? item.name : itemId, (depth || 0) + 1);
        }
        return refresh();
      }).catch(function (err) { toast(err.message); });
  }

  // ---------------------------------------------------------------- tray

  function pushSuggestions(cards, parentName, depth) {
    if (parentName) { state.trayTitle = null; state.trayPull = null; }
    cards.forEach(function (card) {
      var seen = state.tray.some(function (t) { return t.item_id === card.item_id; });
      if (seen) { return; }
      state.tray.push({
        item_id: card.item_id,
        name: card.name,
        note: card.notes || (card.why ? card.why.join(" · ") : ""),
        parent: parentName,
        reasons: card.reasons || null,
        depth: depth || 1
      });
    });
    renderTray();
  }

  function renderTray() {
    var tray = $("tray");
    if (!state.tray.length) { tray.hidden = true; return; }
    tray.hidden = false;

    var entry = state.tray[0];
    $("tray-title").textContent = state.trayTitle ||
      (entry.parent ? "Going with " + entry.parent + "?" : "Suggested for this trip");
    $("tray-count").textContent = state.tray.length > 1
      ? "1 of " + state.tray.length
      : "";
    $("tray-name").textContent = entry.name;
    $("tray-note").textContent = entry.note || "";

    // Going through sixty suggestions one at a time is nobody's evening.
    var all = $("tray-all");
    all.hidden = !state.trayPull || state.tray.length < 2;
    if (!all.hidden) { all.textContent = "Add all " + state.tray.length; }
  }

  function trayTop() { return state.tray.length ? state.tray[0] : null; }

  function parentIdOf(entry) {
    var list = catalog();
    for (var i = 0; i < list.length; i++) {
      if (list[i].name === entry.parent) { return list[i].id; }
    }
    return null;
  }

  function closeTray() {
    state.tray = [];
    state.trayTitle = null;
    state.trayPull = null;
    renderTray();
    renderPack();
  }

  function dropFromTray(itemId) {
    state.tray = state.tray.filter(function (t) { return t.item_id !== itemId; });
    if (!state.tray.length) { state.trayTitle = null; state.trayPull = null; }
    renderTray();
  }

  function reviewCandidates(date) {
    var url = "api/candidates" + (date ? "?date=" + encodeURIComponent(date) : "");
    api(url).then(function (res) {
      if (!res.candidates.length) { toast("Nothing new for that."); return; }
      state.tray = [];
      state.trayPull = { date: date || null };
      state.trayTitle = date
        ? "Suggested for " + humanDate(date)
        : "Suggested by your itinerary";
      pushSuggestions(res.candidates.map(function (c) {
        return {
          item_id: c.item_id, name: c.name, notes: c.why.join(" · "), reasons: c.reasons
        };
      }), null, 1);
      switchTab("pack");
      window.scrollTo({ top: 0, behavior: "smooth" });
    }).catch(function (err) { toast(err.message); });
  }

  // ---------------------------------------------------------------- item sheet

  function openSheet(title, build) {
    $("sheet-title").textContent = title;
    var body = $("sheet-body");
    clear(body);
    build(body);
    $("sheet").hidden = false;
  }
  function closeSheet() { $("sheet").hidden = true; }

  function openItemSheet(row) {
    openSheet(row.name, function (body) {
      var item = itemById(row.item_id);
      if (item && item.notes) { body.appendChild(el("p", null, item.notes)); }
      if (row.why && row.why.length) {
        body.appendChild(el("h3", null, "On the list because"));
        var ul = el("ul", "why-list");
        row.why.forEach(function (line) { ul.appendChild(el("li", null, line)); });
        body.appendChild(ul);
      }
      if (row.missing) {
        body.appendChild(el("p", null,
          "This item is no longer in the catalogue. Remove it or add it back under Items."));
      }

      if (row.qty !== null && row.qty !== undefined) {
        body.appendChild(el("h3", null, "How many"));
        body.appendChild(el("p", "day-note", row.qty_auto
          ? row.qty + " — worked out from the length of this trip."
          : row.qty + " — you set this. It will not change if the trip does."));
      }

      var actions = el("div", "sheet-actions");
      if (row.qty && !row.qty_auto) {
        var auto = el("button", "chip", "Back to automatic");
        auto.addEventListener("click", function () {
          api("api/pack/" + row.item_id + "/qty", { method: "POST", body: { qty: null } })
            .then(function () { closeSheet(); return refresh(); })
            .catch(function (err) { toast(err.message); });
        });
        actions.appendChild(auto);
      }
      var states = [["todo", "Still to pack"], ["packed", "Packed"], ["skipped", "Leaving it"]];
      states.forEach(function (pair) {
        if (pair[0] === row.state) { return; }
        var button = el("button", "chip", pair[1]);
        button.addEventListener("click", function () {
          api("api/pack/" + row.item_id + "/state", { method: "POST", body: { state: pair[0] } })
            .then(function () { closeSheet(); return refresh(); })
            .catch(function (err) { toast(err.message); });
        });
        actions.appendChild(button);
      });

      var suggest = el("button", "chip", "What goes with this?");
      suggest.addEventListener("click", function () {
        api("api/chain/" + row.item_id).then(function (res) {
          closeSheet();
          if (!res.chain.length) { toast("Nothing linked to " + row.name + " yet."); return; }
          var onList = {};
          trip().packing.forEach(function (r) { onList[r.item_id] = true; });
          var cards = res.chain.filter(function (c) { return !onList[c.item_id]; })
            .map(function (c) { return { item_id: c.item_id, name: c.name }; });
          if (!cards.length) { toast("Everything that goes with it is already on the list."); return; }
          state.tray = [];
          state.trayTitle = null;
          pushSuggestions(cards, row.name, 1);
          switchTab("pack");
        }).catch(function (err) { toast(err.message); });
      });
      actions.appendChild(suggest);

      var remove = el("button", "chip danger", "Remove from list");
      remove.addEventListener("click", function () {
        api("api/pack/" + row.item_id, { method: "DELETE" })
          .then(function () { closeSheet(); return refresh(); })
          .catch(function (err) { toast(err.message); });
      });
      actions.appendChild(remove);
      body.appendChild(actions);
    });
  }

  // ---------------------------------------------------------------- days view

  function renderDays() {
    var host = $("day-list");
    clear(host);
    var active = trip();
    if (!active) { return; }
    if (!active.days.length) {
      var empty = el("div", "empty");
      empty.appendChild(el("strong", null, "No days yet."));
      empty.appendChild(el("span", null, "Add days to this trip and tag what you will be doing."));
      host.appendChild(empty);
    }

    active.days.forEach(function (day) {
      var li = el("li", "day" + (day.candidates === 0 ? " is-clear" : ""));
      var card = el("div", "day-card");
      card.appendChild(el("div", "day-when", day.label));
      card.appendChild(el("h3", null, day.title || "Untitled day"));
      if (day.notes) { card.appendChild(el("p", "day-note", day.notes)); }

      var tags = el("div", "tagrow");
      day.tags.forEach(function (tag) { tags.appendChild(el("span", "tag", tag)); });
      card.appendChild(tags);

      var actions = el("div", "day-actions");
      if (day.candidates) {
        var pull = el("button", "chip", "Add " + day.candidates + " suggested");
        pull.addEventListener("click", function () { reviewCandidates(day.date); });
        actions.appendChild(pull);
      } else {
        actions.appendChild(el("span", "status", "Everything tagged for this day is on the list."));
      }
      if (day.unpacked) {
        actions.appendChild(el("span", "status", day.unpacked + " still to pack"));
      }
      var edit = el("button", "chip", "Edit");
      edit.addEventListener("click", function () { openDaySheet(day); });
      actions.appendChild(edit);

      card.appendChild(actions);
      li.appendChild(card);
      host.appendChild(li);
    });

    var addDay = el("li", "day");
    var addButton = el("button", "text-button", "Add a day");
    addButton.addEventListener("click", function () { openDaySheet(null); });
    addDay.appendChild(addButton);
    host.appendChild(addDay);
  }

  function openDaySheet(day) {
    openSheet(day ? day.title || day.label : "New day", function (body) {
      var date = field(body, "Date", "date", day ? day.date : "");
      var title = field(body, "What happens", "text", day ? day.title : "");
      var tags = field(body, "Tags, comma separated", "text", day ? day.tags.join(", ") : "");
      var notes = textField(body, "Notes", day ? day.notes : "");

      var actions = el("div", "sheet-actions");
      var save = el("button", "filled", "Save day");
      save.addEventListener("click", function () {
        api("api/trips/" + trip().id + "/days", {
          method: "POST",
          body: {
            date: date.value,
            title: title.value,
            tags: tags.value.split(","),
            notes: notes.value
          }
        }).then(function () { closeSheet(); return refresh(); })
          .catch(function (err) { toast(err.message); });
      });
      actions.appendChild(save);

      if (day) {
        var remove = el("button", "chip danger", "Delete day");
        remove.addEventListener("click", function () {
          api("api/trips/" + trip().id + "/days/" + day.date, { method: "DELETE" })
            .then(function () { closeSheet(); return refresh(); })
            .catch(function (err) { toast(err.message); });
        });
        actions.appendChild(remove);
      }
      body.appendChild(actions);
    });
  }

  // ---------------------------------------------------------------- catalog view

  function renderCatalog() {
    var host = $("catalog-list");
    clear(host);
    var query = state.filter.toLowerCase();
    var items = catalog().filter(function (item) {
      return !query || item.name.toLowerCase().indexOf(query) >= 0 ||
        (item.tags || []).join(" ").indexOf(query) >= 0 ||
        (item.category || "").indexOf(query) >= 0;
    });

    var groups = {};
    var order = [];
    items.forEach(function (item) {
      var key = item.category || "other";
      if (!groups[key]) { groups[key] = []; order.push(key); }
      groups[key].push(item);
    });
    order.sort();

    order.forEach(function (category) {
      var card = el("div", "card");
      card.appendChild(el("h2", null, category.charAt(0).toUpperCase() + category.slice(1)));
      groups[category].forEach(function (item) {
        var row = el("div", "catalog-item");
        var grow = el("div", "grow");
        grow.appendChild(el("div", "name", item.name + (item.always ? " · always" : "")));
        var bits = [];
        if (item.per_day) { bits.push(item.per_day + " per day" + (item.qty_max ? ", max " + item.qty_max : "")); }
        else if (item.qty) { bits.push("\u00d7" + item.qty); }
        if (item.tags.length) { bits.push(item.tags.join(", ")); }
        if (item.suggests.length) { bits.push("brings " + item.suggests.length); }
        grow.appendChild(el("div", "meta", bits.join(" · ")));
        row.appendChild(grow);
        var edit = el("button", "chip", "Edit");
        edit.addEventListener("click", function () { openItemEditor(item); });
        row.appendChild(edit);
        card.appendChild(row);
      });
      host.appendChild(card);
    });
  }

  function field(parent, labelText, type, value) {
    var label = el("label", null, labelText);
    var input = document.createElement("input");
    input.type = type;
    input.value = value || "";
    label.appendChild(input);
    parent.appendChild(label);
    return input;
  }

  function numberField(parent, labelText, value, step) {
    var label = el("label", null, labelText);
    var input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    if (step) { input.step = step; }
    input.inputMode = step ? "decimal" : "numeric";
    input.value = (value === null || value === undefined) ? "" : String(value);
    label.appendChild(input);
    parent.appendChild(label);
    return input;
  }

  function numberOf(input) {
    var value = parseFloat(input.value);
    return isFinite(value) && value > 0 ? value : null;
  }

  function textField(parent, labelText, value) {
    var label = el("label", null, labelText);
    var area = document.createElement("textarea");
    area.value = value || "";
    label.appendChild(area);
    parent.appendChild(label);
    return area;
  }

  function openItemEditor(item) {
    openSheet(item ? item.name : "New item", function (body) {
      var name = field(body, "Name", "text", item ? item.name : "");
      var category = field(body, "Category", "text", item ? item.category : "other");
      var tags = field(body, "Tags, comma separated", "text", item ? item.tags.join(", ") : "");
      var notes = textField(body, "Notes", item ? item.notes : "");

      body.appendChild(el("h3", null, "How many to bring"));
      body.appendChild(el("p", "day-note",
        "Leave these empty for things you only ever bring one of. " +
        "Per day scales with the trip; the cap is where you do a wash instead."));
      var counts = el("div", "three");
      var perDay = numberField(counts, "Per day", item ? item.per_day : null, "0.05");
      var qtyMax = numberField(counts, "At most", item ? item.qty_max : null);
      var qtyFixed = numberField(counts, "Or fixed", item ? item.qty : null);
      body.appendChild(counts);

      var alwaysLabel = el("label", null, "");
      var always = document.createElement("input");
      always.type = "checkbox";
      always.checked = item ? !!item.always : false;
      always.style.width = "auto";
      always.style.minHeight = "0";
      alwaysLabel.appendChild(always);
      alwaysLabel.appendChild(document.createTextNode(" Pack this on every trip"));
      body.appendChild(alwaysLabel);

      body.appendChild(el("h3", null, "Goes with"));
      body.appendChild(el("p", "day-note",
        "Tick what should be offered whenever this item is added."));
      var picks = {};
      var box = el("div", "tagrow");
      catalog().forEach(function (other) {
        if (item && other.id === item.id) { return; }
        var chip = el("button", "chip", other.name);
        var on = item && item.suggests.indexOf(other.id) >= 0;
        picks[other.id] = on;
        if (on) { chip.style.borderColor = "var(--accent)"; chip.style.color = "var(--accent)"; }
        chip.addEventListener("click", function () {
          picks[other.id] = !picks[other.id];
          chip.style.borderColor = picks[other.id] ? "var(--accent)" : "var(--line)";
          chip.style.color = picks[other.id] ? "var(--accent)" : "var(--text)";
        });
        box.appendChild(chip);
      });
      body.appendChild(box);

      var actions = el("div", "sheet-actions");
      actions.style.marginTop = "14px";
      var save = el("button", "filled", "Save item");
      save.addEventListener("click", function () {
        var suggests = Object.keys(picks).filter(function (id) { return picks[id]; });
        api("api/items", {
          method: "POST",
          body: {
            id: item ? item.id : null,
            name: name.value,
            category: category.value,
            tags: tags.value.split(","),
            notes: notes.value,
            always: always.checked,
            per_day: numberOf(perDay),
            qty_max: numberOf(qtyMax),
            qty: numberOf(qtyFixed),
            suggests: suggests
          }
        }).then(function () { closeSheet(); return refresh(); })
          .catch(function (err) { toast(err.message); });
      });
      actions.appendChild(save);

      if (item) {
        var remove = el("button", "chip danger", "Delete from catalogue");
        remove.addEventListener("click", function () {
          api("api/items/" + item.id, { method: "DELETE" })
            .then(function () { closeSheet(); return refresh(); })
            .catch(function (err) { toast(err.message); });
        });
        actions.appendChild(remove);
      }
      body.appendChild(actions);
    });
  }

  // ---------------------------------------------------------------- trips view

  function renderTrips() {
    var host = $("trip-list");
    clear(host);
    (state.data.trips || []).forEach(function (t) {
      var card = el("div", "card");
      card.appendChild(el("h2", null, t.name));
      card.appendChild(el("div", "day-when",
        (t.start ? humanDate(t.start) + " to " + humanDate(t.end) : "No dates") +
        " · " + t.days + " days · " + t.progress.packed + "/" + t.progress.total + " packed"));
      var actions = el("div", "sheet-actions");
      actions.style.marginTop = "10px";
      var isActive = trip() && trip().id === t.id;
      if (!isActive) {
        var open = el("button", "chip", "Open this trip");
        open.addEventListener("click", function () {
          api("api/trips/" + t.id + "/active", { method: "POST", body: {} })
            .then(function () { state.tray = []; switchTab("pack"); return refresh(); })
            .catch(function (err) { toast(err.message); });
        });
        actions.appendChild(open);
      } else {
        var reset = el("button", "chip", "Unpack everything");
        reset.addEventListener("click", function () {
          api("api/reset", { method: "POST", body: {} }).then(refresh)
            .catch(function (err) { toast(err.message); });
        });
        actions.appendChild(reset);
        var pull = el("button", "chip", "Review itinerary suggestions");
        pull.addEventListener("click", function () { reviewCandidates(null); });
        actions.appendChild(pull);
      }
      var remove = el("button", "chip danger", "Delete trip");
      remove.addEventListener("click", function () {
        if (!window.confirm("Delete " + t.name + " and its packing list?")) { return; }
        api("api/trips/" + t.id, { method: "DELETE" }).then(refresh)
          .catch(function (err) { toast(err.message); });
      });
      actions.appendChild(remove);
      card.appendChild(actions);
      host.appendChild(card);
    });
  }

  // ---------------------------------------------------------------- tabs

  function switchTab(name) {
    ["pack", "days", "items", "trips"].forEach(function (tab) {
      $("view-" + tab).hidden = tab !== name;
    });
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (button) {
      button.classList.toggle("is-active", button.dataset.tab === name);
    });
  }

  function render() {
    if (!state.data) { return; }
    renderHeader();
    renderPack();
    renderDays();
    renderCatalog();
    renderTrips();
    renderTray();
  }

  // ---------------------------------------------------------------- wiring

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (button) {
      button.addEventListener("click", function () { switchTab(button.dataset.tab); });
    });

    $("add-input").addEventListener("input", renderSearch);
    $("add-new").addEventListener("click", function () {
      var name = $("add-input").value.trim();
      $("add-input").value = "";
      renderSearch();
      openItemEditor({ id: null, name: name, category: "other", tags: [], suggests: [], notes: "", always: false });
    });

    $("tray-close").addEventListener("click", closeTray);
    $("tray-all").addEventListener("click", function () {
      var pull = state.trayPull;
      if (!pull) { return; }
      var count = state.tray.length;
      api("api/pull", { method: "POST", body: { date: pull.date } })
        .then(function () {
          closeTray();
          toast(count + " added");
          return refresh();
        }).catch(function (err) { toast(err.message); });
    });
    $("tray-add").addEventListener("click", function () {
      var entry = trayTop();
      if (!entry) { return; }
      dropFromTray(entry.item_id);
      var reason = entry.reasons && entry.reasons.length
        ? entry.reasons[0]
        : { kind: "suggested_by", item_id: parentIdOf(entry) };
      addItem(entry.item_id, reason, entry.name, entry.depth);
    });
    $("tray-skip").addEventListener("click", function () {
      var entry = trayTop();
      if (!entry) { return; }
      api("api/pack/" + entry.item_id + "/dismiss", { method: "POST", body: {} })
        .then(function () { dropFromTray(entry.item_id); return refresh(); })
        .catch(function (err) { toast(err.message); });
    });
    $("waiting").addEventListener("click", function () { reviewCandidates(null); });
    $("show-skipped").addEventListener("click", function () {
      state.showSkipped = !state.showSkipped;
      renderPack();
    });
    $("item-filter").addEventListener("input", function () {
      state.filter = this.value;
      renderCatalog();
    });
    $("item-new").addEventListener("click", function () { openItemEditor(null); });
    $("sheet-close").addEventListener("click", closeSheet);
    $("sheet").addEventListener("click", function (event) {
      if (event.target === $("sheet")) { closeSheet(); }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { closeSheet(); }
    });

    $("new-trip-save").addEventListener("click", function () {
      var name = $("new-trip-name").value.trim();
      if (!name) { toast("A trip needs a name."); return; }
      api("api/trips", {
        method: "POST",
        body: { name: name, start: $("new-trip-start").value, end: $("new-trip-end").value }
      }).then(function () {
        $("new-trip-name").value = "";
        toast(name + " created");
        return refresh();
      }).catch(function (err) { toast(err.message); });
    });

    refresh();
  });
})();
