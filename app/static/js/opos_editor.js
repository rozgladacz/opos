(() => {
  "use strict";

  const root = document.getElementById("opos-editor");
  if (!root || !window.OPOS) return;

  const {fetchJSON, icon, toast} = window.OPOS;
  const rosterId = Number(root.dataset.rosterId);
  const armyId = Number(root.dataset.armyId || 0);
  const customStats = root.dataset.customStats === "true";
  const pointsScale = Number(root.dataset.pointsScale);
  const collapseDescriptions = root.dataset.collapseDescriptions === "true";
  const smallBattle = root.dataset.smallBattle === "true";
  const shieldFist = root.dataset.shieldFist === "true";
  const armySelect = document.getElementById("roster-army-select");
  const dialog = document.getElementById("unit-dialog");
  dialog.classList.toggle("is-compact", collapseDescriptions);
  const form = document.getElementById("unit-form");
  const units = JSON.parse(document.getElementById("units-data").textContent || "[]");
  const ranges = ["melee", "short", "long"];
  let ruleset = null;
  let editingId = null;
  let quoteTimer = null;
  let quoteSequence = 0;
  let quoteController = null;
  let draggedRow = null;
  let draggedPointerId = null;
  let orderBeforeDrag = [];
  let reorderQueue = Promise.resolve();

  armySelect?.addEventListener("change", () => armySelect.form.requestSubmit());

  function numberText(value) {
    return String(Number(value));
  }

  function formattedStat(statName, value) {
    const text = numberText(value);
    if (!shieldFist) return text;
    if (statName === "strength") return `${text}+`;
    if (statName === "defense") return Number(value) < 0 ? text : `+${text}`;
    return text;
  }

  function createStatControl(id, statName, choices, value) {
    const control = document.createElement(customStats ? "input" : "select");
    control.id = id;
    control.required = true;
    if (customStats) {
      control.type = "number";
      const limits = ruleset.custom_stats[statName];
      control.step = limits.integer_only ? "1" : "any";
      control.min = numberText(limits.minimum);
      control.max = numberText(limits.maximum);
      control.value = numberText(value);
    } else {
      choices.forEach((choice, index) => {
        const option = document.createElement("option");
        option.value = numberText(choice);
        const description = ruleset.stat_descriptions[statName]?.[index];
        option.textContent = description
          ? `${formattedStat(statName, choice)} — ${description}`
          : formattedStat(statName, choice);
        control.append(option);
      });
      control.value = numberText(value);
    }
    return control;
  }

  function abilityChoice(definition, group, checked = false) {
    const label = document.createElement("label");
    label.className = "ability-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = group;
    input.value = definition.slug;
    input.checked = checked;
    const copy = document.createElement("span");
    copy.className = "ability-copy";
    const strong = document.createElement("strong");
    strong.textContent = definition.name;
    copy.append(strong);
    if (!collapseDescriptions) {
      const small = document.createElement("small");
      small.textContent = smallBattle && definition.small_battle_description
        ? definition.small_battle_description
        : definition.description;
      copy.append(small);
    }
    label.append(input, icon(definition.icon, definition.name), copy);
    return label;
  }

  function emptyProfile() {
    return {dice: 0, strength: ruleset.standard_stats.strength[0], abilities: []};
  }

  function emptyUnit() {
    const toughnessChoices = smallBattle
      ? ruleset.standard_stats.toughness.map((value) => Number(value) * 2)
      : ruleset.standard_stats.toughness;
    return {
      name: "",
      models_per_unit: 1,
      unit_copies: 1,
      defense: ruleset.standard_stats.defense[0],
      toughness: toughnessChoices[0],
      passive_abilities: [],
      special_abilities: [],
      profiles: {melee: emptyProfile(), short: emptyProfile(), long: emptyProfile()},
    };
  }

  function targetedSpecialDefinition() {
    return ruleset.abilities.find((item) => item.category === "special" && item.requires_target) || null;
  }

  function buildForm(unit) {
    document.getElementById("unit-name").value = unit.name;
    document.getElementById("models-per-unit").value = unit.models_per_unit;
    document.getElementById("unit-copies").value = unit.unit_copies;

    const defenseHost = document.getElementById("defense-field");
    const toughnessHost = document.getElementById("toughness-field");
    const toughnessChoices = smallBattle
      ? ruleset.standard_stats.toughness.map((value) => Number(value) * 2)
      : ruleset.standard_stats.toughness;
    const defense = createStatControl("defense", "defense", ruleset.standard_stats.defense, unit.defense);
    defenseHost.replaceChildren(defense);
    toughnessHost.replaceChildren(createStatControl("toughness", "toughness", toughnessChoices, unit.toughness));

    const passiveHost = document.getElementById("passive-options");
    passiveHost.replaceChildren();
    ruleset.abilities.filter((item) => item.category === "passive").forEach((definition) => {
      passiveHost.append(abilityChoice(definition, "passive", unit.passive_abilities.includes(definition.slug)));
    });

    const selectedSpecials = new Map(unit.special_abilities.map((item) => [item.slug, item]));
    const specialHost = document.getElementById("special-options");
    specialHost.replaceChildren();
    ruleset.abilities.filter((item) => item.category === "special").forEach((definition) => {
      specialHost.append(abilityChoice(definition, "special", selectedSpecials.has(definition.slug)));
    });
    const auraTarget = document.getElementById("aura-target");
    auraTarget.replaceChildren();
    ruleset.abilities.filter((item) => item.aura_eligible).forEach((definition) => {
      const option = document.createElement("option");
      option.value = definition.slug;
      option.textContent = definition.name;
      auraTarget.append(option);
    });
    const targetedSpecial = targetedSpecialDefinition();
    auraTarget.value = selectedSpecials.get(targetedSpecial?.slug)?.target_slug || auraTarget.options[0]?.value || "";
    toggleAuraTarget();

    const profileHost = document.getElementById("profile-editors");
    profileHost.replaceChildren();
    const weaponAbilities = ruleset.abilities.filter((item) => item.category === "weapon");
    ranges.forEach((rangeSlug) => {
      const profile = unit.profiles[rangeSlug] || emptyProfile();
      const rangeDefinition = ruleset.ranges[rangeSlug];
      const article = document.createElement("article");
      article.className = "profile-editor";
      article.dataset.range = rangeSlug;
      const title = document.createElement("h4");
      title.className = "profile-title";
      title.append(icon(rangeDefinition.icon, rangeDefinition.name), document.createTextNode(rangeDefinition.name));
      const fields = document.createElement("div");
      fields.className = "profile-fields";
      const diceLabel = document.createElement("label");
      diceLabel.textContent = "Kości ataku";
      const dice = document.createElement("input");
      dice.type = "number";
      dice.min = "0";
      dice.max = "999";
      dice.step = "1";
      dice.value = profile.dice;
      dice.dataset.field = "dice";
      diceLabel.append(dice);
      const strengthLabel = document.createElement("label");
      strengthLabel.textContent = ruleset.stat_labels.strength;
      const strength = createStatControl("strength", "strength", ruleset.standard_stats.strength, profile.strength);
      strength.removeAttribute("id");
      strength.dataset.field = "strength";
      strengthLabel.append(strength);
      fields.append(diceLabel, strengthLabel);
      const options = document.createElement("div");
      options.className = "weapon-options";
      weaponAbilities.filter((definition) => definition.allowed_ranges.includes(rangeSlug)).forEach((definition) => {
        options.append(abilityChoice(definition, `weapon-${rangeSlug}`, profile.abilities.includes(definition.slug)));
      });
      article.append(title, fields, options);
      profileHost.append(article);
    });
    refreshAbilityConflicts();
  }

  function selectedAbilitySlugs() {
    return new Set([
      ...values("passive"),
      ...values("special"),
      ...ranges.flatMap((rangeSlug) => values(`weapon-${rangeSlug}`)),
    ]);
  }

  function abilitiesConflict(leftSlug, rightSlug) {
    const left = ruleset.abilities.find((item) => item.slug === leftSlug);
    const right = ruleset.abilities.find((item) => item.slug === rightSlug);
    return (left?.incompatible_with || []).includes(rightSlug)
      || (right?.incompatible_with || []).includes(leftSlug);
  }

  function refreshAbilityConflicts() {
    const selected = selectedAbilitySlugs();
    form.querySelectorAll('.ability-option input[type="checkbox"]').forEach((input) => {
      const conflictingSlug = [...selected].find((slug) => slug !== input.value && abilitiesConflict(input.value, slug));
      const blocked = !input.checked && Boolean(conflictingSlug);
      input.disabled = blocked;
      const label = input.closest(".ability-option");
      label.classList.toggle("is-disabled", blocked);
      label.title = blocked
        ? `Nie można łączyć ze zdolnością „${ruleset.abilities.find((item) => item.slug === conflictingSlug)?.name}”.`
        : "";
    });
  }

  function toggleAuraTarget() {
    const targetedSpecial = targetedSpecialDefinition();
    const checked = targetedSpecial
      ? form.querySelector(`input[name="special"][value="${targetedSpecial.slug}"]`)?.checked
      : false;
    document.getElementById("aura-target-field").hidden = !checked;
  }

  function values(name, scope = form) {
    return [...scope.querySelectorAll(`input[name="${name}"]:checked`)].map((item) => item.value);
  }

  function collectPayload() {
    const specialAbilities = values("special").map((slug) => {
      const definition = ruleset.abilities.find((item) => item.slug === slug);
      return definition?.requires_target
        ? {slug, target_slug: document.getElementById("aura-target").value}
        : {slug};
    });
    const profiles = {};
    ranges.forEach((rangeSlug) => {
      const editor = form.querySelector(`.profile-editor[data-range="${rangeSlug}"]`);
      profiles[rangeSlug] = {
        dice: Number(editor.querySelector('[data-field="dice"]').value),
        strength: editor.querySelector('[data-field="strength"]').value,
        abilities: values(`weapon-${rangeSlug}`, editor),
      };
    });
    return {
      name: document.getElementById("unit-name").value.trim() || "Oddział",
      models_per_unit: Number(document.getElementById("models-per-unit").value),
      unit_copies: Number(document.getElementById("unit-copies").value),
      defense: document.getElementById("defense").value,
      toughness: document.getElementById("toughness").value,
      passive_abilities: values("passive"),
      special_abilities: specialAbilities,
      profiles,
      custom_stats_enabled: customStats,
      points_scale: pointsScale,
      small_battle_enabled: smallBattle,
      shield_fist_enabled: shieldFist,
    };
  }

  function renderQuote(quote) {
    document.getElementById("quote-unit-cost").textContent = `${quote.rounded_unit_cost} pkt`;
    document.getElementById("quote-entry-cost").textContent = `${quote.entry_cost} pkt`;
    const breakdown = document.getElementById("quote-breakdown");
    breakdown.replaceChildren();
    [
      ["Koszt bazowy", quote.base_cost], ["Profile ataku", quote.weapon_cost],
      ["Rozkaz", quote.order_cost], ["Aura", quote.aura_cost],
      ["Modyfikator Życia", `× ${quote.toughness_modifier}`],
      ["Cena surowa", quote.raw_unit_cost],
    ].forEach(([label, value]) => {
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = label;
      dd.textContent = value;
      breakdown.append(dt, dd);
    });
    document.getElementById("quote-error").hidden = true;
  }

  function requestQuote() {
    window.clearTimeout(quoteTimer);
    quoteTimer = window.setTimeout(async () => {
      const sequence = ++quoteSequence;
      quoteController?.abort();
      quoteController = new AbortController();
      try {
        const quote = await fetchJSON("/quote", {method: "POST", body: collectPayload(), signal: quoteController.signal});
        if (sequence === quoteSequence) renderQuote(quote);
      } catch (error) {
        if (error.name === "AbortError" || sequence !== quoteSequence) return;
        document.getElementById("quote-error").textContent = error.message;
        document.getElementById("quote-error").hidden = false;
        document.getElementById("quote-unit-cost").textContent = "—";
        document.getElementById("quote-entry-cost").textContent = "—";
      }
    }, 160);
  }

  function openEditor(unit = emptyUnit()) {
    editingId = unit.id || null;
    document.getElementById("unit-dialog-title").textContent = editingId ? "Edytuj oddział" : "Dodaj oddział";
    document.getElementById("save-unit").textContent = editingId ? "Zapisz zmiany" : "Dodaj oddział";
    buildForm(unit);
    dialog.showModal();
    document.getElementById("unit-name").focus();
    requestQuote();
  }

  function closeEditor() {
    quoteController?.abort();
    dialog.close();
  }

  async function unitAction(url, method = "POST", body = undefined) {
    await fetchJSON(url, {method, body});
    window.location.reload();
  }

  function orderedUnitIds() {
    return [...document.querySelectorAll("#unit-list .unit-row")]
      .map((item) => Number(item.dataset.unitId));
  }

  function saveUnitOrder() {
    const unitIds = orderedUnitIds();
    const send = () => fetchJSON(`/rosters/${rosterId}/units/reorder`, {
      method: "POST",
      body: {unit_ids: unitIds},
    });
    reorderQueue = reorderQueue.then(send, send);
    return reorderQueue;
  }

  function finishDragging() {
    if (!draggedRow) return;
    const handle = draggedRow.querySelector(".drag-handle");
    if (draggedPointerId !== null && handle?.hasPointerCapture(draggedPointerId)) {
      handle.releasePointerCapture(draggedPointerId);
    }
    draggedRow.classList.remove("is-dragging");
    const orderChanged = orderedUnitIds().some((id, index) => id !== orderBeforeDrag[index]);
    draggedRow = null;
    draggedPointerId = null;
    orderBeforeDrag = [];
    if (orderChanged) {
      saveUnitOrder().catch((error) => {
        toast(error.message);
        window.location.reload();
      });
    }
  }

  form.addEventListener("change", (event) => {
    const targetedSpecial = targetedSpecialDefinition();
    if (targetedSpecial && event.target.matches(`input[name="special"][value="${targetedSpecial.slug}"]`)) toggleAuraTarget();
    refreshAbilityConflicts();
    requestQuote();
  });
  form.addEventListener("input", requestQuote);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const button = document.getElementById("save-unit");
    button.disabled = true;
    try {
      const url = editingId ? `/rosters/${rosterId}/units/${editingId}` : `/rosters/${rosterId}/units`;
      await fetchJSON(url, {method: editingId ? "PATCH" : "POST", body: collectPayload()});
      window.location.reload();
    } catch (error) {
      toast(error.message);
      button.disabled = false;
    }
  });

  document.getElementById("add-unit").addEventListener("click", () => openEditor());
  document.getElementById("close-unit-dialog").addEventListener("click", closeEditor);
  document.getElementById("cancel-unit").addEventListener("click", closeEditor);
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeEditor();
  });

  const unitList = document.getElementById("unit-list");
  unitList.addEventListener("pointerdown", (event) => {
    const handle = event.target.closest(".drag-handle");
    if (!handle || event.button !== 0) return;
    draggedRow = handle.closest(".unit-row");
    draggedPointerId = event.pointerId;
    orderBeforeDrag = orderedUnitIds();
    handle.setPointerCapture(event.pointerId);
    draggedRow.classList.add("is-dragging");
    event.preventDefault();
  });
  unitList.addEventListener("pointermove", (event) => {
    if (!draggedRow || event.pointerId !== draggedPointerId) return;
    const target = document.elementFromPoint(event.clientX, event.clientY)?.closest(".unit-row");
    if (!target || target === draggedRow || target.parentElement !== unitList) return;
    const insertAfter = event.clientY > target.getBoundingClientRect().top + target.offsetHeight / 2;
    unitList.insertBefore(draggedRow, insertAfter ? target.nextElementSibling : target);
    event.preventDefault();
  });
  unitList.addEventListener("pointerup", finishDragging);
  unitList.addEventListener("pointercancel", finishDragging);
  unitList.addEventListener("keydown", async (event) => {
    const handle = event.target.closest(".drag-handle");
    if (!handle || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
    const row = handle.closest(".unit-row");
    const sibling = event.key === "ArrowUp" ? row.previousElementSibling : row.nextElementSibling;
    if (!sibling?.classList.contains("unit-row")) return;
    event.preventDefault();
    if (event.key === "ArrowUp") unitList.insertBefore(row, sibling);
    else unitList.insertBefore(sibling, row);
    try {
      await saveUnitOrder();
      handle.focus();
    } catch (error) {
      toast(error.message);
      window.location.reload();
    }
  });

  unitList.addEventListener("click", async (event) => {
    const row = event.target.closest(".unit-row");
    if (!row) return;
    const unitId = Number(row.dataset.unitId);
    const unit = units.find((item) => item.id === unitId);
    try {
      if (event.target.closest(".js-edit-unit")) return openEditor(unit);
      if (event.target.closest(".js-duplicate-unit")) return unitAction(`/rosters/${rosterId}/units/${unitId}/duplicate`);
      if (event.target.closest(".js-delete-unit")) {
        if (window.confirm(`Usunąć profil „${unit.name}”?`)) await unitAction(`/rosters/${rosterId}/units/${unitId}`, "DELETE");
        return;
      }
      if (event.target.closest(".js-save-template") && armyId) {
        await unitAction(`/rosters/${rosterId}/units/${unitId}/save-template`, "POST", {army_id: armyId});
        return;
      }
      if (event.target.closest(".js-update-template")) {
        if (window.confirm("Zastąpić zapisany szablon bieżącym profilem?")) await unitAction(`/rosters/${rosterId}/units/${unitId}/update-template`);
        return;
      }
    } catch (error) {
      toast(error.message);
    }
  });

  document.querySelectorAll(".js-add-template").forEach((button) => {
    button.addEventListener("click", async () => {
      const templateId = Number(button.dataset.templateId);
      try {
        await unitAction(`/rosters/${rosterId}/units/from-template`, "POST", {template_id: templateId});
      } catch (error) {
        if (error.status === 409 && window.confirm("Ten profil ma niestandardowe statystyki. Włączyć tryb „Dowolne statystyki” dla rozpiski?")) {
          try {
            await unitAction(`/rosters/${rosterId}/units/from-template`, "POST", {template_id: templateId, enable_custom_stats: true});
          } catch (retryError) { toast(retryError.message); }
        } else {
          toast(error.message);
        }
      }
    });
  });

  fetchJSON(`/ruleset?shield_fist_enabled=${shieldFist}`)
    .then((manifest) => {
      ruleset = manifest;
      document.getElementById("defense-label").textContent = ruleset.stat_labels.defense;
    })
    .catch((error) => {
      document.getElementById("add-unit").disabled = true;
      toast(`Nie udało się wczytać reguł: ${error.message}`);
    });
})();
