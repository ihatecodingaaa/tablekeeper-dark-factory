/* Tablekeeper browser client. Plain DOM and fetch, no dependencies.
 *
 * The server is authoritative: a confirmation is only ever drawn from a 200/201
 * response body, never from cached data. Booking retries reuse the idempotency
 * key and body of the attempt they repeat, so a retry can never book twice.
 */
(function () {
  "use strict";

  var SESSION_KEY = "tablekeeper.session";
  var REQUEST_TIMEOUT_MS = 12000;
  var SVG_NS = "http://www.w3.org/2000/svg";

  // ---------------------------------------------------------------- DOM helpers

  function byId(id) { return document.getElementById(id); }

  function h(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (name) {
      var value = attrs[name];
      if (value === null || value === undefined || value === false) return;
      if (name === "class") el.className = value;
      else if (name.slice(0, 2) === "on" && typeof value === "function") {
        el.addEventListener(name.slice(2), value);
      } else el.setAttribute(name, value === true ? "" : String(value));
    });
    append(el, Array.prototype.slice.call(arguments, 2));
    return el;
  }

  function append(el, children) {
    children.forEach(function (child) {
      if (Array.isArray(child)) append(el, child);
      else if (child !== null && child !== undefined && child !== false) {
        el.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
      }
    });
  }

  /* Replace an element's children, skipping null/undefined/false entries
   * (Element.replaceChildren would render those as text). */
  function setChildren(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
    append(el, Array.prototype.slice.call(arguments, 1));
  }

  var ICONS = {
    plus: ["M12 5v14", "M5 12h14"],
    check: ["M5 12.5l4.5 4.5L19 7.5"],
    dash: ["M7 12h10"],
    x: ["M6.5 6.5l11 11", "M17.5 6.5l-11 11"],
    alert: ["M12 3.8l9 16H3z", "M12 10v4.2", "M12 17.3v.2"],
    question: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M9.6 9.4a2.5 2.5 0 1 1 3.4 2.4c-.6.3-1 .8-1 1.4v.6",
               "M12 17v.2"],
    info: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 11v5.5", "M12 7.8v.2"],
    calendar: ["M4.5 6h15v13.5h-15z", "M4.5 10h15", "M8.5 3.5v4", "M15.5 3.5v4"],
    spinner: ["M12 3a9 9 0 1 1-9 9"],
    lock: ["M6 11h12v9H6z", "M8.5 11V8a3.5 3.5 0 0 1 7 0v3"],
    search: ["M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13z", "M15.5 15.5L20 20"]
  };

  function icon(name, extraClass) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    svg.setAttribute("class", "icon" + (extraClass ? " " + extraClass : ""));
    ICONS[name].forEach(function (d) {
      var path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", d);
      svg.appendChild(path);
    });
    return svg;
  }

  /* kind: error | uncertain | info | success. Errors are alerts; the rest are polite. */
  function notice(kind, iconName, title, body, testId) {
    return h("div", {
      "class": "notice notice--" + kind,
      role: kind === "error" ? "alert" : "status",
      "data-testid": testId
    }, icon(iconName), h("div", null,
      title ? h("strong", { "class": "notice__title" }, title) : null,
      h("div", { "class": "notice__body" }, body)));
  }

  function loadingLine(text) {
    return h("p", { "class": "loading", role: "status" }, icon("spinner", "spinner"), text);
  }

  function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function reveal(el) {
    if (!el) return;
    el.focus({ preventScroll: true });
    el.scrollIntoView({ block: "nearest", behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }

  // ---------------------------------------------------------------- formatting

  var DATE_FORMAT = new Intl.DateTimeFormat("en-GB", {
    weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC"
  });

  function formatDate(ymd) {
    var parts = String(ymd || "").split("-").map(Number);
    if (parts.length !== 3 || parts.some(isNaN)) return String(ymd || "");
    return DATE_FORMAT.format(new Date(Date.UTC(parts[0], parts[1] - 1, parts[2])));
  }

  function timeOf(local) { return String(local || "").slice(11, 16); }
  function dateOf(local) { return String(local || "").slice(0, 10); }
  function whenText(local) { return formatDate(dateOf(local)) + " at " + timeOf(local); }
  function guests(n) { return n === 1 ? "1 guest" : n + " guests"; }

  function todayISO() {
    var d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" +
      String(d.getDate()).padStart(2, "0");
  }

  function formatMinutes(total) {
    if (total % 1440 === 0 && total >= 1440) return plural(total / 1440, "day");
    if (total % 60 === 0 && total >= 60) return plural(total / 60, "hour");
    return plural(total, "minute");
  }

  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }

  function initial(name) {
    var first = Array.from(String(name || "").trim())[0];
    return first ? first.toUpperCase() : "?";
  }

  // Human table labels: "Table 2", joined numeric tables "Tables 1 + 2".
  function findTable(restaurant, id) {
    var tables = (restaurant && restaurant.tables) || [];
    for (var i = 0; i < tables.length; i++) if (tables[i].id === id) return tables[i];
    return null;
  }

  function rawLabel(restaurant, id) {
    var table = findTable(restaurant, id);
    return table && table.label !== undefined && table.label !== null ? String(table.label) : String(id);
  }

  function isNumeric(text) { return /^\d+$/.test(text); }

  function tablesLabel(restaurant, ids) {
    var labels = ids.map(function (id) { return rawLabel(restaurant, id); });
    if (labels.length === 1) return isNumeric(labels[0]) ? "Table " + labels[0] : labels[0];
    if (labels.every(isNumeric)) return "Tables " + labels.join(" + ");
    return labels.map(function (l) { return isNumeric(l) ? "Table " + l : l; }).join(" + ");
  }

  function seats(restaurant, ids) {
    return ids.reduce(function (sum, id) {
      var table = findTable(restaurant, id);
      return sum + (table && typeof table.capacity === "number" ? table.capacity : 0);
    }, 0);
  }

  function reservationTableIds(reservation) {
    if (Array.isArray(reservation.table_ids) && reservation.table_ids.length) return reservation.table_ids;
    return reservation.table_id ? [reservation.table_id] : [];
  }

  // ---------------------------------------------------------------- session

  var memorySession = null;  // fallback when the browser refuses storage

  var session = {
    get: function () {
      try {
        var stored = JSON.parse(window.localStorage.getItem(SESSION_KEY) || "null");
        if (stored && typeof stored.token === "string" && stored.token) return stored;
      } catch (e) {
        return memorySession;
      }
      return null;
    },
    set: function (data) {
      var value = { token: data.token, user_id: data.user_id, display_name: data.display_name };
      memorySession = value;
      try { window.localStorage.setItem(SESSION_KEY, JSON.stringify(value)); } catch (e) { /* memory only */ }
    },
    clear: function () {
      memorySession = null;
      try { window.localStorage.removeItem(SESSION_KEY); } catch (e) { /* nothing stored */ }
    }
  };

  // ---------------------------------------------------------------- API

  /* Thrown when the outcome of a request is unknown: the connection failed, it
   * timed out, the server answered 5xx, or the body could not be read. */
  function Uncertain(reason) { this.reason = reason; }

  function api(method, path, options) {
    var opts = options || {};
    var headers = { "Accept": "application/json" };
    var init = { method: method, headers: headers, cache: "no-store", credentials: "same-origin" };
    if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    if (opts.key) headers["Idempotency-Key"] = opts.key;
    if (opts.auth) {
      var current = session.get();
      if (current) headers["Authorization"] = "Bearer " + current.token;
    }
    var controller = new AbortController();
    init.signal = controller.signal;
    var timer = setTimeout(function () { controller.abort(); }, opts.timeout || REQUEST_TIMEOUT_MS);
    var status = 0;
    return fetch(path, init)
      .catch(function () { throw new Uncertain("network"); })
      .then(function (response) {
        status = response.status;
        return response.text().catch(function () { throw new Uncertain("body"); });
      })
      .then(function (text) {
        if (status >= 500) throw new Uncertain("server");
        var data = null;
        if (text) {
          try { data = JSON.parse(text); } catch (e) { throw new Uncertain("unreadable"); }
        }
        if (opts.auth && status === 401) signedOutByServer();
        return {
          status: status,
          ok: status >= 200 && status < 300,
          data: data,
          code: data && data.error ? data.error.code : null
        };
      })
      .finally(function () { clearTimeout(timer); });
  }

  function newIdempotencyKey() {
    // crypto.getRandomValues also works on plain-http origins, unlike randomUUID.
    var bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    return "tk-" + Array.prototype.map.call(bytes, function (b) {
      return b.toString(16).padStart(2, "0");
    }).join("");
  }

  var restaurantCache = {};

  function loadRestaurant(id, fresh) {
    if (!fresh && restaurantCache[id]) return Promise.resolve(restaurantCache[id]);
    return api("GET", "/restaurants/" + encodeURIComponent(id)).then(function (res) {
      if (!res.ok) return null;
      restaurantCache[id] = res.data;
      return res.data;
    }, function () { return null; });
  }

  // ---------------------------------------------------------------- header

  function renderAccount() {
    var slot = byId("account");
    if (!slot) return;
    var current = session.get();
    while (slot.firstChild) slot.removeChild(slot.firstChild);
    if (current) {
      var name = current.display_name || "Guest";
      append(slot, [
        h("span", { "class": "current-user", "data-testid": "current-user" },
          h("span", { "class": "avatar", "aria-hidden": "true" }, initial(name)),
          h("span", { "class": "current-user__name", title: name },
            h("span", { "class": "visually-hidden" }, "Signed in as "), name)),
        h("button", {
          type: "button", "class": "button button--small", "data-testid": "logout-button",
          onclick: signOut
        }, "Sign out")
      ]);
    } else {
      append(slot, [
        h("a", { "class": "site-nav__link", href: "/login", "data-nav": "login" }, "Sign in"),
        h("a", { "class": "button button--small", href: "/signup", "data-nav": "signup" }, "Sign up")
      ]);
    }
    markCurrentNav();
  }

  function markCurrentNav() {
    var screen = document.body.getAttribute("data-screen");
    Array.prototype.forEach.call(document.querySelectorAll("[data-nav]"), function (link) {
      if (link.getAttribute("data-nav") === screen) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  function signOut() {
    session.clear();
    renderAccount();
    document.dispatchEvent(new CustomEvent("tk:signedout"));
  }

  function signedOutByServer() {
    if (!session.get()) return;
    session.clear();
    renderAccount();
    document.dispatchEvent(new CustomEvent("tk:signedout", { detail: { expired: true } }));
  }

  function signInLink(next, text) {
    return h("a", { href: "/login?next=" + encodeURIComponent(next) }, text || "Sign in");
  }

  // ---------------------------------------------------------------- search screen

  function initSearch() {
    var form = byId("search-form");
    var select = byId("search-restaurant");
    var dateInput = byId("search-date");
    var partyInput = byId("search-party");
    var results = byId("results");
    var panel = byId("booking-panel");
    var workspace = results.parentNode;
    var announcer = byId("search-announcer");

    var searchSeq = 0;    // only the newest search may draw the grid
    var view = null;      // the search on screen: query, restaurant, slots
    var booking = null;   // the open booking form
    var mine = {};        // reservations confirmed on this page, by reference

    if (!dateInput.value) dateInput.value = todayISO();
    if (!select.options.length) {
      showState("info", "No restaurants yet", "No restaurant is taking bookings right now. Please check back soon.");
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      startSearch();
    });

    document.addEventListener("tk:signedout", function (event) {
      var b = booking;
      if (!b) return;
      if (event.detail && event.detail.expired) return;  // the booking outcome explains it
      closeBooking();
      if (view) renderGrid();
    });

    function readQuery() {
      return { restaurantId: select.value, date: dateInput.value.trim(), partySize: partyInput.value.trim() };
    }

    function queryProblem(q) {
      if (!q.restaurantId) return "Choose a restaurant.";
      if (!/^\d{4}-\d{2}-\d{2}$/.test(q.date)) return "Choose the date you'd like to visit.";
      if (!/^\d+$/.test(q.partySize) || Number(q.partySize) < 1) return "Enter how many guests are coming (1 or more).";
      return null;
    }

    function startSearch() {
      var query = readQuery();
      closeBooking();
      var problem = queryProblem(query);
      if (problem) {
        searchSeq += 1;
        view = null;
        showState("error", "Check your search", problem);
        return;
      }
      runSearch(query, false);
    }

    function runSearch(query, refreshing) {
      searchSeq += 1;
      var seq = searchSeq;
      if (refreshing) showRefreshing();
      else renderLoading();
      var params = new URLSearchParams({
        restaurant_id: query.restaurantId, date: query.date, party_size: query.partySize
      });
      return Promise.all([
        api("GET", "/availability?" + params.toString()),
        api("GET", "/restaurants/" + encodeURIComponent(query.restaurantId))
      ]).then(function (answers) {
        if (seq !== searchSeq) return;  // a newer search owns the screen: drop this late answer
        var availability = answers[0];
        var restaurant = answers[1];
        if (!availability.ok || !restaurant.ok) {
          showSearchRefusal(availability.ok ? restaurant : availability);
          return;
        }
        restaurantCache[query.restaurantId] = restaurant.data;
        view = {
          query: query,
          restaurant: restaurant.data,
          slots: availability.data.slots || [],
          date: availability.data.date || query.date,
          partySize: Number(query.partySize)
        };
        renderGrid();
        announce(view.slots.length
          ? "Showing " + plural(view.slots.length, "time") + " at " + view.restaurant.name + "."
          : "No bookable times on this day.");
      }, function () {
        if (seq !== searchSeq) return;
        if (refreshing && view) {
          renderGrid();
          results.insertBefore(notice("error", "alert", "Availability not updated",
            "We couldn't refresh the grid. It may be out of date; search again to check."), results.firstChild);
        } else {
          showState("error", "We couldn't load tables",
            "Check your connection and try again.", { label: "Try again", run: function () { runSearch(query, false); } });
        }
      });
    }

    function announce(text) { announcer.textContent = text; }

    function heading(text) {
      return h("h2", { "class": "results__title", id: "results-heading" }, text);
    }

    function showState(kind, title, text, action) {
      view = null;
      var iconName = kind === "error" ? "alert" : "calendar";
      results.setAttribute("aria-busy", "false");
      setChildren(results, h("div", { "class": "state" + (kind === "error" ? " state--error" : "") },
        icon(iconName, "state__icon"),
        h("h2", { "class": "state__title", id: "results-heading" }, title),
        h("p", { "class": "state__text" }, text),
        action ? h("button", { type: "button", "class": "button", onclick: action.run }, action.label) : null));
    }

    function renderLoading() {
      results.setAttribute("aria-busy", "true");
      setChildren(results, 
        h("div", { "class": "results__head" }, heading("Finding tables")),
        loadingLine("Checking which tables are free..."),
        h("div", { "class": "skeleton card", "aria-hidden": "true" },
          h("div", { "class": "skeleton__row" }), h("div", { "class": "skeleton__row" }),
          h("div", { "class": "skeleton__row" })));
    }

    function showRefreshing() {
      var head = results.querySelector(".results__head");
      if (!head || head.querySelector(".results__refresh")) return;
      head.appendChild(h("p", { "class": "results__refresh", role: "status" },
        icon("spinner", "spinner"), "Updating availability..."));
    }

    function showSearchRefusal(answer) {
      if (answer.code === "not_found") {
        showState("error", "Restaurant not found", "This restaurant is no longer taking bookings. Choose another one.");
      } else {
        showState("error", "Check your search", "Choose a valid date and the number of guests, then search again.");
      }
    }

    function legend() {
      function item(cls, iconName, text) {
        return h("li", { "class": "legend__item" },
          h("span", { "class": "legend__swatch cell " + cls }, icon(iconName)), text);
      }
      return h("ul", { "class": "legend", "aria-label": "Key" },
        item("cell--available", "plus", "Free"),
        item("cell--selected", "check", "Selected"),
        item("cell--unavailable", "dash", "Not available"),
        item("cell--mine", "check", "Your booking"));
    }

    function pairsOffered(restaurant, slots) {
      if (Array.isArray(restaurant.combinable) && restaurant.combinable.length) return true;
      return slots.some(function (slot) { return pairOptions(slot).length > 0; });
    }

    function pairOptions(slot) {
      return (slot.available_options || []).filter(function (option) {
        return Array.isArray(option.table_ids) && option.table_ids.length === 2;
      });
    }

    function renderGrid() {
      var restaurant = view.restaurant;
      var tables = restaurant.tables || [];
      results.setAttribute("aria-busy", "false");
      var head = h("div", { "class": "results__head" },
        h("div", null, heading(restaurant.name),
          h("p", { "class": "results__meta" }, formatDate(view.date) + " \u00b7 " + guests(view.partySize) +
            " \u00b7 times in " + restaurant.timezone)),
        view.slots.length ? legend() : null);

      if (!view.slots.length) {
        setChildren(results, head, h("div", { "class": "state", "data-testid": "no-slots" },
          icon("calendar", "state__icon"),
          h("h3", { "class": "state__title" }, "No tables on this day"),
          h("p", { "class": "state__text" }, restaurant.name + " isn't taking bookings on " +
            formatDate(view.date) + ". Try another date.")));
        return;
      }

      var withPairs = pairsOffered(restaurant, view.slots);
      var anyFree = false;
      var rows = view.slots.map(function (slot) {
        var time = timeOf(slot.starts_at_local);
        var free = slot.available_table_ids || [];
        var cells = tables.map(function (table) {
          var open = free.indexOf(table.id) !== -1;
          anyFree = anyFree || open;
          return h("td", null, open ? availableCell(slot, [table.id], time) : unavailableCell(slot, table, time));
        });
        var combos = null;
        if (withPairs) {
          var options = pairOptions(slot);
          anyFree = anyFree || options.length > 0;
          combos = h("td", { "class": "grid__combos" }, options.length
            ? h("div", { "class": "grid__combo-list" }, options.map(function (option) {
              return availableCell(slot, option.table_ids, time);
            }))
            : h("span", { "class": "grid__none" }, h("span", { "aria-hidden": "true" }, "\u2013"),
              h("span", { "class": "visually-hidden" }, "No joined tables free")));
        }
        return h("tr", null, h("th", { scope: "row" }, time), cells, combos);
      });

      var columns = [h("th", { scope: "col" }, "Time")].concat(tables.map(function (table) {
        return h("th", { scope: "col" },
          h("span", { "class": "grid__table-name" }, tablesLabel(restaurant, [table.id])),
          h("span", { "class": "grid__table-seats" }, "Seats " + table.capacity));
      }));
      if (withPairs) {
        columns.push(h("th", { scope: "col" },
          h("span", { "class": "grid__table-name" }, "Joined tables"),
          h("span", { "class": "grid__table-seats" }, "For larger parties")));
      }

      var scroller = h("div", {
        "class": "grid-scroll", role: "region", tabindex: "0",
        "aria-label": "Availability at " + restaurant.name, "data-testid": "availability-grid"
      }, h("table", { "class": "grid" },
        h("caption", { "class": "visually-hidden" }, "Free tables at " + restaurant.name + " on " +
          formatDate(view.date) + " for " + guests(view.partySize)),
        h("thead", null, h("tr", null, columns)),
        h("tbody", null, rows)));
      var hint = h("p", { "class": "grid-hint", hidden: true }, "Swipe sideways to see every table.");
      setChildren(results, head,
        anyFree ? null : notice("info", "info", "Fully booked for " + guests(view.partySize),
          "Every table is taken or too small at these times. Try another date or fewer guests."),
        hint, scroller);
      if (scroller.scrollWidth > scroller.clientWidth + 1) hint.hidden = false;
    }

    function isSelected(slot, ids) {
      return !!booking && booking.startsAtLocal === slot.starts_at_local &&
        booking.tableIds.join("+") === ids.join("+");
    }

    function availableCell(slot, ids, time) {
      var restaurant = view.restaurant;
      var selected = isSelected(slot, ids);
      var pair = ids.length > 1;
      var label = tablesLabel(restaurant, ids);
      var content = pair
        ? h("span", { "class": "cell__text" }, h("span", null, label),
          h("span", { "class": "cell__sub" }, "Seats " + seats(restaurant, ids)))
        : h("span", null, selected ? "Selected" : "Free");
      return h("button", {
        type: "button",
        "class": "cell cell--available" + (pair ? " cell--combo" : "") + (selected ? " cell--selected" : ""),
        "data-testid": "slot-" + ids.join("+") + "-" + time,
        "data-available": "true",
        "aria-pressed": selected ? "true" : "false",
        "aria-label": label + " at " + time + (pair ? ", seats " + seats(restaurant, ids) : "") + ", free",
        onclick: function () { selectSlot(slot, ids); }
      }, icon(selected ? "check" : "plus"), content);
    }

    function unavailableCell(slot, table, time) {
      var yours = heldByMe(slot, table.id);
      var tooSmall = table.capacity < view.partySize;
      var text = yours ? "Yours" : (tooSmall ? "Too small" : "Booked");
      return h("span", {
        "class": "cell " + (yours ? "cell--mine" : "cell--unavailable"),
        "data-testid": "slot-" + table.id + "-" + time,
        "data-available": "false",
        title: tablesLabel(view.restaurant, [table.id]) + " at " + time + ": " +
          (yours ? "your booking" : (tooSmall ? "too small for your party" : "already booked"))
      }, icon(yours ? "check" : "dash"), h("span", null, text));
    }

    // True when a booking confirmed on this page occupies this table during this slot.
    function heldByMe(slot, tableId) {
      var duration = (view.restaurant.reservation_duration_minutes || 0) * 60000;
      var slotStart = Date.parse(slot.starts_at);
      return Object.keys(mine).some(function (reference) {
        var r = mine[reference];
        if (r.restaurant_id !== view.restaurant.id || reservationTableIds(r).indexOf(tableId) === -1) return false;
        var start = Date.parse(r.starts_at);
        var end = r.ends_at ? Date.parse(r.ends_at) : start + duration;
        return slotStart < end && start < slotStart + duration;
      });
    }

    // ------------------------------------------------------------ booking form

    function selectSlot(slot, ids) {
      if (!session.get()) {
        showAuthError();
        return;
      }
      removeAuthError();
      // Switching to another table keeps whatever the diner typed for the party size.
      var party = booking ? booking.partyInput.value : String(view.partySize);
      openBooking(slot, ids, party);
    }

    function showAuthError() {
      removeAuthError();
      results.insertBefore(notice("error", "lock", "Sign in to book this table",
        ["Booking needs an account. ", signInLink("/"), " or ",
          h("a", { href: "/signup" }, "create an account"), ", then choose your table."],
        "auth-error"), results.firstChild);
    }

    function removeAuthError() {
      var existing = results.querySelector('[data-testid="auth-error"]');
      if (existing) existing.parentNode.removeChild(existing);
    }

    function closeBooking() {
      booking = null;
      setChildren(panel);
      workspace.classList.remove("workspace--booking");
      removeAuthError();
    }

    function openBooking(slot, ids, party) {
      var restaurant = view.restaurant;
      var partyInput = h("input", {
        "class": "input booking__party", id: "booking-party", type: "number", min: "1", step: "1",
        inputmode: "numeric", value: party, "data-testid": "booking-party-size"
      });
      var status = h("div", { "class": "booking__status" });
      var submit = h("button", {
        type: "submit", "class": "button button--primary button--block", "data-testid": "booking-submit"
      }, "Confirm booking");
      var title = h("h2", { "class": "booking__title", tabindex: "-1" },
        ids.length > 1 ? "Book these tables" : "Book this table");
      var form = h("form", {
        "class": "booking card", "data-testid": "booking-form", novalidate: true, "aria-labelledby": "booking-title"
      }, title,
      h("div", { "class": "booking-summary", "data-testid": "booking-summary" },
        h("p", { "class": "booking-summary__tables" },
          tablesLabel(restaurant, ids) + " \u00b7 seats " + seats(restaurant, ids)),
        h("p", { "class": "booking-summary__when" }, whenText(slot.starts_at_local)),
        h("p", { "class": "booking-summary__where" }, restaurant.name)),
      h("div", { "class": "field" },
        h("label", { "class": "field__label", "for": "booking-party" }, "Guests"), partyInput),
      status,
      h("div", { "class": "booking__actions" }, submit));
      title.id = "booking-title";
      var confirmation = h("div", null);

      booking = {
        restaurant: restaurant, tableIds: ids.slice(), startsAtLocal: slot.starts_at_local,
        form: form, partyInput: partyInput, status: status, submit: submit, confirmation: confirmation,
        fingerprint: null, body: null, key: null, busy: false
      };
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        submitBooking(booking);
      });
      setChildren(panel, form, confirmation);
      workspace.classList.add("workspace--booking");
      renderGrid();
      reveal(title);
    }

    function setBusy(b, busy) {
      b.busy = busy;
      b.submit.disabled = busy;
      b.form.setAttribute("aria-busy", busy ? "true" : "false");
      if (busy) setChildren(b.submit, icon("spinner", "spinner"), "Booking...");
    }

    function setSubmitLabel(b, text) { setChildren(b.submit, text); }

    function submitBooking(b) {
      if (!b || b.busy) return;
      var party = b.partyInput.value.trim();
      if (!/^\d+$/.test(party) || Number(party) < 1) {
        showBookingError(b, "Check the number of guests", "Enter how many guests are coming, as a whole number of at least 1.");
        return;
      }
      var body = { restaurant_id: b.restaurant.id };
      if (b.tableIds.length === 1) body.table_id = b.tableIds[0];
      else body.table_ids = b.tableIds.slice();
      body.starts_at_local = b.startsAtLocal;
      body.party_size = Number(party);
      // One idempotency key per distinct request body: an unchanged form repeats
      // the same request, so retries and resubmits can only ever replay it.
      var fingerprint = JSON.stringify(body);
      if (fingerprint !== b.fingerprint) {
        b.fingerprint = fingerprint;
        b.body = body;
        b.key = newIdempotencyKey();
      }
      setBusy(b, true);
      api("POST", "/reservations", { body: b.body, key: b.key, auth: true }).then(function (res) {
        if (booking !== b) return;  // the diner moved on to another table meanwhile
        setBusy(b, false);
        if (res.status === 200 || res.status === 201) {
          showConfirmed(b, res.data);
          return;
        }
        if (res.status === 401) {
          showBookingError(b, "Please sign in again",
            ["Your session has ended, so the booking was not made. ", signInLink("/", "Sign in"), " and try again."]);
          return;
        }
        var message = bookingRefusal(b, res);
        showBookingError(b, message[0], message[1]);
        if (res.code === "table_unavailable" && view) runSearch(view.query, true);
      }, function () {
        if (booking !== b) return;
        setBusy(b, false);
        showUncertain(b);
      });
    }

    function bookingRefusal(b, res) {
      var r = b.restaurant;
      var label = tablesLabel(r, b.tableIds);
      var time = timeOf(b.startsAtLocal);
      switch (res.code) {
        case "table_unavailable":
          return ["Just booked by someone else", label + " is no longer free at " + time +
            ". The grid has been updated: choose another table or time. Your details are kept."];
        case "party_exceeds_capacity":
          return ["Too many guests for this table", label + " seats " + seats(r, b.tableIds) +
            ". Choose a larger table or joined tables."];
        case "outside_opening_hours":
          return ["Outside opening hours", r.name + " can't seat a full booking at " + time + "."];
        case "not_on_slot_grid":
          return ["Not a bookable time", "Bookings start at the times shown in the grid."];
        case "invalid_local_time":
          return ["That time doesn't exist", "The clocks change on this date, so " + time + " is skipped."];
        case "combination_not_allowed":
          return ["These tables can't be joined", "Choose one of the joined options shown in the grid."];
        case "not_found":
          return ["No longer available", "This restaurant or table can't be booked any more. Please search again."];
        case "validation_failed":
          return ["Check your booking", "Enter how many guests are coming, as a whole number of at least 1."];
        default:
          return ["Booking not made", "Tablekeeper couldn't make this booking. Please try again."];
      }
    }

    function showBookingError(b, title, body) {
      setChildren(b.confirmation);
      setChildren(b.status, notice("error", "alert", title, body, "booking-error"));
      setSubmitLabel(b, "Confirm booking");
    }

    function showUncertain(b) {
      setChildren(b.confirmation);
      setChildren(b.status, notice("uncertain", "question", "We couldn't confirm this booking",
        "The connection dropped before Tablekeeper replied, so the table may or may not be booked. " +
        "Press \u201cTry again\u201d to check: it is safe and will never book twice.", "booking-uncertain"));
      setSubmitLabel(b, "Try again");
    }

    function showConfirmed(b, reservation) {
      var ids = reservationTableIds(reservation);
      var known = ids.every(function (id) { return findTable(b.restaurant, id); }) &&
        reservation.restaurant_id === b.restaurant.id;
      var restaurantReady = known ? Promise.resolve(b.restaurant) : loadRestaurant(reservation.restaurant_id, true);
      return restaurantReady.then(function (restaurant) {
        if (booking !== b) return;
        var r = restaurant || b.restaurant;
        mine[reservation.reference] = reservation;
        setChildren(b.status);
        setSubmitLabel(b, "Confirm booking");
        var section = h("section", {
          "class": "confirmation card", "data-testid": "confirmation", tabindex: "-1",
          role: "status", "aria-labelledby": "confirmation-title"
        },
        h("p", { "class": "confirmation__badge", id: "confirmation-title" }, icon("check"), "Booking confirmed"),
        h("p", { "class": "confirmation__label" }, "Your reference"),
        h("p", { "class": "confirmation__reference", "data-testid": "confirmation-reference" }, reservation.reference),
        h("div", { "class": "confirmation__details", "data-testid": "confirmation-details" },
          h("p", { "class": "confirmation__restaurant" }, r.name),
          h("p", { "data-testid": "confirmation-tables" }, tablesLabel(r, ids)),
          h("p", null, whenText(reservation.starts_at_local)),
          h("p", null, guests(reservation.party_size))),
        h("p", { "class": "confirmation__note" },
          "Keep this reference to look up or cancel your booking. ",
          h("a", { href: "/lookup?reference=" + encodeURIComponent(reservation.reference) }, "Manage booking")));
        setChildren(b.confirmation, section);
        reveal(section);
        if (view) runSearch(view.query, true);
      });
    }
  }

  // ---------------------------------------------------------------- auth screens

  function nextTarget() {
    var next = new URLSearchParams(window.location.search).get("next");
    if (next && next.charAt(0) === "/" && next.charAt(1) !== "/" && next.charAt(1) !== "\\") return next;
    return "/";
  }

  function initAuthForm(kind) {
    var form = byId(kind + "-form");
    var messages = byId("auth-messages");
    var submit = form.querySelector('button[type="submit"]');
    var submitText = submit.textContent;
    var fields = kind === "signup"
      ? { display_name: "signup-display-name", email: "signup-email", password: "signup-password" }
      : { email: "login-email", password: "login-password" };
    var busy = false;

    var current = session.get();
    if (current) {
      setChildren(messages, notice("info", "info", null,
        "You're signed in as " + (current.display_name || "a guest") + ". Signing in again switches account."));
    }

    function showError(title, body) {
      setChildren(messages, notice("error", "alert", title, body, "auth-error"));
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (busy) return;
      var body = {};
      Object.keys(fields).forEach(function (name) { body[name] = byId(fields[name]).value; });
      body.email = body.email.trim();
      var missing = Object.keys(body).some(function (name) { return !body[name]; });
      if (missing) {
        showError("Fill in every field", kind === "signup"
          ? "Enter your name, your email address and a password of at least 8 characters."
          : "Enter the email address and password for your account.");
        return;
      }
      busy = true;
      submit.disabled = true;
      setChildren(submit, icon("spinner", "spinner"), kind === "signup" ? "Creating account..." : "Signing in...");
      api("POST", kind === "signup" ? "/auth/signup" : "/auth/login", { body: body }).then(function (res) {
        if (res.ok && res.data && res.data.token) {
          session.set(res.data);
          window.location.assign(nextTarget());
          return;
        }
        if (res.code === "email_taken") {
          showError("That email already has an account", ["Try ", h("a", { href: "/login" }, "signing in"), " instead."]);
        } else if (kind === "login") {
          showError("Email or password is incorrect", "Check them and try again.");
        } else {
          showError("Check your details", "Use a valid email address like name@example.com, a password of at least 8 characters and your name.");
        }
      }, function () {
        showError("We couldn't reach Tablekeeper", "Check your connection and try again.");
      }).finally(function () {
        busy = false;
        submit.disabled = false;
        setChildren(submit, submitText);
      });
    });
  }

  // ---------------------------------------------------------------- lookup screen

  function initLookup() {
    var form = byId("lookup-form");
    var input = byId("lookup-reference");
    var out = byId("lookup-result");
    var announcer = byId("lookup-announcer");
    var seq = 0;
    var current = null;  // { reservation, restaurant }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      lookUp(input.value.trim());
    });

    document.addEventListener("tk:signedout", function () {
      seq += 1;
      current = null;
      setChildren(out);
    });

    var preset = new URLSearchParams(window.location.search).get("reference");
    if (preset) {
      input.value = preset;
      if (session.get()) lookUp(preset.trim());
    }

    function showError(title, body) {
      current = null;
      setChildren(out, notice("error", "alert", title, body, "reservation-error"));
    }

    function lookUp(reference) {
      seq += 1;
      var mySeq = seq;
      if (!reference) {
        showError("Enter a booking reference", "You'll find it on your confirmation, for example K3P7QW.");
        return;
      }
      if (!session.get()) {
        showError("Sign in to look up a booking",
          [signInLink("/lookup?reference=" + encodeURIComponent(reference)), " to see the reservations made with your account."]);
        return;
      }
      setChildren(out, loadingLine("Looking up " + reference + "..."));
      api("GET", "/reservations/" + encodeURIComponent(reference), { auth: true }).then(function (res) {
        if (mySeq !== seq) return null;
        if (res.status === 401) {
          showError("Please sign in again", ["Your session has ended. ",
            signInLink("/lookup?reference=" + encodeURIComponent(reference)), " to look up this booking."]);
          return null;
        }
        if (!res.ok) {
          showError("No booking found", "There's no reservation with reference " + reference +
            " on your account. Check the reference and try again.");
          return null;
        }
        return loadRestaurant(res.data.restaurant_id).then(function (restaurant) {
          if (mySeq !== seq) return;
          current = { reservation: res.data, restaurant: restaurant };
          renderReservation(null);
          announcer.textContent = "Found reservation " + res.data.reference + ", " + res.data.status + ".";
        });
      }, function () {
        if (mySeq === seq) showError("We couldn't reach Tablekeeper", "Check your connection and try again.");
      });
    }

    function renderReservation(problem) {
      var r = current.reservation;
      var restaurant = current.restaurant;
      var ids = reservationTableIds(r);
      var confirmed = r.status === "confirmed";
      var actions;
      if (confirmed) {
        var cutoff = restaurant ? restaurant.cancellation_cutoff_minutes : null;
        actions = h("div", { "class": "reservation__actions" },
          h("button", {
            type: "button", "class": "button button--danger", "data-testid": "reservation-cancel-button",
            onclick: function (event) { cancel(event.currentTarget); }
          }, "Cancel reservation"),
          typeof cutoff === "number" && cutoff > 0
            ? h("p", { "class": "field__hint" }, "Free cancellation until " + formatMinutes(cutoff) + " before the booking.")
            : null);
      } else {
        actions = notice("info", "info", null, "This reservation is cancelled. The table is free for other guests.");
      }
      setChildren(out, h("article", {
        "class": "reservation card", "data-testid": "reservation-detail", "aria-labelledby": "reservation-heading"
      },
      h("div", { "class": "reservation__head" },
        h("div", null,
          h("p", { "class": "eyebrow", id: "reservation-heading" }, "Reservation"),
          h("p", { "class": "reservation__reference" }, r.reference)),
        h("p", { "class": "status status--" + (confirmed ? "confirmed" : "cancelled") },
          icon(confirmed ? "check" : "x"), h("span", { "data-testid": "reservation-status" }, r.status))),
      h("dl", { "class": "reservation__facts" },
        h("dt", null, "Restaurant"), h("dd", null, restaurant ? restaurant.name : r.restaurant_id),
        h("dt", null, ids.length > 1 ? "Tables" : "Table"),
        h("dd", { "data-testid": "reservation-tables" }, tablesLabel(restaurant, ids)),
        h("dt", null, "When"), h("dd", null, whenText(r.starts_at_local)),
        h("dt", null, "Guests"), h("dd", null, String(r.party_size))),
      problem,
      actions));
    }

    function cancel(button) {
      var mySeq = seq;
      var r = current.reservation;
      button.disabled = true;
      setChildren(button, icon("spinner", "spinner"), "Cancelling...");
      api("POST", "/reservations/" + encodeURIComponent(r.reference) + "/cancel", { auth: true }).then(function (res) {
        if (mySeq !== seq) return;
        if (res.ok) {
          current.reservation = res.data;
          renderReservation(null);
          announcer.textContent = "Reservation " + r.reference + " is cancelled.";
          return;
        }
        if (res.status === 401) {
          showError("Please sign in again", ["Your session has ended, so nothing was cancelled. ",
            signInLink("/lookup?reference=" + encodeURIComponent(r.reference)), " to try again."]);
          return;
        }
        var restaurant = current.restaurant;
        var text = res.code === "cutoff_passed"
          ? ["Too late to cancel online", "This booking starts within " + (restaurant ? restaurant.name + "'s " : "the ") +
            "cancellation window" + (restaurant ? " of " + formatMinutes(restaurant.cancellation_cutoff_minutes) : "") +
            ", so it can no longer be cancelled here."]
          : ["Cancellation not made", "Tablekeeper couldn't cancel this booking. Please look it up again."];
        renderReservation(notice("error", "alert", text[0], text[1], "reservation-error"));
      }, function () {
        if (mySeq !== seq) return;
        renderReservation(notice("error", "alert", "We couldn't confirm the cancellation",
          "The connection dropped. Press Cancel reservation again to retry: cancelling twice is safe.", "reservation-error"));
      });
    }
  }

  // ---------------------------------------------------------------- start

  renderAccount();
  var screen = document.body.getAttribute("data-screen");
  if (screen === "search") initSearch();
  else if (screen === "signup" || screen === "login") initAuthForm(screen);
  else if (screen === "lookup") initLookup();
})();
