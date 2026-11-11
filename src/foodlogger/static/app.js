"use strict";

const $ = (id) => document.getElementById(id);
const state = { foods: [], photoUrl: null, predictionVersion: 0, journalVersion: 0, toastTimer: null, saving: false, predicting: false, user: null, csrf: null, mode: "photo", product: null, authMode: "login" };
const format = (value) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 });
function today() {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

async function request(path, options) {
  const headers = new Headers(options?.headers || {});
  if (state.csrf) headers.set("X-CSRF-Token", state.csrf);
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  if (response.status === 401 && !path.startsWith("/api/auth/")) setAccount(null);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload.detail === "string" ? payload.detail : "Please check your entry and try again.");
  }
  return response.status === 204 ? null : response.json();
}

function toast(message, error = false) {
  clearTimeout(state.toastTimer);
  $("toast").textContent = message;
  $("toast").className = error ? "toast error" : "toast";
  $("toast").hidden = false;
  state.toastTimer = setTimeout(() => { $("toast").hidden = true; }, 5000);
}

function predictionMessage(message, kind = "") {
  $("prediction-message").textContent = message;
  $("prediction-message").className = `prediction-message ${kind}`;
  $("prediction-message").hidden = !message;
}

function updateEstimate() {
  const food = state.mode === "photo" ? state.foods.find((item) => item.id === $("food-select").value) : readNutrition();
  const grams = Number($("grams").value);
  if (!food || coreNutrients.some((key) => food[key] == null || !Number.isFinite(food[key]))) {
    $("portion-estimate").textContent = state.mode === "photo" ? "Choose a food to see your portion estimate." : "Enter energy, protein, carbohydrates and fat to see your portion estimate.";
    return;
  }
  if (!Number.isFinite(grams) || grams < 1 || grams > 2000) {
    $("portion-estimate").textContent = `Enter a portion between 1 and 2,000 ${$("quantity-unit").textContent}.`;
    return;
  }
  $("portion-estimate").textContent = `${format(food.calories * grams / 100)} kcal · ${format(food.protein * grams / 100)} g protein · ${format(food.carbs * grams / 100)} g carbs · ${format(food.fat * grams / 100)} g fat`;
}

function selectFood(foodId) {
  $("food-select").value = foodId;
  document.querySelectorAll(".candidate").forEach((button) => button.classList.toggle("selected", button.dataset.foodId === foodId));
  updateEstimate();
}

function updateBusyState() {
  const busy = state.saving || state.predicting;
  $("add-food").setAttribute("aria-disabled", String(!state.user));
  $("add-food").querySelectorAll("input, select, button").forEach((control) => { control.disabled = busy || !state.user; });
  $("drop-zone").classList.toggle("busy", busy || !state.user);
  $("logout-button").disabled = busy;
  $("catalog-fields").querySelectorAll("input, select").forEach((control) => { control.disabled ||= state.mode !== "photo"; });
  $("custom-fields").querySelectorAll("input, select").forEach((control) => { control.disabled ||= state.mode === "photo"; });
}

