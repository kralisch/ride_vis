/* Map, elevation profile and timeline, all fed from tour.js.
   The three views share one state: which days are visible, which day is in
   focus, and which photo is currently being touched. */

const DEM = {
  tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
  attribution: "Elevation: Mapzen Terrarium / AWS Open Data",
};

const ESRI = "&copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors";

const BASEMAPS = [
  { id: "light", hillshade: true,
    tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"],
    attribution: ESRI, maxzoom: 16 },
  { id: "topo", hillshade: false,
    tiles: ["https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
            "https://b.tile.opentopomap.org/{z}/{x}/{y}.png"],
    attribution: "Map data &copy; OpenStreetMap contributors, SRTM | Style &copy; OpenTopoMap (CC-BY-SA)",
    maxzoom: 17 },
  { id: "satellite", hillshade: false,
    tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
    attribution: ESRI, maxzoom: 18 },
  { id: "relief", hillshade: false,
    tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}"],
    attribution: ESRI, maxzoom: 16 },
  { id: "osm", hillshade: true,
    tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
    attribution: "&copy; OpenStreetMap contributors", maxzoom: 19 },
];

const DEFAULT_PITCH = 45;
/* A steeper pitch makes fitBounds zoom far out on a north-south route -
   45 degrees is where the relief reads and the ride still fills the frame. */
const FIT_PADDING = { top: 44, bottom: 44, left: 300, right: 44 };

const $ = (sel) => document.querySelector(sel);

/** Wording and number format come from lang/<language>.toml via tour.js. */
let fmt = new Intl.NumberFormat("en-GB");
const t = (key, params = {}) =>
  String(state.tour?.ui?.strings?.[key] ?? key)
    .replace(/\{(\w+)\}/g, (_, name) => (name in params ? params[name] : ""));
const km = (m, digits = 0) => `${fmt.format(+(m / 1000).toFixed(digits))} km`;
const hhmm = (s) => `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")} h`;
const megabytes = (bytes) => `${fmt.format(+(bytes / 1024 ** 2).toFixed(1))} MB`;

const state = {
  tour: null,
  hidden: new Set(),      // day numbers switched off
  hiddenSets: new Set(),  // collections switched off
  focus: null,            // day in focus, otherwise null
  active: null,           // index of the touched photo in tour.photos
};

let map, hoverMarker, profile;
let mapReady = false;
let photosReady = false;

/* ------------------------------------------------------------- Map -- */

function buildStyle() {
  const sources = { dem: { type: "raster-dem", tiles: DEM.tiles, encoding: "terrarium",
                           tileSize: 256, maxzoom: 15, attribution: DEM.attribution } };
  const layers = [];
  for (const base of BASEMAPS) {
    sources[base.id] = { type: "raster", tiles: base.tiles, tileSize: 256,
                         maxzoom: base.maxzoom, attribution: base.attribution };
    layers.push({ id: `base-${base.id}`, type: "raster", source: base.id,
                  layout: { visibility: base.id === state.tour.ui.basemap ? "visible" : "none" } });
  }
  // Hillshading belongs under the flat maps only - over imagery or the relief
  // map it doubles up their own lighting.
  const shaded = BASEMAPS.find((b) => b.id === state.tour.ui.basemap).hillshade;
  layers.push({ id: "hillshade", type: "hillshade", source: "dem",
                paint: { "hillshade-exaggeration": 0.35 },
                layout: { visibility: shaded ? "visible" : "none" } });
  return { version: 8, sources, layers };
}

/** Wait for the parsed style - the `load` event only fires after the first
 *  render and in some environments never arrives. Adding sources and layers
 *  only needs the style; the timeout keeps this from hanging. */
function styleReady(map, timeout = 8000) {
  if (map.isStyleLoaded()) return Promise.resolve();
  return new Promise((resolve) => {
    const finish = () => { map.off("styledata", check); clearTimeout(timer); resolve(); };
    const check = () => { if (map.isStyleLoaded()) finish(); };
    const timer = setTimeout(finish, timeout);
    map.on("styledata", check);
  });
}

function dayLine(day) {
  return { type: "Feature", properties: { day: day.index },
           geometry: { type: "LineString", coordinates: day.coords.map((c) => [c[0], c[1]]) } };
}

