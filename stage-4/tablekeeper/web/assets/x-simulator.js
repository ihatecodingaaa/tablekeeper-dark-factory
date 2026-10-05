/* Recovery simulator (/simulator): rehearse a table closure on the official planner.
 *
 * 1. Show the healthy service for a date.  2. Choose a table and a window.
 * 3. Run the official replans preview: it stores a plan and changes nothing else.
 * 4. Show, per affected booking, BEFORE -> disruption -> repair -> AFTER and why it holds.
 * 5. Show the messages guests would get.  Applying is a separate, explicit official call.
 */
(function () {
  "use strict";
  var X = window.TKX;
  var h = X.h;
  var root = X.byId("x-root");
  var announcer = X.byId("x-announcer");
  var ctx = { restaurants: [], restaurantId: null, date: X.todayISO(), detail: null, room: null, plan: null,
              closure: null, step: 1 };
  var previewWriter = new X.KeyedWriter("preview");
  var applyWriter = new X.KeyedWriter("apply");
  var serviceSeq = 0;

  if (!X.session.get()) {
    X.signInGate(root, "/simulator", "Sign in to open the simulator", "The recovery simulator is for restaurant managers.");
    return;
  }
  X.managedRestaurants().then(function (info) {
    if (info.signedOut) { X.signInGate(root, "/simulator", "Please sign in again", "Your session has ended."); return; }
    if (!info.restaurants.length) { X.notAManager(root); return; }
    ctx.restaurants = info.restaurants;
    ctx.restaurantId = info.restaurants[0].id;
    frame();
    loadService();
  }, function (err) { X.setChildren(root, X.failureNotice(err, "sim-error")); });

  var steps, serviceArea, disruptionArea, planArea;

  function frame() {
    var select = h("select", { "class": "input", id: "sim-restaurant", "data-testid": "sim-restaurant" },
      ctx.restaurants.map(function (r) { return h("option", { value: r.id }, r.name); }));
    var date = h("input", { "class": "input", id: "sim-date", type: "date", value: ctx.date, "data-testid": "sim-date" });
    var form = h("form", { "class": "x-toolbar card", novalidate: true },
      h("div", { "class": "field" }, h("label", { "class": "field__label", "for": "sim-restaurant" }, "Restaurant"), select),
      h("div", { "class": "field" }, h("label", { "class": "field__label", "for": "sim-date" }, "Service date"), date),
      h("button", { type: "submit", "class": "button", "data-testid": "sim-load" }, X.icon("refresh"), "Show service"));
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      ctx.restaurantId = select.value;
      ctx.date = date.value || X.todayISO();
      ctx.plan = null;
      loadService();
    });
    steps = h("ol", { "class": "x-steps", "aria-label": "Progress", "data-testid": "sim-steps" });
    serviceArea = h("div", { "class": "x-stack" });
    disruptionArea = h("div", { "class": "x-stack" });
    planArea = h("div", { "class": "x-stack", "data-testid": "sim-plan-area" });
    X.setChildren(root,
      h("header", { "class": "x-intro" },
        h("p", { "class": "eyebrow" }, "Restaurant"),
        h("h1", { "class": "x-intro__title" }, "Recovery simulator"),
        h("p", { "class": "x-intro__lede" }, "Rehearse closing a table. The preview runs the real seating planner but changes nothing; " +
          "only \u201cApply plan\u201d moves bookings, and it asks first.")),
      form, steps, serviceArea, disruptionArea, planArea);
    renderSteps();
  }

  function renderSteps() {
    var labels = [["Healthy service", "Bookings as they stand"], ["Disruption", "Pick a table and a window"],
                  ["Repair preview", "The planner's proposal"], ["Applied", "Bookings moved"]];
    X.setChildren(steps, labels.map(function (pair, i) {
      var n = i + 1;
      var cls = n < ctx.step ? " x-step--done" : n === ctx.step ? " x-step--current" : "";
      return h("li", { "class": "x-step" + cls, "aria-current": n === ctx.step ? "step" : null },
        h("strong", null, n + ". " + pair[0]), pair[1]);
    }));
  }

  function loadService(message) {
    serviceSeq += 1;
    var seq = serviceSeq;
    var rid = encodeURIComponent(ctx.restaurantId);
    X.setChildren(serviceArea, X.loading("Loading the service..."));
    X.setChildren(disruptionArea);
    if (!ctx.plan) X.setChildren(planArea);
    return Promise.all([
      X.api("GET", "/x/restaurants/" + rid + "/control-room?date=" + encodeURIComponent(ctx.date)),
      X.api("GET", "/restaurants/" + rid, { auth: false })
    ]).then(function (answers) {
      if (seq !== serviceSeq) return;
      if (!answers[0].ok || !answers[1].ok) {
        var bad = answers[0].ok ? answers[1] : answers[0];
        X.setChildren(serviceArea, bad.status === 403
          ? X.notice("error", "lock", "Not your restaurant", "You don't manage this restaurant.", "sim-error")
          : X.notice("error", "alert", "The service didn't load", bad.message || "", "sim-error"));
        return;
      }
      ctx.room = answers[0].data;
      ctx.detail = answers[1].data;
      if (!ctx.plan) ctx.step = 1;
      renderSteps();
      renderService();
      renderDisruption();
      if (message) announcer.textContent = message;
    }, function (err) {
      if (seq === serviceSeq) X.setChildren(serviceArea, X.failureNotice(err, "sim-error"));
    });
  }

  function labelOf(tableId) {
    var tables = (ctx.detail && ctx.detail.tables) || [];
    for (var i = 0; i < tables.length; i++) if (tables[i].id === tableId) return tables[i].label;
    return tableId;
  }

  function byReference(reference) {
    var rows = (ctx.room && ctx.room.reservations) || [];
    for (var i = 0; i < rows.length; i++) if (rows[i].reference === reference) return rows[i];
    return null;
  }

  function renderService() {
    var rows = ctx.room.reservations.filter(function (r) { return r.status === "confirmed"; });
    X.setChildren(serviceArea, h("section", { "class": "x-card card", "data-testid": "sim-service", "aria-labelledby": "sim-service-title" },
      h("div", { "class": "x-card__head" }, X.icon("calendar"),
        h("h2", { "class": "x-card__title", id: "sim-service-title" }, (ctx.plan ? "Service now" : "Healthy service") + ", " + X.formatDate(ctx.room.date))),
      rows.length ? h("div", { "class": "x-scroll", role: "region", tabindex: "0", "aria-label": "Bookings" },
        h("table", { "class": "x-table" },
          h("thead", null, h("tr", null, ["Time", "Guest", "Party", "Tables", "Ref"].map(function (t) { return h("th", { scope: "col" }, t); }))),
          h("tbody", null, rows.map(function (r) {
            return h("tr", null, h("td", null, r.time), h("td", null, r.guest), h("td", { "class": "x-num" }, String(r.party_size)),
              h("td", null, X.tableText(r.table_labels)), h("td", { "class": "x-reference" }, r.reference));
          }))))
        : X.emptyState("calendar", "No bookings on this date", "Pick a busier date to see a repair in action."),
      (ctx.room.closures || []).length ? h("p", { "class": "x-hint" }, "Already closed: " + ctx.room.closures.map(function (c) {
        return X.tableText([labelOf(c.table_id)]) + " (" + X.stamp(c.from) + " \u2013 " + X.stamp(c.to) + ")";
      }).join(", ")) : null));
  }

  function renderDisruption() {
    var tables = (ctx.detail.tables || []);
    var table = h("select", { "class": "input", id: "sim-table", "data-testid": "sim-table" },
      tables.map(function (t) { return h("option", { value: t.id }, X.tableText([t.label]) + " \u00b7 seats " + t.capacity); }));
    var from = h("input", { "class": "input", id: "sim-from", type: "time", value: "18:00", "data-testid": "sim-from" });
    var to = h("input", { "class": "input", id: "sim-to", type: "time", value: "23:00", "data-testid": "sim-to" });
    var status = h("div", { "class": "x-status", "data-testid": "sim-preview-status" });
    var run = h("button", { type: "submit", "class": "button button--primary", "data-testid": "sim-preview" },
      X.icon("tool"), "Preview repair");
    var form = h("form", { "class": "x-form", novalidate: true },
      h("div", { "class": "x-form__row" },
        h("div", { "class": "field" }, h("label", { "class": "field__label", "for": "sim-table" }, "Table that becomes unavailable"), table),
        h("div", { "class": "x-form__row" },
          h("div", { "class": "field" }, h("label", { "class": "field__label", "for": "sim-from" }, "From"), from),
          h("div", { "class": "field" }, h("label", { "class": "field__label", "for": "sim-to" }, "Until"), to))),
      h("p", { "class": "x-hint" }, "Times are local to the restaurant (" + ctx.room.restaurant.timezone + "). The preview changes nothing."),
      h("div", { "class": "x-actions" }, run), status);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!from.value || !to.value || to.value <= from.value) {
        X.setChildren(status, X.notice("error", "alert", "Check the window", "Choose a start time before the end time on the same day.", "sim-preview-error"));
        return;
      }
      preview(table.value, from.value, to.value, run, status);
    });
    X.setChildren(disruptionArea, h("section", { "class": "x-card card", "data-testid": "sim-disruption", "aria-labelledby": "sim-d-title" },
      h("div", { "class": "x-card__head" }, X.icon("pause"), h("h2", { "class": "x-card__title", id: "sim-d-title" }, "Choose a disruption")),
      form));
  }

  var PREVIEW_ERRORS = {
    no_feasible_plan: ["No repair is possible", "There is no way to reseat every affected booking with the tables left. Try a shorter window or another table."],
    planning_limit: ["Too large to plan here", "This closure affects more bookings or tables than the planner handles at once. Try a shorter window."],
    validation_failed: ["Check the window", "The closure window isn't valid."],
    not_found: ["Unknown table", "That table isn't part of this restaurant."],
    forbidden: ["Not your restaurant", "You don't manage this restaurant."]
  };

  function preview(tableId, fromTime, toTime, button, status) {
    var zone = ctx.room.restaurant.timezone;
    var body = { table_id: tableId, from: X.zonedInstant(ctx.date, fromTime, zone), to: X.zonedInstant(ctx.date, toTime, zone) };
    var path = "/restaurants/" + encodeURIComponent(ctx.restaurantId) + "/replans";
    button.disabled = true;
    X.setChildren(status, X.loading("Asking the planner..."));
    X.api("POST", path, { body: body, key: previewWriter.keyFor(path, body) }).then(function (res) {
      if (!res.ok) {
        var text = PREVIEW_ERRORS[res.code] || ["No preview", res.message || "Please try again."];
        X.setChildren(status, X.notice("error", "alert", text[0], text[1], "sim-preview-error"));
        return;
      }
      X.setChildren(status);
      ctx.plan = res.data;
      ctx.closure = { table_id: tableId, from: fromTime, to: toTime };
      ctx.step = 3;
      renderSteps();
      renderPlan(false);
      announcer.textContent = "Preview ready: " + X.plural(res.data.moved_count, "booking") + " would move.";
    }, function (err) {
      X.setChildren(status, X.failureNotice(err, "sim-preview-error"));
    }).finally(function () { button.disabled = false; });
  }

  function renderPlan(applied) {
    var plan = ctx.plan;
    var closedLabel = X.tableText([labelOf(ctx.closure.table_id)]);
    var rows = plan.assignments.map(function (a) {
      var before = byReference(a.reference);
      var beforeLabels = before ? before.table_labels : [];
      var afterLabels = a.table_ids.map(labelOf);
      var why = a.changed
        ? "Fits the party of " + (before ? before.party_size : "?") + " under the terms this booking accepted, with no clash with other bookings or closed tables. Time, party and terms stay the same."
        : "Not touched: its tables are unaffected by the closure.";
      return h("li", { "class": "x-repair__row card", "data-testid": "sim-assignment-" + a.reference },
        cell("Before", X.tableText(beforeLabels), (before ? before.time + " \u00b7 " + before.guest : a.reference)),
        h("span", { "class": "x-repair__arrow", "aria-hidden": "true" }, X.icon("arrow")),
        cell("Disruption", closedLabel + " closed", ctx.closure.from + " \u2013 " + ctx.closure.to),
        h("span", { "class": "x-repair__arrow", "aria-hidden": "true" }, X.icon("arrow")),
        cell(applied ? "After" : "Proposed", X.tableText(afterLabels), a.changed ? "Guest is told" : "Guest not affected"),
        h("p", { "class": "x-repair__why" },
          a.changed ? X.badge("warn", "refresh", "Moves") : X.badge("ok", "check", "Stays"), " ", why));
    });
    var apply = h("button", { type: "button", "class": "button button--primary", "data-testid": "sim-apply" },
      X.icon("check"), "Apply plan");
    var status = h("div", { "class": "x-status", "data-testid": "sim-apply-status" });
    apply.addEventListener("click", function () { applyPlan(apply, status); });
    X.setChildren(planArea,
      h("section", { "class": "x-card card", "data-testid": "sim-plan", "aria-labelledby": "sim-plan-title" },
        h("div", { "class": "x-card__head" }, X.icon("tool"),
          h("h2", { "class": "x-card__title", id: "sim-plan-title" }, applied ? "Repair applied" : "Proposed repair")),
        h("p", { "class": "x-card__sub" }, X.plural(plan.moved_count, "booking") + " " + (applied ? "moved" : "would move") +
          " \u00b7 " + X.plural(plan.unused_seats, "unused seat") + " across affected bookings \u00b7 plan " + plan.plan_id),
        rows.length ? h("ol", { "class": "x-repair" }, rows)
          : h("p", { "class": "x-hint" }, "No bookings overlap this window, so nobody needs to move."),
        applied ? X.notice("success", "check", "Bookings moved", "Guests have been told about their new tables.", "sim-applied")
          : h("div", { "class": "x-actions" }, apply), status),
      messagesCard(plan, applied));
  }

  function cell(label, value, sub) {
    return h("div", { "class": "x-repair__cell" }, h("span", { "class": "x-repair__label" }, label),
      h("span", { "class": "x-repair__value" }, value), sub ? h("span", { "class": "x-hint" }, sub) : null);
  }

  function messagesCard(plan, applied) {
    var moved = plan.assignments.filter(function (a) { return a.changed; });
    return h("section", { "class": "x-card card", "data-testid": "sim-messages", "aria-labelledby": "sim-m-title" },
      h("div", { "class": "x-card__head" }, X.icon("bell"),
        h("h2", { "class": "x-card__title", id: "sim-m-title" }, applied ? "Messages sent" : "Messages guests would get")),
      applied ? null : h("p", { "class": "x-card__sub" }, "A preview; nothing has been sent."),
      moved.length ? h("ul", { "class": "x-list" }, moved.map(function (a) {
        var before = byReference(a.reference);
        return h("li", { "class": "x-list__item" },
          h("p", { "class": "x-list__title" }, "To " + (before ? before.guest : "the guest") + " \u00b7 " + a.reference),
          h("p", { "class": "x-list__body" }, "Your table at " + ctx.room.restaurant.name + " on " + X.formatDate(ctx.date) +
            (before ? " at " + before.time : "") + " changes from " + X.tableText(before ? before.table_labels : []) +
            " to " + X.tableText(a.table_ids.map(labelOf)) + ". Your time, party size and booking terms stay the same."));
      })) : h("p", { "class": "x-hint" }, "Nobody needs a message."));
  }

  var APPLY_ERRORS = {
    stale_plan: ["Something changed since the preview", "A booking or rule changed after this preview. Preview again to plan with the latest bookings."],
    plan_already_applied: ["Already applied", "This plan has already been applied."]
  };

  function applyPlan(button, status) {
    X.confirmDialog({ title: "Apply this repair?", confirm: "Apply plan", cancel: "Not yet",
                      text: X.plural(ctx.plan.moved_count, "booking") + " will move to new tables and the guests will be told. " +
                            "Times, party sizes and booking terms do not change." }).then(function (yes) {
      if (!yes) return;
      var path = "/restaurants/" + encodeURIComponent(ctx.restaurantId) + "/replans/" + encodeURIComponent(ctx.plan.plan_id) + "/apply";
      button.disabled = true;
      X.setChildren(status, X.loading("Applying the repair..."));
      X.api("POST", path, { body: {}, key: applyWriter.keyFor(path, {}) }).then(function (res) {
        if (res.ok) {
          ctx.step = 4;
          renderSteps();
          renderPlan(true);
          loadService("Repair applied. " + X.plural(ctx.plan.moved_count, "booking") + " moved.");
          return;
        }
        button.disabled = false;
        var text = APPLY_ERRORS[res.code] || ["Not applied", res.message || "Please try again."];
        X.setChildren(status, X.notice("error", "alert", text[0], text[1], "sim-apply-error"));
      }, function () {
        button.disabled = false;
        X.setChildren(status, X.notice("uncertain", "question", "Outcome unknown",
          "Press \u201cApply plan\u201d again to check. It is safe and never applies twice.", "sim-apply-uncertain"));
      });
    });
  }
})();