async function analyzePhoto(file) {
  if (!file || !state.user || state.saving || state.predicting) return;
  const version = ++state.predictionVersion;
  $("candidates").replaceChildren();
  selectFood("");
  if (file.size > 8 * 1024 * 1024) {
    predictionMessage("This image is too large. Choose one under 8 MiB.", "error");
    return;
  }
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
    predictionMessage("Choose a JPEG, PNG or WebP photo.", "error");
    return;
  }
  if (state.photoUrl) URL.revokeObjectURL(state.photoUrl);
  state.photoUrl = URL.createObjectURL(file);
  $("preview-image").src = state.photoUrl;
  $("upload-prompt").hidden = true;
  $("image-preview").hidden = false;
  state.predicting = true;
  updateBusyState();
  predictionMessage("Looking at your food… This may take a moment.");
  const body = new FormData();
  body.append("file", file);
  try {
    const result = await request("/api/predict", { method: "POST", body });
    if (version !== state.predictionVersion) return;
    const recognized = result.status === "recognized";
    predictionMessage(recognized ? "A possible match. Confirm the food and enter its weight before saving." : (result.unmapped_label ? `The model suggested “${result.unmapped_label.replaceAll("_", " ")}”, which has no nutrition entry. Choose a catalog food manually.` : "No confident match. Choose a food manually, or try a clearer photo of one food."), recognized ? "" : "warning");
    for (const candidate of result.candidates) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "candidate";
      button.dataset.foodId = candidate.food_id;
      button.textContent = `${candidate.emoji} ${candidate.name} · ${format(candidate.score * 100)}%`;
      button.title = "Model score; not a measured accuracy or calibrated probability";
      button.addEventListener("click", () => selectFood(candidate.food_id));
      $("candidates").append(button);
    }
    if (recognized && result.candidates.length) selectFood(result.candidates[0].food_id);
  } catch (error) {
    if (version === state.predictionVersion) predictionMessage(error.message, "error");
  } finally {
    if (version === state.predictionVersion) {
      state.predicting = false;
      updateBusyState();
    }
  }
}

function renderMeal(meal) {
  const row = document.createElement("article");
  row.className = "meal-entry";
  const emoji = document.createElement("span");
  emoji.className = "meal-emoji";
  emoji.setAttribute("aria-hidden", "true");
  emoji.textContent = meal.emoji;
  const details = document.createElement("div");
  details.className = "meal-main";
  const title = document.createElement("h3");
  title.textContent = meal.name;
  const subtitle = document.createElement("p");
  subtitle.textContent = `${meal.meal_type} · ${format(meal.grams)} ${meal.details?.basis_unit || "g"}`;
  const macros = document.createElement("small");
  macros.textContent = `P ${format(meal.protein)} g · C ${format(meal.carbs)} g · F ${format(meal.fat)} g`;
  details.append(title, subtitle, macros);
  if (meal.details?.nutrition_total) {
    const disclosure = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Nutrition details";
    const list = document.createElement("dl");
    list.className = "nutrition-list";
    nutrientNames.forEach(([key, label]) => addDefinition(list, label, meal.details.nutrition_total[key] == null ? "Not supplied" : `${format(meal.details.nutrition_total[key])} ${key === "calories" ? "kcal" : "g"}`));
    disclosure.append(summary, list);
    if (meal.details.barcode) {
      const source = document.createElement("a");
      source.href = `https://world.openfoodfacts.org/product/${encodeURIComponent(meal.details.barcode)}`;
      source.target = "_blank"; source.rel = "noopener";
      source.textContent = `Open Food Facts · ${meal.details.barcode}`;
      disclosure.append(source);
    }
    if (Object.keys(meal.details.raw_nutriments || {}).length) {
      const raw = document.createElement("details");
      const heading = document.createElement("summary"); heading.textContent = "Original product values";
      const values = document.createElement("dl"); values.className = "nutrition-list";
      appendRawValues(values, meal.details.raw_nutriments);
      raw.append(heading, values); disclosure.append(raw);
    }
    details.append(disclosure);
  }
  const energy = document.createElement("div");
  energy.className = "meal-energy";
  const amount = document.createElement("strong");
  amount.textContent = format(meal.calories);
  const unit = document.createElement("span");
  unit.textContent = "kcal";
  energy.append(amount, unit);
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "delete-meal";
  remove.textContent = "×";
  remove.setAttribute("aria-label", `Delete ${meal.name}`);
  remove.addEventListener("click", async () => {
    remove.disabled = true;
    try {
      await request(`/api/meals/${encodeURIComponent(meal.id)}`, { method: "DELETE" });
      toast("Meal removed from your journal.");
      await loadJournal();
    } catch (error) { toast(error.message, true); remove.disabled = false; }
  });
  row.append(emoji, details, energy, remove);
  return row;
}