function addRoutes() {
  for (const day of state.tour.days) {
    map.addSource(`day-${day.index}`, { type: "geojson", data: dayLine(day) });
    map.addLayer({
      id: `casing-${day.index}`, type: "line", source: `day-${day.index}`,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#ffffff", "line-width": 7, "line-opacity": 0.9 },
    });
    const paint = { "line-color": day.color, "line-width": 3.4 };
    if (day.dashArray) paint["line-dasharray"] = day.dashArray;
    map.addLayer({
      id: `line-${day.index}`, type: "line", source: `day-${day.index}`,
      layout: { "line-cap": day.dashArray ? "butt" : "round", "line-join": "round" },
      paint,
    });
  }
}

/** Load markers through an image element rather than map.loadImage: its fetch
 *  fails when the page is opened straight from the file system. */
function loadImageElement(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`cannot load image: ${url}`));
    image.src = url;
  });
}


async function addPhotoLayer() {
  const photos = state.tour.photos;

  // Order matters: source first, then register the markers, and the symbol
  // layer last. Add the layer earlier and its tiles are built without icons and
  // stay empty - MapLibre does not rebuild them when images arrive later.
  map.addSource("photos", {
    type: "geojson",
    data: { type: "FeatureCollection", features: photos.map((p, i) => ({
      type: "Feature",
      properties: { index: i, icon: p.key, day: p.day, set: p.collection },
      geometry: { type: "Point", coordinates: [p.lon, p.lat] },
    })) },
  });

  await Promise.all(photos.map(async (photo) => {
    try {
      const image = await loadImageElement(photo.marker);
      if (!map.hasImage(photo.key)) map.addImage(photo.key, image, { pixelRatio: 2 });
    } catch (error) {
      console.warn("marker missing:", photo.marker, error);
    }
  }));

  map.addLayer({
    id: "photos", type: "symbol", source: "photos",
    layout: {
      "icon-image": ["get", "icon"],
      // Without allow-overlap MapLibre hides colliding markers by itself -
      // that does the decluttering which clustering handled on the Leaflet map.
      "icon-allow-overlap": false,
      "icon-padding": 3,
      "symbol-sort-key": ["get", "index"],
    },
  });
  photosReady = true;

  map.on("click", "photos", (e) => openLightbox(e.features[0].properties.index));
  map.on("mouseenter", "photos", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "photos", () => (map.getCanvas().style.cursor = ""));
}

function applyDayVisibility() {
  for (const day of state.tour.days) {
    const shown = !state.hidden.has(day.index) && (!state.focus || state.focus === day.index);
    const visibility = shown ? "visible" : "none";
    map.setLayoutProperty(`line-${day.index}`, "visibility", visibility);
    map.setLayoutProperty(`casing-${day.index}`, "visibility", visibility);
  }
  if (!photosReady) return;
  map.setFilter("photos", ["all",
    ["in", ["get", "day"], ["literal", state.tour.days.filter(visibleDay).map((d) => d.index)]],
    ["in", ["get", "set"], ["literal", state.tour.collections.filter((c) => visibleSet(c.id)).map((c) => c.id)]],
  ]);
}

const visibleDay = (day) =>
  !state.hidden.has(day.index) && (!state.focus || state.focus === day.index);

const visibleSet = (id) => !state.hiddenSets.has(id);

/** A photo counts only when both its day and its collection are switched on. */
const visiblePhoto = (photo) =>
  visibleSet(photo.collection) && visibleDay(dayByIndex(photo.day));

const photosOfDay = (index) =>
  state.tour.photos.filter((photo) => photo.day === index && visibleSet(photo.collection));

function fitTo(days, duration = 900) {
  const bounds = new maplibregl.LngLatBounds();
  for (const day of days) for (const c of day.coords) bounds.extend([c[0], c[1]]);
  map.fitBounds(bounds, { padding: FIT_PADDING, pitch: map.getPitch(), duration });
}

/* ---------------------------------------------------------- Legend -- */

