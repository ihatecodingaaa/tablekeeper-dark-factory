/* Passport (/passport): the diner's evenings, history, guarantees and saved preferences.
 * Counts come straight from the server; there are no points or invented scores. */
(function () {
  "use strict";
  var X = window.TKX;
  var h = X.h;
  var root = X.byId("x-root");

  var GUARANTEE = {
    NO_GUARANTEE: null, HELD: ["held", "lock", "Guarantee held"], CAPTURED: ["wine", "coin", "Charged"],
    RELEASED: ["ok", "check", "Released"], REFUNDED: ["ok", "refresh", "Refunded"]
  };

  if (!X.session.get()) {
    X.signInGate(root, "/passport", "Sign in to see your evenings",
      "Your passport keeps your upcoming and past evenings and your preferences in one place.");
    return;
  }
  load();

  function load() {
    X.api("GET", "/x/me/passport").then(function (res) {
      if (res.status === 401) { X.signInGate(root, "/passport", "Please sign in again", "Your session has ended."); return; }
      if (!res.ok) { X.setChildren(root, X.notice("error", "alert", "Your passport didn't load", res.message || "")); return; }
      render(res.data);
    }, function (err) {
      X.setChildren(root, X.failureNotice(err, "passport-error"),
        h("div", { "class": "x-actions" }, h("button", { type: "button", "class": "button", onclick: load }, X.icon("refresh"), "Try again")));
    });
  }

  function row(item, kind) {
    var g = GUARANTEE[item.guarantee_state];
    return h("li", { "class": "x-list__item card", "data-testid": "passport-" + kind },
      h("div", { "class": "x-list__top" },
        h("a", { "class": "x-list__title", href: "/evening/" + encodeURIComponent(item.reference) },
          X.icon(item.status === "cancelled" ? "x" : "calendar"), item.restaurant.name),
        item.status === "cancelled" ? X.badge("muted", "x", "Cancelled") : X.badge("ok", "check", "Confirmed")),
      h("p", { "class": "x-list__body" }, X.whenText(item.starts_at_local)),
      h("p", { "class": "x-list__meta" },
        h("span", null, X.guests(item.party_size)),
        h("span", null, X.tableText(item.table_labels)),
        h("span", { "class": "x-reference" }, item.reference),
        g ? X.badge(g[0], g[1], g[2]) : null));
  }

  function section(title, items, kind, empty) {
    var id = "passport-" + kind + "-title";
    return h("section", { "aria-labelledby": id, "class": "x-stack" },
      h("h2", { "class": "x-card__title", id: id }, title),
      items.length ? h("ul", { "class": "x-list" }, items.map(function (item) { return row(item, kind); }))
        : h("p", { "class": "x-hint" }, empty));
  }

  function render(p) {
    var counts = p.counts || {};
    X.setChildren(root,
      h("header", { "class": "x-intro" },
        h("p", { "class": "eyebrow" }, "Your passport"),
        h("h1", { "class": "x-intro__title" }, "Your evenings"),
        h("p", { "class": "x-intro__lede" }, "Upcoming and past bookings, what happened with them, and the preferences we bring to every new one.")),
      h("div", { "class": "x-kpis", "data-testid": "passport-counts" },
        kpi(counts.reservations, "Bookings made"), kpi(counts.amendments, "Changes"), kpi(counts.cancellations, "Cancellations"),
        kpi((p.restaurants_visited || []).length, "Restaurants")),
      h("div", { "class": "x-columns" },
        h("div", { "class": "x-stack" },
          section("Coming up", p.upcoming || [], "upcoming", "Nothing booked yet. Your next evening will appear here."),
          (p.cancelled_upcoming || []).length ? section("Cancelled", p.cancelled_upcoming, "cancelled", "") : null,
          section("Past evenings", p.past || [], "past", "No past evenings yet.")),
        h("div", { "class": "x-stack" },
          guarantees(p.guarantees || []),
          visited(p.restaurants_visited || []),
          preferences(p.preferences))));
  }

  function kpi(value, label) {
    return h("div", { "class": "x-kpi card" }, h("p", { "class": "x-kpi__value" }, String(value === undefined ? 0 : value)),
      h("p", { "class": "x-kpi__label" }, label));
  }

  function guarantees(items) {
    return h("section", { "class": "x-card card", "data-testid": "passport-guarantees", "aria-labelledby": "pg-title" },
      h("div", { "class": "x-card__head" }, X.icon("shield"), h("h2", { "class": "x-card__title", id: "pg-title" }, "Guarantees")),
      items.length ? h("ul", { "class": "x-list" }, items.map(function (g) {
        var b = GUARANTEE[g.state] || ["muted", "shield", g.state];
        return h("li", { "class": "x-list__item" },
          h("div", { "class": "x-list__top" },
            h("a", { href: "/evening/" + encodeURIComponent(g.reference), "class": "x-reference" }, g.reference),
            X.badge(b[0], b[1], b[2])),
          h("p", { "class": "x-list__body" }, X.money(g.amount_minor, g.currency) +
            (g.last_event ? " \u00b7 " + g.last_event : "")));
      })) : h("p", { "class": "x-hint" }, "No guarantees on your bookings."));
  }

  function visited(names) {
    return h("section", { "class": "x-card card", "aria-labelledby": "pv-title" },
      h("div", { "class": "x-card__head" }, X.icon("map"), h("h2", { "class": "x-card__title", id: "pv-title" }, "Restaurants visited")),
      names.length ? h("ul", { "class": "x-list" }, names.map(function (name) { return h("li", null, name); }))
        : h("p", { "class": "x-hint" }, "None yet."));
  }

  function preferences(prefs) {
    return h("section", { "class": "x-card card", "data-testid": "passport-preferences", "aria-labelledby": "pp-title" },
      h("div", { "class": "x-card__head" }, X.icon("heart"), h("h2", { "class": "x-card__title", id: "pp-title" }, "Make it yours")),
      h("p", { "class": "x-card__sub" }, "Saved defaults, copied onto each new booking. You can change them per evening."),
      X.prefsForm(prefs, {
        withChannel: true, saveLabel: "Save defaults",
        onSave: function (body) {
          return X.api("PUT", "/x/me/preferences", { body: body }).then(function (res) {
            return { ok: res.ok, message: res.message };
          });
        }
      }));
  }
})();
