/* Tablekeeper extras: shared helpers for the evening, passport, notifications,
 * control-room and simulator screens. Plain DOM and fetch, no dependencies.
 *
 * Every number shown on these screens comes from a server response; nothing is
 * estimated in the browser. Money is integer minor units, formatted for display only.
 */
(function () {
  "use strict";

  var SESSION_KEY = "tablekeeper.session";
  var REQUEST_TIMEOUT_MS = 12000;
  var SVG_NS = "http://www.w3.org/2000/svg";

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

  function setChildren(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
    append(el, Array.prototype.slice.call(arguments, 1));
  }

  var ICONS = {
    check: ["M5 12.5l4.5 4.5L19 7.5"],
    x: ["M6.5 6.5l11 11", "M17.5 6.5l-11 11"],
    alert: ["M12 3.8l9 16H3z", "M12 10v4.2", "M12 17.3v.2"],
    info: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 11v5.5", "M12 7.8v.2"],
    question: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M9.6 9.4a2.5 2.5 0 1 1 3.4 2.4c-.6.3-1 .8-1 1.4v.6",
               "M12 17v.2"],
    spinner: ["M12 3a9 9 0 1 1-9 9"],
    calendar: ["M4.5 6h15v13.5h-15z", "M4.5 10h15", "M8.5 3.5v4", "M15.5 3.5v4"],
    clock: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 7.5V12l3 2"],
    users: ["M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z", "M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5",
            "M16 4.5a3.5 3.5 0 0 1 0 6.5", "M18 14.8c1.9.7 3.1 2.4 3.5 5.2"],
    table: ["M4 9h16", "M6 9v9", "M18 9v9", "M9 9V6h6v3"],
    shield: ["M12 3l7.5 3v5.5c0 4.6-3.2 8.2-7.5 9.5-4.3-1.3-7.5-4.9-7.5-9.5V6z", "M9 12l2 2 4-4"],
    coin: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M14.8 9.2c-.5-.9-1.6-1.4-2.8-1.4-1.6 0-2.8.9-2.8 2.1 0 2.9 5.6 1.3 5.6 4.2 0 1.2-1.2 2.1-2.8 2.1-1.2 0-2.3-.5-2.8-1.4",
           "M12 6v1.8", "M12 16.2V18"],
    bell: ["M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z", "M10 20.5a2.2 2.2 0 0 0 4 0"],
    share: ["M12 15V4", "M8 8l4-4 4 4", "M5 12v7.5h14V12"],
    copy: ["M8 8h11v12H8z", "M5 16V4h11"],
    download: ["M12 4v11", "M8 11l4 4 4-4", "M5 19.5h14"],
    refresh: ["M19.5 12a7.5 7.5 0 1 1-2.2-5.3", "M19.5 4.5v4h-4"],
    arrow: ["M5 12h14", "M13 6l6 6-6 6"],
    heart: ["M12 20s-7.5-4.5-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.5-7.5 10-7.5 10z"],
    map: ["M12 21s6-5.4 6-10.5a6 6 0 0 0-12 0C6 15.6 12 21 12 21z", "M12 12.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4z"],
    lock: ["M6 11h12v9H6z", "M8.5 11V8a3.5 3.5 0 0 1 7 0v3"],
    wifi: ["M2.5 9a14 14 0 0 1 19 0", "M5.5 12.5a9.5 9.5 0 0 1 13 0", "M8.8 16a5 5 0 0 1 6.4 0", "M12 19.5v.2"],
    pause: ["M8 5v14", "M16 5v14"],
    tool: ["M14.5 6.5a4 4 0 0 0-5.3 5.3L4 17l3 3 5.2-5.2a4 4 0 0 0 5.3-5.3l-2.6 2.6-2.4-.6-.6-2.4z"]
  };

  function icon(name, extraClass) {
    var svg = document.createElementNS(SVG_NS, "svg");
    var attrs = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2",
                  "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true",
                  focusable: "false", "class": "icon" + (extraClass ? " " + extraClass : "") };
    Object.keys(attrs).forEach(function (k) { svg.setAttribute(k, attrs[k]); });
    (ICONS[name] || ICONS.info).forEach(function (d) {
      var path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", d);
      svg.appendChild(path);
    });
    return svg;
  }

  /* kind: error | uncertain | info | success | offline. Errors are alerts, the rest polite. */
  function notice(kind, iconName, title, body, testId) {
    return h("div", {
      "class": "notice notice--" + kind, role: kind === "error" ? "alert" : "status", "data-testid": testId
    }, icon(iconName), h("div", null,
      title ? h("strong", { "class": "notice__title" }, title) : null,
      body ? h("div", { "class": "notice__body" }, body) : null));
  }

  function badge(kind, iconName, text, testId) {
    return h("span", { "class": "x-badge x-badge--" + kind, "data-testid": testId },
      icon(iconName), h("span", null, text));
  }

  function loading(text) {
    return h("p", { "class": "loading", role: "status" }, icon("spinner", "spinner"), text);
  }

  function emptyState(iconName, title, text, action) {
    return h("div", { "class": "state x-empty" }, icon(iconName, "state__icon"),
      h("h2", { "class": "state__title" }, title), h("p", { "class": "state__text" }, text),
      action || null);
  }

  // ---------------------------------------------------------------- formatting

  var DATE_FORMAT = new Intl.DateTimeFormat("en-GB", {
    weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC"
  });
  var SHORT_DATE = new Intl.DateTimeFormat("en-GB", {
    weekday: "short", day: "numeric", month: "short", timeZone: "UTC"
  });

  function ymdToUtcDate(ymd) {
    var p = String(ymd || "").split("-").map(Number);
    return p.length === 3 && !p.some(isNaN) ? new Date(Date.UTC(p[0], p[1] - 1, p[2])) : null;
  }

  function formatDate(ymd) { var d = ymdToUtcDate(ymd); return d ? DATE_FORMAT.format(d) : String(ymd || ""); }
  function formatShortDate(ymd) { var d = ymdToUtcDate(ymd); return d ? SHORT_DATE.format(d) : String(ymd || ""); }
  function timeOf(local) { return String(local || "").slice(11, 16); }
  function dateOf(local) { return String(local || "").slice(0, 10); }
  function whenText(local) { return formatDate(dateOf(local)) + " at " + timeOf(local); }
  function guests(n) { return n === 1 ? "1 guest" : n + " guests"; }

  /* An RFC 3339 instant shown in the viewer's own time, e.g. "18 Sep, 12:04". */
  function stamp(rfc3339) {
    var t = Date.parse(rfc3339);
    if (isNaN(t)) return String(rfc3339 || "");
    return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit",
                                              minute: "2-digit" }).format(new Date(t));
  }

  var CURRENCY_SYMBOLS = { EUR: "\u20ac", GBP: "\u00a3", USD: "$" };

  /* Integer minor units to "EUR 15.00"-style text, without floating point. */
  function money(minor, currency) {
    if (typeof minor !== "number" || !isFinite(minor)) return "\u2013";
    var sign = minor < 0 ? "-" : "";
    var abs = Math.abs(Math.trunc(minor));
    var units = Math.floor(abs / 100);
    var cents = String(abs % 100).padStart(2, "0");
    var grouped = String(units).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    var symbol = CURRENCY_SYMBOLS[currency];
    return sign + (symbol ? symbol : (currency || "") + " ") + grouped + "." + cents;
  }

  function isNumeric(text) { return /^\d+$/.test(String(text)); }

  function tableText(labels) {
    labels = (labels || []).map(String);
    if (!labels.length) return "\u2013";
    if (labels.length === 1) return isNumeric(labels[0]) ? "Table " + labels[0] : labels[0];
    if (labels.every(isNumeric)) return "Tables " + labels.join(" + ");
    return labels.map(function (l) { return isNumeric(l) ? "Table " + l : l; }).join(" + ");
  }

  function minutesText(total) {
    if (typeof total !== "number") return "";
    if (total >= 1440 && total % 1440 === 0) return plural(total / 1440, "day");
    if (total >= 60 && total % 60 === 0) return plural(total / 60, "hour");
    return plural(total, "minute");
  }

  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }

  function todayISO() {
    var d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" +
      String(d.getDate()).padStart(2, "0");
  }

  /* The UTC offset (minutes) of an IANA zone at an instant, via Intl. */
  function zoneOffsetMinutes(zone, epochMs) {
    var parts = new Intl.DateTimeFormat("en-US", {
      timeZone: zone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit"
    }).formatToParts(new Date(epochMs));
    var v = {};
    parts.forEach(function (p) { v[p.type] = Number(p.value); });
    var asUtc = Date.UTC(v.year, v.month - 1, v.day, v.hour, v.minute, v.second);
    return Math.round((asUtc - epochMs) / 60000);
  }

  /* Local "YYYY-MM-DD" + "HH:MM" in a zone to RFC 3339 with that zone's offset. */
  function zonedInstant(ymd, hhmm, zone) {
    var d = ymdToUtcDate(ymd);
    var hm = String(hhmm).split(":").map(Number);
    var wall = d.getTime() + (hm[0] * 60 + hm[1]) * 60000;
    var offset = zoneOffsetMinutes(zone, wall);
    offset = zoneOffsetMinutes(zone, wall - offset * 60000);
    var sign = offset < 0 ? "-" : "+";
    var abs = Math.abs(offset);
    return ymd + "T" + hhmm + ":00" + sign + String(Math.floor(abs / 60)).padStart(2, "0") + ":" +
      String(abs % 60).padStart(2, "0");
  }

  // ---------------------------------------------------------------- session and API

  var session = {
    get: function () {
      try {
        var stored = JSON.parse(window.localStorage.getItem(SESSION_KEY) || "null");
        return stored && typeof stored.token === "string" && stored.token ? stored : null;
      } catch (e) { return null; }
    }
  };

  function Uncertain(reason) { this.reason = reason; }

  /* fetch with a timeout. Network failures, 5xx and unreadable bodies are Uncertain.
   * opts.raw returns the Response body as a Blob (calendar files). */
  function api(method, path, options) {
    var opts = options || {};
    var headers = { "Accept": opts.raw ? "*/*" : "application/json" };
    var init = { method: method, headers: headers, cache: "no-store", credentials: "same-origin" };
    if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    if (opts.key) headers["Idempotency-Key"] = opts.key;
    if (opts.auth !== false) {
      var current = session.get();
      if (current) headers["Authorization"] = "Bearer " + current.token;
    }
    var controller = new AbortController();
    init.signal = controller.signal;
    var timer = setTimeout(function () { controller.abort(); }, opts.timeout || REQUEST_TIMEOUT_MS);
    var status = 0;
    var contentType = "";
    return fetch(path, init)
      .catch(function () { throw new Uncertain("network"); })
      .then(function (response) {
        status = response.status;
        contentType = response.headers.get("Content-Type") || "";
        if (opts.raw && response.ok) return response.blob();
        return response.text();
      })
      .catch(function (err) { throw err instanceof Uncertain ? err : new Uncertain("body"); })
      .then(function (payload) {
        if (status >= 500) throw new Uncertain("server");
        if (opts.raw && status >= 200 && status < 300) {
          return { status: status, ok: true, blob: payload, contentType: contentType };
        }
        var data = null;
        if (payload) {
          try { data = JSON.parse(payload); } catch (e) { throw new Uncertain("unreadable"); }
        }
        return { status: status, ok: status >= 200 && status < 300, data: data,
                 code: data && data.error ? data.error.code : null,
                 message: data && data.error ? data.error.message : null };
      })
      .finally(function () { clearTimeout(timer); });
  }

  function newKey(prefix) {
    var bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    return (prefix || "x") + "-" + Array.prototype.map.call(bytes, function (b) {
      return b.toString(16).padStart(2, "0");
    }).join("");
  }

  /* A write that is safe to retry: one key per distinct body, reused until it changes. */
  function KeyedWriter(prefix) {
    this.prefix = prefix;
    this.fingerprint = null;
    this.key = null;
  }
  KeyedWriter.prototype.keyFor = function (path, body) {
    var fingerprint = path + " " + JSON.stringify(body === undefined ? null : body);
    if (fingerprint !== this.fingerprint) {
      this.fingerprint = fingerprint;
      this.key = newKey(this.prefix);
    }
    return this.key;
  };

  function signInGate(container, next, title, text) {
    setChildren(container, emptyState("lock", title || "Sign in to continue",
      text || "This page shows details from your account.",
      h("a", { "class": "button button--primary", href: "/login?next=" + encodeURIComponent(next) },
        "Sign in")));
  }

  function failureNotice(err, testId) {
    if (err instanceof Uncertain) {
      return notice("offline", "wifi", "We couldn't reach Tablekeeper",
        "Your connection or the service may be down. Nothing was changed on this page; try again in a moment.",
        testId);
    }
    return notice("error", "alert", "Something went wrong", String(err && err.message || err), testId);
  }

  /* An in-page confirmation, never window.confirm. Resolves true or false. */
  function confirmDialog(opts) {
    return new Promise(function (resolve) {
      var previous = document.activeElement;
      var title = h("h2", { "class": "x-dialog__title", id: "x-dialog-title" }, opts.title);
      var confirmButton = h("button", { type: "button", "class": "button " + (opts.danger ? "button--danger" : "button--primary"),
                                        "data-testid": "x-dialog-confirm" }, opts.confirm || "Confirm");
      var cancelButton = h("button", { type: "button", "class": "button", "data-testid": "x-dialog-cancel" },
        opts.cancel || "Keep as is");
      var dialog = h("div", { "class": "x-dialog", role: "dialog", "aria-modal": "true",
                              "aria-labelledby": "x-dialog-title", "data-testid": "x-dialog" },
        h("div", { "class": "x-dialog__panel card" }, title,
          h("p", { "class": "x-dialog__text" }, opts.text),
          h("div", { "class": "x-dialog__actions" }, cancelButton, confirmButton)));
      function close(result) {
        document.removeEventListener("keydown", onKey);
        dialog.parentNode.removeChild(dialog);
        if (previous && previous.focus) previous.focus();
        resolve(result);
      }
      function onKey(event) {
        if (event.key === "Escape") close(false);
        if (event.key === "Tab") {  // keep focus inside the dialog
          var first = cancelButton, last = confirmButton;
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
      }
      cancelButton.addEventListener("click", function () { close(false); });
      confirmButton.addEventListener("click", function () { close(true); });
      document.addEventListener("keydown", onKey);
      document.body.appendChild(dialog);
      cancelButton.focus();
    });
  }

  // ---------------------------------------------------------------- preferences form

  var DIETARY = ["vegetarian", "vegan", "pescatarian", "gluten-free", "dairy-free", "nut-free",
                 "halal", "kosher"];
  var ACCESS = ["step-free access", "wheelchair space", "hearing support", "high chair"];
  var OCCASIONS = ["", "birthday", "anniversary", "date night", "business", "celebration"];
  var SEATING = [["no_preference", "No preference"], ["indoor", "Indoors"], ["outdoor", "Outdoors"]];
  var CHANNELS = [["in_app", "In Tablekeeper"], ["email", "Email"], ["telegram", "Telegram"]];
  var formSeq = 0;

  /* "Make it yours": the preference fields as a form. onSave(prefs) returns a promise of
   * {ok, message}. Preferences are wishes for the restaurant, never promises. */
  function prefsForm(initial, opts) {
    formSeq += 1;
    var id = "prefs" + formSeq;
    var prefs = initial || {};
    var status = h("div", { "class": "x-status", "data-testid": opts.statusTestId || "prefs-status" });

    function chips(name, label, options, chosen) {
      var all = options.slice();
      (chosen || []).forEach(function (value) { if (all.indexOf(value) === -1) all.push(value); });
      return h("fieldset", { "class": "x-fieldset" }, h("legend", null, label),
        h("div", { "class": "x-chips" }, all.map(function (value) {
          return h("label", { "class": "x-chip" },
            h("input", { type: "checkbox", name: name, value: value,
                         checked: (chosen || []).indexOf(value) !== -1 }), value);
        })));
    }

    function field(label, control, hint) {
      return h("div", { "class": "field" },
        h("label", { "class": "field__label", "for": control.id }, label), control,
        hint ? h("p", { "class": "field__hint" }, hint) : null);
    }

    var allergies = h("textarea", { "class": "input", id: id + "-allergies", maxlength: "300",
                                    "data-testid": "prefs-allergies" });
    allergies.value = prefs.allergies || "";
    var occasion = h("select", { "class": "input", id: id + "-occasion", "data-testid": "prefs-occasion" },
      OCCASIONS.concat(prefs.occasion && OCCASIONS.indexOf(prefs.occasion) === -1 ? [prefs.occasion] : [])
        .map(function (value) {
          return h("option", { value: value, selected: (prefs.occasion || "") === value },
            value ? value.charAt(0).toUpperCase() + value.slice(1) : "Nothing in particular");
        }));
    var seating = h("fieldset", { "class": "x-fieldset" }, h("legend", null, "Seating"),
      h("div", { "class": "x-chips" }, SEATING.map(function (pair) {
        return h("label", { "class": "x-chip" },
          h("input", { type: "radio", name: id + "-seating", value: pair[0],
                       checked: (prefs.seating || "no_preference") === pair[0] }), pair[1]);
      })));
    var quiet = h("label", { "class": "x-chip" },
      h("input", { type: "checkbox", name: "quiet", checked: !!prefs.quiet, "data-testid": "prefs-quiet" }),
      "A quieter table, if possible");
    var celebration = h("input", { "class": "input", id: id + "-celebration", maxlength: "200",
                                   "data-testid": "prefs-celebration" });
    celebration.value = prefs.celebration_note || "";
    var note = h("textarea", { "class": "input", id: id + "-note", maxlength: "500", "data-testid": "prefs-note" });
    note.value = prefs.note || "";
    var channel = null;
    if (opts.withChannel) {
      channel = h("select", { "class": "input", id: id + "-channel", "data-testid": "prefs-channel" },
        CHANNELS.map(function (pair) {
          return h("option", { value: pair[0], selected: (prefs.channel || "in_app") === pair[0] }, pair[1]);
        }));
    }
    var save = h("button", { type: "submit", "class": "button button--primary", "data-testid": "prefs-save",
                             disabled: opts.disabled }, opts.saveLabel || "Save preferences");
    var form = h("form", { "class": "x-form", novalidate: true, "data-testid": opts.testId || "prefs-form" },
      chips("dietary", "Dietary", DIETARY, prefs.dietary),
      field("Allergies", allergies, "Up to 300 characters. The kitchen sees exactly what you write."),
      chips("accessibility", "Access needs", ACCESS, prefs.accessibility),
      h("div", { "class": "x-form__row" }, field("Occasion", occasion), field("Celebration note", celebration)),
      seating, quiet,
      field("Anything else", note, "Up to 500 characters."),
      channel ? field("How should we reach you?", channel, "Email and Telegram are simulated unless the restaurant has set them up.") : null,
      h("p", { "class": "x-hint" }, "We'll do our best. The restaurant sees these wishes, but they can't be guaranteed."),
      h("div", { "class": "x-actions" }, save), status);

    function checked(name) {
      return Array.prototype.filter.call(form.querySelectorAll('input[name="' + name + '"]'),
        function (input) { return input.checked; }).map(function (input) { return input.value; });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (save.disabled) return;
      var body = {
        dietary: checked("dietary"), allergies: allergies.value, accessibility: checked("accessibility"),
        occasion: occasion.value, seating: (form.querySelector('input[name="' + id + '-seating"]:checked') || {}).value || "no_preference",
        quiet: form.querySelector('input[name="quiet"]').checked,
        celebration_note: celebration.value, note: note.value
      };
      if (channel) body.channel = channel.value;
      save.disabled = true;
      setChildren(status, loading("Saving..."));
      opts.onSave(body).then(function (outcome) {
        setChildren(status, outcome.ok
          ? notice("success", "check", "Saved", "We'll do our best to make it happen.", "prefs-saved")
          : notice("error", "alert", "Not saved", outcome.message || "Please check the details.", "prefs-error"));
      }, function (err) {
        setChildren(status, failureNotice(err, "prefs-error"));
      }).finally(function () { save.disabled = !!opts.disabled; });
    });
    return form;
  }

  // ---------------------------------------------------------------- manager context

  /* The signed-in user's managed restaurants as [{id, name, timezone}], in fixture order. */
  function managedRestaurants() {
    return Promise.all([api("GET", "/x/me"), api("GET", "/restaurants", { auth: false })]).then(function (answers) {
      var me = answers[0], all = answers[1];
      if (me.status === 401) return { signedOut: true, restaurants: [] };
      if (!me.ok || !all.ok) throw new Error(me.message || all.message || "could not load restaurants");
      var managed = me.data.managed_restaurant_ids || [];
      return { me: me.data, restaurants: (all.data.restaurants || []).filter(function (r) {
        return managed.indexOf(r.id) !== -1;
      }) };
    });
  }

  function notAManager(container) {
    setChildren(container, emptyState("lock", "For restaurant managers",
      "This page is for the managers of a restaurant. Your account doesn't manage one.",
      h("a", { "class": "button", href: "/" }, "Find a table")));
  }

  window.TKX = {
    managedRestaurants: managedRestaurants, notAManager: notAManager,
    prefsForm: prefsForm,
    byId: byId, h: h, append: append, setChildren: setChildren, icon: icon, notice: notice,
    badge: badge, loading: loading, emptyState: emptyState,
    formatDate: formatDate, formatShortDate: formatShortDate, timeOf: timeOf, dateOf: dateOf,
    whenText: whenText, guests: guests, stamp: stamp, money: money, tableText: tableText,
    minutesText: minutesText, plural: plural, todayISO: todayISO, zonedInstant: zonedInstant,
    session: session, api: api, Uncertain: Uncertain, newKey: newKey, KeyedWriter: KeyedWriter,
    signInGate: signInGate, failureNotice: failureNotice, confirmDialog: confirmDialog
  };
})();
