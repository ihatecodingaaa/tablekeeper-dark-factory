/* Search-screen extras: the Best Times panel and the 409 recovery suggestions.
 *
 * Both only read what the server says. Best Times shows the server's ranked slots
 * with its stated reasons; recovery picks the nearest options that the latest
 * GET /availability actually offers. Neither books anything by itself.
 */
(function () {
  "use strict";
  var X = window.TKX;
  var h = X.h;
  var seq = 0;

  /* Render GET /x/best-times into `container`. onPick(starts_at_local) is called when a
   * diner chooses one. A failure leaves a quiet note: the grid still works. */
  function bestTimes(container, query, onPick) {
    seq += 1;
    var mine = seq;
    var params = new URLSearchParams({ restaurant_id: query.restaurantId, date: query.date, party_size: query.partySize });
    X.setChildren(container, X.loading("Finding the best times..."));
    return X.api("GET", "/x/best-times?" + params.toString(), { auth: false }).then(function (res) {
      if (mine !== seq) return;
      if (!res.ok || !res.data || !(res.data.best_times || []).length) {
        X.setChildren(container);
        return;
      }
      X.setChildren(container, h("section", { "class": "x-best card", "data-testid": "best-times", "aria-labelledby": "best-title" },
        h("div", { "class": "x-card__head" }, X.icon("clock"),
          h("h2", { "class": "x-card__title", id: "best-title" }, "Best times for " + X.guests(Number(query.partySize)))),
        h("ol", { "class": "x-best__list" }, res.data.best_times.map(function (item) {
          var button = h("button", { type: "button", "class": "x-best__item", "data-testid": "best-time-" + X.timeOf(item.starts_at_local) },
            h("span", { "class": "x-best__time" }, X.timeOf(item.starts_at_local)),
            h("span", { "class": "x-best__reasons" }, (item.reasons || []).join(" \u00b7 ")));
          button.addEventListener("click", function () { onPick(item.starts_at_local); });
          return h("li", null, button);
        }))));
    }, function () {
      if (mine === seq) X.setChildren(container);
    });
  }

  function minutesOf(local) {
    var t = X.timeOf(local).split(":").map(Number);
    return t[0] * 60 + t[1];
  }

  /* The closest real alternatives after a 409, from the refreshed slots: the same time
   * first, then the nearest times, at most `limit`. Each option is {slot, ids, capacity}. */
  function closestOptions(slots, failedLocal, failedIds, limit) {
    var target = minutesOf(failedLocal);
    var failedKey = failedIds.join("+");
    var options = [];
    (slots || []).forEach(function (slot) {
      (slot.available_options || []).forEach(function (option) {
        var ids = option.table_ids || [];
        if (slot.starts_at_local === failedLocal && ids.join("+") === failedKey) return;
        options.push({ slot: slot, ids: ids, capacity: option.capacity,
                       distance: Math.abs(minutesOf(slot.starts_at_local) - target), size: ids.length });
      });
    });
    options.sort(function (a, b) {
      return a.distance - b.distance || a.size - b.size || a.capacity - b.capacity ||
        a.slot.starts_at_local.localeCompare(b.slot.starts_at_local);
    });
    return options.slice(0, limit || 3);
  }

  /* "This table just went; here are the closest options": buttons that call onSelect(slot, ids). */
  function recoveryPanel(options, describe, onSelect) {
    if (!options.length) {
      return X.notice("info", "calendar", "Nothing close is free",
        "Every table near that time is taken now. Try another date or fewer guests.", "recovery-none");
    }
    return h("section", { "class": "x-recovery", "data-testid": "recovery-options", "aria-labelledby": "recovery-title" },
      h("h3", { "class": "x-recovery__title", id: "recovery-title" }, X.icon("refresh"), "This table just went; here are the closest options"),
      h("ul", { "class": "x-recovery__list" }, options.map(function (option) {
        var button = h("button", { type: "button", "class": "button button--small",
                                   "data-testid": "recovery-" + option.ids.join("+") + "-" + X.timeOf(option.slot.starts_at_local) },
          X.icon("arrow"), describe(option));
        button.addEventListener("click", function () { onSelect(option.slot, option.ids); });
        return h("li", null, button);
      })));
  }

  window.TKSearchExtras = { bestTimes: bestTimes, closestOptions: closestOptions, recoveryPanel: recoveryPanel };
})();