async function loadJournal() {
  if (!state.user) { clearJournal(); return; }
  const day = $("journal-date").value;
  const version = ++state.journalVersion;
  if (!day || !$("journal-date").checkValidity()) {
    $("journal-entries").replaceChildren();
    $("empty-journal").hidden = true;
    $("meal-count").textContent = "—";
    $("journal-day-label").textContent = "Select a date";
    $("export-button").removeAttribute("href");
    $("export-button").setAttribute("aria-disabled", "true");
    for (const key of ["calories", "protein", "carbs", "fat"]) $("total-" + key).textContent = "—";
    $("journal-error").textContent = "Choose a valid journal date to see your meals.";
    $("journal-error").hidden = false;
    return;
  }
  $("journal-error").hidden = true;
  $("export-button").removeAttribute("aria-disabled");
  $("export-button").href = `/api/export?day=${encodeURIComponent(day)}`;
  try {
    const data = await request(`/api/meals?day=${encodeURIComponent(day)}`);
    if (version !== state.journalVersion) return;
    $("journal-entries").replaceChildren(...data.meals.map(renderMeal));
    $("empty-journal").hidden = data.meals.length > 0;
    $("meal-count").textContent = data.summary.count;
    for (const key of ["calories", "protein", "carbs", "fat"]) $("total-" + key).textContent = format(data.summary[key]);
    $("journal-day-label").textContent = day === today() ? "Today" : new Date(day + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch (error) {
    if (version !== state.journalVersion) return;
    $("journal-entries").replaceChildren();
    $("empty-journal").hidden = true;
    $("meal-count").textContent = "—";
    for (const key of ["calories", "protein", "carbs", "fat"]) $("total-" + key).textContent = "—";
    $("journal-error").textContent = `Could not load this day. ${error.message}`;
    $("journal-error").hidden = false;
  }
}

$("meal-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.user || state.saving || state.predicting) return;
  if (!$("meal-form").reportValidity() || !$("journal-date").reportValidity()) return;
  let meal = { food_id: $("food-select").value, grams: Number($("grams").value), meal_type: $("meal-type").value, day: $("journal-date").value };
  if (state.mode !== "photo") {
    meal = { ...meal, name: $("product-name").value.trim(), brand: $("product-brand").value.trim(), basis_unit: $("basis-unit").value, nutrition: readNutrition(), source: state.product ? "barcode" : "manual", barcode: state.product?.barcode || null, raw_nutriments: state.product ? { ...state.product.raw_nutriments, ...state.product.nutriment_units } : {} };
    delete meal.food_id;
  }
  state.saving = true;
  updateBusyState();
  try {
    await request(state.mode === "photo" ? "/api/meals" : "/api/meals/custom", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(meal) });
    toast(`Meal added to your journal for ${meal.day}.`);
    selectFood("");
    $("grams").value = 100;
    $("candidates").replaceChildren();
    predictionMessage("");
    $("food-photo").value = "";
    $("upload-prompt").hidden = false;
    $("image-preview").hidden = true;
    if (state.photoUrl) { URL.revokeObjectURL(state.photoUrl); state.photoUrl = null; }
    resetEntry();
    await loadJournal();
  } catch (error) { toast(error.message, true); }
  finally { state.saving = false; updateBusyState(); }
});

$("food-photo").addEventListener("change", (event) => analyzePhoto(event.target.files[0]));
$("food-select").addEventListener("change", () => selectFood($("food-select").value));
$("grams").addEventListener("input", updateEstimate);
$("journal-date").addEventListener("change", loadJournal);
for (const event of ["dragenter", "dragover"]) $("drop-zone").addEventListener(event, (e) => { e.preventDefault(); $("drop-zone").classList.add("dragging"); });
for (const event of ["dragleave", "drop"]) $("drop-zone").addEventListener(event, (e) => { e.preventDefault(); $("drop-zone").classList.remove("dragging"); });
$("drop-zone").addEventListener("drop", (e) => { if (!$("food-photo").disabled) analyzePhoto(e.dataTransfer.files[0]); });
for (const id of ["about-button", "model-info-button"]) $(id).addEventListener("click", () => $("about-dialog").showModal());
$("close-dialog").addEventListener("click", () => $("about-dialog").close());
$("about-dialog").addEventListener("click", (e) => { if (e.target === $("about-dialog")) { const r = e.target.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) e.target.close(); } });