function renderLegend() {
  const list = $("#days");
  list.innerHTML = "";
  for (const day of state.tour.days) {
    const li = document.createElement("li");
    li.dataset.day = day.index;
    const dash = day.dash === "solid" ? "" : ` stroke-dasharray="${day.dash === "dashed" ? "9,6" : "1.6,5"}"`;
    li.innerHTML =
      `<button type="button">
         <svg width="30" height="10" aria-hidden="true">
           <line x1="0" y1="5" x2="30" y2="5" stroke="${day.color}" stroke-width="3"${dash}/>
         </svg>
         <span>${day.label}</span>
         <span class="num">${km(day.distance_m)} · <span class="count"></span></span>
       </button>`;
    li.querySelector("button").addEventListener("click", (event) => {
      if (event.shiftKey) toggleDay(day.index);
      else focusDay(state.focus === day.index ? null : day.index);
    });
    list.append(li);
  }
  renderSets();
  syncLegend();
}

function renderSets() {
  const list = $("#collections");
  list.innerHTML = "";
  for (const set of state.tour.collections) {
    const li = document.createElement("li");
    li.dataset.set = set.id;
    li.innerHTML =
      `<label><input type="checkbox"${visibleSet(set.id) ? " checked" : ""}>
         <span class="swatch" style="--c:${set.color}"></span>
         <span>${set.name}</span><span class="num">${set.photos}</span></label>`;
    li.querySelector("input").addEventListener("change", (event) => {
      event.target.checked ? state.hiddenSets.delete(set.id) : state.hiddenSets.add(set.id);
      refresh();
      writeHash();
    });
    list.append(li);
  }
}

function syncLegend() {
  for (const li of $("#days").children) {
    const index = +li.dataset.day;
    li.classList.toggle("is-off", state.hidden.has(index));
    li.classList.toggle("is-focus", state.focus === index);
    li.querySelector(".count").textContent = photosOfDay(index).length;
  }
  for (const li of $("#collections").children) {
    li.classList.toggle("is-off", !visibleSet(li.dataset.set));
  }
  $("#reset").hidden = !state.focus && state.hidden.size === 0 && state.hiddenSets.size === 0;
}

function toggleDay(index) {
  state.hidden.has(index) ? state.hidden.delete(index) : state.hidden.add(index);
  refresh();
}

function focusDay(index) {
  state.focus = index;
  refresh();
  writeHash();
  fitTo(index ? [dayByIndex(index)] : state.tour.days);
}

const dayByIndex = (index) => state.tour.days.find((d) => d.index === index);
const setById = (id) => state.tour.collections.find((c) => c.id === id);

function refresh() {
  if (mapReady) applyDayVisibility();
  syncLegend();
  syncCounts();
  drawProfile();
  syncStrip();
}

/* --------------------------------------------------------- Elevation -- */

const PAD = { top: 6, right: 14, bottom: 17, left: 52 };

function buildSeries() {
  const days = state.tour.days.filter(visibleDay);
  const segments = [];
  let offset = 0, min = Infinity, max = -Infinity;
  for (const day of days) {
    const points = day.coords.map((c) => ({ x: offset + c[4], y: c[2], lon: c[0], lat: c[1], t: c[3] }));
    for (const p of points) {
      if (p.y === null) continue;
      if (p.y < min) min = p.y;
      if (p.y > max) max = p.y;
    }
    segments.push({ day, points, offset });
    offset += day.distance_m;
  }
  const photos = state.tour.photos
    .map((photo, index) => ({ photo, index }))
    .filter(({ photo }) => visibleSet(photo.collection) && days.some((d) => d.index === photo.day))
    .map(({ photo, index }) => {
      const segment = segments.find((s) => s.day.index === photo.day);
      return { photo, index, x: segment.offset + photo.d, y: photo.ele, color: segment.day.color };
    });
  return { segments, photos, totalX: offset, min, max };
}

function niceTicks(min, max, count) {
  const raw = (max - min) / count;
  const step = [50, 100, 200, 250, 500, 1000].find((s) => s >= raw) ?? 1000;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max; v += step) ticks.push(v);
  return ticks;
}

