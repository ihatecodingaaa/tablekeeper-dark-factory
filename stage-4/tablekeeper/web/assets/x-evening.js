/* My Evening (/evening/{reference}): one booking as a calm companion page. */
(function () {
  "use strict";
  var X = window.TKX;
  var h = X.h;
  var root = X.byId("x-root");
  var announcer = X.byId("x-announcer");
  var reference = decodeURIComponent(window.location.pathname.replace(/^\/evening\//, "").replace(/\/+$/, ""));
  var holdWriter = new X.KeyedWriter("hold");
  var data = null;

  if (!X.session.get()) {
    X.signInGate(root, window.location.pathname, "Sign in to see your evening",
      "Your evening page shows the booking, its guarantee and your messages.");
    return;
  }
  load();

  function load(message) {
    if (!data) X.setChildren(root, X.loading("Gathering the details of your evening..."));
    X.api("GET", "/x/evening/" + encodeURIComponent(reference)).then(function (res) {
      if (res.status === 401) {
        X.signInGate(root, window.location.pathname, "Please sign in again", "Your session has ended.");
        return;
      }
      if (res.status === 404) {
        X.setChildren(root, X.emptyState("question", "We couldn't find this evening",
          "There is no reservation " + reference + " on your account. Check the reference, or look it up.",
          h("a", { "class": "button", href: "/lookup" }, "Look up a booking")));
        return;
      }
      if (!res.ok) {
        X.setChildren(root, X.notice("error", "alert", "This page didn't load", res.message || "Please try again."));
        return;
      }
      data = res.data;
      render();
      if (message) announcer.textContent = message;
    }, function (err) {
      X.setChildren(root, X.failureNotice(err, "evening-error"),
        h("div", { "class": "x-actions" }, h("button", { type: "button", "class": "button", onclick: function () { load(); } },
          X.icon("refresh"), "Try again")));
    });
  }

  function render() {
    var r = data.reservation;
    var confirmed = r.status === "confirmed";
    var past = Date.parse(r.starts_at) < Date.now();
    X.setChildren(root,
      h("header", { "class": "x-intro" },
        h("p", { "class": "eyebrow" }, "My evening"),
        h("h1", { "class": "x-intro__title" }, "Your evening at " + data.restaurant.name)),
      h("div", { "class": "x-columns" },
        h("div", { "class": "x-stack" },
          hero(r, confirmed, past),
          recovery(),
          historyCard(),
          preferencesCard(confirmed && !past)),
        h("div", { "class": "x-stack" },
          guaranteeCard(confirmed),
          calendarCard(),
          notificationsCard(),
          manageCard(r, confirmed && !past))));
  }

  // ------------------------------------------------------------ summary

  function hero(r, confirmed, past) {
    var stateText = !confirmed
      ? "This evening is cancelled. Nothing more is needed from you."
      : past ? "This evening has passed. We hope it was a good one."
        : "You're all set. The table is held for you, so there's nothing else to do before you arrive.";
    return h("section", { "class": "x-hero card", "data-testid": "evening-summary", "aria-label": "Your booking" },
      h("p", { "class": "eyebrow" }, "Reservation ", h("span", { "class": "x-reference", "data-testid": "evening-reference" }, r.reference)),
      h("h2", { "class": "x-hero__restaurant" }, data.restaurant.name),
      h("p", { "class": "x-hero__when", "data-testid": "evening-when" }, X.whenText(r.starts_at_local)),
      h("div", { "class": "x-hero__facts" },
        h("span", { "class": "x-hero__fact" }, X.icon("users"), X.guests(r.party_size)),
        h("span", { "class": "x-hero__fact", "data-testid": "evening-tables" }, X.icon("table"), X.tableText(data.table_labels)),
        h("span", { "class": "x-hero__fact" }, X.icon("clock"), "Local time, " + data.restaurant.timezone),
        data.series ? h("span", { "class": "x-hero__fact" }, X.icon("calendar"),
          "Part of a recurring booking (#" + (data.series.index + 1) + ")") : null),
      h("div", { "class": "x-hero__state" },
        confirmed ? X.badge("ok", "check", "Confirmed", "evening-status") : X.badge("muted", "x", "Cancelled", "evening-status"),
        h("span", { "class": "x-hero__state-text" }, stateText)));
  }

  function recovery() {
    var rec = data.recovery;
    if (!rec || !rec.was_reassigned || !rec.last_reassignment) return null;
    var last = rec.last_reassignment;
    return X.notice("info", "refresh", "Your table changed",
      data.restaurant.name + " moved your booking from " + X.tableText(last.from_labels) + " to " +
      X.tableText(last.to_labels) + " (" + X.stamp(last.at) + ") because a table became unavailable. " +
      "Your time, party size and booking terms stayed exactly the same.", "evening-recovery");
  }

  var EVENT_TEXT = { created: "Booked", changed: "Changed", cancelled: "Cancelled", reassigned: "Moved by the restaurant" };
  var EVENT_ICON = { created: "check", changed: "refresh", cancelled: "x", reassigned: "tool" };

  function describeChanges(entry) {
    if (entry.event === "created") {
      var size = (entry.changes || []).filter(function (c) { return c.field === "party_size"; })[0];
      return size ? "Table for " + X.guests(size.to) + "." : "";
    }
    if (entry.event === "cancelled") return "";
    return (entry.changes || []).map(function (c) {
      if (c.field === "starts_at_local") return "Time " + X.timeOf(c.from) + " \u2192 " + X.timeOf(c.to);
      if (c.field === "party_size") return "Party " + c.from + " \u2192 " + c.to;
      return "Table changed";
    }).join(" \u00b7 ");
  }

  function historyCard() {
    var entries = data.history || [];
    return h("section", { "class": "x-card card", "data-testid": "evening-history", "aria-labelledby": "history-title" },
      h("div", { "class": "x-card__head" }, X.icon("clock"), h("h2", { "class": "x-card__title", id: "history-title" }, "What has happened")),
      entries.length ? h("ol", { "class": "x-timeline" }, entries.map(function (entry) {
        return h("li", { "class": "x-timeline__item" },
          h("span", { "class": "x-timeline__dot" }, X.icon(EVENT_ICON[entry.event] || "info")),
          h("div", null,
            h("p", { "class": "x-timeline__title" }, EVENT_TEXT[entry.event] || entry.event),
            h("p", { "class": "x-timeline__meta" }, X.stamp(entry.at)),
            describeChanges(entry) ? h("p", { "class": "x-timeline__body" }, describeChanges(entry)) : null));
      })) : h("p", { "class": "x-hint" }, "Nothing recorded yet."));
  }

  // ------------------------------------------------------------ preferences

  function preferencesCard(editable) {
    return h("section", { "class": "x-card card", "data-testid": "evening-preferences", "aria-labelledby": "prefs-title" },
      h("div", { "class": "x-card__head" }, X.icon("heart"), h("h2", { "class": "x-card__title", id: "prefs-title" }, "Make it yours")),
      h("p", { "class": "x-card__sub" }, editable
        ? "Tell the restaurant what would make the evening right for you."
        : "These were the wishes for this evening."),
      X.prefsForm(data.preferences, {
        disabled: !editable,
        onSave: function (body) {
          return X.api("PUT", "/x/reservations/" + encodeURIComponent(reference) + "/preferences", { body: body })
            .then(function (res) {
              if (res.ok) data.preferences = res.data;
              return { ok: res.ok, message: res.message };
            });
        }
      }));
  }

  // ------------------------------------------------------------ guarantee

  var STATE_BADGE = {
    NO_GUARANTEE: ["muted", "shield", "No guarantee"],
    HELD: ["held", "lock", "Held"],
    CAPTURED: ["wine", "coin", "Charged"],
    RELEASED: ["ok", "check", "Released"],
    REFUNDED: ["ok", "refresh", "Refunded"]
  };
  var EVENT_LABEL = { held: "Held", hold_adjusted: "Hold adjusted", captured: "Charged", released: "Released",
                      refunded: "Refunded" };
  var ACTOR = { guest: "by you", manager: "by the restaurant", system: "automatically" };

  function guaranteeCard(confirmed) {
    var g = data.guarantee || { state: "NO_GUARANTEE", events: [] };
    var b = STATE_BADGE[g.state] || STATE_BADGE.NO_GUARANTEE;
    var status = h("div", { "class": "x-status", "data-testid": "guarantee-status" });
    var body = [];
    if (g.state === "NO_GUARANTEE") {
      body.push(h("p", null, g.explanation || "There is no card guarantee on this booking."));
      if (confirmed) {
        var hold = h("button", { type: "button", "class": "button button--primary", "data-testid": "guarantee-hold" },
          X.icon("shield"), "Hold a guarantee");
        hold.addEventListener("click", function () { placeHold(hold, status); });
        body.push(h("div", { "class": "x-actions" }, hold),
          h("p", { "class": "x-hint" }, "Nothing is charged now. The hold is released automatically if you cancel in time."));
      }
    } else {
      body.push(
        h("p", { "class": "x-amount", "data-testid": "guarantee-amount" }, X.money(g.amount_minor, g.currency)),
        h("p", { "class": "x-amount__note", "data-testid": "guarantee-explanation" }, g.explanation),
        g.next_expected ? h("p", { "class": "x-hint" }, X.icon("arrow"), " ", g.next_expected) : null,
        h("h3", { "class": "x-card__title x-card__title--small" }, "What happened to my money?"),
        h("ol", { "class": "x-timeline", "data-testid": "guarantee-timeline" }, (g.events || []).map(function (event) {
          var amount = event.type === "hold_adjusted"
            ? (event.amount_minor >= 0 ? "+" : "") + X.money(event.amount_minor, event.currency)
            : X.money(event.amount_minor, event.currency);
          return h("li", { "class": "x-timeline__item" },
            h("span", { "class": "x-timeline__dot" }, X.icon(event.type === "captured" ? "coin" : event.type === "held" ? "lock" : "check")),
            h("div", null,
              h("p", { "class": "x-timeline__title" }, (EVENT_LABEL[event.type] || event.type) + " \u00b7 " + amount),
              h("p", { "class": "x-timeline__meta" }, X.stamp(event.at) + " \u00b7 " + (ACTOR[event.actor] || event.actor)),
              event.reason ? h("p", { "class": "x-timeline__body" }, event.reason) : null));
        })));
    }
    return h("section", { "class": "x-card card", "data-testid": "guarantee-card", "aria-labelledby": "guarantee-title" },
      h("div", { "class": "x-card__head" }, X.icon("shield"),
        h("h2", { "class": "x-card__title", id: "guarantee-title" }, "Guarantee"),
        X.badge(b[0], b[1], b[2], "guarantee-state")),
      body, status);
  }

  function placeHold(button, status) {
    var path = "/x/reservations/" + encodeURIComponent(reference) + "/guarantee";
    button.disabled = true;
    X.setChildren(status, X.loading("Placing the hold..."));
    X.api("POST", path, { body: {}, key: holdWriter.keyFor(path, {}) }).then(function (res) {
      if (res.ok) {
        data.guarantee = res.data;
        render();
        announcer.textContent = "Guarantee held: " + X.money(res.data.amount_minor, res.data.currency) + ".";
        return;
      }
      button.disabled = false;
      X.setChildren(status, X.notice("error", "alert", "No hold was placed", res.message || "Please try again.", "guarantee-error"));
    }, function () {
      button.disabled = false;
      X.setChildren(status, X.notice("uncertain", "question", "We couldn't confirm the hold",
        "Press \u201cHold a guarantee\u201d again to check. It is safe and will never hold twice.", "guarantee-uncertain"));
    });
  }

  // ------------------------------------------------------------ calendar and share

  function calendarCard() {
    var status = h("div", { "class": "x-status", "data-testid": "calendar-status" });
    var download = h("button", { type: "button", "class": "button", "data-testid": "calendar-ics" },
      X.icon("download"), "Download .ics");
    download.addEventListener("click", function () { downloadIcs(download, status); });
    var share = h("button", { type: "button", "class": "button", "data-testid": "share-button" }, X.icon("share"), "Share");
    share.addEventListener("click", function () { shareEvening(status); });
    return h("section", { "class": "x-card card", "data-testid": "evening-calendar", "aria-labelledby": "calendar-title" },
      h("div", { "class": "x-card__head" }, X.icon("calendar"), h("h2", { "class": "x-card__title", id: "calendar-title" }, "Keep it handy")),
      h("div", { "class": "x-actions" },
        h("a", { "class": "button", href: data.calendar.google_url, target: "_blank", rel: "noopener noreferrer",
                 "data-testid": "calendar-google" }, X.icon("calendar"), "Google Calendar"),
        download, share),
      h("blockquote", { "class": "x-hint", "data-testid": "share-text" }, data.share_text),
      status);
  }

  function downloadIcs(button, status) {
    button.disabled = true;
    X.api("GET", data.calendar.ics_path, { raw: true }).then(function (res) {
      if (!res.ok) {
        X.setChildren(status, X.notice("error", "alert", "The calendar file isn't available", res.message || ""));
        return;
      }
      var url = URL.createObjectURL(res.blob);
      var link = h("a", { href: url, download: "tablekeeper-" + reference + ".ics" });
      document.body.appendChild(link);
      link.click();
      link.parentNode.removeChild(link);
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      X.setChildren(status, X.notice("success", "check", "Calendar file ready",
        "Open it to add the evening to your calendar.", "calendar-downloaded"));
    }, function (err) {
      X.setChildren(status, X.failureNotice(err, "calendar-error"));
    }).finally(function () { button.disabled = false; });
  }

  function shareEvening(status) {
    var text = data.share_text;
    if (navigator.share) {
      navigator.share({ title: "Dinner at " + data.restaurant.name, text: text }).then(function () {
        X.setChildren(status, X.notice("success", "check", "Shared", null, "share-done"));
      }, function () { /* the diner closed the share sheet */ });
      return;
    }
    var copied = navigator.clipboard && navigator.clipboard.writeText
      ? navigator.clipboard.writeText(text) : Promise.reject(new Error("no clipboard"));
    copied.then(function () {
      X.setChildren(status, X.notice("success", "copy", "Copied", "The details are on your clipboard, ready to paste.", "share-copied"));
    }, function () {
      var box = h("textarea", { "class": "input", readonly: true, "aria-label": "Booking details to copy", "data-testid": "share-fallback" });
      box.value = text;
      X.setChildren(status, X.notice("info", "copy", "Copy these details", "Select the text below and copy it."), box);
      box.focus();
      box.select();
    });
  }

  // ------------------------------------------------------------ messages

  var CHANNEL_TEXT = { in_app: "In Tablekeeper", email: "Email", telegram: "Telegram" };
  var DELIVERY = {
    delivered_in_app: ["ok", "check", "Delivered here"], simulated: ["muted", "info", "Simulated"],
    queued: ["warn", "clock", "Queued"], sent: ["ok", "check", "Sent"], failed: ["danger", "alert", "Not delivered"]
  };

  function notificationsCard() {
    var items = (data.notifications || []).slice().reverse();  // newest first
    return h("section", { "class": "x-card card", "data-testid": "evening-notifications", "aria-labelledby": "messages-title" },
      h("div", { "class": "x-card__head" }, X.icon("bell"), h("h2", { "class": "x-card__title", id: "messages-title" }, "Messages about this evening")),
      items.length ? h("ul", { "class": "x-list" }, items.map(function (entry) {
        var d = DELIVERY[entry.delivery_state] || DELIVERY.simulated;
        return h("li", { "class": "x-list__item" },
          h("div", { "class": "x-list__top" }, h("span", { "class": "x-list__title" }, entry.subject),
            X.badge(d[0], d[1], d[2])),
          h("p", { "class": "x-list__body" }, entry.body),
          h("p", { "class": "x-list__meta" }, h("span", null, X.stamp(entry.at)),
            h("span", null, CHANNEL_TEXT[entry.channel] || entry.channel)));
      })) : h("p", { "class": "x-hint" }, "No messages yet."));
  }

  // ------------------------------------------------------------ amend and cancel (official API)

  var REFUSALS = {
    cutoff_passed: "It's too close to the start to change this booking online.",
    table_unavailable: "That table isn't free at the new time. Try another time.",
    outside_opening_hours: "The restaurant isn't open for a full booking at that time.",
    not_on_slot_grid: "Bookings start on the restaurant's time slots. Try a time from the search grid.",
    party_exceeds_capacity: "The table can't seat that many guests. Search for a larger table.",
    invalid_local_time: "That time doesn't exist on this date because the clocks change.",
    reservation_cancelled: "This booking is already cancelled.",
    validation_failed: "Please check the guests and time."
  };

  function manageCard(r, editable) {
    if (!editable) return null;
    var status = h("div", { "class": "x-status", "data-testid": "manage-status" });
    var party = h("input", { "class": "input", id: "manage-party", type: "number", min: "1", step: "1",
                             inputmode: "numeric", value: String(r.party_size), "data-testid": "manage-party" });
    var time = h("input", { "class": "input", id: "manage-time", type: "time", value: X.timeOf(r.starts_at_local),
                            "data-testid": "manage-time" });
    var save = h("button", { type: "submit", "class": "button button--primary", "data-testid": "manage-save" }, "Save changes");
    var cancel = h("button", { type: "button", "class": "button button--danger", "data-testid": "manage-cancel" }, "Cancel booking");
    var form = h("form", { "class": "x-form", novalidate: true },
      h("div", { "class": "x-form__row" },
        h("div", { "class": "field" }, h("label", { "class": "field__label", "for": "manage-party" }, "Guests"), party),
        h("div", { "class": "field" }, h("label", { "class": "field__label", "for": "manage-time" }, "Time"), time)),
      h("div", { "class": "x-actions" }, save, cancel), status);

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var change = { expected_revision: r.revision };
      var size = party.value.trim();
      if (!/^\d+$/.test(size) || Number(size) < 1) {
        X.setChildren(status, X.notice("error", "alert", "Check the guests", "Enter a whole number of at least 1.", "manage-error"));
        return;
      }
      if (Number(size) !== r.party_size) change.party_size = Number(size);
      if (time.value && time.value !== X.timeOf(r.starts_at_local)) {
        change.starts_at_local = X.dateOf(r.starts_at_local) + "T" + time.value;
      }
      if (Object.keys(change).length === 1) {
        X.setChildren(status, X.notice("info", "info", "Nothing to change", "The booking already has these details."));
        return;
      }
      save.disabled = true;
      X.api("PATCH", "/reservations/" + encodeURIComponent(reference), { body: change }).then(function (res) {
        if (res.ok) { load("Your booking was updated."); return; }
        if (res.code === "stale_revision") { load("This booking had changed elsewhere; showing the latest details."); return; }
        X.setChildren(status, X.notice("error", "alert", "Not changed", REFUSALS[res.code] || res.message || "Please try again.", "manage-error"));
      }, function (err) {
        X.setChildren(status, X.failureNotice(err, "manage-error"));
      }).finally(function () { save.disabled = false; });
    });

    cancel.addEventListener("click", function () {
      X.confirmDialog({ title: "Cancel this booking?", danger: true, confirm: "Cancel booking", cancel: "Keep it",
                        text: "The table at " + data.restaurant.name + " on " + X.whenText(r.starts_at_local) +
                              " will be released for other guests." }).then(function (yes) {
        if (!yes) return;
        cancel.disabled = true;
        X.api("POST", "/reservations/" + encodeURIComponent(reference) + "/cancel").then(function (res) {
          if (res.ok) { load("Your booking is cancelled."); return; }
          X.setChildren(status, X.notice("error", "alert", "Not cancelled", REFUSALS[res.code] || res.message || "Please try again.", "manage-error"));
        }, function () {
          X.setChildren(status, X.notice("uncertain", "question", "We couldn't confirm the cancellation",
            "Press Cancel booking again to check. Cancelling twice is safe.", "manage-uncertain"));
        }).finally(function () { cancel.disabled = false; });
      });
    });

    return h("section", { "class": "x-card card", "data-testid": "evening-manage", "aria-labelledby": "manage-title" },
      h("div", { "class": "x-card__head" }, X.icon("tool"), h("h2", { "class": "x-card__title", id: "manage-title" }, "Change or cancel")),
      h("p", { "class": "x-card__sub" }, "Changes keep your reference. The restaurant's booking rules for the date apply."),
      form);
  }
})();