async function initialize() {
  $("journal-date").value = today();
  try {
    const data = await request("/api/foods");
    state.foods = data.foods;
    for (const category of [...new Set(data.foods.map((food) => food.category))]) {
      const group = document.createElement("optgroup");
      group.label = category;
      for (const food of data.foods.filter((item) => item.category === category)) {
        const option = document.createElement("option");
        option.value = food.id;
        option.textContent = `${food.emoji} ${food.name}`;
        group.append(option);
      }
      $("food-select").append(group);
    }
  } catch (error) { predictionMessage(`Could not load foods. Refresh to retry. ${error.message}`, "error"); }
  try { setAccount(await request("/api/auth/me")); }
  catch { setAccount(null); }
  await loadJournal();
}


const nutrientNames = [["calories", "Energy"], ["protein", "Protein"], ["carbs", "Carbohydrates"], ["fat", "Fat"], ["sugars", "Sugars"], ["saturated_fat", "Saturated fat"], ["fiber", "Fibre"], ["salt", "Salt"], ["sodium", "Sodium"]];
const coreNutrients = ["calories", "protein", "carbs", "fat"];
for (const [key, name] of nutrientNames) {
  const label = document.createElement("label");
  label.htmlFor = `nutrient-${key}`;
  label.textContent = `${name} (${key === "calories" ? "kcal" : "g"})${coreNutrients.includes(key) ? " *" : ""}`;
  const input = document.createElement("input");
  input.id = `nutrient-${key}`; input.type = "number"; input.min = 0;
  input.max = key === "calories" ? 1000 : 100; input.step = "any";
  input.inputMode = "decimal"; input.required = coreNutrients.includes(key);
  input.addEventListener("input", updateEstimate);
  label.append(input); $("nutrient-fields").append(label);
}
function readNutrition() {
  return Object.fromEntries(nutrientNames.map(([key]) => [key, $(`nutrient-${key}`).value === "" ? null : Number($(`nutrient-${key}`).value)]));
}
function addDefinition(list, name, value) {
  const term = document.createElement("dt"); term.textContent = name;
  const detail = document.createElement("dd"); detail.textContent = value;
  list.append(term, detail);
}
function appendRawValues(list, values) {
  for (const [key, value] of Object.entries(values)) {
    // Explicit database names distinguish 100g values, serving values and source units.
    addDefinition(list, key.replaceAll("_", " "), String(value));
  }
}
function clearJournal() {
  ++state.journalVersion;
  $("journal-entries").replaceChildren(); $("meal-count").textContent = "0";
  for (const key of coreNutrients) $("total-" + key).textContent = "0";
  $("export-button").removeAttribute("href"); $("export-button").setAttribute("aria-disabled", "true");
  $("journal-error").hidden = true; $("empty-journal").hidden = false;
}
function setAccount(account) {
  state.user = account?.user || null; state.csrf = account?.csrf_token || null;
  $("account-button").textContent = state.user ? state.user.username : "Sign in / Create account";
  $("logout-button").hidden = !state.user; $("account-banner").hidden = !!state.user;
  if (!state.user) { clearJournal(); resetEntry(); }
  updateBusyState();
}
function resetEntry() {
  state.product = null;
  $("product-name").value = ""; $("product-brand").value = ""; $("barcode-number").value = "";
  $("basis-unit").value = "g"; $("grams").value = 100; $("quantity-unit").textContent = "grams";
  for (const [key] of nutrientNames) $(`nutrient-${key}`).value = "";
  $("source-details").hidden = true; $("source-values").replaceChildren(); $("product-source").replaceChildren();
  $("barcode-status").hidden = true;
  for (const id of ["food-photo", "food-camera", "barcode-photo", "barcode-camera"]) $(id).value = "";
  $("preview-image").removeAttribute("src"); $("image-preview").hidden = true; $("upload-prompt").hidden = false;
  if (state.photoUrl) { URL.revokeObjectURL(state.photoUrl); state.photoUrl = null; }
  $("candidates").replaceChildren(); predictionMessage(""); selectFood("");
}
function switchMode(mode) {
  if (state.saving || state.predicting) return;
  resetEntry(); state.mode = mode;
  document.querySelectorAll("[data-mode]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.mode === mode)));
  $("photo-section").hidden = mode !== "photo"; $("barcode-section").hidden = mode !== "barcode";
  $("catalog-fields").hidden = mode !== "photo"; $("custom-fields").hidden = mode === "photo";
  updateBusyState(); updateEstimate();
}
function barcodeStatus(message, error = false) {
  $("barcode-status").textContent = message; $("barcode-status").hidden = false;
  $("barcode-status").className = error ? "prediction-message error" : "prediction-message";
}
function fillProduct(product) {
  state.product = product;
  $("product-name").value = (product.name || "").slice(0, 120);
  $("product-brand").value = (product.brand || "").slice(0, 120);
  $("basis-unit").value = product.basis_unit;
  $("quantity-unit").textContent = product.basis_unit === "ml" ? "ml" : "grams";
  $("grams").value = product.serving_quantity >= 1 && product.serving_quantity <= 2000 ? product.serving_quantity : 100;
  for (const [key] of nutrientNames) $(`nutrient-${key}`).value = product.nutrition[key] ?? "";
  const link = document.createElement("a");
  link.href = `https://world.openfoodfacts.org/product/${encodeURIComponent(product.barcode)}`;
  link.target = "_blank"; link.rel = "noopener"; link.textContent = "Open Food Facts contributors";
  $("product-source").replaceChildren(document.createTextNode(`Product ${product.barcode}${product.quantity ? ` · ${product.quantity}` : ""}. Source: `), link, document.createTextNode(" · ODbL. " + product.notes.join(" ")));
  $("source-values").replaceChildren();
  appendRawValues($("source-values"), { ...product.raw_nutriments, ...product.nutriment_units });
  $("source-details").hidden = !$("source-values").children.length;
  barcodeStatus(product.missing_nutrients.length ? "Product found. Some values are missing. Fill the required values from the label and check your portion before saving." : "Product found. Check the label and portion, then add it to your journal.");
  updateEstimate();
}
async function lookupProduct(file = null) {
  if (!state.user || state.saving || state.predicting) return;
  let barcode = $("barcode-number").value.trim();
  if (!file && !$("barcode-form").reportValidity()) return;
  // Clear the previous result before any new lookup, including failed scans.
  state.product = null; $("product-name").value = ""; $("product-brand").value = "";
  for (const [key] of nutrientNames) $(`nutrient-${key}`).value = "";
  $("product-source").replaceChildren(); $("source-details").hidden = true;
  updateEstimate(); state.predicting = true; updateBusyState();
  try {
    if (file) {
      if (file.size > 8 * 1024 * 1024) throw new Error("Choose a photo under 8 MiB.");
      if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) throw new Error("Choose a JPEG, PNG or WebP photo.");
      barcodeStatus("Reading the barcode…");
      const body = new FormData(); body.append("file", file);
      barcode = (await request("/api/barcode/scan", { method: "POST", body })).barcode;
      $("barcode-number").value = barcode;
    }
    barcodeStatus(`Looking up ${barcode}…`);
    fillProduct(await request(`/api/products/${encodeURIComponent(barcode)}`));
  } catch (error) { barcodeStatus(`${error.message} You can enter the label values below.`, true); }
  finally { state.predicting = false; updateBusyState(); }
}
function setAuthMode(mode) {
  state.authMode = mode;
  document.querySelectorAll("[data-auth]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.auth === mode)));
  $("auth-title").textContent = { login: "Welcome back.", register: "Make this space yours.", recover: "Recover your journal." }[mode];
  $("auth-submit").textContent = { login: "Sign in", register: "Create account", recover: "Reset password" }[mode];
  $("password-label").textContent = mode === "recover" ? "New password" : "Password";
  $("password").autocomplete = mode === "login" ? "current-password" : "new-password";
  $("recovery-field").hidden = mode !== "recover"; $("recovery-code").required = mode === "recover";
  $("auth-error").hidden = true;
}
function showAuth(mode = "login") {
  if (state.user) return;
  setAuthMode(mode); $("auth-dialog").showModal();
}
$("account-button").addEventListener("click", () => showAuth());
$("welcome-signin").addEventListener("click", () => showAuth("register"));
$("close-auth").addEventListener("click", () => $("auth-dialog").close());
$("auth-dialog").addEventListener("close", () => { $("password").value = ""; $("recovery-code").value = ""; });
document.querySelectorAll("[data-auth]").forEach((button) => button.addEventListener("click", () => setAuthMode(button.dataset.auth)));
$("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!$("auth-form").reportValidity()) return;
  const mode = state.authMode;
  const payload = { username: $("username").value.trim(), password: $("password").value };
  if (mode === "recover") { payload.new_password = payload.password; delete payload.password; payload.recovery_code = $("recovery-code").value.trim(); }
  $("auth-dialog").querySelectorAll("button, input").forEach((el) => { el.disabled = true; });
  try {
    const account = await request(`/api/auth/${mode}`, { method: "POST", headers: { "Content-Type": "application/json", "X-FoodLogger-Request": "1" }, body: JSON.stringify(payload) });
    setAccount(account); $("auth-dialog").close();
    if (account.recovery_code) {
      $("saved-recovery").textContent = account.recovery_code;
      $("recovery-username").textContent = account.user.username;
      $("recovery-dialog").showModal();
    }
    await loadJournal();
  } catch (error) { $("auth-error").textContent = error.message; $("auth-error").hidden = false; }
  finally { $("auth-dialog").querySelectorAll("button, input").forEach((el) => { el.disabled = false; }); }
});
$("logout-button").addEventListener("click", async () => {
  try { await request("/api/auth/logout", { method: "POST" }); setAccount(null); toast("You are signed out."); }
  catch (error) { toast(error.message, true); }
});
$("close-recovery").addEventListener("click", () => $("recovery-dialog").close());
$("recovery-dialog").addEventListener("close", () => { $("saved-recovery").textContent = ""; $("recovery-username").textContent = ""; });
$("download-recovery").addEventListener("click", () => {
  const blob = new Blob([`BiteFlow recovery code\nSite: ${location.origin}\nUsername: ${state.user.username}\nRecovery code: ${$("saved-recovery").textContent}\nKeep this private.\n`], { type: "text/plain" });
  const url = URL.createObjectURL(blob); const a = document.createElement("a");
  a.href = url; a.download = "biteflow-recovery.txt"; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => switchMode(button.dataset.mode)));
$("food-camera").addEventListener("change", (event) => analyzePhoto(event.target.files[0]));
for (const id of ["barcode-camera", "barcode-photo"]) $(id).addEventListener("change", (event) => { if (event.target.files[0]) lookupProduct(event.target.files[0]); });
$("barcode-form").addEventListener("submit", (event) => { event.preventDefault(); lookupProduct(); });
$("basis-unit").addEventListener("change", () => { $("quantity-unit").textContent = $("basis-unit").value === "ml" ? "ml" : "grams"; updateEstimate(); });
setAccount(null);
initialize();