function drawProfile() {
  const canvas = $("#profile");
  const wrap = $("#profile-wrap");
  const ratio = window.devicePixelRatio || 1;
  const width = wrap.clientWidth, height = wrap.clientHeight;
  if (!width || !height) return;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const series = buildSeries();
  profile = { ...series, width, height, canvas };
  if (!series.segments.length || !isFinite(series.min)) return;

  const yMin = Math.floor(series.min / 200) * 200;
  const yMax = Math.ceil(series.max / 200) * 200;
  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const sx = (x) => PAD.left + (x / series.totalX) * plotW;
  const sy = (y) => PAD.top + plotH - ((y - yMin) / (yMax - yMin)) * plotH;
  profile.sx = sx; profile.sy = sy; profile.plotW = plotW;

  ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
  ctx.textBaseline = "middle";

  for (const value of niceTicks(yMin, yMax, 3)) {           // elevation grid
    const y = sy(value);
    ctx.strokeStyle = "#e1e0d9"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PAD.left, y + .5); ctx.lineTo(width - PAD.right, y + .5); ctx.stroke();
    ctx.fillStyle = "#898781"; ctx.textAlign = "right";
    ctx.fillText(`${fmt.format(value)} m`, PAD.left - 7, y);
  }

  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (const segment of series.segments) {                   // day boundaries
    const x = sx(segment.offset);
    if (segment.offset > 0) {
      ctx.strokeStyle = "#c3c2b7";
      ctx.beginPath(); ctx.moveTo(x + .5, PAD.top); ctx.lineTo(x + .5, PAD.top + plotH); ctx.stroke();
    }
    ctx.fillStyle = "#52514e";
    ctx.fillText(segment.day.label.length > 14 ? t("dayLabel", { n: segment.day.index }) : segment.day.label, x + (sx(segment.offset + segment.day.distance_m) - x) / 2,
                 PAD.top + plotH + 5);
  }

  for (const segment of series.segments) {                   // area and line
    const path = new Path2D();
    let started = false;
    for (const point of segment.points) {
      if (point.y === null) continue;
      const x = sx(point.x), y = sy(point.y);
      started ? path.lineTo(x, y) : (path.moveTo(x, y), (started = true));
    }
    const area = new Path2D(path);
    const last = segment.points[segment.points.length - 1];
    area.lineTo(sx(last.x), PAD.top + plotH);
    area.lineTo(sx(segment.offset), PAD.top + plotH);
    area.closePath();
    ctx.fillStyle = segment.day.color + "26";
    ctx.fill(area);
    ctx.strokeStyle = segment.day.color; ctx.lineWidth = 1.6;
    ctx.setLineDash(segment.day.dash === "dashed" ? [7, 4]
                  : segment.day.dash === "dotted" ? [1.5, 3.5] : []);
    ctx.stroke(path);
    ctx.setLineDash([]);
  }

  for (const mark of series.photos) {                        // photos as dots
    if (mark.y === null) continue;
    const active = state.active === mark.index;
    ctx.beginPath();
    ctx.arc(sx(mark.x), sy(mark.y), active ? 5 : 3, 0, Math.PI * 2);
    ctx.fillStyle = active ? mark.color : "#fcfcfb";
    ctx.strokeStyle = mark.color; ctx.lineWidth = 1.8;
    ctx.fill(); ctx.stroke();
  }
}

function profileAt(clientX) {
  if (!profile || !profile.sx) return null;
  const rect = profile.canvas.getBoundingClientRect();
  const px = clientX - rect.left;
  const x = ((px - PAD.left) / profile.plotW) * profile.totalX;
  if (x < 0 || x > profile.totalX) return null;

  let nearestPhoto = null, bestPhoto = Infinity;
  for (const mark of profile.photos) {
    const d = Math.abs(profile.sx(mark.x) - px);
    if (d < bestPhoto) { bestPhoto = d; nearestPhoto = mark; }
  }
  let nearest = null, best = Infinity;
  for (const segment of profile.segments) {
    for (const point of segment.points) {
      const d = Math.abs(point.x - x);
      if (d < best) { best = d; nearest = { point, day: segment.day }; }
    }
  }
  return { x, px, nearest, photo: bestPhoto < 7 ? nearestPhoto : null };
}

