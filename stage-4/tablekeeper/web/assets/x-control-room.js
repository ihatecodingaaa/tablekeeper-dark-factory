/* Control room (/control-room): a manager's view of one service day. Every figure is
 * read from the server; guarantee actions confirm in the page and are idempotent. */
(function () {
  "use strict";
  var X = window.TKX;
  var h = X.h;
  var root = X.byId("x-root");
  var announcer = X.byId("x-announcer");
  var writers = {};      // one idempotency key per (reference, action) until it succeeds
  var ctx = { restaurants: [], restaurantId: null, date: X.todayISO(), detail: null };
  var loadSeq = 0;

  var RES_STATE = { confirmed: ["ok", "check", "Confirmed"], cancelled: ["muted", "x", "Cancelled"] };
  var G_STATE = {
    NO_GUARANTEE: ["muted", "shield", "None"], HELD: ["held", "lock", "Held"], CAPTURED: ["wine", "coin", "Charged"],
    RELEASED: ["ok", "check", "Released"], REFUNDED: ["ok", "refresh", "Refunded"]
  };
  var FLAG_TEXT = { allergy: "Allergy", dietary: "Dietary", accessibility: "Access", occasion: "Occasion",
                    quiet: "Quiet", indoor: "Indoors", outdoor: "Outdoors" };

  if (!X.session.get()) {
    X.signInGate(root, "/control-room", "Sign in to open the control room", "This page is for restaurant managers.");
    return;
  }
  X.managedRestaurants().then(function (info) {
    if (info.signedOut) { X.signInGate(root, "/control-room", "Please sign in again", "Your session has ended."); return; }
    if (!info.restaurants.length) { X.notAManager(root); return; }
    ctx.restaurants = info.restaurants;
    ctx.restaurantId = info.restaurants[0].id;
    frame();
    load();
  }, function (err) { X.setChildren(root, X.failureNotice(err, "control-error")); });

  var body;  // the area below the toolbar

  function frame() {
    var select = h("select", { "class": "input", id: "cr-restaurant", "data-testid": "cr-restaurant" },
      ctx.restaurants.map(function (r) { return h("option", { value: r.id }, r.name); }));
    var date = h("input", { "class": "input", id: "cr-date", type: "date", value: ctx.date, "data-testid": "cr-date" });
    var form = h("form", { "class": "x-toolbar card", novalidate: true },
      h("div", { "class": "field" }, h("label", { "class": "field__label", "for": "cr-restaurant" }, "Restaurant"), select),
      h("div", { "class": "field" }, h("label", { "class": "field__label", "for": "cr-date" }, "Service date"), date),
      h("button", { type: "submit", "class": "button button--primary", "data-testid": "cr-load" }, X.icon("refresh"), "Show service"));
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      ctx.restaurantId = select.value;
      ctx.date = date.value || X.todayISO();
      load();
    });
    body = h("div", { "class": "x-stack", "data-testid": "cr-body" });
    X.setChildren(root,
      h("header", { "class": "x-intro" },
        h("p", { "class": "eyebrow" }, "Restaurant"),
        h("h1", { "class": "x-intro__title" }, "Control room"),
        h("p", { "class": "x-intro__lede" }, "Tonight's bookings, how full each slot is, guarantees and every message to guests, in one place.")),
      form, body);
  }

  function load(message) {
    loadSeq += 1;
    var seq = loadSeq;
    var rid = encodeURIComponent(ctx.restaurantId);
    X.setChildren(body, X.loading("Loading the service..."));
    Promise.all([
      X.api("GET", "/x/restaurants/" + rid + "/control-room?date=" + encodeURIComponent(ctx.date)),
      X.api("GET", "/x/restaurants/" + rid + "/guarantees"),
      X.api("GET", "/x/restaurants/" + rid + "/outbox"),
      X.api("GET", "/restaurants/" + rid, { auth: false })
    ]).then(function (answers) {
      if (seq !== loadSeq) return;
      var failed = answers.filter(function (a) { return !a.ok; })[0];
      if (failed) {
        X.setChildren(body, failed.status === 403
          ? X.notice("error", "lock", "Not your restaurant", "You don't manage this restaurant.", "control-error")
          : X.notice("error", "alert", "The service didn't load", failed.message || "Please check the date.", "control-error"));
        return;
      }
      ctx.detail = answers[3].data;
      render(answers[0].data, answers[1].data, answers[2].data);
      if (message) announcer.textContent = message;
    }, function (err) {
      if (seq === loadSeq) X.setChildren(body, X.failureNotice(err, "control-error"));
    });
  }

  function labelOf(tableId) {
    var tables = (ctx.detail && ctx.detail.tables) || [];
    for (var i = 0; i < tables.length; i++) if (tables[i].id === tableId) return X.tableText([tables[i].label]);
    return tableId;
  }

  function render(room, settlement, outbox) {
    var confirmed = room.reservations.filter(function (r) { return r.status === "confirmed"; });
    var covers = confirmed.reduce(function (sum, r) { return sum + r.party_size; }, 0);
    var peak = room.pressure.reduce(function (best, p) { return !best || p.pressure_percent > best.pressure_percent ? p : best; }, null);
    X.setChildren(body,
      h("div", { "class": "x-kpis", "data-testid": "cr-kpis" },
        kpi(confirmed.length, "Bookings confirmed"), kpi(covers, "Guests expected"),
        kpi(peak ? peak.pressure_percent + "%" : "0%", peak ? "Busiest at " + peak.time : "Busiest slot"),
        kpi(X.money(room.guarantees.held_minor, settlement.currency), "Guarantees held")),
      reservationsCard(room),
      h("div", { "class": "x-columns" },
        h("div", { "class": "x-stack" }, pressureCard(room), changesCard(room)),
        h("div", { "class": "x-stack" }, policyCard(room), closuresCard(room))),
      settlementCard(settlement),
      outboxCard(outbox));
  }

  function kpi(value, label) {
    return h("div", { "class": "x-kpi card" }, h("p", { "class": "x-kpi__value" }, String(value)), h("p", { "class": "x-kpi__label" }, label));
  }

  function card(iconName, title, testId, content, sub) {
    var id = testId + "-title";
    return h("section", { "class": "x-card card", "data-testid": testId, "aria-labelledby": id },
      h("div", { "class": "x-card__head" }, X.icon(iconName), h("h2", { "class": "x-card__title", id: id }, title)),
      sub ? h("p", { "class": "x-card__sub" }, sub) : null, content);
  }

  function reservationsCard(room) {
    var rows = room.reservations;
    return card("calendar", "Bookings on " + X.formatDate(room.date), "cr-reservations",
      rows.length ? h("div", { "class": "x-scroll", role: "region", tabindex: "0", "aria-label": "Bookings" },
        h("table", { "class": "x-table" },
          h("thead", null, h("tr", null, ["Time", "Guest", "Party", "Tables", "Status", "Wishes", "Guarantee", "Ref"].map(function (t) {
            return h("th", { scope: "col" }, t);
          }))),
          h("tbody", null, rows.map(function (r) {
            var s = RES_STATE[r.status] || RES_STATE.confirmed;
            var g = G_STATE[r.guarantee_state] || G_STATE.NO_GUARANTEE;
            return h("tr", { "data-testid": "cr-row-" + r.reference },
              h("td", null, r.time), h("td", null, r.guest), h("td", { "class": "x-num" }, String(r.party_size)),
              h("td", null, X.tableText(r.table_labels)), h("td", null, X.badge(s[0], s[1], s[2])),
              h("td", { "class": "x-wrap" }, (r.preference_flags || []).map(function (f) { return FLAG_TEXT[f] || f; }).join(", ") || "\u2013"),
              h("td", null, X.badge(g[0], g[1], g[2])), h("td", { "class": "x-reference" }, r.reference));
          }))))
        : X.emptyState("calendar", "No bookings on this date", "Nothing is booked yet. New bookings appear here as they come in."));
  }

  function pressureCard(room) {
    return card("users", "How full each slot is", "cr-pressure",
      room.pressure.length ? h("ul", { "class": "x-bars" }, room.pressure.map(function (p) {
        var fill = h("span", { "class": "x-bar__fill" + (p.pressure_percent >= 85 ? " x-bar__fill--high" : "") });
        fill.style.width = Math.max(0, Math.min(100, p.pressure_percent)) + "%";
        return h("li", { "class": "x-bar" },
          h("span", null, p.time),
          h("span", { "class": "x-bar__track", "aria-hidden": "true" }, fill),
          h("span", { "class": "x-bar__value" }, p.booked_seats + "/" + p.total_seats + " \u00b7 " + p.pressure_percent + "%"));
      })) : h("p", { "class": "x-hint" }, "The restaurant is closed on this date."),
      "Seats booked out of seats available, per start time.");
  }

  function changesCard(room) {
    var changes = room.recent_changes || [];
    var text = { created: "Booked", changed: "Changed", cancelled: "Cancelled", reassigned: "Moved by a seating repair" };
    return card("clock", "Recent changes guests felt", "cr-changes",
      changes.length ? h("ol", { "class": "x-timeline" }, changes.map(function (c) {
        return h("li", { "class": "x-timeline__item" },
          h("span", { "class": "x-timeline__dot" }, X.icon(c.event === "cancelled" ? "x" : c.event === "reassigned" ? "tool" : "check")),
          h("div", null, h("p", { "class": "x-timeline__title" }, (text[c.event] || c.event) + " \u00b7 " + c.guest),
            h("p", { "class": "x-timeline__meta" }, X.stamp(c.at) + " \u00b7 " + c.reference)));
      })) : h("p", { "class": "x-hint" }, "No changes yet."));
  }

  function policyCard(room) {
    var p = room.policy_in_effect || {};
    var caps = p.capacities || {};
    return card("shield", "Rules in force", "cr-policy", h("dl", { "class": "x-facts" },
      h("dt", null, "Policy"), h("dd", null, p.policy_version ? "Published policy v" + p.policy_version : "The restaurant's own setup"),
      h("dt", null, "Slots"), h("dd", null, "Every " + X.minutesText(p.slot_minutes)),
      h("dt", null, "Booking length"), h("dd", null, X.minutesText(p.reservation_duration_minutes)),
      h("dt", null, "Free cancellation"), h("dd", null, "Until " + X.minutesText(p.cancellation_cutoff_minutes) + " before"),
      h("dt", null, "Seats"), h("dd", null, Object.keys(caps).map(function (id) { return labelOf(id) + ": " + caps[id]; }).join(", ") || "\u2013"),
      h("dt", null, "Recurring series"), h("dd", null, String(room.series_count || 0))));
  }

  function closuresCard(room) {
    var closures = room.closures || [];
    return card("pause", "Closed tables", "cr-closures",
      closures.length ? h("ul", { "class": "x-list" }, closures.map(function (c) {
        return h("li", { "class": "x-list__item" }, h("span", { "class": "x-list__title" }, X.icon("pause"), labelOf(c.table_id)),
          h("p", { "class": "x-list__meta" }, h("span", null, X.stamp(c.from) + " \u2013 " + X.stamp(c.to)),
            c.plan_id ? h("span", null, "Plan " + c.plan_id) : null));
      })) : h("p", { "class": "x-hint" }, "No tables are closed."));
  }

  function settlementCard(s) {
    var t = s.totals || {};
    var rows = s.rows || [];
    return card("coin", "Guarantees", "cr-guarantees",
      [h("div", { "class": "x-kpis" },
        kpi(X.money(t.held_minor, s.currency), "Held"), kpi(X.money(t.captured_minor, s.currency), "Charged"),
        kpi(X.money(t.released_minor, s.currency), "Released"), kpi(X.money(t.refunded_minor, s.currency), "Refunded")),
      rows.length ? h("div", { "class": "x-scroll", role: "region", tabindex: "0", "aria-label": "Guarantees" },
        h("table", { "class": "x-table" },
          h("thead", null, h("tr", null, ["Guest", "Booking", "Amount", "State", "Last event", "Actions"].map(function (t2) {
            return h("th", { scope: "col" }, t2);
          }))),
          h("tbody", null, rows.map(function (row) { return guaranteeRow(row); }))))
        : h("p", { "class": "x-hint" }, "No guarantees at this restaurant yet.")],
      "Amounts in " + s.currency + ". Charging a no-show is possible only once the booking has started.");
  }

  var ACTIONS = {
    HELD: [["release", "Release", "Guest arrived: release the hold"], ["capture", "Charge no-show", "Charge the held amount as a no-show"]],
    CAPTURED: [["refund", "Refund", "Refund the full charged amount"]]
  };

  function guaranteeRow(row) {
    var g = G_STATE[row.state] || G_STATE.NO_GUARANTEE;
    var status = h("div", { "class": "x-status" });
    var buttons = (ACTIONS[row.state] || []).map(function (a) {
      var b = h("button", { type: "button", "class": "button button--small" + (a[0] === "capture" ? " button--danger" : ""),
                            "data-testid": "cr-" + a[0] + "-" + row.reference }, a[1]);
      b.addEventListener("click", function () { act(row, a, b, status); });
      return b;
    });
    return h("tr", { "data-testid": "cr-guarantee-" + row.reference },
      h("td", null, row.guest), h("td", null, row.reference + " \u00b7 " + X.timeOf(row.starts_at_local) + " \u00b7 " + X.guests(row.party_size)),
      h("td", { "class": "x-num" }, X.money(row.amount_minor, row.currency)),
      h("td", null, X.badge(g[0], g[1], g[2])),
      h("td", { "class": "x-wrap" }, row.last_event || "\u2013"),
      h("td", { "class": "x-wrap" }, buttons.length ? h("div", { "class": "x-actions" }, buttons) : "\u2013", status));
  }

  function act(row, action, button, status) {
    var path = "/x/restaurants/" + encodeURIComponent(ctx.restaurantId) + "/guarantees/" +
      encodeURIComponent(row.reference) + "/" + action[0];
    X.confirmDialog({
      title: action[2] + "?", danger: action[0] === "capture", confirm: action[1],
      text: row.guest + ", " + row.reference + ": " + X.money(row.amount_minor, row.currency) + ". The guest is told straight away."
    }).then(function (yes) {
      if (!yes) return;
      var writer = writers[path] || (writers[path] = new X.KeyedWriter(action[0]));
      button.disabled = true;
      X.api("POST", path, { body: {}, key: writer.keyFor(path, {}) }).then(function (res) {
        if (res.ok) { delete writers[path]; load(action[1] + " done for " + row.reference + "."); return; }
        button.disabled = false;
        X.setChildren(status, X.notice("error", "alert", "Not done", res.message || "Please refresh.", "cr-action-error"));
      }, function () {
        button.disabled = false;
        X.setChildren(status, X.notice("uncertain", "question", "Outcome unknown",
          "Press the button again to check. It is safe and never applies twice.", "cr-action-uncertain"));
      });
    });
  }

  function outboxCard(outbox) {
    var entries = (outbox.outbox || []).slice().reverse().slice(0, 12);
    var states = (outbox.summary && outbox.summary.by_state) || {};
    return card("bell", "Messages to guests", "cr-outbox",
      [h("p", { "class": "x-list__meta" }, h("span", null, (outbox.summary ? outbox.summary.total : 0) + " in total"),
        Object.keys(states).map(function (k) { return h("span", null, k.replace(/_/g, " ") + ": " + states[k]); })),
      entries.length ? h("ul", { "class": "x-list" }, entries.map(function (e) {
        return h("li", { "class": "x-list__item" },
          h("div", { "class": "x-list__top" }, h("span", { "class": "x-list__title" }, e.subject),
            h("span", { "class": "x-hint" }, e.delivery_state.replace(/_/g, " "))),
          h("p", { "class": "x-list__meta" }, h("span", null, X.stamp(e.at)), h("span", null, e.recipient_label),
            h("span", null, e.channel.replace("_", " "))));
      })) : h("p", { "class": "x-hint" }, "No messages yet.")],
      "Email and Telegram are simulated unless credentials are configured on the server.");
  }
})();
