/* Notification centre (/notifications): every message about the diner's bookings. */
(function () {
  "use strict";
  var X = window.TKX;
  var h = X.h;
  var root = X.byId("x-root");

  var EVENT_ICON = {
    confirmed: "check", amended: "refresh", cancelled: "x", reassigned: "tool", series_created: "calendar",
    series_amended: "calendar", guarantee_held: "lock", guarantee_hold_adjusted: "lock",
    guarantee_captured: "coin", guarantee_released: "check", guarantee_refunded: "refresh", reminder: "clock"
  };
  var CHANNEL_TEXT = { in_app: "In Tablekeeper", email: "Email", telegram: "Telegram" };
  var DELIVERY = {
    delivered_in_app: ["ok", "check", "Delivered here"], simulated: ["muted", "info", "Simulated delivery"],
    queued: ["warn", "clock", "Queued"], sent: ["ok", "check", "Sent"], failed: ["danger", "alert", "Not delivered"]
  };

  if (!X.session.get()) {
    X.signInGate(root, "/notifications", "Sign in to see your messages",
      "Confirmations, changes and guarantee updates for your bookings appear here.");
    return;
  }
  load();

  function load() {
    X.api("GET", "/x/me/notifications").then(function (res) {
      if (res.status === 401) { X.signInGate(root, "/notifications", "Please sign in again", "Your session has ended."); return; }
      if (!res.ok) { X.setChildren(root, X.notice("error", "alert", "Messages didn't load", res.message || "")); return; }
      render(res.data);
    }, function (err) {
      X.setChildren(root, X.failureNotice(err, "notifications-error"),
        h("div", { "class": "x-actions" }, h("button", { type: "button", "class": "button", onclick: load }, X.icon("refresh"), "Try again")));
    });
  }

  function entryItem(entry, upcoming) {
    var d = DELIVERY[entry.delivery_state] || DELIVERY.simulated;
    return h("li", { "class": "x-list__item card", "data-testid": upcoming ? "reminder" : "notification" },
      h("div", { "class": "x-list__top" },
        h("span", { "class": "x-list__title" }, X.icon(EVENT_ICON[entry.event] || "bell"), entry.subject),
        X.badge(d[0], d[1], d[2])),
      h("p", { "class": "x-list__body" }, entry.body),
      h("p", { "class": "x-list__meta" },
        h("span", null, X.stamp(entry.at)),
        h("span", null, CHANNEL_TEXT[entry.channel] || entry.channel),
        entry.recipient_label ? h("span", null, "To " + entry.recipient_label) : null,
        entry.reference ? h("a", { href: "/evening/" + encodeURIComponent(entry.reference) }, "Open evening " + entry.reference) : null));
  }

  function render(payload) {
    var items = (payload.notifications || []).slice().reverse();  // newest first
    var reminders = payload.reminders || [];
    X.setChildren(root,
      h("header", { "class": "x-intro" },
        h("p", { "class": "eyebrow" }, "Messages"),
        h("h1", { "class": "x-intro__title" }, "Your notifications"),
        h("p", { "class": "x-intro__lede" }, "Everything we have told you about your bookings, newest first. Email and Telegram show as simulated unless the restaurant has connected them.")),
      reminders.length ? h("section", { "aria-labelledby": "reminders-title" },
        h("h2", { "class": "x-card__title", id: "reminders-title" }, "Coming up in the next 24 hours"),
        h("ul", { "class": "x-list", "data-testid": "reminder-list" }, reminders.map(function (r) { return entryItem(r, true); }))) : null,
      items.length
        ? h("section", { "aria-labelledby": "all-title" },
          h("h2", { "class": "x-card__title visually-hidden", id: "all-title" }, "All messages"),
          h("ul", { "class": "x-list", "data-testid": "notification-list" }, items.map(function (e) { return entryItem(e, false); })))
        : X.emptyState("bell", "No messages yet", "When you book, change or cancel a table, the confirmation lands here.",
          h("a", { "class": "button button--primary", href: "/" }, "Find a table")));
  }
})();