function wireProfile() {
  const wrap = $("#profile-wrap");
  wrap.addEventListener("mousemove", (event) => {
    const hit = profileAt(event.clientX);
    if (!hit || !hit.nearest) return;
    const { point, day } = hit.nearest;
    $("#crosshair").hidden = false;
    $("#crosshair").style.left = `${hit.px}px`;
    const into = point.x - profile.segments.find((s) => s.day.index === day.index).offset;
    $("#profile-readout").textContent = t("readout", {
      day: day.label,
      distance: km(into, 1),
      elevation: fmt.format(point.y),
      time: hhmm(point.t),
    })
;
    hoverMarker.setLngLat([point.lon, point.lat]).addTo(map);
    wrap.style.cursor = hit.photo ? "pointer" : "crosshair";
  });
  wrap.addEventListener("mouseleave", () => {
    $("#crosshair").hidden = true;
    $("#profile-readout").textContent = "";
    hoverMarker.remove();
  });
  wrap.addEventListener("click", (event) => {
    const hit = profileAt(event.clientX);
    if (hit && hit.photo) openLightbox(hit.photo.index);
  });
}

/* -------------------------------------------------------- Timeline -- */

function renderStrip() {
  const strip = $("#strip");
  strip.innerHTML = "";
  for (const day of state.tour.days) {
    const shots = state.tour.photos
      .map((photo, index) => ({ photo, index }))
      .filter(({ photo }) => photo.day === day.index);
    if (!shots.length) continue;

    const section = document.createElement("div");
    section.className = "strip-day";
    section.style.setProperty("--c", day.color);
    section.dataset.day = day.index;
    section.innerHTML = `<h3>${day.label}</h3><div class="strip-shots"></div>`;
    const row = section.querySelector(".strip-shots");
    for (const { photo, index } of shots) {
      const button = document.createElement("button");
      button.className = "strip-shot";
      button.dataset.index = index;
      button.innerHTML = `<img src="${photo.thumb}" alt="" loading="lazy"><span>${photo.time}</span>`;
      button.addEventListener("click", () => openLightbox(index));
      button.addEventListener("mouseenter", () => highlight(index));
      button.addEventListener("mouseleave", () => highlight(null));
      row.append(button);
    }
    strip.append(section);
  }
}

function syncStrip() {
  for (const button of $("#strip").querySelectorAll(".strip-shot")) {
    const photo = state.tour.photos[+button.dataset.index];
    button.hidden = !visibleSet(photo.collection);
    button.classList.toggle("is-active", +button.dataset.index === state.active);
  }
  for (const section of $("#strip").children) {
    const index = +section.dataset.day;
    section.hidden = !visibleDay(dayByIndex(index)) || photosOfDay(index).length === 0;
  }
}

function highlight(index) {
  state.active = index;
  syncStrip();
  drawProfile();
  if (index === null) { hoverMarker.remove(); return; }
  const photo = state.tour.photos[index];
  hoverMarker.setLngLat([photo.lon, photo.lat]).addTo(map);
}

/* -------------------------------------------------------- Deep links -- */
/* `#stage=4` opens one day, `#photo=<file name>` a single image, `#off=<id>`
   hides collections - so a particular view can be sent to someone. */

let applyingHash = false;

function writeHash() {
  if (applyingHash) return;
  const parts = [];
  if (state.focus) parts.push(`stage=${state.focus}`);
  if (state.hiddenSets.size) parts.push(`off=${[...state.hiddenSets].join(",")}`);
  if (!$("#lightbox").hidden && state.active !== null) {
    parts.push(`photo=${state.tour.photos[state.active].name}`);
  }
  const hash = parts.length ? `#${parts.join("&")}` : "";
  if (hash !== location.hash) history.replaceState(null, "", hash || location.pathname);
}

function applyHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  const stage = Number(params.get("stage"));
  const name = params.get("photo");
  const off = params.get("off");
  applyingHash = true;
  if (off !== null) {
    state.hiddenSets = new Set(off.split(",").filter((id) => setById(id)));
    renderSets();
    refresh();
  }
  if (stage && dayByIndex(stage)) {
    state.focus = stage;
    refresh();
    fitTo([dayByIndex(stage)], 0);
  }
  if (name) {
    const index = state.tour.photos.findIndex((photo) => photo.name === name);
    if (index >= 0) openLightbox(index);
  }
  applyingHash = false;
}

/* ---------------------------------------------------------- Lightbox -- */

function openLightbox(index) {
  const photo = state.tour.photos[index];
  state.active = index;
  $("#lb-img").src = photo.view;
  $("#lb-img").alt = photo.datetime.slice(0, 10);
  $("#lb-title").textContent = `${photo.time} · ${dayByIndex(photo.day).label}`;
  $("#lb-meta").textContent =
    [
      setById(photo.collection)?.name,
      t("intoTheDay", { distance: km(photo.d, 1) }),
      photo.ele !== null ? `${fmt.format(photo.ele)} m` : null,
      photo.name,
    ].filter(Boolean).join(" · ");
  // The large image opens in a new tab, where the browser's own zoom and save
  // apply. When the build left it out the link stays hidden rather than
  // pointing nowhere.
  const full = $("#lb-full");
  full.hidden = !photo.full;
  if (photo.full) {
    full.href = photo.full;
    // Say "full resolution" only when it really is the untouched camera file.
    const wording = t(state.tour.fullKind === "half" ? "largeView" : "fullResolution");
    full.textContent =
      `${wording} · ${fmt.format(photo.fullW)} × ${fmt.format(photo.fullH)} · ${megabytes(photo.fullBytes)}`;
  }

  $("#lightbox").hidden = false;
  syncStrip(); drawProfile(); writeHash();
  map.flyTo({ center: [photo.lon, photo.lat], zoom: Math.max(map.getZoom(), 12), duration: 800 });
}

function stepLightbox(delta) {
  const photos = state.tour.photos;
  let index = state.active;
  for (let i = 0; i < photos.length; i++) {
    index = (index + delta + photos.length) % photos.length;
    if (visiblePhoto(photos[index])) break;
  }
  openLightbox(index);
}

function closeLightbox() { $("#lightbox").hidden = true; writeHash(); }

function wireLightbox() {
  $(".lb-close").addEventListener("click", closeLightbox);
  $(".lb-prev").addEventListener("click", () => stepLightbox(-1));
  $(".lb-next").addEventListener("click", () => stepLightbox(1));
  $("#lightbox").addEventListener("click", (event) => {
    if (event.target.id === "lightbox") closeLightbox();
  });
  document.addEventListener("keydown", (event) => {
    if ($("#lightbox").hidden) return;
    if (event.key === "Escape") closeLightbox();
    if (event.key === "ArrowLeft") stepLightbox(-1);
    if (event.key === "ArrowRight") stepLightbox(1);
  });
}

/* --------------------------------------------------------- Controls -- */

function fillBasemapSelect() {
  const select = $("#basemap");
  for (const base of BASEMAPS) {
    const option = document.createElement("option");
    option.value = base.id; option.textContent = state.tour.ui.basemaps[base.id] ?? base.id;
    select.append(option);
  }
  select.value = state.tour.ui.basemap;
}

function wireControls() {
  const select = $("#basemap");
  select.addEventListener("change", () => {
    for (const base of BASEMAPS) {
      map.setLayoutProperty(`base-${base.id}`, "visibility",
                            base.id === select.value ? "visible" : "none");
    }
    const chosen = BASEMAPS.find((b) => b.id === select.value);
    map.setLayoutProperty("hillshade", "visibility", chosen.hillshade ? "visible" : "none");
  });

  const tilt = $("#tilt");
  tilt.addEventListener("click", () => {
    const on = tilt.getAttribute("aria-pressed") !== "true";
    tilt.setAttribute("aria-pressed", String(on));
    map.setTerrain(on ? { source: "dem", exaggeration: +$("#exaggeration").value } : null);
    map.easeTo({ pitch: on ? DEFAULT_PITCH : 0, duration: 700 });
  });

  $("#exaggeration").addEventListener("input", (event) => {
    if ($("#tilt").getAttribute("aria-pressed") === "true") {
      map.setTerrain({ source: "dem", exaggeration: +event.target.value });
    }
  });

  $("#reset").addEventListener("click", () => {
    state.hidden.clear(); state.hiddenSets.clear(); state.focus = null;
    renderSets();
    refresh(); writeHash(); fitTo(state.tour.days);
  });

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(drawProfile, 120);
  });
}

/* ----------------------------------------------------------- Setup -- */

/** Fill the fixed labels from the language file. */
function renderChrome() {
  const { title, ui } = state.tour;
  fmt = new Intl.NumberFormat(ui.locale);
  document.documentElement.lang = ui.language;
  $("#title").textContent = title;
  document.title = title;

  const labels = {
    "#head .field:nth-of-type(1) span": "map",
    "#head .field:nth-of-type(2) span": "relief",
    "#tilt": "threeD",
    ".legend-head h2": "days",
    "#reset": "showAll",
    ".legend-sub": "collections",
    "#legend-hint": "hint",
    "#profile-panel .panel-head h2": "elevation",
    "#strip-panel .panel-head h2": "timeline",
  };
  for (const [selector, key] of Object.entries(labels)) {
    const node = $(selector);
    if (node) node.textContent = t(key);
  }
  const aria = { ".lb-close": "close", ".lb-prev": "previous", ".lb-next": "next" };
  for (const [selector, key] of Object.entries(aria)) {
    $(selector)?.setAttribute("aria-label", t(key));
  }
}

/** The photo counts follow the switches - otherwise they would state a number
 *  that matches nothing on screen. */
function syncCounts() {
  const { totals } = state.tour;
  const shown = state.tour.photos.filter(visiblePhoto).length;
  const count = shown === totals.photos
    ? t("photos", { n: fmt.format(totals.photos) })
    : t("photosOf", { shown: fmt.format(shown), total: fmt.format(totals.photos) });
  $("#totals").textContent = t("totals", {
    distance: km(totals.distance_m),
    ascent: fmt.format(totals.ascent_m),
    days: totals.days,
    photos: count,
  });
  $("#strip-count").textContent = t("captureOrder", { photos: count });
}

async function init() {
  state.tour = window.TOUR;
  if (!state.tour) throw new Error("tour.js was not loaded");
  for (const set of state.tour.collections) {
    if (!set.enabled) state.hiddenSets.add(set.id);   // default from ride.toml
  }

  // Header, legend, profile and timeline do not depend on the map module -
  // they are up at once, even if WebGL or the tiles take their time.
  renderChrome();
  renderLegend();
  renderStrip();
  wireProfile();
  wireLightbox();
  fillBasemapSelect();
  $("#exaggeration").value = state.tour.ui.exaggeration;
  $("#tilt").setAttribute("aria-pressed", String(state.tour.ui.terrain));
  refresh();
  new ResizeObserver(() => drawProfile()).observe($("#profile-wrap"));

  const [w, s, e, n] = state.tour.bounds;
  map = new maplibregl.Map({
    container: "map",
    style: buildStyle(),
    bounds: [[w, s], [e, n]],
    fitBoundsOptions: { padding: FIT_PADDING },
    maxPitch: 80,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
  map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-right");
  map.addControl(new maplibregl.FullscreenControl(), "top-right");

  const dot = document.createElement("div");
  dot.style.cssText =
    "width:13px;height:13px;border-radius:50%;background:#0b0b0b;border:2.5px solid #fff;"
    + "box-shadow:0 1px 4px rgba(0,0,0,.5)";
  hoverMarker = new maplibregl.Marker({ element: dot });

  await styleReady(map);
  if (state.tour.ui.terrain) {
    map.setTerrain({ source: "dem", exaggeration: +$("#exaggeration").value });
  }
  addRoutes();
  // The photo layer has to exist before the camera is set: added afterwards,
  // MapLibre stops placing the symbols on the terrain.
  await addPhotoLayer();
  mapReady = true;

  wireControls();
  applyDayVisibility();
  map.jumpTo({ pitch: state.tour.ui.terrain ? DEFAULT_PITCH : 0 });
  fitTo(state.tour.days, 0);
  applyHash();
  window.addEventListener("hashchange", applyHash);
}

/** Without this the app fails silently and the reader sees only empty panels. */
function fail(error) {
  console.error(error);
  const box = document.createElement("div");
  box.id = "fatal";
  box.textContent = state.tour ? t("buildFailed", { error: error?.message ?? error })
                              : `The view could not be built: ${error?.message ?? error}`;
  document.body.append(box);
  document.documentElement.dataset.error = String(error?.stack ?? error).slice(0, 400);
}

window.addEventListener("unhandledrejection", (event) => fail(event.reason));
init().catch(fail);
