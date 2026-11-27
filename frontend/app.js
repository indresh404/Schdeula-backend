/**
 * Schedula CMPN - Frontend Application
 * Vanilla JavaScript (HTML5 / CSS3 / ES6)
 */

// Application State
const state = {
  currentUser: null,
  stats: {},
  faculty: [],
  subjects: [],
  divisions: [],
  batches: [],
  rooms: [],
  floors: [],
  roomsByFloor: [],
  distances: [],
  assignments: [],
  settings: {},
  timetable: { entries: [], last_generated: null, validation_report: null },
  selectedYear: "TY",
  selectedDivisionId: null,
  selectedFacultyId: null,
  selectedRoomId: null,
  viewMode: "division", // 'division' | 'faculty' | 'room'
  filters: {
    year: "ALL",      // "ALL" | "FY" | "SY" | "TY" | "BE"
    division: "ALL",  // "ALL" | divisionId
    faculty: "ALL",   // "ALL" | facultyId
    room: "ALL",      // "ALL" | roomId
    day: "ALL",       // "ALL" | "Monday" | ...
    years: ["ALL"],
    divisions: ["ALL"],
    days: ["ALL"],
  },
  recentlySwappedEntryIds: [],
};

// -------------------------------------------------------------
// Initialization
// -------------------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  setupNavigation();
  setupModals();
  setupEventListeners();
  setupDataExportImport();
  setupInteractiveHelpTour();
  initTimetableInsightsPanel();

  await checkAuthStatus();
  await refreshAllData();
});

// -------------------------------------------------------------
// Navigation
// -------------------------------------------------------------
function setupNavigation() {
  const navItems = document.querySelectorAll(".nav-item");
  navItems.forEach((btn) => {
    btn.addEventListener("click", () => {
      navItems.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      const tabId = btn.getAttribute("data-tab");
      document.querySelectorAll(".tab-pane").forEach((pane) => {
        pane.classList.remove("active");
      });
      const activePane = document.getElementById(tabId);
      if (activePane) {
        activePane.classList.add("active");
      }

      if (tabId === "tab-timetable") {
        renderTimetableGrid();
      }
    });
  });

  setupSidebarAndFullView();
}

function setupSidebarAndFullView() {
  const appLayout = document.querySelector(".app-layout");
  const btnToggleSidebar = document.getElementById("btn-toggle-sidebar");
  const btnSidebarCollapse = document.getElementById("btn-sidebar-collapse");
  const btnSidebarCollapseBottom = document.getElementById("btn-sidebar-collapse-bottom");
  const sidebarToggleIcon = document.querySelector(".sidebar-toggle-icon");

  // Load saved sidebar state from localStorage
  const savedCollapsed = localStorage.getItem("schedula_sidebar_collapsed") === "true";
  if (savedCollapsed && appLayout) {
    appLayout.classList.add("sidebar-collapsed");
    if (sidebarToggleIcon) sidebarToggleIcon.textContent = "☰";
  }

  function toggleSidebar(forceState) {
    if (!appLayout) return;
    const isNowCollapsed = forceState !== undefined
      ? forceState
      : !appLayout.classList.contains("sidebar-collapsed");

    if (isNowCollapsed) {
      appLayout.classList.add("sidebar-collapsed");
      if (btnToggleSidebar) btnToggleSidebar.setAttribute("title", "Expand Sidebar (Open)");
    } else {
      appLayout.classList.remove("sidebar-collapsed");
      if (btnToggleSidebar) btnToggleSidebar.setAttribute("title", "Collapse Sidebar (Close)");
    }

    localStorage.setItem("schedula_sidebar_collapsed", isNowCollapsed ? "true" : "false");

    // Trigger window resize so sticky table headers and scroll widths adapt immediately
    setTimeout(() => {
      window.dispatchEvent(new Event("resize"));
    }, 260);
  }

  if (btnToggleSidebar) {
    btnToggleSidebar.addEventListener("click", () => toggleSidebar());
  }

  if (btnSidebarCollapse) {
    btnSidebarCollapse.addEventListener("click", () => toggleSidebar(true));
  }

  if (btnSidebarCollapseBottom) {
    btnSidebarCollapseBottom.addEventListener("click", () => toggleSidebar(true));
  }

  // -------------------------------------------------------------
  // Timetable Full Screen, Zoom & Fit to Screen Controls
  // -------------------------------------------------------------
  const btnToggleFullView = document.getElementById("btn-toggle-timetable-fullview");
  const btnCanvasFullscreen = document.getElementById("btn-canvas-fullscreen");
  const btnExitFullView = document.getElementById("btn-exit-fullview");
  const timetableMasterCard = document.getElementById("timetable-master-card");
  const scrollContainer = document.getElementById("timetable-scroll-container");
  const zoomBadge = document.getElementById("tt-zoom-badge");
  const btnZoomIn = document.getElementById("btn-tt-zoom-in");
  const btnZoomOut = document.getElementById("btn-tt-zoom-out");
  const btnZoomReset = document.getElementById("btn-tt-zoom-reset");
  const btnZoomFit = document.getElementById("btn-tt-zoom-fit");
  const filterIndicator = document.getElementById("tt-active-filter-indicator");

  state.timetableZoom = 1.0;

  function updateActiveFilterIndicator() {
    if (!filterIndicator) return;
    const years = (state.filters && state.filters.years) || ["ALL"];
    const divs = (state.filters && state.filters.divisions) || ["ALL"];
    const days = (state.filters && state.filters.days) || ["ALL"];

    let parts = [];
    if (years.includes("ALL")) {
      parts.push("All Years");
    } else {
      parts.push(years.join(" + "));
    }

    if (!divs.includes("ALL")) {
      parts.push("Div " + divs.join(", "));
    }

    if (!days.includes("ALL")) {
      parts.push(days.map((d) => d.slice(0, 3)).join(", "));
    }

    filterIndicator.textContent = "View: " + parts.join(" • ");
    filterIndicator.className = years.includes("ALL") ? "badge badge-primary" : "badge badge-info";
  }
  window.updateActiveFilterIndicator = updateActiveFilterIndicator;

  function setTimetableZoom(newZoom) {
    state.timetableZoom = Math.min(2.0, Math.max(0.45, Math.round(newZoom * 100) / 100));
    if (zoomBadge) zoomBadge.textContent = `${Math.round(state.timetableZoom * 100)}%`;
    const targetEl = document.getElementById("timetable-canvas-wrapper") || document.getElementById("timetable-master-table");
    if (targetEl) {
      if ("zoom" in document.body.style) {
        targetEl.style.zoom = state.timetableZoom;
      } else {
        targetEl.style.transform = `scale(${state.timetableZoom})`;
        targetEl.style.transformOrigin = "top left";
      }
    }

    // Snap labels into short abbreviations if zoomed out (< 0.85)
    if (timetableMasterCard) {
      if (state.timetableZoom < 0.85) {
        timetableMasterCard.classList.add("is-zoomed-out");
      } else {
        timetableMasterCard.classList.remove("is-zoomed-out");
      }
    }
  }

  const ZOOM_LEVELS = [0.45, 0.55, 0.65, 0.75, 0.85, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0];
  function zoomIn() {
    const next = ZOOM_LEVELS.find((z) => z > state.timetableZoom + 0.01) || 2.0;
    setTimetableZoom(next);
  }
  function zoomOut() {
    const prev = [...ZOOM_LEVELS].reverse().find((z) => z < state.timetableZoom - 0.01) || 0.45;
    setTimetableZoom(prev);
  }

  function fitTimetableToScreen() {
    const container = document.getElementById("timetable-scroll-container");
    const table = document.getElementById("timetable-master-table");
    if (!container || !table) return;

    setTimetableZoom(1.0);
    setTimeout(() => {
      const availWidth = container.clientWidth - 16;
      const tableWidth = table.scrollWidth || table.offsetWidth || 1400;
      if (tableWidth > 0 && availWidth > 0) {
        const fitScale = Math.min(1.0, Math.max(0.45, Math.round((availWidth / tableWidth) * 100) / 100));
        setTimetableZoom(fitScale);
        container.scrollLeft = 0;
        container.scrollTop = 0;
        showBanner(`Timetable scaled to ${Math.round(fitScale * 100)}% to fit screen cleanly.`, "info");
      }
    }, 25);
  }

  if (btnZoomIn) btnZoomIn.addEventListener("click", (e) => { e.stopPropagation(); zoomIn(); });
  if (btnZoomOut) btnZoomOut.addEventListener("click", (e) => { e.stopPropagation(); zoomOut(); });
  if (btnZoomReset) btnZoomReset.addEventListener("click", (e) => { e.stopPropagation(); setTimetableZoom(1.0); });
  if (btnZoomFit) btnZoomFit.addEventListener("click", (e) => { e.stopPropagation(); fitTimetableToScreen(); });

  // Mouse wheel zoom when Ctrl or Meta is held
  if (scrollContainer) {
    scrollContainer.addEventListener("wheel", (e) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        if (e.deltaY < 0) zoomIn();
        else zoomOut();
      }
    }, { passive: false });
  }

  // Full Screen Toggle
  async function toggleFullView(forceState) {
    if (!timetableMasterCard) return;
    const isNowFull = forceState !== undefined
      ? forceState
      : !timetableMasterCard.classList.contains("is-full-view");

    if (isNowFull) {
      timetableMasterCard.classList.add("is-full-view");
      if (btnToggleFullView) {
        const textSpan = btnToggleFullView.querySelector("span");
        if (textSpan) textSpan.textContent = "Exit Full Screen";
        btnToggleFullView.classList.add("btn-primary");
        btnToggleFullView.classList.remove("btn-outline");
      }
      if (btnCanvasFullscreen) {
        const textSpan = btnCanvasFullscreen.querySelector(".btn-text") || btnCanvasFullscreen.querySelector("span");
        if (textSpan) textSpan.textContent = "Exit Full Screen";
        btnCanvasFullscreen.classList.add("btn-primary");
        btnCanvasFullscreen.classList.remove("btn-outline");
      }
      if (btnExitFullView) btnExitFullView.style.display = "inline-flex";
      document.body.style.overflow = "hidden";
      try {
        if (!document.fullscreenElement && timetableMasterCard.requestFullscreen) {
          const p = timetableMasterCard.requestFullscreen();
          if (p && typeof p.catch === "function") p.catch(() => {});
        }
      } catch (err) {}
    } else {
      timetableMasterCard.classList.remove("is-full-view");
      if (btnToggleFullView) {
        const textSpan = btnToggleFullView.querySelector("span");
        if (textSpan) textSpan.textContent = "Full Screen";
        btnToggleFullView.classList.remove("btn-primary");
        btnToggleFullView.classList.add("btn-outline");
      }
      if (btnCanvasFullscreen) {
        const textSpan = btnCanvasFullscreen.querySelector(".btn-text") || btnCanvasFullscreen.querySelector("span");
        if (textSpan) textSpan.textContent = "Full Screen";
        btnCanvasFullscreen.classList.remove("btn-primary");
        btnCanvasFullscreen.classList.add("btn-outline");
      }
      if (btnExitFullView) btnExitFullView.style.display = "none";
      document.body.style.overflow = "";
      try {
        if (document.fullscreenElement && document.exitFullscreen) {
          const p = document.exitFullscreen();
          if (p && typeof p.catch === "function") p.catch(() => {});
        }
      } catch (err) {}
    }

    updateActiveFilterIndicator();
    setTimeout(() => {
      window.dispatchEvent(new Event("resize"));
    }, 100);
  }
  window.toggleTimetableFullscreen = toggleFullView;

  if (btnToggleFullView) {
    btnToggleFullView.addEventListener("click", () => toggleFullView());
  }
  if (btnCanvasFullscreen) {
    btnCanvasFullscreen.addEventListener("click", () => toggleFullView());
  }
  if (btnExitFullView) {
    btnExitFullView.addEventListener("click", () => toggleFullView(false));
  }

  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement && timetableMasterCard && timetableMasterCard.classList.contains("is-full-view")) {
      toggleFullView(false);
    }
  });

  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && timetableMasterCard && timetableMasterCard.classList.contains("is-full-view")) {
      toggleFullView(false);
    }
  });
}

// -------------------------------------------------------------
// Auth & RBAC Management
// -------------------------------------------------------------
async function checkAuthStatus() {
  try {
    const res = await fetch("/api/auth/current");
    const data = await res.json();
    if (data.authenticated) {
      state.currentUser = data.user;
      updateAuthUI();
    } else {
      // Auto login as default main admin for smooth prototype demonstration
      await autoLoginDefaultAdmin();
    }
  } catch (err) {
    console.error("Auth check failed:", err);
  }
}

async function autoLoginDefaultAdmin() {
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "admin", password: "admin123" }),
    });
    if (res.ok) {
      const data = await res.json();
      state.currentUser = data.user;
      updateAuthUI();
    }
  } catch (e) {
    console.error("Default login error:", e);
  }
}

function updateDivAutoSplitPreview() {
  const nameInput = document.getElementById("div-input-name");
  const capInput = document.getElementById("div-input-capacity");
  const partsInput = document.getElementById("div-split-parts");
  const preview = document.getElementById("div-split-preview");
  if (!nameInput || !capInput || !partsInput || !preview) return;

  const name = nameInput.value.trim() || "Division A";
  const cap = parseInt(capInput.value) || 75;
  const parts = parseInt(partsInput.value) || 3;

  let prefix = "";
  const words = name.split(/\s+/);
  if (words.length > 1 && words[words.length - 1].length === 1 && /^[a-zA-Z]$/.test(words[words.length - 1])) {
    prefix = words[words.length - 1].toUpperCase();
  } else if (/^[a-zA-Z]$/.test(name.charAt(0))) {
    prefix = name.charAt(0).toUpperCase();
  } else {
    prefix = "A";
  }

  const base = Math.floor(cap / parts);
  const rem = cap % parts;
  const items = [];
  for (let i = 1; i <= parts; i++) {
    const c = base + (i <= rem ? 1 : 0);
    items.push(`Batch ${prefix}${i} (${c})`);
  }
  preview.textContent = `💡 Preview: ${items.join(", ")}`;
}

function updateAutoSplitModalPreview() {
  const divSelect = document.getElementById("split-input-division");
  const partsSelect = document.getElementById("split-input-parts");
  const prefixInput = document.getElementById("split-input-prefix");
  const previewText = document.getElementById("split-preview-text");
  if (!divSelect || !partsSelect || !previewText) return;

  const divId = divSelect.value;
  const div = state.divisions.find((d) => d.id === divId);
  const parts = parseInt(partsSelect.value) || 3;
  let customPrefix = prefixInput ? prefixInput.value.trim().toUpperCase() : "";

  if (!div) {
    previewText.textContent = "Please select a division.";
    return;
  }

  let prefix = customPrefix;
  if (!prefix) {
    const words = div.name.trim().split(/\s+/);
    if (words.length > 1 && words[words.length - 1].length === 1 && /^[a-zA-Z]$/.test(words[words.length - 1])) {
      prefix = words[words.length - 1].toUpperCase();
    } else {
      prefix = div.name.charAt(0).toUpperCase() || "A";
    }
  }

  const totalCap = parseInt(div.capacity) || 75;
  const base = Math.floor(totalCap / parts);
  const rem = totalCap % parts;
  const items = [];
  for (let i = 1; i <= parts; i++) {
    const c = base + (i <= rem ? 1 : 0);
    items.push(`<strong>Batch ${prefix}${i}</strong> (${c} students)`);
  }
  previewText.innerHTML = items.join(" &nbsp;&bull;&nbsp; ");
}

function updateAuthUI() {
  const badge = document.getElementById("user-badge");
  const btnLogout = document.getElementById("btn-logout");

  if (state.currentUser) {
    badge.textContent = `👤 ${state.currentUser.name} [Administrator]`;
    badge.className = "badge badge-primary";
    btnLogout.style.display = "inline-flex";
  } else {
    badge.textContent = "Guest / Logged Out";
    badge.className = "badge";
    btnLogout.style.display = "none";
  }
}

// -------------------------------------------------------------
// Data Fetching & Sync
// -------------------------------------------------------------
async function refreshAllData() {
  try {
    const [
      statsRes,
      facultyRes,
      subjectsRes,
      divisionsRes,
      batchesRes,
      roomsRes,
      asgnRes,
      settingsRes,
      ttRes,
      floorsRes,
      roomsByFloorRes,
      distancesRes,
    ] = await Promise.all([
      fetch("/api/dashboard/stats"),
      fetch("/api/faculty"),
      fetch("/api/subjects"),
      fetch("/api/divisions"),
      fetch("/api/batches"),
      fetch("/api/rooms"),
      fetch("/api/faculty-assignments"),
      fetch("/api/settings"),
      fetch("/api/timetable"),
      fetch("/api/floors"),
      fetch("/api/rooms/by-floor"),
      fetch("/api/spatial/distances"),
    ]);

    state.stats = await statsRes.json();
    state.faculty = await facultyRes.json();
    state.subjects = await subjectsRes.json();
    state.divisions = await divisionsRes.json();
    state.batches = await batchesRes.json();
    state.rooms = await roomsRes.json();
    state.assignments = await asgnRes.json();
    state.settings = await settingsRes.json();
    state.timetable = await ttRes.json();
    state.floors = await floorsRes.json();
    state.roomsByFloor = await roomsByFloorRes.json();
    state.distances = await distancesRes.json();

    // Render all views
    renderDashboard();
    renderFacultyTable();
    renderSubjectsTable();
    renderAssignmentsTable();
    renderDivisionsView();
    renderFloorsView();
    renderRoomsTable();
    populateFloorDropdowns();
    populateSettingsForm();
    populateFilterDropdowns();
    renderTimetableGrid();
    if (typeof loadTimetableInsights === "function") {
      loadTimetableInsights();
    }
  } catch (err) {
    console.error("Error loading data:", err);
    showBanner("Failed to load data from server. Check backend connection.", "danger");
  }
}

// -------------------------------------------------------------
// Dashboard Rendering
// -------------------------------------------------------------
function renderDashboard() {
  document.getElementById("stat-faculty").textContent = state.stats.total_faculty || 0;
  document.getElementById("stat-subjects").textContent = state.stats.total_subjects || 0;
  document.getElementById("stat-divisions").textContent = state.stats.total_divisions || 0;
  document.getElementById("stat-required").textContent = state.stats.total_required_lectures || 0;
  document.getElementById("stat-scheduled").textContent = state.stats.total_scheduled_lectures || 0;
  document.getElementById("stat-unscheduled").textContent = state.stats.unscheduled_lectures || 0;

  const statusBadge = document.getElementById("stat-status-badge");
  if (state.stats.total_scheduled_lectures === 0) {
    statusBadge.textContent = "Not Generated";
    statusBadge.className = "badge badge-warning";
  } else if (!state.stats.is_conflict_free) {
    statusBadge.textContent = `Clashes Detected (${state.stats.conflicts_count})`;
    statusBadge.className = "badge badge-danger";
  } else if (state.stats.unscheduled_lectures > 0) {
    statusBadge.textContent = "Partially Scheduled";
    statusBadge.className = "badge badge-warning";
  } else {
    statusBadge.textContent = "Conflict-Free & Synced";
    statusBadge.className = "badge badge-success";
  }

  // Scheduling log box
  const logBox = document.getElementById("log-summary-box");
  const logTime = document.getElementById("log-timestamp");
  const lastLog = state.stats.last_log;

  renderAgentCards(lastLog);

  if (lastLog) {
    logTime.textContent = `Generated: ${new Date(lastLog.timestamp).toLocaleTimeString()} (${new Date(lastLog.timestamp).toLocaleDateString()})`;
    logBox.innerHTML = `
      <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:10px; font-size:13px;">
        <div>
          <strong>Total Requests:</strong> ${lastLog.total_requests} &nbsp;|&nbsp;
          <strong>Scheduled:</strong> <span class="text-success font-weight-bold">${lastLog.scheduled_count}</span> &nbsp;|&nbsp;
          <strong>Unscheduled:</strong> <span class="${lastLog.unscheduled_count > 0 ? 'text-danger' : 'text-success'}">${lastLog.unscheduled_count}</span>
        </div>
        <div>
          <strong>Backtracks:</strong> ${lastLog.backtracking_attempts} &nbsp;|&nbsp;
          <strong>Execution Time:</strong> ${lastLog.duration_seconds}s &nbsp;|&nbsp;
          <strong>Verification:</strong> ${lastLog.is_conflict_free ? '<span class="badge badge-success">0 Hard Clashes</span>' : `<span class="badge badge-danger">${lastLog.conflicts_count} Hard Conflicts</span>`}
        </div>
      </div>
    `;

    state.agentLogs = lastLog.execution_logs || [];
    state.divisionBreakdown = lastLog.division_breakdown || {};

    renderAgentLogsStream();
    renderDivisionBreakdown();

    // Unscheduled lectures table
    const unContainer = document.getElementById("unscheduled-reasons-container");
    const unTbody = document.querySelector("#table-unscheduled tbody");
    if (lastLog.unscheduled_details && lastLog.unscheduled_details.length > 0) {
      unContainer.classList.remove("hidden");
      unTbody.innerHTML = lastLog.unscheduled_details
        .map(
          (u) => `
        <tr>
          <td><span class="badge badge-primary">${u.year_id}</span></td>
          <td>${u.division_name} ${u.batch_name ? `(${u.batch_name})` : ""}</td>
          <td><strong>${u.subject_name}</strong></td>
          <td>${u.duration_minutes} min</td>
          <td class="text-danger">${u.reason}</td>
        </tr>
      `
        )
        .join("");
    } else {
      unContainer.classList.add("hidden");
    }
  } else {
    logTime.textContent = "No timetable generated yet.";
    logBox.innerHTML = "<p>Click <strong>⚡ Generate Timetable</strong> to run the multi-year Python Rule-Based Orchestrator with MRV and Future Flexibility Protection.</p>";
    document.getElementById("unscheduled-reasons-container").classList.add("hidden");
    renderAgentLogsStream([]);
    renderDivisionBreakdown({});
  }
}

function renderAgentCards(lastLog) {
  const summaries = lastLog && lastLog.agent_summaries ? lastLog.agent_summaries : null;

  // Orchestrator Card
  const orchBadge = document.getElementById("agent-stat-orch-badge");
  const orchBacktracks = document.getElementById("agent-stat-orch-backtracks");
  const orchTime = document.getElementById("agent-stat-orch-time");

  if (summaries && summaries.Orchestrator) {
    const o = summaries.Orchestrator;
    if (orchBadge) {
      orchBadge.textContent = o.status;
      orchBadge.className = o.unscheduled_count === 0 ? "badge badge-success" : "badge badge-warning";
    }
    if (orchBacktracks) orchBacktracks.textContent = o.backtracking_attempts;
    if (orchTime) orchTime.textContent = `${o.duration_seconds}s`;
  } else {
    if (orchBadge) {
      orchBadge.textContent = "Idle";
      orchBadge.className = "badge";
    }
    if (orchBacktracks) orchBacktracks.textContent = "0";
    if (orchTime) orchTime.textContent = "0.0s";
  }

  // FY, SY, TY, BE Cards
  ["FY", "SY", "TY", "BE"].forEach((yr) => {
    const yrLower = yr.toLowerCase();
    const badge = document.getElementById(`agent-stat-${yrLower}-badge`);
    const divsElem = document.getElementById(`agent-stat-${yrLower}-divs`);
    const progElem = document.getElementById(`agent-stat-${yrLower}-prog`);

    const yearDivs = state.divisions.filter((d) => d.year_id === yr);
    if (divsElem) divsElem.textContent = yearDivs.length;

    if (summaries && summaries[yr]) {
      const s = summaries[yr];
      if (badge) {
        badge.textContent = s.status;
        badge.className = s.remaining_count === 0 && s.required_count > 0 ? "badge badge-success" : "badge badge-primary";
      }
      if (progElem) progElem.textContent = `${s.scheduled_count}/${s.required_count}`;
    } else {
      if (badge) {
        badge.textContent = "Idle";
        badge.className = "badge";
      }
      if (progElem) progElem.textContent = "0/0";
    }
  });
}

function renderAgentLogsStream(logs = null) {
  const streamContainer = document.getElementById("agent-logs-stream");
  if (!streamContainer) return;

  const logsToRender = logs !== null ? logs : (state.agentLogs || []);
  if (!logsToRender || logsToRender.length === 0) {
    streamContainer.innerHTML = `
      <div style="color:#94a3b8; text-align:center; padding:24px;">
        No logs recorded yet. Click <strong>⚡ Generate Timetable</strong> to view rule-based agent reasoning and orchestrator decisions.
      </div>
    `;
    return;
  }

  const agentFilter = document.getElementById("agent-filter-select") ? document.getElementById("agent-filter-select").value : "ALL";
  const typeFilter = document.getElementById("agent-filter-type") ? document.getElementById("agent-filter-type").value : "ALL";
  const searchFilter = document.getElementById("agent-filter-search") ? document.getElementById("agent-filter-search").value.toLowerCase().trim() : "";

  const filtered = logsToRender.filter((item) => {
    if (agentFilter !== "ALL" && item.agent !== agentFilter) return false;
    if (typeFilter !== "ALL") {
      const t = (item.type || "").toUpperCase();
      if (typeFilter === "THINKING" && !["THINKING", "INITIALIZATION", "COORDINATION", "SUBMISSION"].includes(t)) return false;
      if (typeFilter === "REASONING" && t !== "REASONING") return false;
      if (typeFilter === "ASSIGNMENT" && t !== "ASSIGNMENT") return false;
      if (typeFilter === "BACKTRACK" && t !== "BACKTRACK") return false;
      if (typeFilter === "WARNING" && !["WARNING", "FAILURE"].includes(t)) return false;
    }
    if (searchFilter) {
      const msg = (item.message || "").toLowerCase();
      const div = (item.division || "").toLowerCase();
      if (!msg.includes(searchFilter) && !div.includes(searchFilter)) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    streamContainer.innerHTML = `
      <div style="color:#94a3b8; text-align:center; padding:20px;">
        No logs match the current filter criteria.
      </div>
    `;
    return;
  }

  const badgeClassMap = {
    "Python Rule-Based Orchestrator": "log-agent-orchestrator",
    "FY Agent": "log-agent-fy",
    "SY Agent": "log-agent-sy",
    "TY Agent": "log-agent-ty",
    "BE Agent": "log-agent-be",
  };

  // Recent logs appear at the top
  const recentFirst = [...filtered].reverse();

  streamContainer.innerHTML = recentFirst
    .map((item) => {
      const typeLower = (item.type || "").toLowerCase();
      let typeClass = "log-item";
      let typeIcon = "ℹ️";

      if (typeLower.includes("assignment")) {
        typeClass += " type-assignment";
        typeIcon = "⚡";
      } else if (typeLower.includes("thinking") || typeLower.includes("init") || typeLower.includes("coord") || typeLower.includes("submission")) {
        typeClass += " type-thinking";
        typeIcon = "🧠";
      } else if (typeLower.includes("reasoning")) {
        typeClass += " type-reasoning";
        typeIcon = "💡";
      } else if (typeLower.includes("backtrack")) {
        typeClass += " type-backtrack";
        typeIcon = "🔄";
      } else if (typeLower.includes("warning") || typeLower.includes("fail")) {
        typeClass += " type-warning";
        typeIcon = "⚠️";
      }

      const agentClass = badgeClassMap[item.agent] || "log-agent-orchestrator";
      const timeStr = item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : "";
      const divBadge = item.division ? `<span class="badge" style="background:#334155; color:#f8fafc; font-size:10px;">${item.year_id ? item.year_id + ' ' : ''}${item.division}</span>` : "";

      return `
        <div class="${typeClass}">
          <div class="log-meta">
            <span class="log-time">${timeStr}</span>
            <span class="log-agent-badge ${agentClass}">${item.agent}</span>
            ${divBadge}
            <span style="font-size:10px; color:#cbd5e1; margin-left:auto;">${typeIcon} ${item.type || 'LOG'}</span>
          </div>
          <div class="log-msg">${item.message}</div>
        </div>
      `;
    })
    .join("");

  streamContainer.scrollTop = 0;
}

function renderDivisionBreakdown(breakdown = null) {
  const container = document.getElementById("division-cards-container");
  if (!container) return;

  const data = breakdown !== null ? breakdown : (state.divisionBreakdown || {});
  const filterYear = document.getElementById("div-filter-year") ? document.getElementById("div-filter-year").value : "ALL";

  const divIds = Object.keys(data);
  let divsToRender = [];

  if (divIds.length > 0) {
    divsToRender = Object.values(data);
  } else if (state.divisions && state.divisions.length > 0) {
    divsToRender = state.divisions.map((d) => ({
      id: d.id,
      name: d.name,
      year_id: d.year_id,
      capacity: d.capacity || 0,
      required_count: 0,
      scheduled_count: 0,
      unscheduled_count: 0,
      status: "Not Generated",
      entries: [],
      unscheduled: [],
    }));
  }

  if (filterYear !== "ALL") {
    divsToRender = divsToRender.filter((d) => d.year_id === filterYear);
  }

  if (divsToRender.length === 0) {
    container.innerHTML = `
      <p class="text-muted" style="padding:20px; text-align:center; grid-column:1/-1;">
        No divisions found for academic year ${filterYear}.
      </p>
    `;
    return;
  }

  container.innerHTML = divsToRender
    .map((d) => {
      const pct = d.required_count > 0 ? Math.min(100, Math.round((d.scheduled_count / d.required_count) * 100)) : 0;
      const statusBadgeClass =
        d.status === "Fully Scheduled"
          ? "badge badge-success"
          : d.status === "Partially Scheduled"
          ? "badge badge-warning"
          : "badge";

      // Build small schedule table
      let entriesHtml = "";
      if (d.entries && d.entries.length > 0) {
        const dayOrder = { Monday: 1, Tuesday: 2, Wednesday: 3, Thursday: 4, Friday: 5, Saturday: 6 };
        const sortedEntries = [...d.entries].sort((a, b) => {
          const dDiff = (dayOrder[a.day] || 99) - (dayOrder[b.day] || 99);
          if (dDiff !== 0) return dDiff;
          return a.start_time.localeCompare(b.start_time);
        });

        entriesHtml = `
          <div style="max-height: 180px; overflow-y: auto; margin-top: 10px;">
            <table class="division-table-mini">
              <thead>
                <tr>
                  <th>Day & Slot</th>
                  <th>Subject</th>
                  <th>Faculty</th>
                  <th>Room</th>
                </tr>
              </thead>
              <tbody>
                ${sortedEntries
                  .map(
                    (e) => `
                  <tr>
                    <td><strong>${e.day.slice(0, 3)}</strong> ${e.start_time}-${e.end_time}</td>
                    <td>${e.subject_name} ${e.batch_name ? `<span class="badge badge-warning" style="font-size:9px;">${e.batch_name}</span>` : ""}</td>
                    <td>👨‍🏫 ${e.faculty_name}</td>
                    <td>📍 ${e.room_name}</td>
                  </tr>
                `
                  )
                  .join("")}
              </tbody>
            </table>
          </div>
        `;
      } else {
        entriesHtml = `<p class="text-muted" style="font-size:11px; margin-top:8px;">No lectures currently scheduled for this division.</p>`;
      }

      let unscheduledAlert = "";
      if (d.unscheduled && d.unscheduled.length > 0) {
        unscheduledAlert = `
          <div style="background:#fce8e6; border-left:3px solid #d93025; padding:6px 10px; margin-top:8px; border-radius:4px; font-size:11px; color:#c5221f;">
            <strong>⚠️ Bottlenecks (${d.unscheduled.length}):</strong>
            ${d.unscheduled.map((u) => `<div>• ${u.subject_name}${u.batch_name ? ` (${u.batch_name})` : ''}: ${u.reason}</div>`).join("")}
          </div>
        `;
      }

      return `
        <div class="division-card">
          <div class="division-card-header">
            <div>
              <strong style="font-size:14px;">${d.year_id} - ${d.name}</strong>
              <div class="text-muted" style="font-size:11px;">Strength: ${d.capacity ? d.capacity + ' students' : 'Not set'}</div>
            </div>
            <span class="${statusBadgeClass}">${d.status}</span>
          </div>
          <div class="division-card-progress">
            <div class="division-card-progress-bar" style="width: ${pct}%;"></div>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:11px; color:#5f6368;">
            <span>Required: <strong>${d.required_count}</strong></span>
            <span>Scheduled: <strong class="text-success">${d.scheduled_count}</strong></span>
            <span>Progress: <strong>${pct}%</strong></span>
          </div>
          ${unscheduledAlert}
          ${entriesHtml}
        </div>
      `;
    })
    .join("");
}

// -------------------------------------------------------------
// Timetable Label Snapping & Shortening Helpers (Zoom-Out / Fit)
// -------------------------------------------------------------
function getShortSubjectName(fullName, code) {
  if (code && code.length >= 2 && code.length <= 6 && !code.includes(" ")) {
    return code;
  }
  if (!fullName) return code || "SUB";
  let clean = fullName.trim();
  if (clean.toUpperCase().includes("MDM")) return "MDM";
  const known = {
    "computer science": "CS",
    "computer network": "CN",
    "computer networks": "CN",
    "database management systems": "DBMS",
    "database management system": "DBMS",
    "operating systems": "OS",
    "operating system": "OS",
    "object oriented programming": "OOP",
    "artificial intelligence": "AI",
    "machine learning": "ML",
    "data structures": "DS",
    "data structures and algorithms": "DSA",
    "software engineering": "SE",
    "information technology": "IT",
    "cyber security": "CSS",
  };
  const lower = clean.toLowerCase();
  if (known[lower]) return known[lower];
  const words = clean.split(/[\s\-_]+/).filter(Boolean);
  if (words.length > 1) {
    const acronym = words.map((w) => w[0].toUpperCase()).join("");
    if (acronym.length >= 2 && acronym.length <= 5) return acronym;
  }
  return clean.slice(0, 4).toUpperCase();
}

function getShortFacultyName(fullName) {
  if (!fullName) return "";
  let clean = fullName.trim();
  let prefix = "";
  const titleMatch = clean.match(/^(Dr\.|Prof\.|Mr\.|Ms\.|Mrs\.)\s*/i);
  if (titleMatch) {
    prefix = titleMatch[1] + " ";
    clean = clean.slice(titleMatch[0].length).trim();
  }
  if (clean.toLowerCase().includes("utkarsha patil") && !prefix) {
    prefix = "Ms. ";
  }
  const parts = clean.split(/[\s\-_]+/).filter(Boolean);
  if (parts.length === 0) return prefix.trim();
  if (parts.length === 1) {
    return (prefix + parts[0].slice(0, 3).toUpperCase()).trim();
  }
  const initials = parts.map((p) => p[0].toUpperCase()).join("");
  return (prefix + initials).trim();
}

function getShortRoomName(roomName) {
  if (!roomName) return "";
  let clean = roomName.trim();
  clean = clean.replace(/^Room[\s\-_]*/i, "R");
  clean = clean.replace(/^Lab[\s\-_]*/i, "L");
  return clean;
}

function toggleFilterValue(type, val) {
  if (!state.filters[type]) state.filters[type] = ["ALL"];
  let list = [...state.filters[type]];
  if (val === "ALL") {
    list = ["ALL"];
  } else {
    list = list.filter((x) => x !== "ALL");
    const idx = list.indexOf(val);
    if (idx >= 0) {
      list.splice(idx, 1);
      if (list.length === 0) list = ["ALL"];
    } else {
      list.push(val);
    }
  }
  state.filters[type] = list;
  if (type === "years") {
    state.filters.year = list.length === 1 ? list[0] : (list.includes("ALL") ? "ALL" : list[0]);
    state.selectedYear = state.filters.year === "ALL" ? "TY" : state.filters.year;
    // When years change, ensure divisions filter stays valid
    state.filters.divisions = ["ALL"];
    state.filters.division = "ALL";
  } else if (type === "divisions") {
    state.filters.division = list.length === 1 ? list[0] : (list.includes("ALL") ? "ALL" : list[0]);
  } else if (type === "days") {
    state.filters.day = list.length === 1 ? list[0] : (list.includes("ALL") ? "ALL" : list[0]);
  }
  populateFilterDropdowns();
  renderTimetableGrid();
}
window.toggleFilterValue = toggleFilterValue;

// -------------------------------------------------------------
// Timetable View & Grid Rendering
// -------------------------------------------------------------
function populateFilterDropdowns() {
  if (!state.filters) {
    state.filters = {
      year: "ALL",
      division: "ALL",
      faculty: "ALL",
      room: "ALL",
      day: "ALL",
      years: ["ALL"],
      divisions: ["ALL"],
      days: ["ALL"],
    };
  }
  if (!state.filters.years) state.filters.years = [state.filters.year || "ALL"];
  if (!state.filters.divisions) state.filters.divisions = [state.filters.division || "ALL"];
  if (!state.filters.days) state.filters.days = [state.filters.day || "ALL"];

  if (window.updateActiveFilterIndicator) {
    window.updateActiveFilterIndicator();
  }

  // 1. Academic Year Dropdown & Multi-Select Box Buttons
  const yearSelect = document.getElementById("tt-year-select");
  if (yearSelect) {
    yearSelect.value = state.filters.years.length === 1 ? state.filters.years[0] : "ALL";
  }
  const boxYear = document.getElementById("box-filter-year");
  if (boxYear) {
    const activeYears = state.filters.years;
    boxYear.querySelectorAll(".btn-filter-box").forEach((btn) => {
      const val = btn.getAttribute("data-val");
      if (val === "ALL") {
        if (activeYears.includes("ALL")) btn.classList.add("active");
        else btn.classList.remove("active");
      } else {
        if (!activeYears.includes("ALL") && activeYears.includes(val)) {
          btn.classList.add("active");
        } else {
          btn.classList.remove("active");
        }
      }
    });
  }

  // 2. Divisions Dropdown & Multi-Select Box Buttons (Filtered by Year, sorted by rank)
  const divSelect = document.getElementById("tt-division-select");
  const activeYears = state.filters.years;
  let availableDivs = [...(state.divisions || [])];
  const yearRank = { "FY": 1, "FE": 1, "SY": 2, "SE": 2, "TY": 3, "TE": 3, "BE": 4 };
  availableDivs.sort((a, b) => {
    const rA = yearRank[a.year_id] || 99;
    const rB = yearRank[b.year_id] || 99;
    if (rA !== rB) return rA - rB;
    return (a.name || "").localeCompare(b.name || "");
  });

  if (!activeYears.includes("ALL")) {
    availableDivs = availableDivs.filter((d) => activeYears.includes(d.year_id));
  }

  if (divSelect) {
    let divOptionsHtml = `<option value="ALL">All Divisions ${activeYears.includes("ALL") ? "(Across Years)" : `(${activeYears.join(", ")})`}</option>`;
    divOptionsHtml += availableDivs
      .map((d) => {
        const cleanName = (d.name || "").replace(/Division\s*/i, "").trim();
        const label = activeYears.includes("ALL") ? `${d.year_id} – ${cleanName || d.name}` : (cleanName || d.name);
        return `<option value="${d.id}">${label}</option>`;
      })
      .join("");
    divSelect.innerHTML = divOptionsHtml;

    if (state.filters.division !== "ALL") {
      const exists = availableDivs.some((d) => {
        const clean = (d.name || "").replace(/Division\s*/i, "").trim().toUpperCase();
        return d.id === state.filters.division || clean === state.filters.division.toUpperCase();
      });
      if (exists) {
        divSelect.value = state.filters.division;
      } else {
        state.filters.division = "ALL";
        state.filters.divisions = ["ALL"];
        divSelect.value = "ALL";
      }
    } else {
      divSelect.value = "ALL";
    }
  }

  // Multi-Select Box Buttons for Divisions (A, B, C)
  const boxDiv = document.getElementById("box-filter-division");
  if (boxDiv) {
    const distinctLetters = [];
    availableDivs.forEach((d) => {
      const clean = (d.name || "").replace(/Division\s*/i, "").trim().toUpperCase();
      const l = clean || d.name;
      if (l && !distinctLetters.includes(l)) distinctLetters.push(l);
    });
    distinctLetters.sort();

    const activeDivs = state.filters.divisions;
    let divBtnsHtml = `<button type="button" class="btn-filter-box ${activeDivs.includes('ALL') ? 'active' : ''}" data-val="ALL">All</button>`;
    distinctLetters.forEach((l) => {
      const isActive = !activeDivs.includes("ALL") && activeDivs.some((dVal) => dVal.toUpperCase() === l.toUpperCase());
      divBtnsHtml += `<button type="button" class="btn-filter-box ${isActive ? 'active' : ''}" data-val="${l}">${l}</button>`;
    });
    boxDiv.innerHTML = divBtnsHtml;

    boxDiv.querySelectorAll(".btn-filter-box").forEach((btn) => {
      btn.addEventListener("click", () => {
        toggleFilterValue("divisions", btn.getAttribute("data-val"));
      });
    });
  }

  // 3. Faculty Dropdown
  const facSelect = document.getElementById("tt-faculty-select");
  if (facSelect) {
    const sortedFaculty = [...(state.faculty || [])].sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    let facOptionsHtml = `<option value="ALL">All Faculty (${sortedFaculty.length})</option>`;
    facOptionsHtml += sortedFaculty.map((f) => `<option value="${f.id}">${f.name}</option>`).join("");
    facSelect.innerHTML = facOptionsHtml;
    facSelect.value = state.filters.faculty || "ALL";
  }

  // 4. Room Dropdown
  const roomSelect = document.getElementById("tt-room-select");
  if (roomSelect) {
    const sortedRooms = [...(state.rooms || [])].sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    let roomOptionsHtml = `<option value="ALL">All Rooms (${sortedRooms.length})</option>`;
    roomOptionsHtml += sortedRooms
      .map((r) => `<option value="${r.id}">${r.name} (${r.type})</option>`)
      .join("");
    roomSelect.innerHTML = roomOptionsHtml;
    roomSelect.value = state.filters.room || "ALL";
  }

  // 5. Day Dropdown & Multi-Select Box Buttons
  const daySelect = document.getElementById("tt-day-select");
  const workingDays = state.settings.working_days || ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
  if (daySelect) {
    let dayOptionsHtml = `<option value="ALL">All Days (${workingDays.length})</option>`;
    dayOptionsHtml += workingDays.map((d) => `<option value="${d}">${d}</option>`).join("");
    daySelect.innerHTML = dayOptionsHtml;
    daySelect.value = state.filters.days.length === 1 ? state.filters.days[0] : "ALL";
  }
  const boxDay = document.getElementById("box-filter-day");
  if (boxDay) {
    const activeDays = state.filters.days;
    boxDay.querySelectorAll(".btn-filter-box").forEach((btn) => {
      const val = btn.getAttribute("data-val");
      if (val === "ALL") {
        if (activeDays.includes("ALL")) btn.classList.add("active");
        else btn.classList.remove("active");
      } else {
        if (!activeDays.includes("ALL") && activeDays.includes(val)) {
          btn.classList.add("active");
        } else {
          btn.classList.remove("active");
        }
      }
    });
  }
}

// -------------------------------------------------------------
// Global Time Conversion Utilities
// -------------------------------------------------------------
function toMin(t) {
  if (!t) return 0;
  const parts = t.split(":");
  return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
}

function toTime(m) {
  const hh = String(Math.floor(m / 60)).padStart(2, "0");
  const mm = String(m % 60).padStart(2, "0");
  return `${hh}:${mm}`;
}

// -------------------------------------------------------------
// Common Time Slot Generation (Based on Institutional Settings)
// -------------------------------------------------------------
function generateCommonTimeSlots(settings) {
  const toMin = (t) => {
    if (!t) return 0;
    const parts = t.split(":");
    return parseInt(parts[0]) * 60 + parseInt(parts[1]);
  };
  const toTime = (m) => {
    const hh = String(Math.floor(m / 60)).padStart(2, "0");
    const mm = String(m % 60).padStart(2, "0");
    return `${hh}:${mm}`;
  };

  const startMin = toMin(settings.day_start_time || "09:00");
  const endMin = toMin(settings.day_end_time || "17:00");
  const stepMin = parseInt(settings.default_lecture_duration || 60);

  const breaks = (settings.breaks || [])
    .map((b) => ({
      name: b.name,
      startMin: toMin(b.start),
      endMin: toMin(b.end),
      start: b.start,
      end: b.end,
      type: b.type || "short_break",
    }))
    .sort((a, b) => a.startMin - b.startMin);

  const rows = [];
  let curr = startMin;
  let periodNum = 1;

  while (curr < endMin) {
    // Check if a break starts exactly at curr
    const activeBreak = breaks.find((b) => b.startMin === curr);
    if (activeBreak) {
      rows.push({
        isBreak: true,
        name: activeBreak.name,
        type: activeBreak.type,
        start: activeBreak.start,
        end: activeBreak.end,
        startMin: activeBreak.startMin,
        endMin: activeBreak.endMin,
        label: `${activeBreak.name} (${activeBreak.start} - ${activeBreak.end})`,
        durationMinutes: activeBreak.endMin - activeBreak.startMin,
      });
      curr = activeBreak.endMin;
      continue;
    }

    // Check if the next period intersects with an upcoming break
    const nextBreak = breaks.find((b) => b.startMin > curr && b.startMin < curr + stepMin);
    const slotEndMin = nextBreak ? nextBreak.startMin : Math.min(curr + stepMin, endMin);

    if (slotEndMin > curr) {
      rows.push({
        isBreak: false,
        period: periodNum++,
        start: toTime(curr),
        end: toTime(slotEndMin),
        startMin: curr,
        endMin: slotEndMin,
        label: `${toTime(curr)} - ${toTime(slotEndMin)}`,
        durationMinutes: slotEndMin - curr,
      });
      curr = slotEndMin;
    } else {
      break;
    }
  }

  return rows;
}

function renderTimetableGrid() {
  const masterTable = document.getElementById("timetable-master-table");
  const thead = document.getElementById("tt-master-thead");
  const tbody = document.getElementById("tt-master-tbody");
  const gridBoard = document.getElementById("timetable-grid-board"); // legacy fallback
  const clashAlert = document.getElementById("timetable-clash-alert");
  const clashCount = document.getElementById("timetable-clash-count");
  const clashList = document.getElementById("timetable-clash-list");

  if (!masterTable || !thead || !tbody) return;

  if (!state.filters) {
    state.filters = { year: "ALL", division: "ALL", faculty: "ALL", room: "ALL", day: "ALL" };
  }

  if (window.updateActiveFilterIndicator) {
    window.updateActiveFilterIndicator();
  }

  const workingDays = state.settings.working_days || ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
  const allSlots = generateCommonTimeSlots(state.settings);

  // Hidden table element fallbacks
  const headerRow = document.getElementById("tt-header-row");
  if (headerRow) headerRow.innerHTML = "";

  // 1. Check validation conflicts for highlighting
  const valReport = state.timetable.validation_report;
  const hardConflicts = (valReport && valReport.hard_conflicts) || [];
  if (hardConflicts.length > 0) {
    if (clashAlert) clashAlert.classList.remove("hidden");
    if (clashCount) clashCount.textContent = `${hardConflicts.length} conflict(s)`;
    if (clashList) clashList.innerHTML = hardConflicts.map((c) => `<li>${c.message}</li>`).join("");
  } else {
    if (clashAlert) clashAlert.classList.add("hidden");
  }

  const conflictingEntryIds = new Set();
  hardConflicts.forEach((c) => {
    if (c.entry_id) conflictingEntryIds.add(c.entry_id);
    if (c.entry_ids) c.entry_ids.forEach((id) => conflictingEntryIds.add(id));
  });

  // 2. Build thead with Time Columns (Sticky Top)
  let theadHtml = `
    <tr>
      <th class="tt-col-day">Day</th>
      <th class="tt-col-class">Class / Div</th>
  `;
  allSlots.forEach((slot) => {
    if (slot.isBreak) {
      theadHtml += `
        <th class="tt-col-break" title="${slot.name} (${slot.start} - ${slot.end})">
          <div class="tt-break-header-content">
            <span class="tt-break-name">BREAK</span>
            <span class="tt-break-time">${slot.start}–${slot.end}</span>
          </div>
        </th>
      `;
    } else {
      theadHtml += `
        <th class="tt-col-slot">
          <div class="tt-slot-header-content">
            <span class="tt-slot-time">${slot.start} – ${slot.end}</span>
            <span class="tt-slot-period">Period ${slot.period}</span>
          </div>
        </th>
      `;
    }
  });
  theadHtml += `</tr>`;
  thead.innerHTML = theadHtml;

  // 3. Determine visible Days (Supports Multi-Select)
  const activeDays = state.filters.days || (state.filters.day ? [state.filters.day] : ["ALL"]);
  const visibleDays = activeDays.includes("ALL")
    ? workingDays
    : workingDays.filter((d) => activeDays.includes(d));

  // 4. Determine visible Divisions (Strict order: FY -> SY -> TY -> BE, then division name)
  let targetDivisions = [...(state.divisions || [])];
  const yearRank = { "FY": 1, "FE": 1, "SY": 2, "SE": 2, "TY": 3, "TE": 3, "BE": 4 };
  targetDivisions.sort((a, b) => {
    const rA = yearRank[a.year_id] || 99;
    const rB = yearRank[b.year_id] || 99;
    if (rA !== rB) return rA - rB;
    return (a.name || "").localeCompare(b.name || "");
  });

  const activeYears = state.filters.years || (state.filters.year ? [state.filters.year] : ["ALL"]);
  if (!activeYears.includes("ALL")) {
    targetDivisions = targetDivisions.filter((d) => activeYears.includes(d.year_id));
  }

  const activeDivs = state.filters.divisions || (state.filters.division ? [state.filters.division] : ["ALL"]);
  if (!activeDivs.includes("ALL")) {
    targetDivisions = targetDivisions.filter((d) => {
      const cleanLetter = (d.name || "").replace(/Division\s*/i, "").trim().toUpperCase();
      return activeDivs.includes(d.id) ||
             activeDivs.some((v) => v.toUpperCase() === cleanLetter || v.toUpperCase() === (d.name || "").toUpperCase());
    });
  }

  // If no divisions match selection
  if (targetDivisions.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="${allSlots.length + 2}" class="text-center p-4 text-muted" style="background:#ffffff; padding: 48px 16px !important; text-align:center;">
          <div style="font-size:16px; font-weight:700; color:#1e293b; margin-bottom:6px;">No divisions match the active filter criteria</div>
          <div style="font-size:13px; color:#64748b;">Try selecting "ALL YEARS" or adding new divisions in the Divisions & Batches tab.</div>
        </td>
      </tr>
    `;
    if (gridBoard) gridBoard.innerHTML = "";
    return;
  }

  const allEntries = state.timetable.entries || [];
  let tbodyHtml = "";

  // 5. Render Day Row Groups & Class Rows
  visibleDays.forEach((day) => {
    const numDivRows = targetDivisions.length;

    targetDivisions.forEach((div, divIdx) => {
      const isFirstRowOfDay = divIdx === 0;
      const isLastRowOfDay = divIdx === numDivRows - 1;
      const rowClass = isLastRowOfDay ? "tt-row tt-row-last-of-day" : "tt-row";

      tbodyHtml += `<tr class="${rowClass}" data-day="${day}" data-div="${div.id}">`;

      // Vertically merged Day cell
      if (isFirstRowOfDay) {
        tbodyHtml += `
          <td class="tt-day-cell" rowspan="${numDivRows}">
            <div class="tt-day-badge">
              <span class="tt-day-text">${day.toUpperCase()}</span>
              <span class="tt-day-sub">${numDivRows} ${numDivRows === 1 ? "Class" : "Classes"}</span>
            </div>
          </td>
        `;
      }

      // Class / Division column
      const cleanDivName = (div.name || "").replace(/Division\s*/i, "").trim();
      tbodyHtml += `
        <td class="tt-class-cell">
          <div class="tt-class-badge-wrapper">
            <span class="tt-class-year-pill">${div.year_id}</span>
            <span class="tt-class-code">${div.year_id} – ${cleanDivName || div.name}</span>
          </div>
        </td>
      `;

      // Render cells for all time slots
      let skipSlots = 0;
      for (let sIdx = 0; sIdx < allSlots.length; sIdx++) {
        if (skipSlots > 0) {
          skipSlots--;
          continue;
        }

        const slot = allSlots[sIdx];
        if (slot.isBreak) {
          tbodyHtml += `
            <td class="tt-break-cell" title="${slot.name} (${slot.start} - ${slot.end})">
              <div class="tt-break-vertical-letters">
                <span>B</span>
                <span>R</span>
                <span>E</span>
                <span>A</span>
                <span>K</span>
              </div>
            </td>
          `;
          continue;
        }

        const slotStartMin = slot.startMin !== undefined ? slot.startMin : toMin(slot.start);
        const slotEndMin = slot.endMin !== undefined ? slot.endMin : toMin(slot.end);

        // Find entries matching this day, division, and start time
        const divDayEntries = allEntries.filter((e) => {
          if (e.day !== day) return false;
          if (e.division_id !== div.id) return false;
          const eStart = toMin(e.start_time);
          return eStart === slotStartMin;
        });

        // Apply Faculty filter if selected
        let matchingEntries = divDayEntries;
        if (state.filters.faculty !== "ALL") {
          matchingEntries = matchingEntries.filter((e) => e.faculty_id === state.filters.faculty);
        }

        // Apply Room filter if selected
        if (state.filters.room !== "ALL") {
          matchingEntries = matchingEntries.filter((e) => e.room_id === state.filters.room || e.fixed_room_id === state.filters.room);
        }

        if (matchingEntries.length === 0) {
          // Clean empty cell
          tbodyHtml += `
            <td class="tt-slot-cell tt-empty-cell"
                id="cell-${day}-${div.id}-${slot.start.replace(':', '')}"
                data-day="${day}"
                data-div="${div.id}"
                data-year="${div.year_id}"
                data-start="${slot.start}"
                data-end="${slot.end}"
                onclick="if (Date.now() < window.suppressClickUntil) return; handleCellClick('${day}', '${slot.start}', '${slot.end}', '${div.id}', '${div.year_id}')"
                ondblclick="window.handleEmptyCellDblClick(event, '${day}', '${slot.start}', '${slot.end}', '${div.id}')"
                ondragover="handleCellDragOver(event)"
                ondragleave="handleCellDragLeave(event)"
                ondrop="handleCellDrop(event, '${day}', '${slot.start}', '${slot.end}', '${div.id}')"
                title="Available • Double-click to add, or drop dragged lecture to schedule/swap">
              <div class="empty-slot-content">
                <span class="empty-plus">+</span>
              </div>
            </td>
          `;
          continue;
        }

        // Calculate multi-slot span (colspan)
        let maxEndMin = slotEndMin;
        matchingEntries.forEach((e) => {
          maxEndMin = Math.max(maxEndMin, toMin(e.end_time));
        });

        let spanCount = 1;
        let checkIdx = sIdx + 1;
        while (checkIdx < allSlots.length) {
          const nextSlot = allSlots[checkIdx];
          if (nextSlot.isBreak) break;
          const nextStart = nextSlot.startMin !== undefined ? nextSlot.startMin : toMin(nextSlot.start);
          if (nextStart < maxEndMin) {
            spanCount++;
            checkIdx++;
          } else {
            break;
          }
        }
        skipSlots = spanCount - 1;

        // Check if this slot contains MDM / elective tracks
        const isElective = matchingEntries.some((e) =>
          e.is_elective ||
          e.type === "Elective" ||
          e.fixed_room_id ||
          (e.subject_name && e.subject_name.toUpperCase().includes("MDM"))
        );

        let cellContent = "";
        if (isElective) {
          // Consolidated MDM elective card
          cellContent = renderConsolidatedElectiveCard(matchingEntries, conflictingEntryIds);
        } else if (matchingEntries.length > 1) {
          // Multiple simultaneous practical batches stacked vertically in parallel lanes
          cellContent = `
            <div class="tt-cell-batches-container">
              ${matchingEntries.map((e) => `
                <div class="tt-batch-lane">
                  ${renderEntryCard(e, conflictingEntryIds, true)}
                </div>
              `).join("")}
            </div>
          `;
        } else {
          // Single lecture card
          cellContent = renderEntryCard(matchingEntries[0], conflictingEntryIds);
        }

        const colspanAttr = spanCount > 1 ? ` colspan="${spanCount}"` : "";
        const effectiveEnd = allSlots[sIdx + spanCount - 1].end;

        tbodyHtml += `
          <td class="tt-slot-cell"${colspanAttr}
              id="cell-${day}-${div.id}-${slot.start.replace(':', '')}"
              data-day="${day}"
              data-div="${div.id}"
              data-start="${slot.start}"
              data-end="${effectiveEnd}"
              ondragover="handleCellDragOver(event)"
              ondragleave="handleCellDragLeave(event)"
              ondrop="handleCellDrop(event, '${day}', '${slot.start}', '${effectiveEnd}', '${div.id}')">
            ${cellContent}
          </td>
        `;
      }

      tbodyHtml += `</tr>`;
    });
  });

  tbody.innerHTML = tbodyHtml;
  if (gridBoard) gridBoard.innerHTML = "";
}

function renderEntryCard(entry, conflictingEntryIds, isCompactBatch = false) {
  const hasClash = conflictingEntryIds.has(entry.id);
  const isMDM = Boolean(
    entry.is_elective ||
    entry.type === "Elective" ||
    entry.fixed_room_id ||
    (entry.subject_name && entry.subject_name.toUpperCase().includes("MDM"))
  );
  const isLab = entry.type === "Practical" || entry.duration_minutes === 120;
  const typeClass = isLab
    ? "practical"
    : isMDM
    ? "elective"
    : entry.type === "Other"
    ? "other"
    : "theory";
  const clashClass = hasClash ? "has-clash" : "";

  // Lookup Subject Code
  const sub = (state.subjects || []).find((s) => s.id === entry.subject_id || s.id === entry.parent_subject_id);
  const subCode = (sub && (sub.code || sub.subject_code)) || entry.subject_code || "";

  // Clean subject display: show MDM only, not composite sub-subjects
  let subjectDisplay = entry.subject_name || "Lecture";
  if (isMDM) {
    if (subjectDisplay.toUpperCase().includes("MDM")) {
      subjectDisplay = "MDM (Theory)";
    } else if (subjectDisplay.includes(" (")) {
      subjectDisplay = subjectDisplay.split(" (")[0];
    }
  }

  // Generate compact initials / short names for zoom out
  const subShort = getShortSubjectName(subjectDisplay, subCode);
  const facShort = getShortFacultyName(entry.faculty_name);
  const roomShort = getShortRoomName(entry.room_name);

  const batchBadge = entry.elective_group_name
    ? `<span class="badge" style="font-size:10px; background:#f5f3ff; color:#7c3aed; border:1px solid #ddd6fe; padding:2px 5px; font-weight:600;">📖 Track: ${entry.elective_group_name}</span>`
    : entry.batch_name
    ? `<span class="badge badge-warning" style="font-size:10px; padding:2px 5px; font-weight:600;">🔬 Batch ${entry.batch_name}</span>`
    : "";

  const typeBadge = isMDM
    ? `<span class="badge" style="font-size:9px; background:#ede9fe; color:#6d28d9; padding:1px 5px; font-weight:700;">MDM (Theory)</span>`
    : isLab
    ? `<span class="badge" style="font-size:9px; background:#dcfce7; color:#15803d; padding:1px 5px; font-weight:700;">🔬 Lab (Practical)</span>`
    : `<span class="badge" style="font-size:9px; background:rgba(0,0,0,0.06); color:#334155; padding:1px 4px;">Theory</span>`;

  const roomDisplay = entry.fixed_room_id
    ? `<span class="tt-entry-room" title="Fixed Classroom Reservation">
         <span class="tt-room-full">📍 ${entry.room_name} <strong style="color:#7c3aed;">🔒</strong></span>
         <span class="tt-room-short">📍 ${roomShort}🔒</span>
       </span>`
    : `<span class="tt-entry-room">
         <span class="tt-room-full">📍 ${entry.room_name}</span>
         <span class="tt-room-short">📍 ${roomShort}</span>
       </span>`;

  const classInfo =
    state.viewMode !== "division"
      ? `<div style="font-size:10px; color:#475569; font-weight:600; margin-top:2px;">🎓 ${entry.year_id} ${entry.division_name || ""}</div>`
      : "";

  const durMin = toMin(entry.end_time) - toMin(entry.start_time);
  const durLabel = durMin > 60 ? ` (${durMin}m)` : "";

  const isSelected = state.selectedEntryId === entry.id;
  const selectedClass = isSelected ? "is-selected" : "";
  const isRecentlySwapped = (state.recentlySwappedEntryIds || []).includes(entry.id);
  const swappedClass = isRecentlySwapped ? "tt-entry-swapped" : "";

  const clickAction = isElective
    ? `window.openElectiveDetailsForEntry('${entry.id}')`
    : `openEditLectureModal('${entry.id}')`;
  const clickTitle = isElective
    ? "Click to view MDM tracks, or drag to swap/reschedule"
    : "Click to edit, or drag to swap/reschedule";

  if (isCompactBatch) {
    return `
      <div class="tt-entry ${typeClass} ${clashClass} ${selectedClass} ${swappedClass} tt-entry-batch-compact"
           data-entry-id="${entry.id}"
           draggable="true"
           ondragstart="handleDragStart(event, '${entry.id}')"
           ondragend="handleDragEnd(event)"
           onclick="if (Date.now() < window.suppressClickUntil) return; event.stopPropagation(); ${clickAction}"
           title="${clickTitle}">
        <div class="tt-entry-header" style="margin-bottom:2px;">
          <span class="tt-entry-sub" style="font-size:11px; font-weight:700;">
            <span class="tt-sub-full">${batchBadge} ${subjectDisplay} ${subCode ? `<span class="tt-sub-code">${subCode}</span>` : ""}</span>
            <span class="tt-sub-short">${batchBadge} ${subShort}</span>
          </span>
          <div style="display:inline-flex; align-items:center; gap:2px;">
            ${hasClash ? `<button type="button" class="tt-clash-badge-btn" title="Click to auto-fix this clash" onclick="event.stopPropagation(); window.handleFixSingleEntry('${entry.id}', 'fix_this')">⚠️</button>` : ""}
            <span class="tt-drag-handle" title="Drag to reschedule">⠿</span>
            <button type="button" class="tt-quick-del-btn" title="Delete this lecture"
                    onclick="event.stopPropagation(); quickDeleteTimetableEntry('${entry.id}', '${(entry.subject_name || '').replace(/'/g, "\\'")}')">✕</button>
          </div>
        </div>
        <div class="tt-entry-fac" style="font-size:11px; color:#334155;">
          <span class="tt-fac-full">👨‍🏫 ${entry.faculty_name} &nbsp;•&nbsp; ${roomDisplay}</span>
          <span class="tt-fac-short">👨‍🏫 ${facShort} • ${roomShort}</span>
        </div>
        ${hasClash ? `
          <div class="tt-clash-actions" style="margin-top:2px;">
            <button type="button" class="btn-clash-action btn-fix-this" title="Move THIS lecture somewhere with no clash" onclick="event.stopPropagation(); window.handleFixSingleEntry('${entry.id}', 'fix_this')">
              🔧 Fix This
            </button>
            <button type="button" class="btn-clash-action btn-fix-other" title="Keep THIS lecture here and adjust other clashing lecture(s)" onclick="event.stopPropagation(); window.handleFixSingleEntry('${entry.id}', 'fix_other')">
              🔄 Fix Other
            </button>
          </div>
        ` : ""}
      </div>
    `;
  }

  return `
    <div class="tt-entry ${typeClass} ${clashClass} ${selectedClass} ${swappedClass}"
         data-entry-id="${entry.id}"
         draggable="true"
         ondragstart="handleDragStart(event, '${entry.id}')"
         ondragend="handleDragEnd(event)"
         onclick="if (Date.now() < window.suppressClickUntil) return; event.stopPropagation(); ${clickAction}"
         title="${clickTitle}">
      <div class="tt-entry-header">
        <span class="tt-entry-sub">
          <span class="tt-sub-full">${subjectDisplay} ${subCode ? `<span class="tt-sub-code">${subCode}</span>` : ""}</span>
          <span class="tt-sub-short">${subShort}</span>
        </span>
        <div style="display:inline-flex; align-items:center; gap:3px;">
          ${hasClash ? `<button type="button" class="tt-clash-badge-btn" title="Click to auto-fix this clash" onclick="event.stopPropagation(); window.handleFixSingleEntry('${entry.id}', 'fix_this')">⚠️ Fix</button>` : ""}
          <span class="tt-drag-handle" title="Drag to reschedule">⠿</span>
          <button type="button" class="tt-quick-del-btn" title="Delete this lecture"
                  onclick="event.stopPropagation(); quickDeleteTimetableEntry('${entry.id}', '${(entry.subject_name || '').replace(/'/g, "\\'")}')">✕</button>
        </div>
      </div>
      <div class="tt-entry-fac">
        <span class="tt-fac-full">👨‍🏫 ${entry.faculty_name}</span>
        <span class="tt-fac-short">👨‍🏫 ${facShort}</span>
      </div>
      <div class="tt-entry-meta">
        ${roomDisplay}
        <div style="display:flex; gap:3px; align-items:center;">
          ${batchBadge}
          ${typeBadge}
        </div>
      </div>
      <div class="tt-entry-meta" style="margin-top:2px;">
        <span class="tt-entry-time">🕒 ${entry.start_time} - ${entry.end_time}${durLabel}</span>
        ${hasClash ? '<span class="badge badge-danger" style="font-size:9px;">CLASH</span>' : ""}
      </div>
      ${classInfo}
      ${hasClash ? `
        <div class="tt-clash-actions">
          <button type="button" class="btn-clash-action btn-fix-this" title="Move THIS lecture somewhere with no clash" onclick="event.stopPropagation(); window.handleFixSingleEntry('${entry.id}', 'fix_this')">
            🔧 Fix This
          </button>
          <button type="button" class="btn-clash-action btn-fix-other" title="Keep THIS lecture here and adjust other clashing lecture(s)" onclick="event.stopPropagation(); window.handleFixSingleEntry('${entry.id}', 'fix_other')">
            🔄 Fix Other
          </button>
        </div>
      ` : ""}
    </div>
  `;
}

// -------------------------------------------------------------
// Quick Delete Timetable Entry
// -------------------------------------------------------------
window.quickDeleteTimetableEntry = async function (entryId, subjectName) {
  if (!confirm(`Are you sure you want to remove "${subjectName}" from the timetable?`)) {
    return;
  }
  try {
    const res = await fetch(`/api/timetable/entry/${entryId}`, { method: "DELETE" });
    if (res.ok) {
      showBanner(`Removed "${subjectName}" from timetable.`, "success");
      await refreshAllData();
    } else {
      const d = await res.json();
      showBanner(d.error || "Failed to delete lecture.", "danger");
    }
  } catch (err) {
    console.error("Delete entry error:", err);
    showBanner("Failed to delete lecture.", "danger");
  }
};

// -------------------------------------------------------------
// Consolidated Elective Card & Modal
// -------------------------------------------------------------
function renderConsolidatedElectiveCard(entries, conflictingEntryIds) {
  const hasClash = entries.some((e) => conflictingEntryIds.has(e.id));
  const clashClass = hasClash ? "has-clash" : "";

  const first = entries[0];
  const parentSub = (state.subjects || []).find((s) => s.id === first.parent_subject_id || s.id === first.subject_id);
  
  // Clean Subject Title: Always show "MDM" (or parent subject name), never composite sub-subjects
  let title = "MDM";
  if (parentSub && parentSub.name) {
    title = parentSub.name.toUpperCase().includes("MDM") ? "MDM" : parentSub.name;
  } else if (first.subject_name && first.subject_name.toUpperCase().includes("MDM")) {
    title = "MDM";
  } else if (first.subject_name) {
    title = first.subject_name.split(" (")[0];
  }
  const subCode = (parentSub && (parentSub.code || parentSub.subject_code)) || (first.subject_code && !first.subject_code.includes(" ") ? first.subject_code : "");

  const trackCount = entries.length;
  const roomNames = [...new Set(entries.map((e) => e.fixed_room_name || e.room_name).filter(Boolean))].join(", ");
  const facNames = entries.map((e) => e.faculty_name).filter(Boolean).join(" & ");

  // Short labels for zoom out
  const subShort = getShortSubjectName(title, subCode);
  const facShort = getShortFacultyName(facNames);
  const roomShort = getShortRoomName(roomNames);

  const isSelected = state.selectedEntryId === first.id;
  const selectedClass = isSelected ? "is-selected" : "";
  const isRecentlySwapped = entries.some((e) => (state.recentlySwappedEntryIds || []).includes(e.id));
  const swappedClass = isRecentlySwapped ? "tt-entry-swapped" : "";

  const durMin = toMin(first.end_time) - toMin(first.start_time);
  const durLabel = durMin > 60 ? ` (${durMin}m)` : "";

  const entryIdsJson = encodeURIComponent(JSON.stringify(entries.map((e) => e.id)));

  return `
    <div class="tt-entry consolidated-elective ${clashClass} ${selectedClass} ${swappedClass}"
         data-entry-id="${first.id}"
         draggable="true"
         ondragstart="handleDragStart(event, '${first.id}')"
         ondragend="handleDragEnd(event)"
         onclick="if (Date.now() < window.suppressClickUntil) return; event.stopPropagation(); window.openElectiveDetailsModal('${entryIdsJson}')"
         title="Click to view all MDM tracks, or drag to swap/reschedule">
      <div class="tt-entry-header">
        <span class="tt-entry-sub" style="color: #6d28d9; font-weight: 700;">
          <span class="tt-sub-full">📖 ${title} <span class="badge" style="background:#ede9fe; color:#6d28d9; font-size:9px; font-weight:700; margin-left:3px;">Theory</span></span>
          <span class="tt-sub-short">📖 ${subShort}</span>
        </span>
        <div style="display:inline-flex; align-items:center; gap:3px;">
          ${hasClash ? `<button type="button" class="tt-clash-badge-btn" title="Click to auto-fix this clash" onclick="event.stopPropagation(); window.handleFixSingleEntry('${first.id}', 'fix_this')">⚠️ Fix</button>` : ""}
          <span class="tt-drag-handle" title="Drag to reschedule">⠿</span>
          <button type="button" class="tt-quick-del-btn" title="Delete this MDM slot"
                  onclick="event.stopPropagation(); window.quickDeleteElectiveEntries('${entryIdsJson}', '${title.replace(/'/g, "\\'")}')">✕</button>
        </div>
      </div>
      <div class="tt-entry-fac" style="color: #5b21b6; font-size: 11px;">
        <span class="tt-fac-full">👨‍🏫 ${facNames || "Multiple Assigned Faculty"}</span>
        <span class="tt-fac-short">👨‍🏫 ${facShort}</span>
      </div>
      <div class="tt-entry-meta">
        <span class="tt-entry-room" title="Allocated Classrooms">
          <span class="tt-room-full">📍 Classrooms: ${roomNames || "Assigned Classrooms"} <strong style="color:#7c3aed;">🔒</strong></span>
          <span class="tt-room-short">📍 ${roomShort}🔒</span>
        </span>
        <div style="display:flex; gap:3px; align-items:center;">
          <span class="tt-elec-pill" style="background:#f3e8ff; color:#6b21a8; font-weight:700;">📖 ${trackCount} Theory Tracks</span>
        </div>
      </div>
      <div class="tt-entry-meta" style="margin-top:2px;">
        <span class="tt-entry-time">🕒 ${first.start_time} - ${first.end_time}${durLabel}</span>
        ${hasClash ? '<span class="badge badge-danger" style="font-size:9px;">CLASH</span>' : ""}
        <span style="font-size: 10px; color: #7c3aed; font-weight: 600; margin-left: auto;">Inside MDM ↗</span>
      </div>
      ${hasClash ? `
        <div class="tt-clash-actions">
          <button type="button" class="btn-clash-action btn-fix-this" title="Move THIS lecture somewhere with no clash" onclick="event.stopPropagation(); window.handleFixSingleEntry('${first.id}', 'fix_this')">
            🔧 Fix This
          </button>
          <button type="button" class="btn-clash-action btn-fix-other" title="Keep THIS lecture here and adjust other clashing lecture(s)" onclick="event.stopPropagation(); window.handleFixSingleEntry('${first.id}', 'fix_other')">
            🔄 Fix Other
          </button>
        </div>
      ` : ""}
    </div>
  `;
}

window.openElectiveDetailsForEntry = function (entryId) {
  const allEntries = (state.timetable && state.timetable.entries) || [];
  const target = allEntries.find((e) => e.id === entryId);
  if (!target) return;
  const pId = target.parent_subject_id || (target.subject_name && target.subject_name.toUpperCase().includes("MDM") ? "mdm" : target.subject_id);
  const siblings = allEntries.filter((e) =>
    e.day === target.day &&
    e.start_time === target.start_time &&
    e.end_time === target.end_time &&
    e.division_id === target.division_id &&
    Boolean(
      e.is_elective ||
      e.type === "Elective" ||
      e.parent_subject_id === pId ||
      e.subject_id === pId ||
      (e.subject_name && e.subject_name.toUpperCase().includes("MDM"))
    )
  );
  const ids = siblings.length ? siblings.map((e) => e.id) : [target.id];
  window.openElectiveDetailsModal(encodeURIComponent(JSON.stringify(ids)));
};

window.openElectiveDetailsModal = function (entryIdsJson) {
  let ids = [];
  try {
    ids = JSON.parse(decodeURIComponent(entryIdsJson));
  } catch (err) {
    console.error("Failed to parse elective entry ids:", err);
    return;
  }

  const allEntries = (state.timetable && state.timetable.entries) || [];
  const entries = allEntries.filter((e) => ids.includes(e.id));
  if (!entries.length) return;

  const first = entries[0];
  const parentSub = (state.subjects || []).find((s) => s.id === first.parent_subject_id || s.id === first.subject_id);
  let title = "MDM (Theory Lecture)";
  if (parentSub && parentSub.name) {
    title = parentSub.name.toUpperCase().includes("MDM") ? "MDM (Theory Lecture)" : `${parentSub.name} (Theory Lecture)`;
  }

  const divObj = (state.divisions || []).find((d) => d.id === first.division_id);
  const divName = divObj ? divObj.name : (first.division_name || first.division_id || "");

  const titleEl = document.getElementById("elec-detail-title");
  if (titleEl) titleEl.textContent = title;

  const divEl = document.getElementById("elec-detail-division");
  if (divEl) divEl.textContent = `Class Schedule: ${first.year_id || ""} ${divName} • MDM Theory Lecture across Classrooms`;

  const timeEl = document.getElementById("elec-detail-timing");
  if (timeEl) {
    const durMin = toMin(first.end_time) - toMin(first.start_time);
    timeEl.innerHTML = `<strong>Day:</strong> ${first.day} &nbsp;|&nbsp; <strong>Time:</strong> ${first.start_time} - ${first.end_time} (${durMin} mins) &nbsp;|&nbsp; <strong>Format:</strong> Theory Lecture &nbsp;|&nbsp; <strong>Parallel Tracks:</strong> ${entries.length}`;
  }

  const tracksContainer = document.getElementById("elec-detail-tracks-list");
  if (tracksContainer) {
    tracksContainer.innerHTML = entries.map((e, idx) => {
      let subSubjectName = e.elective_group_name || "";
      if (!subSubjectName && e.subject_name) {
        if (e.subject_name.includes("(") && e.subject_name.includes(")")) {
          subSubjectName = e.subject_name.split("(")[1].split(")")[0].trim();
        } else {
          subSubjectName = e.subject_name;
        }
      }
      if (!subSubjectName || subSubjectName.toUpperCase() === "MDM") {
        subSubjectName = `Track ${idx + 1}`;
      }
      const fac = e.faculty_name || "Faculty Assigned";
      const room = e.fixed_room_name || e.room_name || "Room Assigned";
      const cap = e.student_capacity || 35;
      return `
        <div class="elec-track-card" style="background:#f8fafc; border:1px solid #cbd5e1; border-left:4px solid #7c3aed; border-radius:8px; padding:12px 14px; margin-bottom:8px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <span class="elec-track-name" style="font-size:14px; color:#1e1b4b; font-weight:700;">
              📖 ${subSubjectName}
            </span>
            <span class="badge" style="background:#ede9fe; color:#6d28d9; font-size:11px; padding:3px 8px; font-weight:600; border-radius:12px;">
              👥 ${cap} Students
            </span>
          </div>
          <div class="elec-track-meta" style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:12px; color:#334155;">
            <div><strong>📍 Classroom:</strong> <span style="color:#7c3aed; font-weight:700;">${room}</span> <strong style="color:#7c3aed;">🔒</strong></div>
            <div><strong>👨‍🏫 Faculty:</strong> <span style="font-weight:600; color:#0f172a;">${fac}</span></div>
            <div><strong>📖 Format:</strong> <span style="font-weight:700; color:#0f172a;">Theory Lecture (60m)</span></div>
            <div><strong>🕒 Time:</strong> ${e.day} ${e.start_time}–${e.end_time}</div>
          </div>
        </div>
      `;
    }).join("");
  }

  const modal = document.getElementById("modal-elective-details");
  if (modal) modal.classList.remove("hidden");
};

window.quickDeleteElectiveEntries = async function (entryIdsJson, title) {
  let ids = [];
  try {
    ids = JSON.parse(decodeURIComponent(entryIdsJson));
  } catch (err) {
    return;
  }
  if (!confirm(`Are you sure you want to remove the entire elective session "${title}" (${ids.length} parallel tracks)?`)) {
    return;
  }
  try {
    for (const id of ids) {
      await fetch(`/api/timetable/entry/${id}`, { method: "DELETE" });
    }
    showBanner(`Removed elective session "${title}".`, "success");
    await refreshAllData();
  } catch (err) {
    showBanner("Failed to delete elective session: " + err.message, "danger");
  }
};

// -------------------------------------------------------------
// Double-Click Slot Selection & Action Handlers
// -------------------------------------------------------------
window.handleSlotDblClick = function (e, entryId) {
  e.preventDefault();
  e.stopPropagation();

  if (state.selectedEntryId === entryId) {
    openEditLectureModal(entryId);
    return;
  }

  if (window.deselectCurrentSlot) window.deselectCurrentSlot();

  const entryEl = document.querySelector(`.tt-entry[data-entry-id="${entryId}"]`);
  if (!entryEl) return;

  entryEl.classList.add("is-selected");
  entryEl.setAttribute("draggable", "true");
  state.selectedEntryId = entryId;

  const entry = (state.timetable.entries || []).find((x) => x.id === entryId);
  const bar = document.getElementById("tt-selected-slot-bar");
  const titleEl = document.getElementById("tt-selected-slot-title");
  if (bar && titleEl && entry) {
    titleEl.textContent = `${entry.subject_name || 'Lecture'} (${entry.faculty_name || 'Faculty'}) • ${entry.day} ${entry.start_time}`;
    bar.classList.remove("hidden");
  }
};

window.handleEmptyCellDblClick = function (e, day, start, end, divId) {
  e.preventDefault();
  e.stopPropagation();

  const daySelect = document.getElementById("manual-day");
  const startInput = document.getElementById("manual-start");
  const endInput = document.getElementById("manual-end");
  const divSelect = document.getElementById("manual-division");

  if (daySelect && day) daySelect.value = day;
  if (startInput && start) startInput.value = start;
  if (endInput && end) endInput.value = end;
  if (divSelect && divId) divSelect.value = divId;

  const modal = document.getElementById("modal-manual-add");
  if (modal) modal.classList.add("active");
};

// -------------------------------------------------------------
// Native Drag & Drop Handlers for Timetable Rescheduling
// -------------------------------------------------------------
window.handleDragStart = function (e, entryId) {
  e.stopPropagation();
  state.draggedEntryId = entryId;
  e.dataTransfer.setData("text/plain", entryId);
  e.dataTransfer.effectAllowed = "move";
  document.body.classList.add("is-dragging-entry");

  setTimeout(() => {
    const el = document.querySelector(`.tt-entry[data-entry-id="${entryId}"]`);
    if (el) el.classList.add("dragging");
  }, 0);
};

window.handleDragEnd = function (e) {
  document.body.classList.remove("is-dragging-entry");
  const draggingEl = document.querySelector(".tt-entry.dragging");
  if (draggingEl) draggingEl.classList.remove("dragging");
  document.querySelectorAll(".tt-cell.drag-over, .tt-slot-bg.drag-over, .tt-slot-cell.drag-over").forEach((c) => c.classList.remove("drag-over"));
  state.draggedEntryId = null;
};

window.handleCellDragOver = function (e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = "move";
  const cell = e.currentTarget;
  if (cell && !cell.classList.contains("drag-over")) {
    cell.classList.add("drag-over");
  }
};

window.handleCellDragLeave = function (e) {
  const cell = e.currentTarget;
  if (cell) {
    cell.classList.remove("drag-over");
  }
};

window.handleCellDrop = async function (e, targetDay, targetStart, targetEnd, targetDivId) {
  e.preventDefault();
  e.stopPropagation();
  document.body.classList.remove("is-dragging-entry");
  const cell = e.currentTarget;
  if (cell) cell.classList.remove("drag-over");

  const entryId = e.dataTransfer.getData("text/plain") || state.draggedEntryId;
  if (!entryId) return;

  const entry = (state.timetable.entries || []).find((x) => x.id === entryId);
  if (!entry) return;

  // If dropped in the same slot, day, and division, do nothing
  if (entry.day === targetDay && entry.start_time === targetStart && (!targetDivId || targetDivId === entry.division_id)) {
    return;
  }

  const toMin = (t) => {
    const [h, m] = t.split(":").map(Number);
    return h * 60 + m;
  };
  const toTime = (m) => {
    const hh = String(Math.floor(m / 60)).padStart(2, "0");
    const mm = String(m % 60).padStart(2, "0");
    return `${hh}:${mm}`;
  };

  const origDuration = toMin(entry.end_time) - toMin(entry.start_time);
  const newStartMin = toMin(targetStart);
  const newEndMin = newStartMin + (origDuration > 0 ? origDuration : 60);
  const newEnd = toTime(newEndMin);

  // Check if overlaps any break
  const breaks = state.settings.breaks || [];
  const overlapsBreak = breaks.some((b) => intervalsOverlapStr(targetStart, newEnd, b.start, b.end));
  if (overlapsBreak) {
    showBanner(`Cannot move lecture: ${targetStart} - ${newEnd} intersects a scheduled break or lunch interval.`, "danger");
    return;
  }

  // Check if exceeds day_end_time
  const dayEndMin = toMin(state.settings.day_end_time || "17:00");
  if (newEndMin > dayEndMin) {
    showBanner(`Cannot move lecture: End time ${newEnd} exceeds institutional day end time (${state.settings.day_end_time}).`, "danger");
    return;
  }

  // Check if target slot has existing entry to SWAP with
  const existingEntriesInTarget = (state.timetable.entries || []).filter((e) => {
    return e.day === targetDay &&
           (e.start_time === targetStart || (e.start_time <= targetStart && e.end_time > targetStart)) &&
           (!targetDivId || e.division_id === targetDivId) &&
           e.id !== entryId;
  });

  const swapPayload = {
    source_entry_id: entryId,
    target_entry_id: existingEntriesInTarget.length > 0 ? existingEntriesInTarget[0].id : null,
    target_day: targetDay,
    target_start_time: targetStart,
    target_division_id: targetDivId,
  };

  try {
    const res = await fetch("/api/timetable/swap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(swapPayload),
    });

    const data = await res.json();

    if (res.ok && data.success) {
      state.recentlySwappedEntryIds = [entryId];
      if (swapPayload.target_entry_id) {
        state.recentlySwappedEntryIds.push(swapPayload.target_entry_id);
      }
      setTimeout(() => {
        state.recentlySwappedEntryIds = [];
        document.querySelectorAll(".tt-entry.tt-entry-swapped").forEach((el) => {
          el.classList.remove("tt-entry-swapped");
        });
      }, 1200);

      if (data.has_clash) {
        showBanner(`${data.message} ⚠️ Warning: Conflict detected in new arrangement. Hover on cards to auto-fix.`, "warning");
      } else {
        showBanner(data.message, "success");
      }
      if (window.deselectCurrentSlot) window.deselectCurrentSlot();
      await refreshAllData();
      return;
    }

    if (!res.ok) {
      showBanner(data.error || data.message || "Failed to swap/move lecture.", "danger");
      return;
    }
  } catch (err) {
    console.error(err);
    showBanner("Network error while swapping/moving lecture.", "danger");
  }
};

window.handleFixSingleEntry = async function (entryId, mode) {
  try {
    const res = await fetch("/api/timetable/fix-entry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entry_id: entryId, mode: mode || "fix_this" }),
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showBanner(data.message, data.is_conflict_free ? "success" : "info");
      await refreshAllData();
    } else {
      showBanner(data.error || "Could not automatically resolve this clash.", "warning");
    }
  } catch (err) {
    console.error("Fix single entry error:", err);
    showBanner("Failed to fix clash due to network/server error.", "danger");
  }
};

function intervalsOverlapStr(s1, e1, s2, e2) {
  const toMin = (t) => {
    const p = t.split(":");
    return parseInt(p[0]) * 60 + parseInt(p[1]);
  };
  return Math.max(toMin(s1), toMin(s2)) < Math.min(toMin(e1), toMin(e2));
}

function handleCellClick(day, start, end, divId, yearId) {
  // If clicked directly on the cell (not on an entry inside it), open Add Lecture pre-filled
  openAddLectureModal({ day, start, end, division_id: divId, year_id: yearId });
}

// =============================================================
// Dedicated Timetable Export Engine (High-Resolution PNG & Landscape PDF)
// =============================================================

async function exportTimetable(format = "png") {
  const masterTable = document.getElementById("timetable-master-table");
  if (!masterTable) {
    showBanner("No timetable table available to export.", "warning");
    return;
  }

  // Ensure libraries are loaded
  if (typeof html2canvas === "undefined") {
    showBanner("Export library (html2canvas) is still initializing. Please wait a moment...", "warning");
    return;
  }
  if (format === "pdf" && typeof window.jspdf === "undefined" && typeof window.jsPDF === "undefined") {
    showBanner("Export library (jsPDF) is still initializing. Please wait a moment...", "warning");
    return;
  }

  const filters = state.filters || { year: "ALL", division: "ALL", faculty: "ALL", room: "ALL", day: "ALL" };

  // 1. Prepare Title & Metadata based on filters
  let viewTitle = "ALL YEARS – COMPLETE DEPARTMENT TIMETABLE";
  let viewSubtitle = "Academic Schedule • All Academic Years (FY · SY · TY · BE)";
  let fileSlug = "Timetable_All_Years";

  if (filters.faculty !== "ALL") {
    const facObj = (state.faculty || []).find((f) => f.id === filters.faculty);
    const facName = facObj ? facObj.name : "Faculty";
    viewTitle = `CMPN DEPARTMENT — FACULTY SCHEDULE: ${facName}`;
    viewSubtitle = `Faculty Member: ${facName} • Cross-Year Timetable`;
    fileSlug = `Timetable_Faculty_${facName.replace(/\s+/g, "_")}`;
  } else if (filters.room !== "ALL") {
    const rmObj = (state.rooms || []).find((r) => r.id === filters.room);
    const rmName = rmObj ? rmObj.name : "Room";
    const rmType = rmObj ? rmObj.type : "Classroom/Lab";
    viewTitle = `CMPN DEPARTMENT — ROOM OCCUPANCY: ${rmName}`;
    viewSubtitle = `Venue: ${rmName} (${rmType}) • Department-Wide Schedule`;
    fileSlug = `Timetable_Room_${rmName.replace(/\s+/g, "_")}`;
  } else if (filters.year !== "ALL") {
    if (filters.division !== "ALL") {
      const divObj = (state.divisions || []).find((d) => d.id === filters.division);
      const divName = divObj ? divObj.name : filters.division;
      viewTitle = `CMPN DEPARTMENT — ${filters.year} DIVISION ${divName}`;
      viewSubtitle = `Academic Schedule • Year: ${filters.year} • Division: ${divName}`;
      fileSlug = `Timetable_${filters.year}_Div_${divName.replace(/\s+/g, "_")}`;
    } else {
      viewTitle = `CMPN DEPARTMENT — ${filters.year} ALL DIVISIONS`;
      viewSubtitle = `Academic Schedule • Year: ${filters.year} • All Divisions Schedule`;
      fileSlug = `Timetable_${filters.year}_All_Divisions`;
    }
  } else if (filters.division !== "ALL") {
    const divObj = (state.divisions || []).find((d) => d.id === filters.division);
    const divName = divObj ? divObj.name : filters.division;
    viewTitle = `CMPN DEPARTMENT — DIVISION ${divName}`;
    viewSubtitle = `Academic Schedule • Division: ${divName}`;
    fileSlug = `Timetable_Div_${divName.replace(/\s+/g, "_")}`;
  }

  if (filters.day !== "ALL") {
    viewSubtitle += ` • Day: ${filters.day}`;
    fileSlug += `_${filters.day}`;
  }

  showBanner(`Generating high-resolution ${format.toUpperCase()} export...`, "info");

  // 2. Build Dedicated Offscreen Full-Size Export Container
  const exportContainer = document.createElement("div");
  exportContainer.className = "tt-export-isolated-container";
  exportContainer.id = "tt-export-isolated-container";
  exportContainer.style.position = "absolute";
  exportContainer.style.left = "-99999px";
  exportContainer.style.top = "0";
  exportContainer.style.background = "#ffffff";
  exportContainer.style.width = "max-content";
  exportContainer.style.padding = "24px";
  exportContainer.style.boxSizing = "border-box";

  // Institutional Header
  const headerHtml = `
    <div style="text-align: center; margin-bottom: 20px; border-bottom: 2px solid #2563eb; padding-bottom: 14px;">
      <div style="font-size: 11px; font-weight: 700; color: #64748b; letter-spacing: 1px; text-transform: uppercase;">
        Thadomal Shahani Engineering College • Department of Computer Engineering
      </div>
      <h1 style="font-size: 22px; font-weight: 800; color: #1e3a8a; margin: 6px 0; text-transform: uppercase; letter-spacing: 0.5px;">
        ${viewTitle}
      </h1>
      <h2 style="font-size: 13px; font-weight: 600; color: #2563eb; margin: 4px 0;">
        ${viewSubtitle}
      </h2>
      <div style="font-size: 11px; color: #64748b; margin-top: 6px;">
        Generated on: ${new Date().toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'short', day: 'numeric' })} at ${new Date().toLocaleTimeString()}
      </div>
    </div>
  `;

  // Clone the master table
  const cloneTable = masterTable.cloneNode(true);
  cloneTable.style.position = "relative";
  cloneTable.style.width = "max-content";
  cloneTable.style.minWidth = "100%";
  cloneTable.style.boxShadow = "none";

  // Remove sticky positioning in the clone so html2canvas renders all elements without viewport clipping
  cloneTable.querySelectorAll("th, td, .tt-day-cell, .tt-class-cell").forEach((el) => {
    el.style.position = "static";
    el.style.boxShadow = "none";
  });

  // Remove interactive UI buttons/handles
  cloneTable.querySelectorAll(".tt-drag-handle, .tt-quick-del-btn, .tt-clash-actions, .empty-plus, .tt-clash-badge-btn").forEach((el) => {
    el.remove();
  });

  // Ensure entries inside clone have no hover artifacts
  cloneTable.querySelectorAll(".tt-entry").forEach((entryEl) => {
    entryEl.style.boxShadow = "none";
    entryEl.style.cursor = "default";
    entryEl.removeAttribute("draggable");
  });

  // Footer
  const footerHtml = `
    <div style="margin-top: 18px; display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: 10px;">
      <span><strong>Schedula CMPN</strong> • Intelligent Multi-Year Timetable Engine</span>
      <span>Color Legend: <span style="color:#2563eb; font-weight:600;">■ Theory</span> &nbsp;•&nbsp; <span style="color:#059669; font-weight:600;">■ Practical (Batches)</span> &nbsp;•&nbsp; <span style="color:#7c3aed; font-weight:600;">■ Elective / MDM</span></span>
      <span>Status: <strong>Approved Official Academic Timetable</strong></span>
    </div>
  `;

  const cloneBoard = cloneTable;
  if (format === "png") {
    // For photo export, remove header and footer completely
    exportContainer.innerHTML = "";
    exportContainer.appendChild(cloneBoard);
    exportContainer.style.padding = "0px";
  } else {
    exportContainer.innerHTML = headerHtml;
    exportContainer.appendChild(cloneBoard);
    exportContainer.insertAdjacentHTML("beforeend", footerHtml);
  }

  // Watermark overlay of Schedula at bottom right corner (proper big grey overlay)
  const watermarkEl = document.createElement("div");
  watermarkEl.className = "tt-export-watermark";
  watermarkEl.textContent = "SCHEDULA";
  watermarkEl.style.cssText = "position:absolute; right:28px; bottom:20px; font-size:64px; font-weight:900; letter-spacing:6px; color:rgba(100,116,139,0.28); text-transform:uppercase; pointer-events:none; user-select:none; z-index:9999; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;";
  exportContainer.appendChild(watermarkEl);

  document.body.appendChild(exportContainer);

  try {
    // Allow DOM reflow and font metrics to settle
    await new Promise((resolve) => setTimeout(resolve, 250));

    // Capture using html2canvas with 2x retina sharpness
    const canvas = await html2canvas(exportContainer, {
      scale: 2,
      useCORS: true,
      logging: false,
      backgroundColor: "#ffffff",
      windowWidth: exportContainer.scrollWidth + 100,
      windowHeight: exportContainer.scrollHeight + 100,
    });

    // Stamp watermark directly on canvas bottom right corner for crisp PNG & PDF rendering
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.save();
      const fontSize = Math.max(54, Math.round(canvas.width * 0.035));
      ctx.font = `900 ${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;
      ctx.fillStyle = "rgba(100, 116, 139, 0.28)";
      ctx.textAlign = "right";
      ctx.textBaseline = "bottom";
      ctx.fillText("SCHEDULA", canvas.width - Math.round(fontSize * 0.5), canvas.height - Math.round(fontSize * 0.35));
      ctx.restore();
    }

    if (format === "png") {
      // Export PNG
      const link = document.createElement("a");
      link.download = `${fileSlug}_${new Date().toISOString().slice(0, 10)}.png`;
      link.href = canvas.toDataURL("image/png");
      link.click();
      showBanner("Timetable successfully exported as high-resolution PNG image!", "success");
    } else if (format === "pdf") {
      // Export Landscape PDF
      const jsPDFClass = (window.jspdf && window.jspdf.jsPDF) || window.jsPDF;
      if (!jsPDFClass) {
        throw new Error("jsPDF library not available");
      }

      const imgWidth = canvas.width;
      const imgHeight = canvas.height;

      // Use A3 Landscape (420 x 297 mm) for complete departmental timetables, or A4 Landscape
      const isWide = imgWidth > 2000;
      const pdfFormat = isWide ? "a3" : "a4";

      const pdf = new jsPDFClass({
        orientation: "landscape",
        unit: "mm",
        format: pdfFormat,
      });

      const pageWidth = pdf.internal.pageSize.getWidth();
      const pageHeight = pdf.internal.pageSize.getHeight();
      const margin = 10;
      const availWidth = pageWidth - margin * 2;
      const availHeight = pageHeight - margin * 2;

      const scale = availWidth / imgWidth;
      const renderedHeight = imgHeight * scale;

      const imgData = canvas.toDataURL("image/png");

      if (renderedHeight <= availHeight) {
        // Fits on a single landscape page
        pdf.addImage(imgData, "PNG", margin, margin, availWidth, renderedHeight, undefined, "FAST");
      } else {
        // Multi-page slicing preserving alignment
        let heightLeft = imgHeight;
        let sourceY = 0;
        const sliceCanvas = document.createElement("canvas");
        sliceCanvas.width = imgWidth;
        const sliceHeightPx = availHeight / scale;
        sliceCanvas.height = sliceHeightPx;
        const sliceCtx = sliceCanvas.getContext("2d");

        while (heightLeft > 0) {
          sliceCtx.fillStyle = "#ffffff";
          sliceCtx.fillRect(0, 0, imgWidth, sliceHeightPx);
          const takeHeight = Math.min(sliceHeightPx, heightLeft);
          sliceCtx.drawImage(canvas, 0, sourceY, imgWidth, takeHeight, 0, 0, imgWidth, takeHeight);
          const sliceData = sliceCanvas.toDataURL("image/png");
          pdf.addImage(sliceData, "PNG", margin, margin, availWidth, takeHeight * scale, undefined, "FAST");

          heightLeft -= sliceHeightPx;
          sourceY += sliceHeightPx;
          if (heightLeft > 0) {
            pdf.addPage(pdfFormat, "landscape");
          }
        }
      }

      pdf.save(`${fileSlug}_${new Date().toISOString().slice(0, 10)}.pdf`);
      showBanner("Timetable successfully exported as Landscape PDF document!", "success");
    }
  } catch (err) {
    console.error("Export error:", err);
    showBanner(`Failed to export timetable: ${err.message}`, "danger");
  } finally {
    if (exportContainer && exportContainer.parentNode) {
      exportContainer.parentNode.removeChild(exportContainer);
    }
  }
}

// -------------------------------------------------------------
// Manual Timetable Editing with Clash Highlight & Suggestions
// -------------------------------------------------------------
function getSubjectsForDivision(divId, yearId) {
  const div = (state.divisions || []).find((d) => d.id === divId);
  const effYear = (div && div.year_id) || yearId || (state.selectedYear && state.selectedYear !== "ALL" ? state.selectedYear : null);
  const assignments = state.assignments || [];

  const matched = (state.subjects || []).filter((s) => {
    // Check year matching
    if (effYear && s.year_id && s.year_id !== effYear) return false;

    // 1. Explicitly mapped in subject.division_ids
    if (Array.isArray(s.division_ids) && s.division_ids.length > 0) {
      if (divId) return s.division_ids.includes(divId);
      return true;
    }

    // 2. Explicitly mapped in faculty_assignments
    if (divId && assignments.some((a) => a.subject_id === s.id && a.division_id === divId)) {
      return true;
    }

    // 3. If no division_ids specified on subject, applicable to all divisions of that year
    if (!s.division_ids || s.division_ids.length === 0) {
      return true;
    }

    return false;
  });

  // If division is set but matched is empty, fallback to year subjects so list is not broken
  if (matched.length === 0 && effYear) {
    return (state.subjects || []).filter((s) => s.year_id === effYear);
  }
  return matched;
}

function getAssignedFacultyForDivisionAndSubject(divId, subId, batchId = null) {
  const assignments = state.assignments || [];
  if (batchId) {
    const bAsgn = assignments.find((a) => a.subject_id === subId && a.division_id === divId && a.batch_id === batchId);
    if (bAsgn && bAsgn.faculty_id) return bAsgn.faculty_id;
  }
  const dAsgn = assignments.find((a) => a.subject_id === subId && a.division_id === divId);
  if (dAsgn && dAsgn.faculty_id) return dAsgn.faculty_id;

  const sub = (state.subjects || []).find((s) => s.id === subId);
  if (sub && Array.isArray(sub.eligible_faculty_ids) && sub.eligible_faculty_ids.length > 0) {
    return sub.eligible_faculty_ids[0];
  }
  return null;
}

function getSuggestedRoomForSubjectAndDivision(sub, divId) {
  const rooms = state.rooms || [];
  const div = (state.divisions || []).find((d) => d.id === divId);
  if (!sub) return rooms.length ? rooms[0].id : "";

  if (sub.type === "Practical" || sub.required_room_type === "Laboratory") {
    const lab = rooms.find((r) => r.type === "Laboratory");
    if (lab) return lab.id;
  } else {
    if (div && div.preferred_room_id) {
      const pr = rooms.find((r) => r.id === div.preferred_room_id);
      if (pr) return pr.id;
    }
    const cr = rooms.find((r) => r.type === "Classroom");
    if (cr) return cr.id;
  }
  return rooms.length ? rooms[0].id : "";
}

window.openEditLectureModal = function (entryId) {
  const entry = (state.timetable.entries || []).find((e) => e.id === entryId);
  if (!entry) return;

  document.getElementById("modal-edit-lecture-title").textContent = "Edit / Move Lecture";
  document.getElementById("edit-entry-id").value = entry.id;
  document.getElementById("edit-is-new").value = "false";
  document.getElementById("btn-delete-entry").style.display = "inline-flex";

  // Hide any previous clash errors
  document.getElementById("edit-clash-box").classList.add("hidden");
  document.getElementById("edit-suggestions-container").classList.add("hidden");

  // Populate Year, Division, Batch
  document.getElementById("edit-year").value = entry.year_id;
  updateEditDivisions(entry.year_id, entry.division_id);
  updateEditBatches(entry.division_id, entry.batch_id);

  // Populate Faculty & Room
  updateEditFacultyAndRooms(entry.faculty_id, entry.room_id);

  // Populate Subject specifically for this division
  updateEditSubjects(entry.year_id, entry.division_id, entry.subject_id);
  const newBox = document.getElementById("edit-new-subject-box");
  if (newBox) newBox.classList.add("hidden");

  // Populate Day & Time
  document.getElementById("edit-day").value = entry.day;
  document.getElementById("edit-start-time").value = entry.start_time;
  document.getElementById("edit-end-time").value = entry.end_time;

  openModal("modal-edit-lecture");
};

function openAddLectureModal(prefill = {}) {
  document.getElementById("modal-edit-lecture-title").textContent = "+ Add Schedule";
  document.getElementById("edit-entry-id").value = "";
  document.getElementById("edit-is-new").value = "true";
  document.getElementById("btn-delete-entry").style.display = "none";

  document.getElementById("edit-clash-box").classList.add("hidden");
  document.getElementById("edit-suggestions-container").classList.add("hidden");

  // Determine target year & division
  let year = prefill.year_id;
  let targetDivId = prefill.division_id;
  if (!year && targetDivId) {
    const divObj = (state.divisions || []).find((d) => d.id === targetDivId);
    if (divObj) year = divObj.year_id;
  }
  if (!year) {
    year = (state.selectedYear && state.selectedYear !== "ALL") ? state.selectedYear : "TY";
  }
  document.getElementById("edit-year").value = year;

  // Populate divisions for this year, selecting targetDivId if matching
  updateEditDivisions(year, targetDivId);
  const effectiveDivId = document.getElementById("edit-division").value;
  updateEditBatches(effectiveDivId, prefill.batch_id);

  // Populate faculty and rooms list
  updateEditFacultyAndRooms();

  // Populate subjects specifically assigned to this division
  updateEditSubjects(year, effectiveDivId);
  syncEditSubjectSelection();

  document.getElementById("edit-day").value = prefill.day || "Monday";
  document.getElementById("edit-start-time").value = prefill.start || "09:15";
  document.getElementById("edit-end-time").value = prefill.end || "10:15";

  // Re-sync end time based on the selected subject's duration if start was provided
  const curSubId = document.getElementById("edit-subject").value;
  const curSub = (state.subjects || []).find((s) => s.id === curSubId);
  if (curSub && curSub.duration_minutes && prefill.start) {
    const [h, m] = prefill.start.split(":").map(Number);
    if (!isNaN(h) && !isNaN(m)) {
      const totalMin = h * 60 + m + curSub.duration_minutes;
      const eh = String(Math.floor(totalMin / 60)).padStart(2, "0");
      const em = String(totalMin % 60).padStart(2, "0");
      document.getElementById("edit-end-time").value = `${eh}:${em}`;
    }
  }

  openModal("modal-edit-lecture");
}

function updateEditDivisions(yearId, selectedDivId) {
  const divSelect = document.getElementById("edit-division");
  if (!divSelect) return;
  const divs = state.divisions.filter((d) => d.year_id === yearId);
  divSelect.innerHTML = divs.map((d) => `<option value="${d.id}">${d.name}</option>`).join("");
  if (selectedDivId && divs.some((d) => d.id === selectedDivId)) {
    divSelect.value = selectedDivId;
  }
}

function updateEditBatches(divId, selectedBatchId) {
  const batchSelect = document.getElementById("edit-batch");
  if (!batchSelect) return;
  const batches = state.batches.filter((b) => b.division_id === divId);
  batchSelect.innerHTML =
    `<option value="">None (Full Division)</option>` +
    batches.map((b) => `<option value="${b.id}">${b.name}</option>`).join("");
  if (selectedBatchId && batches.some((b) => b.id === selectedBatchId)) {
    batchSelect.value = selectedBatchId;
  }
}

function updateEditSubjects(yearId, divId, selectedSubId) {
  const subSelect = document.getElementById("edit-subject");
  if (!subSelect) return;
  const subs = getSubjectsForDivision(divId, yearId);
  
  let optionsHtml = subs
    .map((s) => {
      const dur = s.duration_minutes ? ` (${s.duration_minutes}m)` : "";
      const code = s.code ? `[${s.code}] ` : "";
      return `<option value="${s.id}">${code}${s.name} - ${s.type}${dur}</option>`;
    })
    .join("");

  optionsHtml += `<option value="__NEW__">➕ + Add New Subject...</option>`;
  subSelect.innerHTML = optionsHtml;

  if (selectedSubId && (subs.some((s) => s.id === selectedSubId) || selectedSubId === "__NEW__")) {
    subSelect.value = selectedSubId;
  } else if (subs.length > 0) {
    subSelect.value = subs[0].id;
  } else {
    subSelect.value = "__NEW__";
  }
}

function syncEditSubjectSelection() {
  const subSelect = document.getElementById("edit-subject");
  const newBox = document.getElementById("edit-new-subject-box");
  const divSelect = document.getElementById("edit-division");
  const batchSelect = document.getElementById("edit-batch");
  const facSelect = document.getElementById("edit-faculty");
  const roomSelect = document.getElementById("edit-room");
  if (!subSelect) return;

  const val = subSelect.value;
  if (val === "__NEW__") {
    if (newBox) newBox.classList.remove("hidden");
    return;
  }

  if (newBox) newBox.classList.add("hidden");
  const sub = (state.subjects || []).find((s) => s.id === val);
  if (!sub) return;

  const divId = divSelect ? divSelect.value : null;
  const batchId = batchSelect ? batchSelect.value : null;

  // Auto-map assigned faculty so user does not have to manual map again
  const assignedFacId = getAssignedFacultyForDivisionAndSubject(divId, sub.id, batchId);
  if (assignedFacId && facSelect) {
    facSelect.value = assignedFacId;
  }

  // Auto-map suggested room (Lab for practical, Classroom for theory)
  const suggestedRoomId = getSuggestedRoomForSubjectAndDivision(sub, divId);
  if (suggestedRoomId && roomSelect) {
    roomSelect.value = suggestedRoomId;
  }

  // Auto-sync duration to end time
  const startEl = document.getElementById("edit-start-time");
  const endEl = document.getElementById("edit-end-time");
  if (startEl && endEl && startEl.value && sub.duration_minutes) {
    const [h, m] = startEl.value.split(":").map(Number);
    if (!isNaN(h) && !isNaN(m)) {
      const totalMin = h * 60 + m + sub.duration_minutes;
      const eh = String(Math.floor(totalMin / 60)).padStart(2, "0");
      const em = String(totalMin % 60).padStart(2, "0");
      endEl.value = `${eh}:${em}`;
    }
  }
}

function updateEditFacultyAndRooms(selectedFacId, selectedRoomId) {
  const facSelect = document.getElementById("edit-faculty");
  if (facSelect) {
    facSelect.innerHTML = state.faculty
      .map((f) => `<option value="${f.id}">${f.name}</option>`)
      .join("");
    if (selectedFacId) facSelect.value = selectedFacId;
  }

  const roomSelect = document.getElementById("edit-room");
  if (roomSelect) {
    roomSelect.innerHTML = state.rooms
      .map((r) => `<option value="${r.id}">${r.name} (${r.type})</option>`)
      .join("");
    if (selectedRoomId) roomSelect.value = selectedRoomId;
  }
}

async function handleSaveLectureEdit(e) {
  e.preventDefault();

  const isNew = document.getElementById("edit-is-new").value === "true";
  const entryId = document.getElementById("edit-entry-id").value;

  let subId = document.getElementById("edit-subject").value;
  const divId = document.getElementById("edit-division").value;
  const yearId = document.getElementById("edit-year").value;
  const facId = document.getElementById("edit-faculty").value;

  // If user selected to create a new subject inline
  if (subId === "__NEW__") {
    const newName = (document.getElementById("edit-new-sub-name")?.value || "").trim();
    if (!newName) {
      showBanner("Please enter a name for the new subject.", "warning");
      return;
    }
    const newCode = (document.getElementById("edit-new-sub-code")?.value || "").trim();
    const newType = document.getElementById("edit-new-sub-type")?.value || "Theory";
    const dur = newType === "Practical" ? 120 : 60;
    const reqRoomType = newType === "Practical" ? "Laboratory" : "Classroom";

    try {
      const createRes = await fetch("/api/subjects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newName,
          code: newCode,
          year_id: yearId,
          division_ids: [divId],
          type: newType,
          weekly_lectures: newType === "Practical" ? 1 : 3,
          duration_minutes: dur,
          eligible_faculty_ids: facId ? [facId] : [],
          required_room_type: reqRoomType,
        }),
      });
      const createData = await createRes.json();
      if (!createRes.ok || !createData.subject) {
        showBanner(createData.error || "Failed to create new subject.", "danger");
        return;
      }
      state.subjects.push(createData.subject);
      subId = createData.subject.id;
    } catch (err) {
      showBanner("Error creating new subject on server.", "danger");
      return;
    }
  }

  const sub = state.subjects.find((s) => s.id === subId);
  const div = state.divisions.find((d) => d.id === divId);
  const batchId = document.getElementById("edit-batch").value || null;
  const batch = state.batches.find((b) => b.id === batchId);
  const fac = state.faculty.find((f) => f.id === facId);
  const roomId = document.getElementById("edit-room").value;
  const room = state.rooms.find((r) => r.id === roomId);

  const payload = {
    subject_id: subId,
    subject_name: sub ? sub.name : "",
    year_id: yearId,
    division_id: divId,
    division_name: div ? div.name : "",
    batch_id: batchId,
    batch_name: batch ? batch.name : null,
    faculty_id: facId,
    faculty_name: fac ? fac.name : "",
    room_id: roomId,
    room_name: room ? room.name : "",
    day: document.getElementById("edit-day").value,
    start_time: document.getElementById("edit-start-time").value,
    end_time: document.getElementById("edit-end-time").value,
    type: sub ? sub.type : "Theory",
  };

  const url = isNew ? "/api/timetable/entry" : `/api/timetable/entry/${entryId}`;
  const method = isNew ? "POST" : "PUT";

  try {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();

    if (!res.ok) {
      // Clash detected! Display prominent error & alternatives
      const clashBox = document.getElementById("edit-clash-box");
      const clashMsgList = document.getElementById("edit-clash-messages");
      const sugContainer = document.getElementById("edit-suggestions-container");
      const sugList = document.getElementById("edit-suggestions-list");

      clashBox.classList.remove("hidden");
      clashMsgList.innerHTML = (data.conflicts || [data.error || data.message])
        .map((m) => `<li>${m}</li>`)
        .join("");

      if (data.requires_override_confirmation || res.status === 409) {
        let overrideBtn = document.getElementById("btn-force-admin-override");
        if (!overrideBtn) {
          overrideBtn = document.createElement("button");
          overrideBtn.id = "btn-force-admin-override";
          overrideBtn.type = "button";
          overrideBtn.className = "btn btn-sm btn-danger";
          overrideBtn.style.marginTop = "8px";
          overrideBtn.style.fontWeight = "600";
          overrideBtn.style.display = "inline-flex";
          overrideBtn.style.alignItems = "center";
          overrideBtn.style.gap = "4px";
          overrideBtn.innerHTML = "⚠️ Force Save Schedule (Admin Manual Override)";
          clashBox.appendChild(overrideBtn);
        }
        overrideBtn.onclick = async () => {
          overrideBtn.disabled = true;
          overrideBtn.textContent = "Saving Override...";
          try {
            const ovRes = await fetch(url, {
              method,
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ ...payload, confirm_override: true })
            });
            const ovData = await ovRes.json();
            if (ovRes.ok) {
              closeModal("modal-edit-lecture");
              showBanner("Lecture saved via Admin Manual Override! Logged in audit history.", "warning");
              await refreshAllData();
            } else {
              showBanner(ovData.error || "Override failed.", "danger");
            }
          } catch (e) {
            console.error(e);
            showBanner("Override failed.", "danger");
          } finally {
            overrideBtn.disabled = false;
            overrideBtn.innerHTML = "⚠️ Force Save Schedule (Admin Manual Override)";
          }
        };
      }

      if (data.suggestions && data.suggestions.length > 0) {
        sugContainer.classList.remove("hidden");
        sugList.innerHTML = data.suggestions
          .map(
            (s) => `
          <button type="button" class="suggestion-pill" onclick="applySuggestion('${s.day}', '${s.start_time}', '${s.end_time}', '${s.faculty_id}', '${s.room_id}')">
            ✨ ${s.day} @ ${s.start_time}-${s.end_time} &bull; ${s.faculty_name} &bull; ${s.room_name}
          </button>
        `
          )
          .join("");
      } else {
        sugContainer.classList.add("hidden");
      }
      return;
    }

    // Success!
    closeModal("modal-edit-lecture");
    if (data.warnings && data.warnings.length > 0) {
      showBanner(`Saved with workload note: ${data.warnings.join("; ")}`, "warning");
    } else {
      showBanner(isNew ? "Lecture added successfully!" : "Lecture updated successfully!", "success");
    }
    await refreshAllData();
  } catch (err) {
    console.error("Save lecture error:", err);
    showBanner("Failed to communicate with backend.", "danger");
  }
}

window.applySuggestion = function (day, start, end, facId, roomId) {
  document.getElementById("edit-day").value = day;
  document.getElementById("edit-start-time").value = start;
  document.getElementById("edit-end-time").value = end;
  if (facId) document.getElementById("edit-faculty").value = facId;
  if (roomId) document.getElementById("edit-room").value = roomId;

  // Clear error alert
  document.getElementById("edit-clash-box").classList.add("hidden");
};

async function handleDeleteLecture() {
  const entryId = document.getElementById("edit-entry-id").value;
  if (!entryId) return;

  if (!confirm("Are you sure you want to remove this lecture from the timetable?")) {
    return;
  }

  try {
    const res = await fetch(`/api/timetable/entry/${entryId}`, { method: "DELETE" });
    if (res.ok) {
      closeModal("modal-edit-lecture");
      showBanner("Lecture removed from timetable.", "success");
      await refreshAllData();
    } else {
      const d = await res.json();
      alert(d.error || "Failed to delete lecture.");
    }
  } catch (e) {
    console.error(e);
  }
}

// -------------------------------------------------------------
// Faculty Management
// -------------------------------------------------------------
function renderFacultyTable() {
  const tbody = document.querySelector("#table-faculty tbody");
  tbody.innerHTML = state.faculty
    .map((fac) => {
      // Find subjects eligible for this faculty
      const eligibleSubs = state.subjects
        .filter((s) => s.eligible_faculty_ids && s.eligible_faculty_ids.includes(fac.id))
        .map((s) => `<span class="badge badge-primary">${s.name} (${s.year_id})</span>`)
        .join(" ");

      // Workload from timetable
      const scheduledLectures = (state.timetable.entries || []).filter(
        (e) => e.faculty_id === fac.id
      ).length;

      const isAvailable = fac.is_available !== false;
      const statusBtn = isAvailable
        ? `<button class="btn-status-present" onclick="toggleFacultyStatus('${fac.id}')" title="Click to mark as Absent">🟢 Present</button>`
        : `<button class="btn-status-absent" onclick="toggleFacultyStatus('${fac.id}')" title="Click to mark as Present">🔴 Absent</button>`;

      const floorBadge = fac.staff_room_floor_id
        ? `<span class="badge badge-info" title="Starting location for day's first lecture">🏢 ${fac.staff_room_floor_name || 'Assigned'}</span>`
        : `<span class="text-muted" style="font-size:12px;">None</span>`;

      return `
      <tr>
        <td><code>${fac.id}</code></td>
        <td><strong>${fac.name}</strong></td>
        <td>${floorBadge}</td>
        <td>${statusBtn}</td>
        <td>${eligibleSubs || '<span class="text-muted">None mapped</span>'}</td>
        <td><span class="badge badge-success">${scheduledLectures} lectures/week</span></td>
        <td>
          <button class="btn btn-sm btn-outline" onclick="openRenameFacultyModal('${fac.id}', '${fac.name}')">Edit</button>
          <button class="btn btn-sm btn-outline-danger" onclick="deleteFaculty('${fac.id}')">Delete</button>
        </td>
      </tr>
    `;
    })
    .join("");
}

window.toggleFacultyStatus = async function (id) {
  try {
    const res = await fetch(`/api/faculty/${id}/toggle-status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const data = await res.json();
    if (res.ok) {
      showBanner(data.message, "success");
      await refreshAllData();
    } else {
      showBanner(data.error || "Failed to toggle status.", "danger");
    }
  } catch (err) {
    console.error(err);
    showBanner("Failed to toggle faculty status.", "danger");
  }
};

window.openRenameFacultyModal = function (id, name) {
  const fac = state.faculty.find((f) => f.id === id);
  document.getElementById("fac-rename-id").value = id;
  document.getElementById("fac-rename-name").value = name;
  const floorSelect = document.getElementById("fac-rename-floor");
  if (floorSelect) {
    floorSelect.value = fac ? (fac.staff_room_floor_id || "") : "";
  }
  openModal("modal-rename-faculty");
};

window.deleteFaculty = async function (id, force = false) {
  const fac = state.faculty.find((f) => f.id === id);
  if (!force && !confirm(`Delete faculty member '${fac ? fac.name : id}'?`)) {
    return;
  }

  try {
    const res = await fetch(`/api/faculty/${id}${force ? "?force=true" : ""}`, {
      method: "DELETE",
    });
    const data = await res.json();

    if (!res.ok) {
      if (res.status === 409 && data.error === "ReferencedFaculty") {
        if (confirm(`${data.message}\n\nDo you want to FORCE delete this faculty?`)) {
          await deleteFaculty(id, true);
        }
      } else {
        alert(data.error || "Cannot delete faculty.");
      }
      return;
    }

    showBanner(data.message, "success");
    await refreshAllData();
  } catch (e) {
    console.error(e);
  }
};

// -------------------------------------------------------------
// Subjects & Teaching Assignments
// -------------------------------------------------------------
function renderSubjectsTable() {
  const tbody = document.querySelector("#table-subjects tbody");
  const filterYear = document.getElementById("subject-filter-year").value;
  const filtered =
    filterYear === "ALL"
      ? state.subjects
      : state.subjects.filter((s) => s.year_id === filterYear);

  tbody.innerHTML = filtered
    .map((s) => {
      const facNames = (s.eligible_faculty_ids || [])
        .map((fId) => {
          const f = state.faculty.find((fac) => fac.id === fId);
          return f ? f.name : fId;
        })
        .join(", ");

      const isElective = Boolean(s.is_elective || s.type === "Elective");
      const typeBadge = isElective
        ? `<span class="badge" style="background:#7c3aed; color:#fff;">Elective (MDM)</span>`
        : `<span class="badge ${s.type === 'Practical' ? 'badge-warning' : (s.type === 'Other' ? 'badge-info' : 'badge-primary')}">${s.type}</span>`;

      let scopeHtml = '<span class="badge badge-primary">Entire Division</span>';
      if (s.type === 'Practical' || s.lab_batch_required) {
        scopeHtml = '<span class="badge badge-warning">⚡ Auto Batches</span>';
      } else if (isElective && s.elective_groups && s.elective_groups.length) {
        scopeHtml = s.elective_groups.map(g =>
          `<div style="font-size:11px; margin-bottom:2px;"><span class="badge" style="background:#ede9fe; color:#6d28d9; border:1px solid #ddd6fe; font-weight:600;">${g.name}</span> → 📍<strong>${g.fixed_room_name || g.fixed_room_id || 'Room'}</strong></div>`
        ).join("");
      }

      let facDisplay = facNames || '<span class="text-muted">Assigned via Teaching Assignments</span>';
      if (isElective && s.elective_groups && s.elective_groups.length) {
        facDisplay = s.elective_groups.map(g =>
          `<div style="font-size:11px; margin-bottom:2px;"><strong style="color:#6d28d9;">${g.name}:</strong> 👨‍🏫 ${g.faculty_name || 'Not assigned'}</div>`
        ).join("");
      }

      return `
      <tr>
        <td><span class="badge badge-primary">${s.year_id}</span></td>
        <td><strong>${s.name}</strong>${s.code ? ` <span class="badge" style="background:#e2e8f0; color:#334155; font-size:10px;">${s.code}</span>` : ""}</td>
        <td>${typeBadge}</td>
        <td>${s.weekly_lectures} / wk</td>
        <td>${s.duration_minutes} min</td>
        <td><small>${facDisplay}</small></td>
        <td>${s.required_room_type}</td>
        <td>${scopeHtml}</td>
        <td>
          <button class="btn btn-sm btn-outline-primary" onclick="editSubject('${s.id}')" style="margin-right: 4px;">Edit</button>
          <button class="btn btn-sm btn-outline-danger" onclick="deleteSubject('${s.id}')">Delete</button>
        </td>
      </tr>
    `;
    })
    .join("");
}

window.editSubject = function (id) {
  const sub = state.subjects.find((s) => s.id === id);
  if (!sub) return;

  const titleEl = document.getElementById("modal-subject-title");
  if (titleEl) titleEl.textContent = "Edit Subject";

  document.getElementById("sub-id").value = sub.id;
  document.getElementById("sub-year").value = sub.year_id;
  document.getElementById("sub-type").value = sub.type || "Theory";
  document.getElementById("sub-name").value = sub.name || "";
  document.getElementById("sub-code").value = sub.code || "";
  document.getElementById("sub-weekly-lec").value = sub.weekly_lectures || 3;
  document.getElementById("sub-duration").value = String(sub.duration_minutes || 60);
  document.getElementById("sub-room-type").value = sub.required_room_type || "Classroom";

  const isElectiveCb = document.getElementById("sub-is-elective");
  if (isElectiveCb) {
    isElectiveCb.checked = Boolean(sub.is_elective || sub.type === "Elective");
  }
  toggleElectiveGroupsContainer();
  renderElectiveGroups(sub.elective_groups || []);

  const hint = document.getElementById("sub-type-hint");
  if (hint) {
    if (sub.type === "Practical") {
      hint.textContent = "⚡ Practical sessions automatically divide into batches in Laboratories.";
    } else if (sub.type === "Elective" || sub.is_elective) {
      hint.textContent = "📚 MDM Elective with fixed room reservation per elective group.";
    } else if (sub.type === "Other") {
      hint.textContent = "ℹ️ Other sessions (Tutorials, Seminars, Projects) for the whole division.";
    } else {
      hint.textContent = "📘 Theory sessions for the whole division in Classrooms.";
    }
  }

  // Populate division checkboxes
  const divCheckboxes = document.getElementById("sub-divisions-checkboxes");
  const yearDivs = state.divisions.filter((d) => d.year_id === sub.year_id);
  const targetDivs = yearDivs.length ? yearDivs : state.divisions;
  divCheckboxes.innerHTML = targetDivs
    .map(
      (d) => `
    <label><input type="checkbox" value="${d.id}" ${(sub.division_ids || []).includes(d.id) ? "checked" : ""}> ${d.year_id} ${d.name}</label>
  `
    )
    .join("");

  // Render Faculty Multi-Select
  if (window.renderFacultyMultiSelect) {
    window.renderFacultyMultiSelect(sub.eligible_faculty_ids || []);
  }

  openModal("modal-subject");
};

// -------------------------------------------------------------
// MDM Elective Groups UI Helpers
// -------------------------------------------------------------
function toggleElectiveGroupsContainer() {
  const isElectiveCb = document.getElementById("sub-is-elective");
  const typeSelect = document.getElementById("sub-type");
  const isElective = (isElectiveCb && isElectiveCb.checked) || (typeSelect && typeSelect.value === "Elective");
  const container = document.getElementById("elective-groups-container");
  const notice = document.getElementById("sub-faculty-notice");
  const facGroup = document.getElementById("sub-faculty-group");

  if (container) {
    container.classList.toggle("hidden", !isElective);
    if (isElective && (!document.querySelectorAll(".elective-group-row").length)) {
      // Add initial two default sample groups for convenient setup
      addElectiveGroupRow({ name: "Elective Group 1", student_capacity: 40 });
      addElectiveGroupRow({ name: "Elective Group 2", student_capacity: 40 });
    }
  }

  if (notice) {
    notice.classList.toggle("hidden", isElective);
  }
  if (facGroup) {
    facGroup.classList.add("hidden");
  }
}

function renderElectiveGroups(groups = []) {
  const listEl = document.getElementById("elective-groups-list");
  if (!listEl) return;
  listEl.innerHTML = "";
  if (!groups || groups.length === 0) return;
  groups.forEach((g) => addElectiveGroupRow(g));
}

function addElectiveGroupRow(data = {}) {
  const listEl = document.getElementById("elective-groups-list");
  if (!listEl) return;

  const rowId = `egrp_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`;
  const gName = data.name || "";
  const gRoom = data.fixed_room_id || "";
  const gFac = data.faculty_id || "";
  const gCap = data.student_capacity || 40;
  const gWeekly = data.weekly_lectures || 3;

  const roomOptions = (state.rooms || [])
    .map(r => `<option value="${r.id}" ${r.id === gRoom ? 'selected' : ''}>${r.name} (${r.type}${r.floor_name ? ' - ' + r.floor_name : ''})</option>`)
    .join("");

  const facOptions = (state.faculty || [])
    .map(f => `<option value="${f.id}" ${f.id === gFac ? 'selected' : ''}>${f.name}</option>`)
    .join("");

  const rowHtml = `
    <div class="elective-group-row card p-2 mb-2" id="${rowId}" style="background:#fff; border:1px solid #cbd5e1; border-radius:6px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
        <div style="display:flex; align-items:center; gap:6px;">
          <strong style="font-size:12px; color:#334155;">Group Name:</strong>
          <input type="text" class="egrp-name form-control form-control-sm" style="width:200px; font-weight:600;" value="${gName}" placeholder="e.g. Data Engineering" required>
        </div>
        <button type="button" class="btn btn-xs btn-outline-danger" onclick="document.getElementById('${rowId}').remove()">&times; Remove Group</button>
      </div>
      <div class="form-row" style="display:flex; gap:8px;">
        <div class="form-group col" style="margin-bottom:0; flex:2;">
          <label style="font-size:11px; margin-bottom:2px; font-weight:600;">📍 Fixed Room (Mandatory):</label>
          <select class="egrp-room form-control form-control-sm" required>
            <option value="">Select Fixed Room...</option>
            ${roomOptions}
          </select>
        </div>
        <div class="form-group col" style="margin-bottom:0; flex:2;">
          <label style="font-size:11px; margin-bottom:2px;">👨‍🏫 Faculty:</label>
          <select class="egrp-faculty form-control form-control-sm">
            <option value="">Select Faculty...</option>
            ${facOptions}
          </select>
        </div>
        <div class="form-group col" style="max-width:90px; margin-bottom:0;">
          <label style="font-size:11px; margin-bottom:2px;">Students:</label>
          <input type="number" class="egrp-cap form-control form-control-sm" value="${gCap}" min="5" max="300">
        </div>
        <div class="form-group col" style="max-width:80px; margin-bottom:0;">
          <label style="font-size:11px; margin-bottom:2px;">Lec/Wk:</label>
          <input type="number" class="egrp-weekly form-control form-control-sm" value="${gWeekly}" min="1" max="10">
        </div>
      </div>
    </div>
  `;

  listEl.insertAdjacentHTML("beforeend", rowHtml);
}

window.deleteSubject = async function (id) {
  if (!confirm("Are you sure you want to delete this subject?")) return;
  try {
    const res = await fetch(`/api/subjects/${id}`, { method: "DELETE" });
    if (res.ok) {
      showBanner("Subject deleted.", "success");
      await refreshAllData();
    }
  } catch (e) {
    console.error(e);
  }
};

function renderAssignmentsTable() {
  const tbody = document.querySelector("#table-assignments tbody");
  if (!tbody) return;

  // Combine explicit assignments from state.assignments + elective group faculty from state.subjects
  const allAsgns = [...(state.assignments || [])];
  const existingIds = new Set(allAsgns.map((a) => a.id));

  (state.subjects || []).forEach((s) => {
    if (s.is_elective || s.type === "Elective") {
      (s.elective_groups || []).forEach((g) => {
        if (g.faculty_id) {
          const egrpId = `asgn_egrp_${g.id}`;
          if (!existingIds.has(egrpId)) {
            const fac = (state.faculty || []).find((f) => f.id === g.faculty_id);
            allAsgns.push({
              id: egrpId,
              faculty_id: g.faculty_id,
              faculty_name: g.faculty_name || (fac ? fac.name : g.faculty_id),
              subject_id: s.id,
              subject_name: s.name,
              year_id: s.year_id,
              division_id: null,
              batch_id: g.id,
              batch_name: g.name,
              fixed_room_name: g.fixed_room_name,
              is_elective: true,
            });
            existingIds.add(egrpId);
          }
        }
      });
    }
  });

  if (allAsgns.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-muted text-center" style="padding:16px;">No explicit faculty assignments recorded yet. Use <strong>🔗 Assign Faculty to Subject</strong> above (or assign faculty directly to Elective Groups in Add Subject).</td></tr>`;
    return;
  }

  tbody.innerHTML = allAsgns
    .map((a) => {
      const fac = state.faculty.find((f) => f.id === a.faculty_id);
      const sub = state.subjects.find((s) => s.id === a.subject_id);
      const div = state.divisions.find((d) => d.id === a.division_id);
      const batch = state.batches.find((b) => b.id === a.batch_id);

      const facName = a.faculty_name || (fac ? fac.name : a.faculty_id);
      const subName = a.subject_name || (sub ? sub.name : a.subject_id);
      const yearName = a.year_id || (sub ? sub.year_id : "-");

      if (a.is_elective) {
        return `
        <tr style="background: #faf5ff;">
          <td><strong style="color:#6d28d9;">👨‍🏫 ${facName}</strong></td>
          <td>
            <strong>${subName}</strong>
            <span class="badge" style="background:#7c3aed; color:#fff; font-size:10px; margin-left:4px;">Elective</span>
          </td>
          <td><span class="badge badge-primary">${yearName}</span></td>
          <td><span class="text-muted">All Divisions</span></td>
          <td>
            <span class="badge" style="background:#ede9fe; color:#6d28d9; border:1px solid #ddd6fe; font-size:11px; font-weight:600;">
              ${a.batch_name || a.elective_group_name || "Elective Group"}
              ${a.fixed_room_name ? ` (📍 ${a.fixed_room_name} 🔒)` : ""}
            </span>
          </td>
          <td>
            <button class="btn btn-sm btn-outline-primary" onclick="editSubject('${a.subject_id}')" style="margin-right:4px;">Edit in Subject</button>
            <button class="btn btn-sm btn-outline-danger" onclick="deleteAssignment('${a.id}')">Remove</button>
          </td>
        </tr>
      `;
      }

      return `
      <tr>
        <td><strong>👨‍🏫 ${facName}</strong></td>
        <td>${subName}</td>
        <td><span class="badge badge-primary">${yearName}</span></td>
        <td>${div ? div.name : "All Divisions"}</td>
        <td>${batch ? `<span class="badge badge-warning">${batch.name}</span>` : '<span class="text-muted">All Batches</span>'}</td>
        <td>
          <button class="btn btn-sm btn-outline-danger" onclick="deleteAssignment('${a.id}')">Remove</button>
        </td>
      </tr>
    `;
    })
    .join("");
}

window.deleteAssignment = async function (id) {
  try {
    const res = await fetch(`/api/faculty-assignments/${id}`, { method: "DELETE" });
    if (res.ok) {
      showBanner("Assignment removed.", "success");
      await refreshAllData();
    }
  } catch (e) {
    console.error(e);
  }
};

// -------------------------------------------------------------
// Divisions & Batches View
// -------------------------------------------------------------
function renderDivisionsView() {
  const container = document.getElementById("year-grid-container");
  const years = [
    { id: "FY", name: "First Year (FE)" },
    { id: "SY", name: "Second Year (SE)" },
    { id: "TY", name: "Third Year (TE)" },
    { id: "BE", name: "Bachelor of Engineering (BE)" },
  ];

  container.innerHTML = years
    .map((yr) => {
      const yrDivs = state.divisions.filter((d) => d.year_id === yr.id);
      const divsHtml = yrDivs
        .map((d) => {
          const divBatches = state.batches.filter((b) => b.division_id === d.id);
          const batchesHtml = divBatches
            .map(
              (b) => `
            <span class="batch-tag">
              ${b.name} <small class="text-muted">(${b.capacity || 25})</small>
              <a href="javascript:void(0)" onclick="deleteBatch('${b.id}')" style="color:#d93025; text-decoration:none; margin-left:3px;">&times;</a>
            </span>
          `
            )
            .join("");

          const flr = (state.floors || []).find((f) => f.id === d.floor_id);
          const floorBadge = flr
            ? `<span class="badge" style="background:#e0f2fe; color:#0369a1; font-weight:600; font-size:11px; margin-left:6px;" title="Assigned Floor: ${flr.name}">📍 ${flr.name}</span>`
            : `<span class="badge" style="background:#f1f5f9; color:#64748b; font-size:10px; margin-left:6px;" title="No fixed floor assigned (Flexible across building)">Flexible Floor</span>`;

          return `
          <div class="division-chip">
            <div>
              <strong>${d.name}</strong> <span class="badge badge-primary">${d.capacity || 70} students</span>
              ${floorBadge}
              <div class="batch-tags">${batchesHtml || '<small class="text-muted">No batches</small>'}</div>
            </div>
            <div style="display:flex; gap:6px; align-items:center;">
              <button class="btn btn-sm btn-outline" onclick="openEditDivisionModal('${d.id}')">Edit</button>
              <button class="btn btn-sm btn-outline-danger" onclick="deleteDivision('${d.id}')">Delete</button>
            </div>
          </div>
        `;
        })
        .join("");

      return `
      <div class="card">
        <div class="card-header year-card-header">
          <h3>${yr.name}</h3>
          <span class="badge badge-primary">${yrDivs.length} Divisions</span>
        </div>
        <div class="card-body">
          ${divsHtml || '<p class="text-muted">No divisions configured for this year.</p>'}
        </div>
      </div>
    `;
    })
    .join("");
}

window.openEditDivisionModal = function (id) {
  const div = (state.divisions || []).find((d) => d.id === id);
  if (!div) return;

  document.getElementById("edit-div-id").value = div.id;
  document.getElementById("edit-div-name").value = div.name;
  document.getElementById("edit-div-capacity").value = div.capacity || 70;

  const floorSelect = document.getElementById("edit-div-floor");
  if (floorSelect) {
    floorSelect.innerHTML =
      `<option value="">None (Flexible / Any Floor)</option>` +
      (state.floors || [])
        .map((f) => `<option value="${f.id}">📍 ${f.name} (Level ${f.floor_number})</option>`)
        .join("");
    floorSelect.value = div.floor_id || "";
  }

  openModal("modal-edit-division");
};

window.deleteDivision = async function (id) {
  if (!confirm("Delete this division?")) return;
  try {
    const res = await fetch(`/api/divisions/${id}`, { method: "DELETE" });
    if (res.ok) {
      showBanner("Division deleted.", "success");
      await refreshAllData();
    }
  } catch (e) {
    console.error(e);
  }
};

window.deleteBatch = async function (id) {
  if (!confirm("Delete this batch?")) return;
  try {
    const res = await fetch(`/api/batches/${id}`, { method: "DELETE" });
    if (res.ok) {
      showBanner("Batch deleted.", "success");
      await refreshAllData();
    }
  } catch (e) {
    console.error(e);
  }
};

// -------------------------------------------------------------
// Floor & Spatial Layout Management
// -------------------------------------------------------------
function renderFloorsView() {
  const container = document.getElementById("floors-container");
  if (!container) return;
  if (!state.floors || state.floors.length === 0) {
    container.innerHTML = `<div class="text-muted" style="padding:10px 0;">No floors configured. Click <strong>+ Add Floor</strong> to define building levels.</div>`;
    return;
  }

  container.innerHTML = state.floors.map(flr => {
    const roomsOnFloor = (state.rooms || []).filter(r => r.floor_id === flr.id);
    return `
      <div class="card p-3" style="min-width: 220px; flex: 1 1 220px; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff;">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;">
          <div>
            <h4 style="margin:0; font-size:15px; font-weight:700; color:#1e293b;">🏢 ${flr.name}</h4>
            <small class="text-muted">Level: <strong>${flr.floor_number}</strong> | Seq: ${flr.sequence_order || flr.floor_number}</small>
          </div>
          <span class="badge badge-primary">${roomsOnFloor.length} Rooms</span>
        </div>
        <div style="display:flex; gap:6px; margin-top:10px;">
          <button class="btn btn-sm btn-outline" onclick="openEditFloorModal('${flr.id}')" style="padding:2px 8px; font-size:11px;">Edit</button>
          <button class="btn btn-sm btn-outline-danger" onclick="deleteFloor('${flr.id}')" style="padding:2px 8px; font-size:11px;">Delete</button>
        </div>
      </div>
    `;
  }).join("");
}

window.openAddFloorModal = function() {
  const nextNum = (state.floors || []).length + 1;
  document.getElementById("modal-floor-title").textContent = "+ Add Floor";
  document.getElementById("floor-input-id").value = "";
  document.getElementById("floor-input-name").value = "";
  document.getElementById("floor-input-number").value = nextNum;
  document.getElementById("floor-input-sequence").value = nextNum;
  openModal("modal-floor");
};

window.openEditFloorModal = function(id) {
  const flr = (state.floors || []).find(f => f.id === id);
  if (!flr) return;
  document.getElementById("modal-floor-title").textContent = "Edit Floor";
  document.getElementById("floor-input-id").value = flr.id;
  document.getElementById("floor-input-name").value = flr.name;
  document.getElementById("floor-input-number").value = flr.floor_number;
  document.getElementById("floor-input-sequence").value = flr.sequence_order || flr.floor_number;
  openModal("modal-floor");
};

window.deleteFloor = async function(id) {
  const flr = (state.floors || []).find(f => f.id === id);
  const name = flr ? flr.name : id;
  if (!confirm(`Delete floor '${name}'? Rooms on this floor will become Unassigned.`)) return;
  try {
    const res = await fetch(`/api/floors/${id}`, { method: "DELETE" });
    if (res.ok) {
      showBanner(`Floor '${name}' deleted successfully.`, "success");
      await refreshAllData();
    } else {
      const d = await res.json();
      showBanner(d.error || "Failed to delete floor.", "danger");
    }
  } catch (e) {
    console.error(e);
  }
};

function populateFloorDropdowns() {
  const floors = state.floors || [];
  const optionsHtml = floors.map(f => `<option value="${f.id}">${f.name} (Level ${f.floor_number})</option>`).join("");

  const facAdd = document.getElementById("fac-input-floor");
  if (facAdd) facAdd.innerHTML = `<option value="">None</option>${optionsHtml}`;
  const facRename = document.getElementById("fac-rename-floor");
  if (facRename) facRename.innerHTML = `<option value="">None</option>${optionsHtml}`;

  const roomFloor = document.getElementById("room-input-floor");
  if (roomFloor) roomFloor.innerHTML = `<option value="">Unassigned Floor</option>${optionsHtml}`;

  const allRooms = state.rooms || [];
  const roomOptions = allRooms.map(r => `<option value="${r.id}">${r.name} (${r.floor_name || 'No Floor'})</option>`).join("");
  const distFrom = document.getElementById("dist-input-from");
  if (distFrom) distFrom.innerHTML = roomOptions;
  const distTo = document.getElementById("dist-input-to");
  if (distTo) distTo.innerHTML = roomOptions;
}

// -------------------------------------------------------------
// Rooms Management (Grouped by Floor & Sequence)
// -------------------------------------------------------------
function renderRoomsTable() {
  const container = document.getElementById("rooms-by-floor-container");
  if (!container) return;

  const groups = state.roomsByFloor && state.roomsByFloor.length > 0
    ? state.roomsByFloor
    : [{
        floor: { id: null, name: "All Rooms", floor_number: 0 },
        rooms: state.rooms || []
      }];

  container.innerHTML = groups.map(group => {
    const flr = group.floor;
    const flrRooms = group.rooms || [];
    const floorId = flr.id;
    const floorTitle = flr.id
      ? `🏢 ${flr.name} (Level ${flr.floor_number})`
      : `📦 Unassigned Floor (${flrRooms.length} Rooms)`;

    const rowsHtml = flrRooms.length === 0
      ? `<tr><td colspan="8" class="text-muted text-center" style="padding:15px;">No rooms configured under this floor. Click "+ Add Room on this Floor" to place one.</td></tr>`
      : flrRooms.map((r, idx) => {
          const isFirst = idx === 0;
          const isLast = idx === flrRooms.length - 1;
          const upBtn = isFirst ? '' : `<button class="btn-seq-move" onclick="moveRoomSequence('${floorId}', '${r.id}', -1)" title="Move earlier in floor sequence">▲</button>`;
          const downBtn = isLast ? '' : `<button class="btn-seq-move" onclick="moveRoomSequence('${floorId}', '${r.id}', 1)" title="Move later in floor sequence">▼</button>`;

          return `
            <tr>
              <td><strong>${flr.name || 'Unassigned'}</strong></td>
              <td>
                <span class="seq-badge">#${r.sequence_order || (idx + 1)}</span>
                ${floorId ? `<span class="seq-controls">${upBtn}${downBtn}</span>` : ''}
              </td>
              <td><strong>${r.name}</strong></td>
              <td><span class="cluster-badge">${r.cluster_id || 'Auto'}</span></td>
              <td><span class="badge ${r.type === 'Laboratory' ? 'badge-warning' : 'badge-primary'}">${r.type}</span></td>
              <td><span class="badge badge-success">${r.capacity || 70} seats</span></td>
              <td><small>${(r.available_days || []).join(', ')}</small></td>
              <td>
                <button class="btn btn-sm btn-outline" onclick="openEditRoomModal('${r.id}')">Edit</button>
                <button class="btn btn-sm btn-outline-danger" onclick="deleteRoom('${r.id}')">Delete</button>
              </td>
            </tr>
          `;
        }).join("");

    return `
      <div class="floor-card">
        <div class="floor-card-header">
          <div class="floor-card-title">
            <span>${floorTitle}</span>
            <span class="badge badge-info">${flrRooms.length} Rooms</span>
          </div>
          <div>
            <button class="btn btn-sm btn-outline" onclick="openAddRoomModal('${floorId || ''}')" style="font-size:11px;">+ Add Room on this Floor</button>
          </div>
        </div>
        <div class="table-responsive">
          <table class="data-table">
            <thead>
              <tr>
                <th>Floor</th>
                <th style="width:110px;">Seq #</th>
                <th>Room Name / No</th>
                <th>Cluster</th>
                <th>Type</th>
                <th>Capacity</th>
                <th>Available Days</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              ${rowsHtml}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }).join("");
}

window.moveRoomSequence = async function(floorId, roomId, direction) {
  if (!floorId || floorId === "null" || floorId === "undefined") return;
  const group = (state.roomsByFloor || []).find(g => g.floor && g.floor.id === floorId);
  if (!group || !group.rooms) return;

  const roomList = [...group.rooms];
  const idx = roomList.findIndex(r => r.id === roomId);
  if (idx < 0) return;
  const targetIdx = idx + direction;
  if (targetIdx < 0 || targetIdx >= roomList.length) return;

  const temp = roomList[idx];
  roomList[idx] = roomList[targetIdx];
  roomList[targetIdx] = temp;

  const orderedIds = roomList.map(r => r.id);
  try {
    const res = await fetch("/api/rooms/reorder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ floor_id: floorId, room_ids: orderedIds }),
    });
    if (res.ok) {
      showBanner("Room sequence order updated.", "success");
      await refreshAllData();
    }
  } catch (err) {
    console.error("Reorder failed:", err);
  }
};

window.openAddRoomModal = function(floorId = "") {
  document.getElementById("modal-room-title").textContent = "+ Add Room or Laboratory";
  document.getElementById("room-input-id").value = "";
  document.getElementById("room-input-name").value = "";
  document.getElementById("room-input-type").value = "Classroom";
  document.getElementById("room-input-capacity").value = "70";
  const floorSelect = document.getElementById("room-input-floor");
  if (floorSelect) floorSelect.value = floorId || "";

  // Auto-calculate sequence on this floor
  const floorRooms = (state.rooms || []).filter(r => r.floor_id === (floorId || null));
  const nextSeq = Math.max(0, ...floorRooms.map(r => r.sequence_order || 0)) + 1;
  const seqInput = document.getElementById("room-input-sequence");
  if (seqInput) seqInput.value = nextSeq;

  const clusterInput = document.getElementById("room-input-cluster");
  if (clusterInput) clusterInput.value = "";

  openModal("modal-add-room");
};

window.openEditRoomModal = function(id) {
  const room = state.rooms.find(r => r.id === id);
  if (!room) return;
  document.getElementById("modal-room-title").textContent = "Edit Room / Laboratory";
  document.getElementById("room-input-id").value = room.id;
  document.getElementById("room-input-name").value = room.name;
  document.getElementById("room-input-type").value = room.type;
  document.getElementById("room-input-capacity").value = room.capacity || 70;
  
  const floorSelect = document.getElementById("room-input-floor");
  if (floorSelect) floorSelect.value = room.floor_id || "";

  const seqInput = document.getElementById("room-input-sequence");
  if (seqInput) seqInput.value = room.sequence_order || 1;

  const clusterInput = document.getElementById("room-input-cluster");
  if (clusterInput) clusterInput.value = room.cluster_id || "";

  openModal("modal-add-room");
};

window.deleteRoom = async function (id) {
  if (!confirm("Delete this room?")) return;
  try {
    const res = await fetch(`/api/rooms/${id}`, { method: "DELETE" });
    if (res.ok) {
      showBanner("Room deleted.", "success");
      await refreshAllData();
    }
  } catch (e) {
    console.error(e);
  }
};

function updateRuleUI(chk, inp, bdg, masterEnabled = true) {
  if (!chk || !inp || !bdg) return;
  const active = masterEnabled && chk.checked;
  inp.disabled = !active;
  inp.style.opacity = active ? "1" : "0.5";
  if (!masterEnabled) {
    bdg.textContent = "Ignored (Master Off)";
    bdg.className = "badge";
  } else if (chk.checked) {
    bdg.textContent = "Active";
    bdg.className = "badge badge-primary";
  } else {
    bdg.textContent = "No Rule (Ignored)";
    bdg.className = "badge";
  }
}

// -------------------------------------------------------------
// Settings Form
// -------------------------------------------------------------
function populateSettingsForm() {
  const s = state.settings;
  const days = s.working_days || [];
  document.querySelectorAll("#settings-working-days input").forEach((cb) => {
    cb.checked = days.includes(cb.value);
  });

  document.getElementById("set-day-start").value = s.day_start_time || "09:00";
  document.getElementById("set-day-end").value = s.day_end_time || "17:00";
  document.getElementById("set-default-duration").value = s.default_lecture_duration || 60;
  const labDurEl = document.getElementById("set-default-lab-duration");
  if (labDurEl) labDurEl.value = s.default_lab_duration || 120;

  const primaryBreak = (s.breaks && s.breaks[0]) || {
    name: "Lunch Break",
    start: "13:00",
    end: "14:00",
    type: "lunch",
  };

  const breakNameEl = document.getElementById("set-break-name");
  if (breakNameEl) breakNameEl.value = primaryBreak.name || "Lunch Break";
  document.getElementById("set-break-start").value = primaryBreak.start || "13:00";
  document.getElementById("set-break-end").value = primaryBreak.end || "14:00";

  // Master and individual workload limit rules
  const enforceAll = s.enforce_workload_limits !== false;
  const masterChk = document.getElementById("set-enforce-workload-limits");
  if (masterChk) masterChk.checked = enforceAll;

  const rules = [
    { checkId: "check-max-fac-day", inputId: "set-max-fac-day", badgeId: "badge-fac-day-status", key: "enforce_faculty_daily_limit", valKey: "max_lectures_per_faculty_per_day", defVal: 4 },
    { checkId: "check-max-fac-daily-hours", inputId: "set-max-fac-daily-hours", badgeId: "badge-fac-hours-status", key: "enforce_faculty_daily_hours", valKey: "max_daily_faculty_workload", defVal: 5 },
    { checkId: "check-max-fac-weekly-hours", inputId: "set-max-fac-weekly-hours", badgeId: "badge-fac-weekly-status", key: "enforce_faculty_weekly_hours", valKey: "max_weekly_faculty_workload", defVal: 18 },
    { checkId: "check-max-fac-consecutive", inputId: "set-max-fac-consecutive", badgeId: "badge-fac-consec-status", key: "enforce_faculty_consecutive", valKey: "max_consecutive_faculty_lectures", defVal: 2 },
    { checkId: "check-max-div-day", inputId: "set-max-div-day", badgeId: "badge-div-day-status", key: "enforce_division_daily_limit", valKey: "max_lectures_per_division_per_day", defVal: 6 },
    { checkId: "check-min-div-day", inputId: "set-min-div-day", badgeId: "badge-div-min-status", key: "enforce_min_division_daily_limit", valKey: "min_lectures_per_division_per_day", defVal: 3 },
    { checkId: "check-max-div-consecutive", inputId: "set-max-div-consecutive", badgeId: "badge-div-consec-status", key: "enforce_division_consecutive", valKey: "max_consecutive_division_lectures", defVal: 3 },
  ];

  rules.forEach((r) => {
    const isEnforced = s[r.key] !== false;
    const chk = document.getElementById(r.checkId);
    const inp = document.getElementById(r.inputId);
    const bdg = document.getElementById(r.badgeId);
    if (chk) chk.checked = isEnforced;
    if (inp) inp.value = s[r.valKey] !== undefined ? s[r.valKey] : r.defVal;
    updateRuleUI(chk, inp, bdg, enforceAll);
  });
}

// -------------------------------------------------------------
// Event Listeners & Modals
// -------------------------------------------------------------
function setupEventListeners() {
  // Agent Subtabs
  const btnSubLogs = document.getElementById("subtab-btn-logs");
  const btnSubDivs = document.getElementById("subtab-btn-divisions");
  const subviewLogs = document.getElementById("agent-subview-logs");
  const subviewDivs = document.getElementById("agent-subview-divisions");

  if (btnSubLogs && btnSubDivs) {
    btnSubLogs.addEventListener("click", () => {
      btnSubLogs.classList.add("active");
      btnSubDivs.classList.remove("active");
      if (subviewLogs) subviewLogs.classList.remove("hidden");
      if (subviewDivs) subviewDivs.classList.add("hidden");
    });

    btnSubDivs.addEventListener("click", () => {
      btnSubDivs.classList.add("active");
      btnSubLogs.classList.remove("active");
      if (subviewDivs) subviewDivs.classList.remove("hidden");
      if (subviewLogs) subviewLogs.classList.add("hidden");
    });
  }

  // Agent Filters
  const agentFilterSelect = document.getElementById("agent-filter-select");
  const agentFilterType = document.getElementById("agent-filter-type");
  const agentFilterSearch = document.getElementById("agent-filter-search");
  if (agentFilterSelect) agentFilterSelect.addEventListener("change", () => renderAgentLogsStream());
  if (agentFilterType) agentFilterType.addEventListener("change", () => renderAgentLogsStream());
  if (agentFilterSearch) agentFilterSearch.addEventListener("input", () => renderAgentLogsStream());

  // Division Filter
  const divFilterYear = document.getElementById("div-filter-year");
  if (divFilterYear) divFilterYear.addEventListener("change", () => renderDivisionBreakdown());

  // Admin Intervention (LangGraph Human-in-the-Loop) Modal Handler
  function openAdminInterventionModal(data) {
    document.getElementById("intervention-thread-id").value = data.thread_id || "";
    document.getElementById("intervention-message").textContent = data.reason || data.message || "A scheduling bottleneck was detected.";
    document.getElementById("intervention-scheduled-count").textContent = data.scheduled_count || 0;
    document.getElementById("intervention-unscheduled-count").textContent = data.unscheduled_count || 0;

    const listEl = document.getElementById("intervention-lectures-list");
    if (data.unscheduled_lectures && data.unscheduled_lectures.length > 0) {
      listEl.innerHTML = data.unscheduled_lectures
        .map(
          (u) => `
        <div style="padding: 4px 0; border-bottom: 1px solid var(--border);">
          <strong>${u.year_id || ""} ${u.division_name || ""} - ${u.subject_name}</strong>
          ${u.batch_name ? `<span class="badge badge-warning" style="font-size:10px;">${u.batch_name}</span>` : ""}
          <div class="text-danger" style="font-size: 11px;">⚠️ ${u.reason || "No conflict-free slots found."}</div>
        </div>
      `
        )
        .join("");
    } else {
      listEl.innerHTML = `<div class="text-muted">Bottlenecks recorded during execution.</div>`;
    }

    openModal("modal-admin-intervention");
  }

  const btnResume = document.getElementById("btn-resume-orchestration");
  if (btnResume) {
    btnResume.addEventListener("click", async () => {
      const threadId = document.getElementById("intervention-thread-id").value;
      const decision = document.getElementById("intervention-decision").value.trim() || "Admin approved continuation.";

      btnResume.disabled = true;
      btnResume.textContent = "Resuming...";

      try {
        const res = await fetch("/api/timetable/resume", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ thread_id: threadId, decision: decision }),
        });
        const data = await res.json();
        btnResume.disabled = false;
        btnResume.textContent = "⚡ Approve & Resume Generation";
        closeModal("modal-admin-intervention");

        if (!res.ok) {
          showBanner(data.error || "Failed to resume orchestration.", "danger");
          return;
        }

        showBanner(
          `Timetable Finalized via LangGraph! Scheduled ${data.scheduled_count} lectures with ${data.backtracking_attempts} backtracks.`,
          data.success ? "success" : "warning"
        );
        await refreshAllData();
      } catch (err) {
        btnResume.disabled = false;
        btnResume.textContent = "⚡ Approve & Resume Generation";
        console.error("Resume error:", err);
        showBanner("Failed to resume orchestration.", "danger");
      }
    });
  }

  // Progressive Visual Allocation Player
  let isGeneratingPlayback = false;
  let skipAnimationRequested = false;

  // Live Timetable Progress Bar (Directly Above Timetable Master Card)
  function showTimetableLoadingBar(label, initialPct = 5) {
    const container = document.getElementById("timetable-loading-bar-container");
    const labelEl = document.getElementById("timetable-loading-label");
    const pctEl = document.getElementById("timetable-loading-percentage");
    const fillEl = document.getElementById("timetable-progress-fill");
    if (!container) return;
    if (labelEl) labelEl.textContent = label || "⚡ Processing Timetable...";
    const clamped = Math.max(0, Math.min(100, Math.round(initialPct)));
    if (pctEl) pctEl.textContent = `${clamped}%`;
    if (fillEl) fillEl.style.width = `${clamped}%`;
    container.style.display = "block";
  }

  function updateTimetableLoadingProgress(pct, label) {
    const labelEl = document.getElementById("timetable-loading-label");
    const pctEl = document.getElementById("timetable-loading-percentage");
    const fillEl = document.getElementById("timetable-progress-fill");
    if (label && labelEl) labelEl.textContent = label;
    const clamped = Math.max(0, Math.min(100, Math.round(pct)));
    if (pctEl) pctEl.textContent = `${clamped}%`;
    if (fillEl) fillEl.style.width = `${clamped}%`;
  }

  function hideTimetableLoadingBar() {
    const container = document.getElementById("timetable-loading-bar-container");
    if (container) {
      updateTimetableLoadingProgress(100);
      setTimeout(() => {
        container.style.display = "none";
        updateTimetableLoadingProgress(0);
      }, 400);
    }
  }

  async function playProgressiveAllocation(finalEntries, executionLogs, totalBacktracks) {
    const livePanel = document.getElementById("generation-live-panel");
    const pBar = document.getElementById("gen-progress-bar");
    const pBadge = document.getElementById("gen-percentage-badge");
    const statusTitle = document.getElementById("gen-status-title");
    const tickerAgent = document.getElementById("gen-ticker-agent");
    const tickerStep = document.getElementById("gen-ticker-step");
    const statSched = document.getElementById("gen-stat-scheduled");
    const statBtrack = document.getElementById("gen-stat-backtracks");
    const statConf = document.getElementById("gen-stat-conflicts");

    if (livePanel) livePanel.classList.remove("hidden");
    skipAnimationRequested = false;
    isGeneratingPlayback = true;

    // Filter relevant orchestrator events
    const steps = (executionLogs || []).filter(l => 
      l.type === "ASSIGNMENT" || l.type === "BACKTRACK" || l.type === "ORCHESTRATOR_START" || l.type === "ORCHESTRATOR_FINISH"
    );

    const totalSteps = Math.max(1, steps.length || finalEntries.length);
    state.timetable = state.timetable || {};
    state.timetable.entries = [];
    renderTimetableGrid();

    let scheduledEntriesSoFar = [];
    let currentBacktracks = 0;

    for (let i = 0; i < steps.length; i++) {
      if (skipAnimationRequested) break;

      const step = steps[i];
      const pct = Math.min(98, Math.round(((i + 1) / totalSteps) * 100));

      if (pBar) pBar.style.width = `${pct}%`;
      if (pBadge) pBadge.textContent = `${pct}%`;
      if (tickerAgent) tickerAgent.textContent = `🤖 ${step.agent || "Python Rule-Based Orchestrator"}`;
      if (tickerStep) tickerStep.textContent = step.message || "Placing lecture slot...";
      updateTimetableLoadingProgress(pct, `⚡ Scheduling: ${scheduledEntriesSoFar.length} / ${finalEntries.length} lectures (${step.agent || "Orchestrator"})`);

      if (step.type === "ASSIGNMENT") {
        const matched = finalEntries.find(e => 
          e.subject_name && step.message && step.message.includes(e.subject_name) &&
          !scheduledEntriesSoFar.some(s => s.id === e.id)
        );
        if (matched) {
          scheduledEntriesSoFar.push(matched);
        } else if (finalEntries[scheduledEntriesSoFar.length]) {
          scheduledEntriesSoFar.push(finalEntries[scheduledEntriesSoFar.length]);
        }
      } else if (step.type === "BACKTRACK") {
        currentBacktracks++;
        if (scheduledEntriesSoFar.length > 0) {
          scheduledEntriesSoFar.pop();
        }
      }

      if (statSched) statSched.innerHTML = `Scheduled: <strong>${scheduledEntriesSoFar.length}</strong>`;
      if (statBtrack) statBtrack.innerHTML = `Backtracks: <strong>${currentBacktracks}</strong>`;
      if (statConf) statConf.innerHTML = `Conflicts: <strong>0</strong>`;

      state.timetable.entries = [...scheduledEntriesSoFar];
      renderTimetableGrid();

      await new Promise(r => setTimeout(r, 35));
    }

    // Finish to 100%
    if (pBar) {
      pBar.style.width = "100%";
      pBar.style.background = "linear-gradient(90deg, #10b981 0%, #059669 100%)";
    }
    if (pBadge) {
      pBadge.textContent = "100%";
      pBadge.className = "badge badge-success";
    }
    if (statusTitle) statusTitle.textContent = "✨ Timetable Generated Successfully: Conflict-Free & Synced!";
    if (tickerStep) tickerStep.textContent = `Completed! ${finalEntries.length} lectures scheduled, 0 hard conflicts detected.`;
    if (statSched) statSched.innerHTML = `Scheduled: <strong>${finalEntries.length}</strong>`;
    if (statBtrack) statBtrack.innerHTML = `Backtracks: <strong>${totalBacktracks || 0}</strong>`;
    updateTimetableLoadingProgress(100, `✨ Timetable Generated! ${finalEntries.length} lectures scheduled, 0 conflicts.`);

    state.timetable.entries = finalEntries;
    renderTimetableGrid();
    isGeneratingPlayback = false;

    setTimeout(() => {
      hideTimetableLoadingBar();
      if (livePanel && !isGeneratingPlayback) {
        livePanel.classList.add("hidden");
      }
    }, 4000);
  }

  // Generate Timetable (Live SSE streaming with real agent progress & safe draft commit)
  async function executeGenerateTimetable(triggerBtn) {
    const btn = triggerBtn || document.getElementById("btn-generate-timetable");
    const origText = btn ? btn.textContent : "⚡ Generate Timetable";
    if (btn) {
      btn.disabled = true;
      btn.textContent = "⏳ Generating...";
    }
    const asgnBtn = document.getElementById("btn-generate-from-assignments");
    if (asgnBtn && asgnBtn !== btn) {
      asgnBtn.disabled = true;
      asgnBtn.textContent = "⏳ Generating...";
    }

    // Ensure Timetable view is visible
    const tabTimetableNav = document.querySelector('[data-tab="tab-timetable"]');
    if (tabTimetableNav) tabTimetableNav.click();

    // Show live panel with initial state
    const livePanel = document.getElementById("generation-live-panel");
    const pBar = document.getElementById("gen-progress-bar");
    const pBadge = document.getElementById("gen-percentage-badge");
    const statusTitle = document.getElementById("gen-status-title");
    const tickerStep = document.getElementById("gen-ticker-step");
    if (livePanel) livePanel.classList.remove("hidden");
    if (pBar) {
      pBar.style.width = "5%";
      pBar.style.background = "linear-gradient(90deg, #3b82f6 0%, #6366f1 50%, #10b981 100%)";
    }
    if (pBadge) {
      pBadge.textContent = "5%";
      pBadge.className = "badge badge-primary";
    }
    if (statusTitle) statusTitle.textContent = "Connecting to Multi-Agent Scheduling Engine...";
    if (tickerStep) tickerStep.textContent = "Initializing Agents, checking hard constraints & lab batches...";

    showTimetableLoadingBar("⚡ Orchestrator Evaluating Constraints & Scheduling...", 5);

    // If SSE is available, use real backend event stream
    if (window.EventSource) {
      const evtSource = new EventSource("/api/timetable/generate-stream");
      let streamFinished = false;

      const resetBtns = () => {
        if (btn) {
          btn.disabled = false;
          btn.textContent = origText;
        }
        if (asgnBtn && asgnBtn !== btn) {
          asgnBtn.disabled = false;
          asgnBtn.textContent = "⚡ Generate Timetable";
        }
      };

      evtSource.addEventListener("progress", (e) => {
        try {
          const payload = JSON.parse(e.data);
          const pct = Math.min(Math.max(payload.progress || 10, 5), 98);
          updateTimetableLoadingProgress(pct, payload.message || payload.step);

          if (pBar) pBar.style.width = `${pct}%`;
          if (pBadge) pBadge.textContent = `${pct}%`;
          if (statusTitle) statusTitle.textContent = payload.message || payload.step;
          if (tickerStep) {
            tickerStep.textContent = `Scheduled: ${payload.current_entries_count || 0} entries | Backtracks: ${payload.backtracking_attempts || 0}`;
          }

          // Live partial entry preview
          if (payload.partial_entries && payload.partial_entries.length > 0 && typeof renderTimetableGrid === "function") {
            try {
              renderTimetableGrid({ entries: payload.partial_entries });
            } catch (err) {}
          }
        } catch (err) {
          console.error("SSE progress parse error:", err);
        }
      });

      evtSource.addEventListener("complete", async (e) => {
        streamFinished = true;
        evtSource.close();
        resetBtns();
        hideTimetableLoadingBar();
        if (livePanel) livePanel.classList.add("hidden");

        try {
          const resData = JSON.parse(e.data);
          const finalEntries = resData.timetable_entries || (resData.timetable && resData.timetable.entries) || [];
          const execLogs = (resData.log && resData.log.execution_logs) || resData.execution_logs || [];

          await playProgressiveAllocation(finalEntries, execLogs, resData.backtracking_attempts);

          let statusMsg = `Timetable Generated! Scheduled ${resData.scheduled_count} lectures with ${resData.backtracking_attempts || 0} backtracks.`;
          if (resData.self_repair_applied) {
            statusMsg += " Auto-clash self-repair verified hard constraints.";
          }
          if (resData.cooling_factor_applied) {
            statusMsg += " Normalization cooling balanced weekly subjects.";
          }

          showBanner(statusMsg, resData.success ? "success" : "warning");
          await refreshAllData();
          if (typeof loadTimetableInsights === "function") {
            loadTimetableInsights();
          }
        } catch (err) {
          console.error("SSE complete handler error:", err);
          await refreshAllData();
        }
      });

      evtSource.addEventListener("intervention_required", (e) => {
        streamFinished = true;
        evtSource.close();
        resetBtns();
        hideTimetableLoadingBar();
        if (livePanel) livePanel.classList.add("hidden");
        try {
          const resData = JSON.parse(e.data);
          showBanner("LangGraph Paused: Admin intervention required for resource contention.", "warning");
          openAdminInterventionModal(resData);
        } catch (err) {
          console.error(err);
        }
      });

      evtSource.addEventListener("error", async (e) => {
        if (streamFinished) return;
        evtSource.close();
        console.warn("SSE connection error or closed, falling back to standard generation...");
        try {
          const res = await fetch("/api/timetable/generate", { method: "POST" });
          const data = await res.json();
          resetBtns();
          hideTimetableLoadingBar();
          if (livePanel) livePanel.classList.add("hidden");

          if (!res.ok) {
            showBanner(data.error || "Timetable generation failed.", "danger");
            return;
          }

          const finalEntries = data.timetable_entries || (data.timetable && data.timetable.entries) || [];
          const execLogs = (data.log && data.log.execution_logs) || data.execution_logs || [];
          await playProgressiveAllocation(finalEntries, execLogs, data.backtracking_attempts);
          showBanner(
            `Timetable Generated! Scheduled ${data.scheduled_count} lectures with ${data.backtracking_attempts || 0} backtracks.`,
            data.success ? "success" : "warning"
          );
          await refreshAllData();
          if (typeof loadTimetableInsights === "function") {
            loadTimetableInsights();
          }
        } catch (err) {
          resetBtns();
          hideTimetableLoadingBar();
          if (livePanel) livePanel.classList.add("hidden");
          console.error("Generation error:", err);
          await refreshAllData();
        }
      });

      return;
    }

    // Fallback if EventSource not supported
    try {
      const res = await fetch("/api/timetable/generate", { method: "POST" });
      const data = await res.json();
      if (btn) {
        btn.disabled = false;
        btn.textContent = origText;
      }
      if (asgnBtn && asgnBtn !== btn) {
        asgnBtn.disabled = false;
        asgnBtn.textContent = "⚡ Generate Timetable";
      }
      hideTimetableLoadingBar();
      if (livePanel) livePanel.classList.add("hidden");

      if (!res.ok) {
        showBanner(data.error || "Timetable generation failed.", "danger");
        return;
      }

      const finalEntries = data.timetable_entries || (data.timetable && data.timetable.entries) || [];
      const execLogs = (data.log && data.log.execution_logs) || data.execution_logs || [];
      await playProgressiveAllocation(finalEntries, execLogs, data.backtracking_attempts);

      showBanner(
        `Timetable Generated! Scheduled ${data.scheduled_count} lectures with ${data.backtracking_attempts} backtracks.`,
        data.success ? "success" : "warning"
      );
      await refreshAllData();
      if (typeof loadTimetableInsights === "function") {
        loadTimetableInsights();
      }
    } catch (e) {
      hideTimetableLoadingBar();
      if (btn) {
        btn.disabled = false;
        btn.textContent = origText;
      }
      if (asgnBtn && asgnBtn !== btn) {
        asgnBtn.disabled = false;
        asgnBtn.textContent = "⚡ Generate Timetable";
      }
      if (livePanel) livePanel.classList.add("hidden");
      console.error(e);
      showBanner("Timetable generation failed.", "danger");
    }
  }

  function handleTriggerGenerateTimetable(triggerBtn) {
    const entries = (state.timetable && state.timetable.entries) || [];
    if (entries.length > 0) {
      openConfirmModal(
        "Regenerate Timetable?",
        `A timetable already exists with ${entries.length} scheduled lectures. Generating a new timetable will overwrite and reset the existing schedule. Do you want to proceed and generate a new timetable?`,
        async () => {
          await executeGenerateTimetable(triggerBtn);
        }
      );
    } else {
      executeGenerateTimetable(triggerBtn);
    }
  }

  // Fast forward animation listener
  const btnSkipGenAnim = document.getElementById("btn-skip-gen-animation");
  if (btnSkipGenAnim) {
    btnSkipGenAnim.addEventListener("click", () => {
      skipAnimationRequested = true;
    });
  }

  // Dashboard / Orchestrator Tab Generate Button
  const btnGenMain = document.getElementById("btn-generate-timetable");
  if (btnGenMain) {
    btnGenMain.addEventListener("click", (e) => {
      handleTriggerGenerateTimetable(e.currentTarget);
    });
  }

  // Dashboard "Open Timetable & Generate" Button
  const btnGotoTt = document.getElementById("btn-goto-timetable-gen");
  if (btnGotoTt) {
    btnGotoTt.addEventListener("click", () => {
      const tabTtNav = document.querySelector('[data-tab="tab-timetable"]');
      if (tabTtNav) tabTtNav.click();
    });
  }

  // Explicit Faculty Teaching Assignments Tab Generate Button
  const btnGenFromAsgn = document.getElementById("btn-generate-from-assignments");
  if (btnGenFromAsgn) {
    btnGenFromAsgn.addEventListener("click", (e) => {
      handleTriggerGenerateTimetable(e.currentTarget);
    });
  }

  // Auto-Fix Clashes Preview & Apply
  let pendingAutoFixes = [];

  async function handleAutoFixClashes() {
    const modal = document.getElementById("modal-auto-fix-preview");
    const loading = document.getElementById("autofix-modal-loading");
    const content = document.getElementById("autofix-modal-content");
    const summaryText = document.getElementById("autofix-summary-text");
    const tbody = document.getElementById("autofix-preview-tbody");
    const btnConfirm = document.getElementById("btn-confirm-autofix");

    if (modal) modal.classList.remove("hidden");
    if (loading) loading.classList.remove("hidden");
    if (content) content.classList.add("hidden");

    try {
      const res = await fetch("/api/timetable/auto-fix-preview", { method: "POST" });
      const data = await res.json();
      if (loading) loading.classList.add("hidden");
      if (content) content.classList.remove("hidden");

      if (!res.ok) {
        throw new Error(data.error || data.message || `Server responded with status ${res.status}`);
      }

      pendingAutoFixes = data.proposed_fixes || [];
      if (!data.has_conflicts) {
        summaryText.textContent = data.message || "Timetable is completely conflict-free. No auto-fixes needed!";
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-3">✅ Timetable is completely conflict-free. All constraints satisfied!</td></tr>`;
        if (btnConfirm) btnConfirm.disabled = true;
        return;
      }

      if (pendingAutoFixes.length === 0) {
        summaryText.innerHTML = `⚠️ Found <strong>${data.conflicts_count}</strong> conflict(s). Automatic resolution was unable to find an isolated slot swap without secondary conflicts. You can click <strong>⚡ Generate Timetable</strong> to auto-rebalance all years, or adjust the lecture manually.`;
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-3">No isolated slot swap found. Use <strong>⚡ Generate Timetable</strong> to auto-schedule conflict-free.</td></tr>`;
        if (btnConfirm) btnConfirm.disabled = true;
        return;
      }

      summaryText.textContent = `Found ${data.conflicts_count} conflict(s). Review the ${pendingAutoFixes.length} proposed resolution(s) below:`;
      if (btnConfirm) btnConfirm.disabled = false;

      tbody.innerHTML = pendingAutoFixes.map(f => `
        <tr>
          <td><strong>${f.subject_name || "Subject"}</strong><br><small class="text-muted">${f.division_name || ""}</small></td>
          <td><span class="badge badge-outline">${f.day || ""} ${f.time || ""}</span></td>
          <td><span class="badge badge-warning">${f.conflict_type}</span></td>
          <td><span class="text-danger" style="text-decoration:line-through;">${f.old_value}</span></td>
          <td>
            <strong class="text-success">${f.new_value}</strong>
            <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">${f.change_description}</div>
          </td>
        </tr>
      `).join("");

    } catch (err) {
      if (loading) loading.classList.add("hidden");
      if (content) content.classList.remove("hidden");
      summaryText.textContent = "Error loading conflict resolutions.";
      console.error(err);
      showBanner("Failed to analyze timetable conflicts for auto-fixing.", "danger");
    }
  }

  const btnAutoFix = document.getElementById("btn-auto-fix-clashes");
  if (btnAutoFix) btnAutoFix.addEventListener("click", handleAutoFixClashes);

  const btnBannerFix = document.getElementById("btn-banner-auto-fix");
  if (btnBannerFix) btnBannerFix.addEventListener("click", handleAutoFixClashes);

  const btnCloseAutoFix = document.getElementById("btn-close-autofix-modal");
  if (btnCloseAutoFix) {
    btnCloseAutoFix.addEventListener("click", () => {
      document.getElementById("modal-auto-fix-preview").classList.add("hidden");
    });
  }

  const btnCancelAutoFix = document.getElementById("btn-cancel-autofix");
  if (btnCancelAutoFix) {
    btnCancelAutoFix.addEventListener("click", () => {
      document.getElementById("modal-auto-fix-preview").classList.add("hidden");
    });
  }

  // Apply proposed auto-fixes
  const btnConfirmAutoFix = document.getElementById("btn-confirm-autofix");
  if (btnConfirmAutoFix) {
    btnConfirmAutoFix.addEventListener("click", async () => {
      if (pendingAutoFixes.length === 0) return;
      btnConfirmAutoFix.disabled = true;
      btnConfirmAutoFix.textContent = "Applying Fixes...";
      showTimetableLoadingBar("🔧 Auto-Fixing Timetable Clashes & Rebalancing...", 35);
      try {
        const res = await fetch("/api/timetable/auto-fix-apply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ fixes: pendingAutoFixes })
        });
        const data = await res.json();
        document.getElementById("modal-auto-fix-preview").classList.add("hidden");
        btnConfirmAutoFix.disabled = false;
        btnConfirmAutoFix.textContent = "✅ Apply Proposed Fixes";

        if (res.ok && data.success) {
          updateTimetableLoadingProgress(100, "✅ Clash Resolutions Successfully Applied!");
          setTimeout(() => hideTimetableLoadingBar(), 1500);
          showBanner(data.message || `Applied ${data.applied_count} fixes!`, "success");
          await refreshAllData();
        } else {
          hideTimetableLoadingBar();
          showBanner(data.error || "Failed to apply auto-fixes.", "danger");
        }
      } catch (e) {
        hideTimetableLoadingBar();
        btnConfirmAutoFix.disabled = false;
        btnConfirmAutoFix.textContent = "✅ Apply Proposed Fixes";
        console.error(e);
        showBanner("Error applying auto-fixes.", "danger");
      }
    });
  }

  // Undo Timetable
  const btnUndo = document.getElementById("btn-undo-timetable");
  if (btnUndo) {
    btnUndo.addEventListener("click", async () => {
      btnUndo.disabled = true;
      btnUndo.textContent = "↩️ Undoing...";
      try {
        const res = await fetch("/api/timetable/undo", { method: "POST" });
        const data = await res.json();
        btnUndo.disabled = false;
        btnUndo.textContent = "↩️ Undo";
        if (res.ok && data.success) {
          showBanner(data.message || "Reverted to previous timetable state.", "info");
          await refreshAllData();
        } else {
          showBanner(data.message || data.error || "Nothing to undo.", "warning");
        }
      } catch (err) {
        btnUndo.disabled = false;
        btnUndo.textContent = "↩️ Undo";
        console.error(err);
        showBanner("Error performing undo.", "danger");
      }
    });
  }

  const btnRedo = document.getElementById("btn-redo-timetable");
  if (btnRedo) {
    btnRedo.addEventListener("click", async () => {
      btnRedo.disabled = true;
      btnRedo.textContent = "↪️ Redoing...";
      try {
        const res = await fetch("/api/timetable/redo", { method: "POST" });
        const data = await res.json();
        btnRedo.disabled = false;
        btnRedo.textContent = "↪️ Redo";
        if (res.ok && data.success) {
          showBanner(data.message || "Redone previously undone state.", "info");
          await refreshAllData();
        } else {
          showBanner(data.message || data.error || "Nothing to redo.", "warning");
        }
      } catch (err) {
        btnRedo.disabled = false;
        btnRedo.textContent = "↪️ Redo";
        console.error(err);
        showBanner("Error performing redo.", "danger");
      }
    });
  }

  // Explicit Faculty Teaching Assignments Quick "Assign Faculty" Button
  const btnAsgnFacAlt = document.getElementById("btn-open-assign-faculty-alt");
  if (btnAsgnFacAlt) {
    btnAsgnFacAlt.addEventListener("click", () => {
      const orig = document.getElementById("btn-open-assign-faculty");
      if (orig) orig.click();
    });
  }

  // Clear Timetable
  document.getElementById("btn-clear-timetable").addEventListener("click", () => {
    openConfirmModal(
      "Reset Timetable",
      "Are you sure you want to clear all generated timetable entries? This action will back up existing data before clearing.",
      async () => {
        const res = await fetch("/api/timetable/clear", { method: "POST" });
        if (res.ok) {
          showBanner("Timetable reset successfully.", "success");
          await refreshAllData();
        }
      }
    );
  });

  // Reset All Department Data
  document.getElementById("btn-reset-all-data").addEventListener("click", () => {
    openConfirmModal(
      "Reset All Department Data",
      "WARNING: This will completely wipe all faculty, subjects, divisions, batches, rooms, assignments, and timetable data to empty so you can enter everything fresh. An automatic backup will be created beforehand. Proceed?",
      async () => {
        try {
          const res = await fetch("/api/data/reset-all", { method: "POST" });
          const data = await res.json();
          if (res.ok) {
            showBanner(data.message, "success");
            await refreshAllData();
          } else {
            showBanner(data.error || "Failed to reset all data.", "danger");
          }
        } catch (e) {
          console.error(e);
          showBanner("Failed to reset data.", "danger");
        }
      }
    );
  });

  // Load Demonstration Data
  async function handleLoadDemoData() {
    openConfirmModal(
      "Load Demonstration Data",
      "This will load complete CMPN department demonstration data across FY, SY, TY, and BE (including classrooms, labs, faculty with workloads, lab batches, theory & practical subjects, and explicit assignments). An automatic backup will be created beforehand. Proceed?",
      async () => {
        showTimetableLoadingBar("📦 Loading Complete Demonstration Dataset...", 35);
        try {
          const res = await fetch("/api/data/load-demo", { method: "POST" });
          const data = await res.json();
          if (res.ok) {
            updateTimetableLoadingProgress(100, "✅ Demo Data Successfully Loaded!");
            setTimeout(() => hideTimetableLoadingBar(), 1500);
            showBanner(data.message || "Demo data loaded successfully!", "success");
            await refreshAllData();
          } else {
            hideTimetableLoadingBar();
            showBanner(data.error || "Failed to load demo data.", "danger");
          }
        } catch (e) {
          hideTimetableLoadingBar();
          console.error(e);
          showBanner("Failed to load demo data due to network error.", "danger");
        }
      }
    );
  }

  const btnDemoTop = document.getElementById("btn-load-demo-top");
  if (btnDemoTop) {
    btnDemoTop.addEventListener("click", () => {
      handleLoadDemoData();
    });
  }

  const btnDemoDashboard = document.getElementById("btn-load-demo-dashboard");
  if (btnDemoDashboard) {
    btnDemoDashboard.addEventListener("click", () => {
      handleLoadDemoData();
    });
  }

  // Timetable Unified Filters (Academic Year, Division, Faculty, Room, Day)
  const ttViewModeEl = document.getElementById("tt-view-mode");
  if (ttViewModeEl) {
    ttViewModeEl.addEventListener("change", (e) => {
      state.viewMode = e.target.value;
      renderTimetableGrid();
    });
  }

  const ttYearSelectEl = document.getElementById("tt-year-select");
  if (ttYearSelectEl) {
    ttYearSelectEl.addEventListener("change", (e) => {
      const val = e.target.value;
      state.filters.year = val;
      state.filters.years = [val];
      state.selectedYear = val === "ALL" ? "TY" : val;
      state.filters.divisions = ["ALL"];
      state.filters.division = "ALL";
      populateFilterDropdowns();
      renderTimetableGrid();
    });
  }

  const ttDivSelectEl = document.getElementById("tt-division-select");
  if (ttDivSelectEl) {
    ttDivSelectEl.addEventListener("change", (e) => {
      const val = e.target.value;
      state.filters.division = val;
      state.filters.divisions = [val];
      state.selectedDivisionId = val === "ALL" ? null : val;
      populateFilterDropdowns();
      renderTimetableGrid();
    });
  }

  const ttFacSelectEl = document.getElementById("tt-faculty-select");
  if (ttFacSelectEl) {
    ttFacSelectEl.addEventListener("change", (e) => {
      state.filters.faculty = e.target.value;
      state.selectedFacultyId = state.filters.faculty === "ALL" ? null : state.filters.faculty;
      renderTimetableGrid();
    });
  }

  const ttRoomSelectEl = document.getElementById("tt-room-select");
  if (ttRoomSelectEl) {
    ttRoomSelectEl.addEventListener("change", (e) => {
      state.filters.room = e.target.value;
      state.selectedRoomId = state.filters.room === "ALL" ? null : state.filters.room;
      renderTimetableGrid();
    });
  }

  const ttDaySelectEl = document.getElementById("tt-day-select");
  if (ttDaySelectEl) {
    ttDaySelectEl.addEventListener("change", (e) => {
      const val = e.target.value;
      state.filters.day = val;
      state.filters.days = [val];
      populateFilterDropdowns();
      renderTimetableGrid();
    });
  }

  // Segmented Multi-Select Box Buttons - Year
  const boxYearEl = document.getElementById("box-filter-year");
  if (boxYearEl) {
    boxYearEl.querySelectorAll(".btn-filter-box").forEach((btn) => {
      btn.addEventListener("click", () => {
        toggleFilterValue("years", btn.getAttribute("data-val"));
      });
    });
  }

  // Segmented Multi-Select Box Buttons - Day
  const boxDayEl = document.getElementById("box-filter-day");
  if (boxDayEl) {
    boxDayEl.querySelectorAll(".btn-filter-box").forEach((btn) => {
      btn.addEventListener("click", () => {
        toggleFilterValue("days", btn.getAttribute("data-val"));
      });
    });
  }

  const btnResetFilters = document.getElementById("btn-reset-filters");
  if (btnResetFilters) {
    btnResetFilters.addEventListener("click", () => {
      state.filters = {
        year: "ALL",
        division: "ALL",
        faculty: "ALL",
        room: "ALL",
        day: "ALL",
        years: ["ALL"],
        divisions: ["ALL"],
        days: ["ALL"],
      };
      state.selectedYear = "TY";
      state.selectedDivisionId = null;
      state.selectedFacultyId = null;
      state.selectedRoomId = null;
      populateFilterDropdowns();
      renderTimetableGrid();
      showBanner("Timetable filters have been reset to ALL YEARS complete department schedule.", "info");
    });
  }

  document.getElementById("btn-refresh-timetable").addEventListener("click", () => {
    refreshAllData();
  });

  document.getElementById("btn-manual-add-lecture").addEventListener("click", () => {
    openAddLectureModal();
  });

  // -------------------------------------------------------------
  // Smart Add Lecture (Auto-Slot Scheduler)
  // -------------------------------------------------------------
  state.smartCandidateSlots = [];

  function openSmartAddLectureModal() {
    let targetDivId = state.selectedDivisionId;
    let year = "TY";
    if (targetDivId) {
      const divObj = (state.divisions || []).find((d) => d.id === targetDivId);
      if (divObj) year = divObj.year_id;
    } else if (state.selectedYear && state.selectedYear !== "ALL") {
      year = state.selectedYear;
    }
    const yearSelect = document.getElementById("smart-add-year");
    if (yearSelect) yearSelect.value = year;

    updateSmartAddDivisions(year, targetDivId);
    const effDivId = document.getElementById("smart-add-division")?.value;
    updateSmartAddSubjects(year, effDivId);
    updateSmartAddFaculty();
    updateSmartAddRooms();

    const countInput = document.getElementById("smart-add-count");
    if (countInput) countInput.value = "3";
    state.smartCandidateSlots = [];

    // Reset preview box
    const previewBox = document.getElementById("smart-add-preview-box");
    if (previewBox) previewBox.classList.add("hidden");
    const statusEl = document.getElementById("smart-add-preview-status");
    if (statusEl) statusEl.textContent = "";
    const msgEl = document.getElementById("smart-add-preview-msg");
    if (msgEl) msgEl.textContent = "";
    const listEl = document.getElementById("smart-add-slots-list");
    if (listEl) listEl.innerHTML = "";
    const confirmBtn = document.getElementById("btn-smart-add-confirm");
    if (confirmBtn) confirmBtn.classList.add("hidden");

    openModal("modal-smart-add-lecture");
  }

  function updateSmartAddDivisions(yearId, selectedDivId) {
    const divSelect = document.getElementById("smart-add-division");
    if (!divSelect) return;
    const divs = state.divisions.filter((d) => d.year_id === yearId);
    divSelect.innerHTML = divs.map((d) => `<option value="${d.id}">${d.name}</option>`).join("");
    if (selectedDivId && divs.some((d) => d.id === selectedDivId)) {
      divSelect.value = selectedDivId;
    }
    updateSmartAddBatches(divSelect.value);
  }

  function updateSmartAddBatches(divId) {
    const batchSelect = document.getElementById("smart-add-batch");
    if (!batchSelect) return;
    const batches = state.batches.filter((b) => b.division_id === divId);
    batchSelect.innerHTML =
      `<option value="">None (Full Division)</option>` +
      batches.map((b) => `<option value="${b.id}">${b.name}</option>`).join("");
  }

  function updateSmartAddSubjects(yearId, divId) {
    const subSelect = document.getElementById("smart-add-subject");
    if (!subSelect) return;
    const subs = getSubjectsForDivision(divId, yearId);
    let opts = subs
      .map((s) => {
        const dur = s.duration_minutes || 60;
        const code = s.code ? `[${s.code}] ` : "";
        return `<option value="${s.id}">${code}${s.name} (${s.type}, ${dur}m)</option>`;
      })
      .join("");
    opts += `<option value="__NEW__">➕ + Add New Subject...</option>`;
    subSelect.innerHTML = opts;
    syncSmartAddSubjectDetails();
  }

  function updateSmartAddFaculty(selectedFacId) {
    const facSelect = document.getElementById("smart-add-faculty");
    if (!facSelect) return;
    facSelect.innerHTML =
      `<option value="AUTO">🤖 Auto (Assigned / Eligible Faculty)</option>` +
      state.faculty.map((f) => `<option value="${f.id}">${f.name}</option>`).join("");
    if (selectedFacId) facSelect.value = selectedFacId;
  }

  function updateSmartAddRooms(selectedRoomId) {
    const roomSelect = document.getElementById("smart-add-room");
    if (!roomSelect) return;
    roomSelect.innerHTML =
      `<option value="AUTO">🤖 Auto (Available Required Room)</option>` +
      state.rooms.map((r) => `<option value="${r.id}">${r.name} (${r.type}, Cap: ${r.capacity || 60})</option>`).join("");
    if (selectedRoomId) roomSelect.value = selectedRoomId;
  }

  function syncSmartAddSubjectDetails() {
    const subSelect = document.getElementById("smart-add-subject");
    const divSelect = document.getElementById("smart-add-division");
    const newBox = document.getElementById("smart-add-new-subject-box");
    if (!subSelect || !divSelect) return;

    const subId = subSelect.value;
    if (subId === "__NEW__") {
      if (newBox) newBox.classList.remove("hidden");
      return;
    }
    if (newBox) newBox.classList.add("hidden");

    const divId = divSelect.value;
    const sub = state.subjects.find((s) => s.id === subId);
    if (!sub) return;

    if (sub.weekly_lectures) {
      const countInput = document.getElementById("smart-add-count");
      if (countInput) countInput.value = sub.weekly_lectures;
    }

    const assignedFacId = getAssignedFacultyForDivisionAndSubject(divId, subId);
    const facSelect = document.getElementById("smart-add-faculty");
    if (facSelect) {
      if (assignedFacId) {
        facSelect.value = assignedFacId;
      } else {
        facSelect.value = "AUTO";
      }
    }

    const suggestedRoomId = getSuggestedRoomForSubjectAndDivision(sub, divId);
    const roomSelect = document.getElementById("smart-add-room");
    if (roomSelect && suggestedRoomId) {
      roomSelect.value = suggestedRoomId;
    }
  }

  const btnOpenSmartAdd = document.getElementById("btn-open-smart-add-lecture");
  if (btnOpenSmartAdd) {
    btnOpenSmartAdd.addEventListener("click", () => {
      openSmartAddLectureModal();
    });
  }

  const smartYear = document.getElementById("smart-add-year");
  if (smartYear) {
    smartYear.addEventListener("change", (e) => {
      updateSmartAddDivisions(e.target.value);
      const divId = document.getElementById("smart-add-division")?.value;
      updateSmartAddSubjects(e.target.value, divId);
    });
  }

  const smartDiv = document.getElementById("smart-add-division");
  if (smartDiv) {
    smartDiv.addEventListener("change", (e) => {
      const year = document.getElementById("smart-add-year")?.value;
      updateSmartAddBatches(e.target.value);
      updateSmartAddSubjects(year, e.target.value);
    });
  }

  const smartSub = document.getElementById("smart-add-subject");
  if (smartSub) {
    smartSub.addEventListener("change", () => {
      syncSmartAddSubjectDetails();
    });
  }

  function renderCandidateSlotsList(slots) {
    if (!slots || slots.length === 0) return "<p class='text-muted'>No slots found.</p>";
    return slots
      .map(
        (s, idx) => `
        <div class="smart-slot-item">
          <div>
            <strong>#${idx + 1} 📅 ${s.day}</strong> &bull; 🕒 ${s.start_time} - ${s.end_time} (${s.duration_minutes || 60}m)
            <div style="font-size:11px; color:#475569; margin-top:2px;">
              👨‍🏫 ${s.faculty_name} &bull; 📍 ${s.room_name} ${s.batch_name ? `&bull; 🏷️ ${s.batch_name}` : ""}
            </div>
          </div>
          <span class="smart-slot-badge">Conflict-Free</span>
        </div>
      `
      )
      .join("");
  }

  // Find Suitable Conflict-Free Slots Button
  const btnSmartFind = document.getElementById("btn-smart-add-find");
  if (btnSmartFind) {
    btnSmartFind.addEventListener("click", async () => {
      let subId = document.getElementById("smart-add-subject").value;
      const divId = document.getElementById("smart-add-division").value;
      const yearId = document.getElementById("smart-add-year").value;
      const batchId = document.getElementById("smart-add-batch").value || null;
      const count = parseInt(document.getElementById("smart-add-count").value) || 1;
      let facId = document.getElementById("smart-add-faculty").value;
      let roomId = document.getElementById("smart-add-room").value;

      if (!subId || !divId) {
        showBanner("Please select both Subject and Division.", "warning");
        return;
      }

      if (subId === "__NEW__") {
        const newName = (document.getElementById("smart-add-new-sub-name")?.value || "").trim();
        if (!newName) {
          showBanner("Please enter a name for the new subject.", "warning");
          return;
        }
        const newCode = (document.getElementById("smart-add-new-sub-code")?.value || "").trim();
        const newType = document.getElementById("smart-add-new-sub-type")?.value || "Theory";
        const dur = newType === "Practical" ? 120 : 60;
        const reqRoomType = newType === "Practical" ? "Laboratory" : "Classroom";

        try {
          const createRes = await fetch("/api/subjects", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              name: newName,
              code: newCode,
              year_id: yearId,
              division_ids: [divId],
              type: newType,
              weekly_lectures: newType === "Practical" ? 1 : 3,
              duration_minutes: dur,
              eligible_faculty_ids: facId && facId !== "AUTO" ? [facId] : [],
              required_room_type: reqRoomType,
            }),
          });
          const createData = await createRes.json();
          if (!createRes.ok || !createData.subject) {
            showBanner(createData.error || "Failed to create new subject.", "danger");
            return;
          }
          state.subjects.push(createData.subject);
          subId = createData.subject.id;
        } catch (err) {
          showBanner("Error creating new subject on server.", "danger");
          return;
        }
      }

      if (!subId || !divId) {
        showBanner("Please select both Subject and Division.", "warning");
        return;
      }

      btnSmartFind.disabled = true;
      btnSmartFind.textContent = "⏳ Searching Slots...";

      try {
        const res = await fetch("/api/timetable/smart-add-lectures", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            subject_id: subId,
            division_id: divId,
            batch_id: batchId,
            count: count,
            faculty_id: facId,
            room_id: roomId,
            commit: false,
          }),
        });

        btnSmartFind.disabled = false;
        btnSmartFind.textContent = "🔍 Find Suitable Slots";

        const data = await res.json();
        if (!res.ok) {
          showBanner(data.error || "Failed to search for candidate slots.", "danger");
          return;
        }

        state.smartCandidateSlots = data.candidate_slots || [];
        const previewBox = document.getElementById("smart-add-preview-box");
        const statusEl = document.getElementById("smart-add-preview-status");
        const msgEl = document.getElementById("smart-add-preview-msg");
        const listEl = document.getElementById("smart-add-slots-list");
        const confirmBtn = document.getElementById("btn-smart-add-confirm");

        previewBox.classList.remove("hidden");

        if (data.found_count === 0) {
          statusEl.innerHTML = `<span class="text-danger">❌ No Suitable Conflict-Free Slots Available</span>`;
          msgEl.textContent = data.unallocated_reason || "All potential slots across working days clash with existing division or faculty schedules.";
          listEl.innerHTML = "";
          confirmBtn.classList.add("hidden");
        } else if (data.unallocated_count > 0) {
          statusEl.innerHTML = `<span style="color:#d97706;">⚠️ Found ${data.found_count} of ${data.requested_count} Requested Slots (${data.unallocated_count} Unavailable)</span>`;
          msgEl.innerHTML = `<strong>Note:</strong> ${data.unallocated_reason}<br>You can confirm and accept the ${data.found_count} available slot(s) below:`;
          listEl.innerHTML = renderCandidateSlotsList(state.smartCandidateSlots);
          confirmBtn.textContent = `✅ Accept & Add Available (${data.found_count} Slots)`;
          confirmBtn.classList.remove("hidden");
        } else {
          statusEl.innerHTML = `<span style="color:#16a34a;">✅ Found All ${data.found_count} Conflict-Free Slots</span>`;
          msgEl.textContent = `All requested lectures can be scheduled cleanly without any clashes. Review proposed slots and click accept below:`;
          listEl.innerHTML = renderCandidateSlotsList(state.smartCandidateSlots);
          confirmBtn.textContent = `✅ Accept & Add All (${data.found_count} Slots)`;
          confirmBtn.classList.remove("hidden");
        }
      } catch (err) {
        btnSmartFind.disabled = false;
        btnSmartFind.textContent = "🔍 Find Suitable Slots";
        console.error("Smart add preview error:", err);
        showBanner("Server connection error during slot search.", "danger");
      }
    });
  }

  // Accept & Commit Found Slots
  const formSmartAdd = document.getElementById("form-smart-add-lecture");
  if (formSmartAdd) {
    formSmartAdd.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!state.smartCandidateSlots || state.smartCandidateSlots.length === 0) {
        document.getElementById("btn-smart-add-find").click();
        return;
      }

      const confirmBtn = document.getElementById("btn-smart-add-confirm");
      confirmBtn.disabled = true;
      confirmBtn.textContent = "⏳ Adding Slots...";

      try {
        const res = await fetch("/api/timetable/smart-add-lectures", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            subject_id: document.getElementById("smart-add-subject").value,
            division_id: document.getElementById("smart-add-division").value,
            batch_id: document.getElementById("smart-add-batch").value || null,
            commit: true,
            candidate_slots: state.smartCandidateSlots,
          }),
        });

        confirmBtn.disabled = false;
        confirmBtn.textContent = "✅ Accept & Add Slots";

        const data = await res.json();
        if (!res.ok) {
          showBanner(data.error || "Failed to commit scheduled lectures.", "danger");
          return;
        }

        closeModal("modal-smart-add-lecture");
        showBanner(`🎉 Added ${data.added_count} lecture(s) successfully without clashes!`, "success");
        await refreshAllData();
      } catch (err) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = "✅ Accept & Add Slots";
        console.error("Smart add commit error:", err);
        showBanner("Failed to save scheduled lectures.", "danger");
      }
    });
  }

  // Export Timetable Dropdown & Actions
  const btnExportDropdown = document.getElementById("btn-export-dropdown");
  const exportDropdownMenu = document.getElementById("export-dropdown-menu");
  const btnExportPng = document.getElementById("btn-export-png");
  const btnExportPdf = document.getElementById("btn-export-pdf");

  if (btnExportDropdown && exportDropdownMenu) {
    btnExportDropdown.addEventListener("click", (e) => {
      e.stopPropagation();
      exportDropdownMenu.classList.toggle("hidden");
    });

    document.addEventListener("click", (e) => {
      if (!btnExportDropdown.contains(e.target) && !exportDropdownMenu.contains(e.target)) {
        exportDropdownMenu.classList.add("hidden");
      }
    });
  }

  if (btnExportPng) {
    btnExportPng.addEventListener("click", (e) => {
      e.stopPropagation();
      if (exportDropdownMenu) exportDropdownMenu.classList.add("hidden");
      exportTimetable("png");
    });
  }

  if (btnExportPdf) {
    btnExportPdf.addEventListener("click", (e) => {
      e.stopPropagation();
      if (exportDropdownMenu) exportDropdownMenu.classList.add("hidden");
      exportTimetable("pdf");
    });
  }

  // Workload and Consecutive Rule Toggles
  const masterWorkloadChk = document.getElementById("set-enforce-workload-limits");
  const workloadRuleDefs = [
    { checkId: "check-max-fac-day", inputId: "set-max-fac-day", badgeId: "badge-fac-day-status" },
    { checkId: "check-max-fac-daily-hours", inputId: "set-max-fac-daily-hours", badgeId: "badge-fac-hours-status" },
    { checkId: "check-max-fac-weekly-hours", inputId: "set-max-fac-weekly-hours", badgeId: "badge-fac-weekly-status" },
    { checkId: "check-max-fac-consecutive", inputId: "set-max-fac-consecutive", badgeId: "badge-fac-consec-status" },
    { checkId: "check-max-div-day", inputId: "set-max-div-day", badgeId: "badge-div-day-status" },
    { checkId: "check-min-div-day", inputId: "set-min-div-day", badgeId: "badge-div-min-status" },
    { checkId: "check-max-div-consecutive", inputId: "set-max-div-consecutive", badgeId: "badge-div-consec-status" },
  ];

  if (masterWorkloadChk) {
    masterWorkloadChk.addEventListener("change", () => {
      const isMasterOn = masterWorkloadChk.checked;
      workloadRuleDefs.forEach((r) => {
        updateRuleUI(
          document.getElementById(r.checkId),
          document.getElementById(r.inputId),
          document.getElementById(r.badgeId),
          isMasterOn
        );
      });
    });
  }

  workloadRuleDefs.forEach((r) => {
    const chk = document.getElementById(r.checkId);
    if (chk) {
      chk.addEventListener("change", () => {
        const isMasterOn = masterWorkloadChk ? masterWorkloadChk.checked : true;
        updateRuleUI(
          chk,
          document.getElementById(r.inputId),
          document.getElementById(r.badgeId),
          isMasterOn
        );
      });
    }
  });

  // Save Settings
  document.getElementById("btn-save-settings").addEventListener("click", async () => {
    const selectedDays = [];
    document.querySelectorAll("#settings-working-days input:checked").forEach((cb) => {
      selectedDays.push(cb.value);
    });

    const masterChk = document.getElementById("set-enforce-workload-limits");
    const payload = {
      working_days: selectedDays,
      day_start_time: document.getElementById("set-day-start").value,
      day_end_time: document.getElementById("set-day-end").value,
      default_lecture_duration: parseInt(document.getElementById("set-default-duration").value) || 60,
      default_lab_duration: parseInt(document.getElementById("set-default-lab-duration").value) || 120,
      breaks: [
        {
          name: (document.getElementById("set-break-name") && document.getElementById("set-break-name").value.trim()) || "Lunch Break",
          start: document.getElementById("set-break-start").value,
          end: document.getElementById("set-break-end").value,
          type: "lunch",
        },
      ],
      enforce_workload_limits: masterChk ? masterChk.checked : true,
      enforce_faculty_daily_limit: document.getElementById("check-max-fac-day") ? document.getElementById("check-max-fac-day").checked : true,
      enforce_faculty_daily_hours: document.getElementById("check-max-fac-daily-hours") ? document.getElementById("check-max-fac-daily-hours").checked : true,
      enforce_faculty_weekly_hours: document.getElementById("check-max-fac-weekly-hours") ? document.getElementById("check-max-fac-weekly-hours").checked : true,
      enforce_faculty_consecutive: document.getElementById("check-max-fac-consecutive") ? document.getElementById("check-max-fac-consecutive").checked : true,
      enforce_division_daily_limit: document.getElementById("check-max-div-day") ? document.getElementById("check-max-div-day").checked : true,
      enforce_min_division_daily_limit: document.getElementById("check-min-div-day") ? document.getElementById("check-min-div-day").checked : true,
      enforce_division_consecutive: document.getElementById("check-max-div-consecutive") ? document.getElementById("check-max-div-consecutive").checked : true,
      max_lectures_per_faculty_per_day: parseInt(document.getElementById("set-max-fac-day").value),
      max_daily_faculty_workload: parseFloat(document.getElementById("set-max-fac-daily-hours").value),
      max_weekly_faculty_workload: parseFloat(document.getElementById("set-max-fac-weekly-hours").value),
      max_consecutive_faculty_lectures: parseInt(document.getElementById("set-max-fac-consecutive").value),
      max_lectures_per_division_per_day: parseInt(document.getElementById("set-max-div-day").value),
      min_lectures_per_division_per_day: document.getElementById("set-min-div-day") ? parseInt(document.getElementById("set-min-div-day").value) : 3,
      max_consecutive_division_lectures: parseInt(document.getElementById("set-max-div-consecutive").value),
    };

    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      showBanner("Settings saved successfully!", "success");
      await refreshAllData();
    } else {
      const data = await res.json();
      showBanner(data.error || "Failed to save settings.", "danger");
    }
  });

  // Jump to Backup & Restore in Settings
  const btnJumpBackup = document.getElementById("btn-jump-backup-import");
  if (btnJumpBackup) {
    btnJumpBackup.addEventListener("click", () => {
      const targetCard = document.getElementById("card-data-management");
      if (targetCard) {
        targetCard.scrollIntoView({ behavior: "smooth", block: "start" });
        targetCard.style.outline = "2px solid #0f172a";
        targetCard.style.outlineOffset = "4px";
        setTimeout(() => {
          targetCard.style.outline = "";
          targetCard.style.outlineOffset = "";
        }, 1800);
      }
    });
  }

  // Forms
  document.getElementById("form-add-faculty").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("fac-input-name").value.trim();
    const floorSelect = document.getElementById("fac-input-floor");
    const staff_room_floor_id = floorSelect ? floorSelect.value || null : null;

    const res = await fetch("/api/faculty", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, staff_room_floor_id }),
    });
    if (res.ok) {
      closeModal("modal-add-faculty");
      document.getElementById("fac-input-name").value = "";
      if (floorSelect) floorSelect.value = "";
      showBanner("Faculty added successfully!", "success");
      await refreshAllData();
    } else {
      const d = await res.json();
      alert(d.error || "Failed to add faculty.");
    }
  });

  document.getElementById("form-rename-faculty").addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = document.getElementById("fac-rename-id").value;
    const name = document.getElementById("fac-rename-name").value.trim();
    const floorSelect = document.getElementById("fac-rename-floor");
    const staff_room_floor_id = floorSelect ? floorSelect.value || null : null;

    const res = await fetch(`/api/faculty/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, staff_room_floor_id }),
    });
    if (res.ok) {
      closeModal("modal-rename-faculty");
      showBanner("Faculty updated successfully.", "success");
      await refreshAllData();
    }
  });

  document.getElementById("form-edit-lecture").addEventListener("submit", handleSaveLectureEdit);
  document.getElementById("btn-delete-entry").addEventListener("click", handleDeleteLecture);

  // Dynamic controls for modal-edit-lecture: filter subjects by division and auto-map faculty/room
  const editYearSelect = document.getElementById("edit-year");
  const editDivSelect = document.getElementById("edit-division");
  const editBatchSelect = document.getElementById("edit-batch");
  const editSubSelect = document.getElementById("edit-subject");
  const editStartTime = document.getElementById("edit-start-time");

  if (editYearSelect) {
    editYearSelect.addEventListener("change", (e) => {
      const year = e.target.value;
      updateEditDivisions(year);
      const divId = document.getElementById("edit-division")?.value;
      updateEditBatches(divId);
      updateEditSubjects(year, divId);
      syncEditSubjectSelection();
    });
  }

  if (editDivSelect) {
    editDivSelect.addEventListener("change", (e) => {
      const divId = e.target.value;
      const year = document.getElementById("edit-year")?.value;
      updateEditBatches(divId);
      updateEditSubjects(year, divId);
      syncEditSubjectSelection();
    });
  }

  if (editBatchSelect) {
    editBatchSelect.addEventListener("change", () => {
      syncEditSubjectSelection();
    });
  }

  if (editSubSelect) {
    editSubSelect.addEventListener("change", () => {
      syncEditSubjectSelection();
    });
  }

  if (editStartTime) {
    editStartTime.addEventListener("input", () => {
      syncEditSubjectSelection();
    });
  }

  // Modal open buttons
  document.getElementById("btn-open-add-faculty").addEventListener("click", () => {
    const floorSelect = document.getElementById("fac-input-floor");
    if (floorSelect) floorSelect.value = "";
    openModal("modal-add-faculty");
  });
  document.getElementById("btn-open-add-room").addEventListener("click", () => {
    openAddRoomModal("");
  });
  document.getElementById("btn-open-add-division").addEventListener("click", () => {
    updateDivAutoSplitPreview();
    const floorSelect = document.getElementById("div-input-floor");
    if (floorSelect) {
      floorSelect.innerHTML =
        `<option value="">None (Flexible / Any Floor)</option>` +
        (state.floors || [])
          .map((f) => `<option value="${f.id}">📍 ${f.name} (Level ${f.floor_number})</option>`)
          .join("");
      floorSelect.value = "";
    }
    openModal("modal-add-division");
  });

  document.getElementById("div-auto-split").addEventListener("change", (e) => {
    document.getElementById("div-auto-split-options").style.display = e.target.checked ? "block" : "none";
  });

  ["input", "change"].forEach(evt => {
    document.getElementById("div-input-name").addEventListener(evt, updateDivAutoSplitPreview);
    document.getElementById("div-input-capacity").addEventListener(evt, updateDivAutoSplitPreview);
    document.getElementById("div-split-parts").addEventListener(evt, updateDivAutoSplitPreview);
  });

  document.getElementById("btn-open-auto-split").addEventListener("click", () => {
    const sel = document.getElementById("split-input-division");
    sel.innerHTML = state.divisions.map((d) => `<option value="${d.id}">${d.year_id} - ${d.name} (${d.capacity || 70} students)</option>`).join("");
    updateAutoSplitModalPreview();
    openModal("modal-auto-split-batches");
  });

  ["input", "change"].forEach(evt => {
    document.getElementById("split-input-division").addEventListener(evt, updateAutoSplitModalPreview);
    document.getElementById("split-input-parts").addEventListener(evt, updateAutoSplitModalPreview);
    document.getElementById("split-input-prefix").addEventListener(evt, updateAutoSplitModalPreview);
  });

  document.getElementById("form-auto-split-batches").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      division_id: document.getElementById("split-input-division").value,
      num_parts: parseInt(document.getElementById("split-input-parts").value),
      prefix: document.getElementById("split-input-prefix").value.trim(),
    };

    const res = await fetch("/api/batches/auto-split", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      const data = await res.json();
      closeModal("modal-auto-split-batches");
      showBanner(data.message, "success");
      await refreshAllData();
    } else {
      const d = await res.json();
      alert(d.error || "Failed to auto-split batches.");
    }
  });

  document.getElementById("btn-open-add-batch").addEventListener("click", () => {
    const sel = document.getElementById("batch-input-division");
    sel.innerHTML = state.divisions.map((d) => `<option value="${d.id}">${d.year_id} - ${d.name}</option>`).join("");
    openModal("modal-add-batch");
  });

  // -------------------------------------------------------------
  // Faculty Multi-Select Component for Subject Modal
  // -------------------------------------------------------------
  function renderFacultyMultiSelect(selectedIds = []) {
    const container = document.getElementById("sub-faculty-container");
    if (!container) return;

    const countBadge = document.getElementById("sub-faculty-count-badge");
    const searchInput = document.getElementById("sub-faculty-search");
    if (searchInput) searchInput.value = "";

    const selectedSet = new Set(selectedIds || []);

    container.innerHTML = state.faculty
      .map((f) => {
        const isChecked = selectedSet.has(f.id);
        return `
        <div class="faculty-select-card ${isChecked ? "selected" : ""}" data-faculty-id="${f.id}" data-name="${(f.name || "").toLowerCase()}" data-dept="${(f.department || "").toLowerCase()}">
          <input type="checkbox" id="sub-fac-cb-${f.id}" class="sub-fac-checkbox" value="${f.id}" ${isChecked ? "checked" : ""}>
          <label for="sub-fac-cb-${f.id}" class="faculty-select-label">
            <div class="fac-avatar">👨‍🏫</div>
            <div class="fac-details">
              <div class="fac-name">
                <span>${f.name}</span>
                ${f.department ? `<span class="fac-dept">(${f.department})</span>` : ""}
              </div>
              <div class="fac-subtext">
                Max ${f.max_weekly_hours || 18} hrs/wk • ${f.designation || "Faculty"}
              </div>
            </div>
          </label>
        </div>
      `;
      })
      .join("");

    const updateCount = () => {
      const checked = container.querySelectorAll("input.sub-fac-checkbox:checked");
      if (countBadge) {
        countBadge.textContent = `${checked.length} selected`;
        countBadge.className = checked.length > 0 ? "badge badge-primary" : "badge badge-info";
      }
    };

    updateCount();

    // Smooth card click to toggle checkbox
    container.querySelectorAll(".faculty-select-card").forEach((card) => {
      card.addEventListener("click", (e) => {
        if (e.target.tagName.toLowerCase() === "input") {
          card.classList.toggle("selected", e.target.checked);
          updateCount();
          return;
        }
        e.preventDefault();
        const cb = card.querySelector("input.sub-fac-checkbox");
        if (cb) {
          cb.checked = !cb.checked;
          card.classList.toggle("selected", cb.checked);
          updateCount();
        }
      });
    });
  }
  window.renderFacultyMultiSelect = renderFacultyMultiSelect;

  // Setup Select All / Clear All / Search for Faculty Multi-select
  const btnSelectAll = document.getElementById("btn-sub-fac-select-all");
  if (btnSelectAll) {
    btnSelectAll.addEventListener("click", () => {
      const cards = document.querySelectorAll("#sub-faculty-container .faculty-select-card");
      cards.forEach((card) => {
        if (card.style.display !== "none") {
          const cb = card.querySelector("input.sub-fac-checkbox");
          if (cb) {
            cb.checked = true;
            card.classList.add("selected");
          }
        }
      });
      const checked = document.querySelectorAll("#sub-faculty-container input.sub-fac-checkbox:checked");
      const badge = document.getElementById("sub-faculty-count-badge");
      if (badge) {
        badge.textContent = `${checked.length} selected`;
        badge.className = checked.length > 0 ? "badge badge-primary" : "badge badge-info";
      }
    });
  }

  const btnClearAll = document.getElementById("btn-sub-fac-clear-all");
  if (btnClearAll) {
    btnClearAll.addEventListener("click", () => {
      const cards = document.querySelectorAll("#sub-faculty-container .faculty-select-card");
      cards.forEach((card) => {
        const cb = card.querySelector("input.sub-fac-checkbox");
        if (cb) {
          cb.checked = false;
          card.classList.remove("selected");
        }
      });
      const badge = document.getElementById("sub-faculty-count-badge");
      if (badge) {
        badge.textContent = "0 selected";
        badge.className = "badge badge-info";
      }
    });
  }

  const facSearchInput = document.getElementById("sub-faculty-search");
  if (facSearchInput) {
    facSearchInput.addEventListener("input", (e) => {
      const q = e.target.value.toLowerCase().trim();
      const cards = document.querySelectorAll("#sub-faculty-container .faculty-select-card");
      cards.forEach((card) => {
        const name = card.getAttribute("data-name") || "";
        const dept = card.getAttribute("data-dept") || "";
        if (!q || name.includes(q) || dept.includes(q)) {
          card.style.display = "flex";
        } else {
          card.style.display = "none";
        }
      });
    });
  }

  document.getElementById("btn-open-add-subject").addEventListener("click", () => {
    const titleEl = document.getElementById("modal-subject-title");
    if (titleEl) titleEl.textContent = "Add Subject";
    document.getElementById("sub-id").value = "";

    // Populate divisions checkboxes for FY default
    const divCheckboxes = document.getElementById("sub-divisions-checkboxes");
    const yearDivs = state.divisions.filter((d) => d.year_id === "FY");
    divCheckboxes.innerHTML = (yearDivs.length ? yearDivs : state.divisions)
      .map(
        (d) => `
      <label><input type="checkbox" value="${d.id}"> ${d.year_id} ${d.name}</label>
    `
      )
      .join("");

    // Populate faculty multi-select
    renderFacultyMultiSelect([]);

    // Reset defaults
    document.getElementById("sub-name").value = "";
    document.getElementById("sub-code").value = "";
    document.getElementById("sub-year").value = "FY";
    document.getElementById("sub-type").value = "Theory";
    document.getElementById("sub-duration").value = String(state.settings.default_lecture_duration || 60);
    document.getElementById("sub-room-type").value = "Classroom";
    const isElectiveCb = document.getElementById("sub-is-elective");
    if (isElectiveCb) isElectiveCb.checked = false;
    toggleElectiveGroupsContainer();
    renderElectiveGroups([]);
    const hint = document.getElementById("sub-type-hint");
    if (hint) hint.textContent = "Entire division in Classroom";

    openModal("modal-subject");
  });

  const subYearSelect = document.getElementById("sub-year");
  if (subYearSelect) {
    subYearSelect.addEventListener("change", (e) => {
      const y = e.target.value;
      const subId = document.getElementById("sub-id").value;
      const sub = subId ? state.subjects.find((s) => s.id === subId) : null;
      const selDivIds = sub ? (sub.division_ids || []) : [];

      const divCheckboxes = document.getElementById("sub-divisions-checkboxes");
      const yearDivs = state.divisions.filter((d) => d.year_id === y);
      divCheckboxes.innerHTML = (yearDivs.length ? yearDivs : state.divisions)
        .map(
          (d) => `
        <label><input type="checkbox" value="${d.id}" ${selDivIds.includes(d.id) ? "checked" : ""}> ${d.year_id} ${d.name}</label>
      `
        )
        .join("");
    });
  }

  const subTypeSelect = document.getElementById("sub-type");
  if (subTypeSelect) {
    subTypeSelect.addEventListener("change", (e) => {
      const val = e.target.value;
      const durSelect = document.getElementById("sub-duration");
      const roomSelect = document.getElementById("sub-room-type");
      const hint = document.getElementById("sub-type-hint");
      const isElectiveCb = document.getElementById("sub-is-elective");

      if (val === "Practical") {
        durSelect.value = String(state.settings.default_lab_duration || 120);
        roomSelect.value = "Laboratory";
        if (hint) hint.textContent = "⚡ Practical sessions automatically divide into batches in Laboratories.";
        if (isElectiveCb) isElectiveCb.checked = false;
      } else if (val === "Elective") {
        durSelect.value = String(state.settings.default_lecture_duration || 60);
        roomSelect.value = "Classroom";
        if (isElectiveCb) isElectiveCb.checked = true;
        if (hint) hint.textContent = "📚 MDM Elective with fixed room reservation per elective group.";
      } else if (val === "Other") {
        durSelect.value = String(state.settings.default_lecture_duration || 60);
        roomSelect.value = "Classroom";
        if (hint) hint.textContent = "ℹ️ Other sessions (Tutorials, Seminars, Projects) for the whole division.";
        if (isElectiveCb) isElectiveCb.checked = false;
      } else {
        durSelect.value = String(state.settings.default_lecture_duration || 60);
        roomSelect.value = "Classroom";
        if (hint) hint.textContent = "📘 Theory sessions for the whole division in Classrooms.";
      }
      toggleElectiveGroupsContainer();
    });
  }

  const isElectiveCb = document.getElementById("sub-is-elective");
  if (isElectiveCb) {
    isElectiveCb.addEventListener("change", (e) => {
      if (e.target.checked && document.getElementById("sub-type").value !== "Elective") {
        document.getElementById("sub-type").value = "Elective";
      }
      toggleElectiveGroupsContainer();
    });
  }

  const btnAddEgrp = document.getElementById("btn-add-elective-group");
  if (btnAddEgrp) {
    btnAddEgrp.addEventListener("click", () => {
      addElectiveGroupRow({ name: `Group ${(document.querySelectorAll('.elective-group-row').length + 1)}` });
    });
  }

  document.getElementById("form-subject").addEventListener("submit", async (e) => {
    e.preventDefault();
    const subId = document.getElementById("sub-id").value;
    const isEdit = Boolean(subId);

    const divIds = [];
    document.querySelectorAll("#sub-divisions-checkboxes input:checked").forEach((cb) => {
      divIds.push(cb.value);
    });

    const eligibleFacIds = Array.from(
      document.querySelectorAll("#sub-faculty-container input.sub-fac-checkbox:checked")
    ).map((cb) => cb.value);

    const sType = document.getElementById("sub-type").value;
    const isElective = Boolean(
      document.getElementById("sub-is-elective")?.checked || sType === "Elective"
    );

    const electiveGroups = [];
    if (isElective) {
      document.querySelectorAll(".elective-group-row").forEach((row) => {
        const gName = row.querySelector(".egrp-name")?.value.trim();
        const gRoom = row.querySelector(".egrp-room")?.value;
        const gFac = row.querySelector(".egrp-faculty")?.value;
        const gCap = parseInt(row.querySelector(".egrp-cap")?.value) || 40;
        const gWk = parseInt(row.querySelector(".egrp-weekly")?.value) || parseInt(document.getElementById("sub-weekly-lec").value) || 3;
        if (gName && gRoom) {
          electiveGroups.push({
            name: gName,
            fixed_room_id: gRoom,
            faculty_id: gFac || null,
            student_capacity: gCap,
            weekly_lectures: gWk,
            duration_minutes: parseInt(document.getElementById("sub-duration").value) || 60,
          });
        }
      });
      if (electiveGroups.length === 0) {
        showBanner("Please add at least one Elective Group with an assigned Fixed Room.", "warning");
        return;
      }
    }

    const payload = {
      name: document.getElementById("sub-name").value.trim(),
      code: document.getElementById("sub-code").value.trim(),
      year_id: document.getElementById("sub-year").value,
      division_ids: divIds,
      weekly_lectures: parseInt(document.getElementById("sub-weekly-lec").value),
      duration_minutes: parseInt(document.getElementById("sub-duration").value),
      type: sType,
      eligible_faculty_ids: eligibleFacIds,
      required_room_type: document.getElementById("sub-room-type").value,
      lab_batch_required: sType === "Practical",
      is_elective: isElective,
      elective_groups: electiveGroups,
    };

    const url = isEdit ? `/api/subjects/${subId}` : "/api/subjects";
    const method = isEdit ? "PUT" : "POST";

    const res = await fetch(url, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      closeModal("modal-subject");
      showBanner(isEdit ? "Subject updated successfully!" : "Subject added successfully!", "success");
      await refreshAllData();
    } else {
      const d = await res.json();
      showBanner(d.error || "Failed to save subject.", "danger");
    }
  });

  document.getElementById("btn-open-assign-faculty").addEventListener("click", () => {
    const facSelect = document.getElementById("asgn-faculty");
    facSelect.innerHTML = state.faculty
      .map((f) => `<option value="${f.id}">${f.name}</option>`)
      .join("");

    const subSelect = document.getElementById("asgn-subject");
    subSelect.innerHTML = state.subjects
      .map((s) => `<option value="${s.id}">${s.year_id} - ${s.name} (${s.type})</option>`)
      .join("");

    const divSelect = document.getElementById("asgn-division");
    const batchSelect = document.getElementById("asgn-batch");

    const updateDivAndBatchOptions = () => {
      const selectedSubId = subSelect.value;
      const sub = state.subjects.find((s) => s.id === selectedSubId);
      const subYear = sub ? sub.year_id : null;
      const targetDivs = subYear ? state.divisions.filter((d) => d.year_id === subYear) : state.divisions;

      divSelect.innerHTML =
        `<option value="">All Applicable Divisions</option>` +
        targetDivs.map((d) => `<option value="${d.id}">${d.year_id} - ${d.name}</option>`).join("");

      if (batchSelect) {
        const selectedDivId = divSelect.value;
        const targetBatches = selectedDivId
          ? state.batches.filter((b) => b.division_id === selectedDivId)
          : (subYear ? state.batches.filter((b) => targetDivs.some((d) => d.id === b.division_id)) : state.batches);
        batchSelect.innerHTML =
          `<option value="">All Batches / Full Division</option>` +
          targetBatches.map((b) => `<option value="${b.id}">${b.name}</option>`).join("");
      }
    };

    subSelect.onchange = updateDivAndBatchOptions;
    divSelect.onchange = () => {
      if (batchSelect) {
        const selectedDivId = divSelect.value;
        const targetBatches = selectedDivId
          ? state.batches.filter((b) => b.division_id === selectedDivId)
          : state.batches;
        batchSelect.innerHTML =
          `<option value="">All Batches / Full Division</option>` +
          targetBatches.map((b) => `<option value="${b.id}">${b.name}</option>`).join("");
      }
    };

    updateDivAndBatchOptions();

    openModal("modal-assign-faculty");
  });

  document.getElementById("form-assign-faculty").addEventListener("submit", async (e) => {
    e.preventDefault();
    const subId = document.getElementById("asgn-subject").value;
    const sub = state.subjects.find((s) => s.id === subId);

    const payload = {
      faculty_id: document.getElementById("asgn-faculty").value,
      subject_id: subId,
      year_id: sub ? sub.year_id : "",
      division_id: document.getElementById("asgn-division").value || null,
      batch_id: document.getElementById("asgn-batch").value || null,
    };

    const res = await fetch("/api/faculty-assignments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      closeModal("modal-assign-faculty");
      showBanner("Assignment saved successfully!", "success");
      await refreshAllData();
    }
  });

  document.getElementById("form-add-division").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      year_id: document.getElementById("div-input-year").value,
      name: document.getElementById("div-input-name").value.trim(),
      capacity: parseInt(document.getElementById("div-input-capacity").value) || 70,
      floor_id: document.getElementById("div-input-floor").value || null,
      auto_split: document.getElementById("div-auto-split").checked,
      num_parts: parseInt(document.getElementById("div-split-parts").value) || 3,
    };
    const res = await fetch("/api/divisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      closeModal("modal-add-division");
      document.getElementById("div-input-name").value = "";
      showBanner("Division added.", "success");
      await refreshAllData();
    }
  });

  const formEditDiv = document.getElementById("form-edit-division");
  if (formEditDiv) {
    formEditDiv.addEventListener("submit", async (e) => {
      e.preventDefault();
      const divId = document.getElementById("edit-div-id").value;
      const payload = {
        name: document.getElementById("edit-div-name").value.trim(),
        capacity: parseInt(document.getElementById("edit-div-capacity").value) || 70,
        floor_id: document.getElementById("edit-div-floor").value || null,
      };
      try {
        const res = await fetch(`/api/divisions/${divId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (res.ok) {
          closeModal("modal-edit-division");
          showBanner("Division updated successfully.", "success");
          await refreshAllData();
        } else {
          const d = await res.json();
          showBanner(d.error || "Failed to update division.", "danger");
        }
      } catch (err) {
        console.error("Edit division error:", err);
        showBanner("Failed to update division.", "danger");
      }
    });
  }

  document.getElementById("form-add-batch").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      division_id: document.getElementById("batch-input-division").value,
      name: document.getElementById("batch-input-name").value.trim(),
      capacity: parseInt(document.getElementById("batch-input-capacity").value) || 25,
    };
    const res = await fetch("/api/batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      closeModal("modal-add-batch");
      document.getElementById("batch-input-name").value = "";
      showBanner("Batch added.", "success");
      await refreshAllData();
    }
  });

  document.getElementById("form-add-room").addEventListener("submit", async (e) => {
    e.preventDefault();
    const roomId = document.getElementById("room-input-id").value;

    const floorSelect = document.getElementById("room-input-floor");
    const seqInput = document.getElementById("room-input-sequence");
    const clusterInput = document.getElementById("room-input-cluster");

    const payload = {
      name: document.getElementById("room-input-name").value.trim(),
      type: document.getElementById("room-input-type").value,
      capacity: parseInt(document.getElementById("room-input-capacity").value) || 70,
      floor_id: floorSelect ? floorSelect.value || null : null,
      sequence_order: seqInput && seqInput.value ? parseInt(seqInput.value) : null,
      cluster_id: clusterInput && clusterInput.value.trim() ? clusterInput.value.trim() : null,
    };

    const url = roomId ? `/api/rooms/${roomId}` : "/api/rooms";
    const method = roomId ? "PUT" : "POST";

    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      closeModal("modal-add-room");
      document.getElementById("room-input-name").value = "";
      document.getElementById("room-input-id").value = "";
      showBanner(roomId ? "Room updated successfully!" : "Room added successfully!", "success");
      await refreshAllData();
    } else {
      const d = await res.json();
      showBanner(d.error || "Failed to save room.", "danger");
    }
  });

  // Floor Form
  const formFloor = document.getElementById("form-floor");
  if (formFloor) {
    formFloor.addEventListener("submit", async (e) => {
      e.preventDefault();
      const floorId = document.getElementById("floor-input-id").value;
      const payload = {
        name: document.getElementById("floor-input-name").value.trim(),
        floor_number: parseInt(document.getElementById("floor-input-number").value) || 1,
        sequence_order: parseInt(document.getElementById("floor-input-sequence").value) || 1,
      };

      const url = floorId ? `/api/floors/${floorId}` : "/api/floors";
      const method = floorId ? "PUT" : "POST";

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        closeModal("modal-floor");
        showBanner(floorId ? "Floor updated successfully!" : "Floor added successfully!", "success");
        await refreshAllData();
      } else {
        const d = await res.json();
        showBanner(d.error || "Failed to save floor.", "danger");
      }
    });
  }

  // Distances / Building Graph Handlers
  function renderDistancesTable() {
    const tbody = document.querySelector("#table-distances tbody");
    if (!tbody) return;
    const distances = state.distances || [];
    if (distances.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" class="text-muted text-center" style="padding:15px;">No custom room distances configured. Default geometric corridor distances are used.</td></tr>`;
      return;
    }
    const roomMap = {};
    (state.rooms || []).forEach(r => { roomMap[r.id] = r.name; });

    tbody.innerHTML = distances.map(d => `
      <tr>
        <td><strong>${roomMap[d.from_room_id] || d.from_room_id}</strong></td>
        <td><strong>${roomMap[d.to_room_id] || d.to_room_id}</strong></td>
        <td><span class="badge badge-info">${d.distance_meters} meters</span></td>
        <td>
          <button class="btn btn-sm btn-outline-danger" onclick="deleteDistance('${d.id}')" style="padding:2px 8px; font-size:11px;">Delete</button>
        </td>
      </tr>
    `).join("");
  }

  window.deleteDistance = async function(id) {
    if (!confirm("Remove this custom building distance edge?")) return;
    try {
      const res = await fetch(`/api/spatial/distances/${id}`, { method: "DELETE" });
      if (res.ok) {
        showBanner("Building distance edge removed.", "success");
        await refreshAllData();
        renderDistancesTable();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const btnOpenDistances = document.getElementById("btn-open-distances");
  if (btnOpenDistances) {
    btnOpenDistances.addEventListener("click", () => {
      populateFloorDropdowns();
      renderDistancesTable();
      openModal("modal-distances");
    });
  }

  const btnOpenAddFloor = document.getElementById("btn-open-add-floor");
  if (btnOpenAddFloor) {
    btnOpenAddFloor.addEventListener("click", openAddFloorModal);
  }

  const formAddDistance = document.getElementById("form-add-distance");
  if (formAddDistance) {
    formAddDistance.addEventListener("submit", async (e) => {
      e.preventDefault();
      const from_room_id = document.getElementById("dist-input-from").value;
      const to_room_id = document.getElementById("dist-input-to").value;
      const distance_meters = parseFloat(document.getElementById("dist-input-meters").value) || 10.0;

      if (!from_room_id || !to_room_id || from_room_id === to_room_id) {
        showBanner("Please select two different rooms to connect.", "warning");
        return;
      }

      const res = await fetch("/api/spatial/distances", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ from_room_id, to_room_id, distance_meters }),
      });

      if (res.ok) {
        showBanner("Room distance edge configured successfully!", "success");
        await refreshAllData();
        renderDistancesTable();
      } else {
        const d = await res.json();
        showBanner(d.error || "Failed to configure distance.", "danger");
      }
    });
  }

  // Auth Modals
  document.getElementById("btn-login-modal").addEventListener("click", () => {
    openModal("modal-login");
  });

  document.getElementById("form-login").addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = document.getElementById("login-username").value.trim();
    const password = document.getElementById("login-password").value.trim();

    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });

    if (res.ok) {
      const data = await res.json();
      state.currentUser = data.user;
      updateAuthUI();
      closeModal("modal-login");
      showBanner(`Logged in as ${data.user.name} (${data.user.role})`, "success");
    } else {
      alert("Invalid credentials.");
    }
  });

  document.getElementById("btn-logout").addEventListener("click", async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    state.currentUser = null;
    updateAuthUI();
    showBanner("Logged out.", "success");
  });

  document.getElementById("subject-filter-year").addEventListener("change", () => {
    renderSubjectsTable();
  });
}

// -------------------------------------------------------------
// Modal Helpers
// -------------------------------------------------------------
function setupModals() {
  document.querySelectorAll(".modal-close").forEach((btn) => {
    btn.addEventListener("click", () => {
      const modal = btn.closest(".modal-overlay");
      if (modal) modal.classList.add("hidden");
    });
  });

  window.addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-overlay")) {
      e.target.classList.add("hidden");
    }
  });
}

function openModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.remove("hidden");
}

function closeModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.add("hidden");
}

let confirmCallback = null;
function openConfirmModal(title, message, onConfirm) {
  document.getElementById("confirm-title").textContent = title;
  document.getElementById("confirm-message").textContent = message;
  confirmCallback = onConfirm;
  openModal("modal-confirm");
}

document.getElementById("btn-confirm-yes").addEventListener("click", async () => {
  if (confirmCallback) {
    await confirmCallback();
    confirmCallback = null;
  }
  closeModal("modal-confirm");
});

// -------------------------------------------------------------
// Agent Analytics & Faculty Workload Modal
// -------------------------------------------------------------
let currentAgentDetailsModalState = {
  agentId: "TY",
  scope: "weekly",
};

window.openAgentDetailsModal = function (agentId, scope = "weekly") {
  currentAgentDetailsModalState.agentId = agentId || "TY";
  currentAgentDetailsModalState.scope = scope || "weekly";

  const modal = document.getElementById("modal-agent-details");
  if (!modal) return;

  const agentIdClean = currentAgentDetailsModalState.agentId;
  const currScope = currentAgentDetailsModalState.scope;

  const iconEl = document.getElementById("agent-modal-icon");
  const titleEl = document.getElementById("agent-modal-title");
  const subEl = document.getElementById("agent-modal-subtitle");

  const agentMeta = {
    "TY": { icon: "🟣", title: "Third Year (TY) Agent Analytics", sub: "Third Year Divisions, Subjects & Faculty Workload" },
    "FY": { icon: "🟢", title: "First Year (FY) Agent Analytics", sub: "First Year Divisions, Subjects & Faculty Workload" },
    "SY": { icon: "🔵", title: "Second Year (SY) Agent Analytics", sub: "Second Year Divisions, Subjects & Faculty Workload" },
    "BE": { icon: "🟠", title: "Final Year (BE) Agent Analytics", sub: "Final Year Divisions, Subjects & Faculty Workload" },
    "Orchestrator": { icon: "⚡", title: "Global Orchestrator Analytics", sub: "Cross-Year Global Resource & Faculty Allocation" },
  };

  const meta = agentMeta[agentIdClean] || agentMeta["TY"];
  if (iconEl) iconEl.textContent = meta.icon;
  if (titleEl) titleEl.textContent = meta.title;
  if (subEl) subEl.textContent = meta.sub;

  // Sync scope buttons
  const scopeBtns = document.querySelectorAll("#agent-scope-buttons .btn-filter-box");
  scopeBtns.forEach((btn) => {
    if (btn.getAttribute("data-scope") === currScope) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  });

  const scopeMultiplier = currScope === "daily" ? 0.2 : (currScope === "monthly" ? 4.0 : 1.0);
  const scopeUnit = currScope === "daily" ? "/day" : (currScope === "monthly" ? "/month" : "/week");

  // 1. Populate Subject Coverage
  const subjectsListEl = document.getElementById("agent-subjects-progress-list");
  if (subjectsListEl) {
    let yearSubjects = (state.subjects || []);
    if (agentIdClean !== "Orchestrator") {
      yearSubjects = yearSubjects.filter((s) => s.year_id === agentIdClean);
    }

    if (yearSubjects.length === 0) {
      subjectsListEl.innerHTML = `<div class="p-3 text-muted text-center" style="background:#f8fafc; border-radius:6px;">No subjects configured for ${agentIdClean}.</div>`;
    } else {
      let subjHtml = "";
      yearSubjects.forEach((sub) => {
        const weeklyTargetHours = (sub.weekly_lectures || 0) * ((sub.duration_minutes || 60) / 60);
        const targetHours = +(weeklyTargetHours * scopeMultiplier).toFixed(1);

        // Count scheduled hours from timetable
        const matchingEntries = (state.timetable.entries || []).filter((e) => {
          return e.subject_id === sub.id || e.parent_subject_id === sub.id;
        });

        let totalSchedMinutes = 0;
        matchingEntries.forEach((e) => {
          const d = (toMin(e.end_time) - toMin(e.start_time)) || 60;
          totalSchedMinutes += d;
        });

        const schedWeeklyHours = totalSchedMinutes / 60;
        const schedHours = +(schedWeeklyHours * scopeMultiplier).toFixed(1);
        const pct = targetHours > 0 ? Math.min(100, Math.round((schedHours / targetHours) * 100)) : (schedHours > 0 ? 100 : 0);

        subjHtml += `
          <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:12px 14px; box-shadow:0 1px 2px rgba(0,0,0,0.03);">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
              <div>
                <strong style="font-size:13px; color:#0f172a;">${sub.name}</strong>
                <span class="badge" style="font-size:10px; margin-left:6px; background:#f1f5f9; color:#334155;">${sub.code || sub.type || "Theory"}</span>
              </div>
              <div style="font-size:12px; font-weight:700; color:#0f172a;">
                ${schedHours} / ${targetHours} hrs ${scopeUnit} (${pct}%)
              </div>
            </div>
            <div style="background:#e2e8f0; border-radius:8px; height:8px; overflow:hidden;">
              <div style="background:#0f172a; height:100%; width:${pct}%; transition:width 0.3s ease;"></div>
            </div>
          </div>
        `;
      });
      subjectsListEl.innerHTML = subjHtml;
    }
  }

  // 2. Populate Faculty Workload
  const facultyListEl = document.getElementById("agent-faculty-progress-list");
  if (facultyListEl) {
    const allEntries = (state.timetable.entries || []);
    const relevantEntries = agentIdClean === "Orchestrator"
      ? allEntries
      : allEntries.filter((e) => e.year_id === agentIdClean);

    // Collect faculty IDs from relevant entries or assignments
    const facultyWorkloadMap = {};
    (state.faculty || []).forEach((f) => {
      facultyWorkloadMap[f.id] = {
        name: f.name,
        minutes: 0,
        subjects: new Set(),
      };
    });

    relevantEntries.forEach((e) => {
      if (e.faculty_id && facultyWorkloadMap[e.faculty_id]) {
        const d = (toMin(e.end_time) - toMin(e.start_time)) || 60;
        facultyWorkloadMap[e.faculty_id].minutes += d;
        if (e.subject_name) facultyWorkloadMap[e.faculty_id].subjects.add(e.subject_name);
      }
    });

    const activeFaculty = Object.values(facultyWorkloadMap).filter((f) => f.minutes > 0);
    const displayFaculty = activeFaculty.length > 0 ? activeFaculty : Object.values(facultyWorkloadMap).slice(0, 5);

    const maxWeeklyHours = +(state.settings.max_faculty_weekly_hours || 18);
    const maxHours = +(maxWeeklyHours * scopeMultiplier).toFixed(1);

    let facHtml = "";
    displayFaculty.forEach((f) => {
      const schedWeekly = f.minutes / 60;
      const schedHours = +(schedWeekly * scopeMultiplier).toFixed(1);
      const pct = maxHours > 0 ? Math.min(100, Math.round((schedHours / maxHours) * 100)) : 0;
      const isNearLimit = pct >= 85;
      const isExceeded = pct > 100;
      const barColor = isExceeded ? "#b91c1c" : (isNearLimit ? "#b45309" : "#0f172a");

      const subjStr = Array.from(f.subjects).slice(0, 2).join(", ") || "General Faculty";

      facHtml += `
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:12px 14px; box-shadow:0 1px 2px rgba(0,0,0,0.03);">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <div>
              <strong style="font-size:13px; color:#0f172a;">${f.name}</strong>
              <small class="text-muted" style="display:block; font-size:11px;">${subjStr}</small>
            </div>
            <div style="font-size:12px; font-weight:700; color:${barColor};">
              ${schedHours} / ${maxHours} hrs ${scopeUnit} (${pct}%)
            </div>
          </div>
          <div style="background:#e2e8f0; border-radius:8px; height:8px; overflow:hidden;">
            <div style="background:${barColor}; height:100%; width:${pct}%; transition:width 0.3s ease;"></div>
          </div>
        </div>
      `;
    });
    facultyListEl.innerHTML = facHtml;
  }

  // 3. Populate Divisions Table
  const divsTableEl = document.getElementById("agent-divisions-table-box");
  if (divsTableEl) {
    let yearDivs = (state.divisions || []);
    if (agentIdClean !== "Orchestrator") {
      yearDivs = yearDivs.filter((d) => d.year_id === agentIdClean);
    }

    if (yearDivs.length === 0) {
      divsTableEl.innerHTML = `<div class="p-3 text-muted text-center" style="background:#f8fafc; border-radius:6px;">No divisions configured for ${agentIdClean}.</div>`;
    } else {
      let tblHtml = `
        <table class="data-table" style="font-size:12px; width:100%;">
          <thead>
            <tr>
              <th>Year</th>
              <th>Division</th>
              <th>Capacity</th>
              <th>Scheduled Lectures</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
      `;
      yearDivs.forEach((d) => {
        const divEntries = (state.timetable.entries || []).filter((e) => e.division_id === d.id);
        tblHtml += `
          <tr>
            <td><span class="badge" style="background:#0f172a; color:#ffffff;">${d.year_id}</span></td>
            <td><strong>${d.name}</strong></td>
            <td>${d.capacity || 60} students</td>
            <td>${divEntries.length} lectures scheduled</td>
            <td><span class="badge badge-success">Active & Synced</span></td>
          </tr>
        `;
      });
      tblHtml += `</tbody></table>`;
      divsTableEl.innerHTML = tblHtml;
    }
  }

  openModal("modal-agent-details");
};

// Wire agent card click triggers and scope buttons
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".agent-card").forEach((card) => {
    card.addEventListener("click", () => {
      const agentId = card.getAttribute("data-agent") || "TY";
      window.openAgentDetailsModal(agentId, "weekly");
    });
  });

  const scopeBtnsContainer = document.getElementById("agent-scope-buttons");
  if (scopeBtnsContainer) {
    scopeBtnsContainer.querySelectorAll(".btn-filter-box").forEach((btn) => {
      btn.addEventListener("click", () => {
        const scope = btn.getAttribute("data-scope");
        window.openAgentDetailsModal(currentAgentDetailsModalState.agentId, scope);
      });
    });
  }

  const btnCloseAgent = document.getElementById("btn-close-agent-modal");
  if (btnCloseAgent) btnCloseAgent.addEventListener("click", () => closeModal("modal-agent-details"));
  const btnCloseAgentFoot = document.getElementById("btn-close-agent-modal-foot");
  if (btnCloseAgentFoot) btnCloseAgentFoot.addEventListener("click", () => closeModal("modal-agent-details"));
});

function showBanner(message, type = "success") {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-overlay-container";
    document.body.appendChild(container);
  }

  const icons = {
    success: "✓",
    danger: "⚠️",
    warning: "⚡",
    info: "ℹ️",
  };

  const toast = document.createElement("div");
  toast.className = `toast-item ${type}`;

  const iconEl = document.createElement("span");
  iconEl.className = "toast-icon";
  iconEl.textContent = icons[type] || "ℹ️";

  const msgEl = document.createElement("span");
  msgEl.className = "toast-msg";
  msgEl.textContent = message;

  const closeBtn = document.createElement("button");
  closeBtn.className = "toast-close";
  closeBtn.innerHTML = "&times;";
  closeBtn.title = "Dismiss";

  toast.appendChild(iconEl);
  toast.appendChild(msgEl);
  toast.appendChild(closeBtn);
  container.appendChild(toast);

  // Trigger smooth entrance
  requestAnimationFrame(() => {
    toast.classList.add("toast-show");
  });

  const dismiss = () => {
    toast.classList.remove("toast-show");
    toast.classList.add("toast-hide");
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 250);
  };

  closeBtn.addEventListener("click", dismiss);

  // Auto-dismiss after 3.8 seconds
  const timer = setTimeout(dismiss, 3800);
  toast.addEventListener("mouseenter", () => clearTimeout(timer));
  toast.addEventListener("mouseleave", () => setTimeout(dismiss, 2000));
}

// -------------------------------------------------------------
// Data Management: Export & Import (Backup & Disaster Recovery)
// -------------------------------------------------------------
function setupDataExportImport() {
  const btnExportAll = document.getElementById("btn-export-all-data");
  const btnExportSelected = document.getElementById("btn-export-selected-data");
  const btnSelectAll = document.getElementById("btn-select-all-export");
  const btnClearAll = document.getElementById("btn-clear-all-export");
  const btnAcademic = document.getElementById("btn-academic-export");

  const dropzone = document.getElementById("import-dropzone");
  const fileInput = document.getElementById("input-import-file");
  const fileNameEl = document.getElementById("import-file-name");
  const previewContainer = document.getElementById("import-preview-container");
  const detectedEl = document.getElementById("import-entities-detected");
  const checkboxesContainer = document.getElementById("import-entities-checkboxes");
  const btnCancelImport = document.getElementById("btn-cancel-import");
  const btnExecuteImport = document.getElementById("btn-execute-import");
  const selectImportMode = document.getElementById("select-import-mode");

  let pendingImportData = null;
  let pendingFile = null;

  // 1. Export Everything (All Data)
  if (btnExportAll) {
    btnExportAll.addEventListener("click", () => {
      showBanner("Preparing complete system backup JSON export...", "info");
      window.location.href = "/api/data/export?entities=all";
    });
  }

  // 2. Selective Export Quick Toggles
  if (btnSelectAll) {
    btnSelectAll.addEventListener("click", () => {
      document.querySelectorAll("#export-entities-group input[type='checkbox']").forEach((cb) => (cb.checked = true));
    });
  }

  if (btnClearAll) {
    btnClearAll.addEventListener("click", () => {
      document.querySelectorAll("#export-entities-group input[type='checkbox']").forEach((cb) => (cb.checked = false));
    });
  }

  if (btnAcademic) {
    btnAcademic.addEventListener("click", () => {
      const academicKeys = ["faculty", "rooms", "subjects", "divisions", "batches", "assignments"];
      document.querySelectorAll("#export-entities-group input[type='checkbox']").forEach((cb) => {
        cb.checked = academicKeys.includes(cb.value);
      });
    });
  }

  // 3. Export Selected Entities
  if (btnExportSelected) {
    btnExportSelected.addEventListener("click", () => {
      const selected = [];
      document.querySelectorAll("#export-entities-group input[type='checkbox']:checked").forEach((cb) => {
        selected.push(cb.value);
      });
      if (selected.length === 0) {
        showBanner("Please select at least one dataset to export.", "warning");
        return;
      }
      showBanner(`Exporting ${selected.length} selected datasets...`, "info");
      window.location.href = `/api/data/export?entities=${selected.join(",")}`;
    });
  }

  // 4. File Dropzone & Selection Handling
  if (dropzone && fileInput) {
    dropzone.addEventListener("click", () => fileInput.click());

    dropzone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropzone.style.borderColor = "#2563eb";
      dropzone.style.background = "#eff6ff";
    });

    dropzone.addEventListener("dragleave", (e) => {
      e.preventDefault();
      dropzone.style.borderColor = "#cbd5e1";
      dropzone.style.background = "#f8fafc";
    });

    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzone.style.borderColor = "#cbd5e1";
      dropzone.style.background = "#f8fafc";
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        handleFileSelection(e.dataTransfer.files[0]);
      }
    });

    fileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files.length > 0) {
        handleFileSelection(e.target.files[0]);
      }
    });
  }

  const ENTITY_LABELS = {
    faculty: "Faculty",
    rooms: "Rooms & Labs",
    subjects: "Subjects",
    divisions: "Divisions",
    batches: "Batches",
    assignments: "Assignments",
    settings: "Settings",
    academic_years: "Academic Years",
    floors: "Floors",
    building_graph: "Building Graph",
    timetable: "Timetable",
  };

  function handleFileSelection(file) {
    if (!file.name.endsWith(".json")) {
      showBanner("Please upload a valid Schedula JSON file (.json).", "danger");
      return;
    }
    pendingFile = file;
    if (fileNameEl) {
      fileNameEl.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
      fileNameEl.style.color = "#2563eb";
      fileNameEl.style.fontWeight = "600";
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const json = JSON.parse(e.target.result);
        const data = json.data && typeof json.data === "object" ? json.data : json;
        const keys = Object.keys(data).filter((k) => k in ENTITY_LABELS);

        if (keys.length === 0) {
          showBanner("No recognized departmental datasets found in this file.", "danger");
          if (previewContainer) previewContainer.classList.add("hidden");
          return;
        }

        pendingImportData = data;

        if (detectedEl) {
          detectedEl.textContent = `${keys.length} datasets found`;
        }

        if (checkboxesContainer) {
          checkboxesContainer.innerHTML = keys
            .map((k) => {
              const val = data[k];
              const count = Array.isArray(val)
                ? val.length
                : val && val.entries && Array.isArray(val.entries)
                ? val.entries.length
                : 1;
              const label = ENTITY_LABELS[k] || k;
              return `
                <label style="display:flex; align-items:center; gap:4px; cursor:pointer;">
                  <input type="checkbox" class="import-entity-cb" value="${k}" checked>
                  <span>${label} (${count})</span>
                </label>
              `;
            })
            .join("");
        }

        if (previewContainer) previewContainer.classList.remove("hidden");
      } catch (err) {
        showBanner("Could not parse JSON file: " + err.message, "danger");
        if (previewContainer) previewContainer.classList.add("hidden");
      }
    };
    reader.readAsText(file);
  }

  // 5. Cancel Import
  if (btnCancelImport) {
    btnCancelImport.addEventListener("click", () => {
      pendingImportData = null;
      pendingFile = null;
      if (fileInput) fileInput.value = "";
      if (fileNameEl) {
        fileNameEl.textContent = "Supports full backups and selective exports";
        fileNameEl.style.color = "";
        fileNameEl.style.fontWeight = "";
      }
      if (previewContainer) previewContainer.classList.add("hidden");
    });
  }

  // 6. Execute Import & Restore
  if (btnExecuteImport) {
    btnExecuteImport.addEventListener("click", async () => {
      if (!pendingImportData) {
        showBanner("No valid backup file is loaded.", "warning");
        return;
      }

      const selectedEntities = [];
      document.querySelectorAll(".import-entity-cb:checked").forEach((cb) => {
        selectedEntities.push(cb.value);
      });

      if (selectedEntities.length === 0) {
        showBanner("Please select at least one dataset to import.", "warning");
        return;
      }

      const mode = selectImportMode ? selectImportMode.value : "replace";
      const modeDesc = mode === "replace" ? "Clean Replace (Overwrite)" : "Merge (Update Existing)";

      const confirmed = confirm(
        `Are you sure you want to restore the selected datasets (${selectedEntities.join(", ")})?\n\nMode: ${modeDesc}\n\nAn automatic snapshot backup will be created before restoring.`
      );
      if (!confirmed) return;

      btnExecuteImport.disabled = true;
      btnExecuteImport.textContent = "Restoring Data...";
      showBanner("Importing data and synchronizing system state...", "info");

      try {
        const payload = {
          data: pendingImportData,
          mode: mode,
          selected_entities: selectedEntities,
        };

        const res = await fetch("/api/data/import", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        const result = await res.json();
        if (res.ok && result.success) {
          showBanner(result.message || "Data successfully imported and restored!", "success");
          pendingImportData = null;
          pendingFile = null;
          if (fileInput) fileInput.value = "";
          if (fileNameEl) {
            fileNameEl.textContent = "Supports full backups and selective exports";
            fileNameEl.style.color = "";
            fileNameEl.style.fontWeight = "";
          }
          if (previewContainer) previewContainer.classList.add("hidden");
          await refreshAllData();
        } else {
          showBanner(result.error || "Failed to import data.", "danger");
        }
      } catch (err) {
        showBanner("Network or server error during import: " + err.message, "danger");
      } finally {
        btnExecuteImport.disabled = false;
        btnExecuteImport.textContent = "🚀 Start Import & Restore";
      }
    });
  }
}

// =============================================================================
// INTERACTIVE FEATURE HELP TOUR ENGINE
// =============================================================================

const PAGE_HELP_TOURS = {
  "tab-timetable": [
    {
      target: "#btn-generate-timetable",
      title: "Generate Timetable",
      desc: "Triggers the synchronized multi-agent heuristic solver (MRV + flexibility). Automatically schedules theory lectures and multi-batch labs across all academic years without conflicts, streaming real-time allocation updates.",
      placement: "bottom",
    },
    {
      target: "#btn-auto-fix-clashes",
      title: "Auto-Fix Clashes",
      desc: "Scans the active timetable for room double-bookings, faculty overlaps, or batch conflicts, and executes optimal micro-adjustments and slot shifts to achieve a 100% clash-free state.",
      placement: "bottom",
    },
    {
      target: "#btn-undo-timetable",
      title: "Undo / Redo History",
      desc: "Instantly step backward or forward through timetable generations, slot modifications, and drag-and-drop swaps with full state rollback capability.",
      placement: "bottom",
    },
    {
      target: "#btn-open-smart-add-lecture",
      title: "Smart Add Lecture",
      desc: "Intelligently calculates conflict-free open slots across all academic years for any selected course and room, taking the guesswork out of mid-semester schedule adjustments.",
      placement: "bottom",
    },
    {
      target: "#btn-manual-add-lecture",
      title: "Manual Add Schedule",
      desc: "Manually place a lecture into a designated slot. Context-aware: automatically suggests assigned subjects for the selected division without repetitive manual mapping.",
      placement: "bottom",
    },
    {
      target: "#btn-export-dropdown",
      title: "Export Timetable (PNG / PDF)",
      desc: "Export publication-quality timetables in crystal-clear PNG image or landscape PDF formats, featuring high-contrast layout, complete room metadata, and official Schedula watermarking.",
      placement: "bottom",
    },
    {
      target: "#btn-toggle-timetable-fullview",
      title: "Full Screen & Canvas Mode",
      desc: "Expands the timetable into an edge-to-edge view with custom zoom controls (Zoom In, Zoom Out, Reset, Fit to Screen) for projection on large auditorium screens.",
      placement: "bottom",
    },
    {
      target: "#timetable-filter-bar",
      title: "Interactive Box Filter Selectors",
      desc: "Segmented box filters to instantly toggle between Academic Years (SY, TY), Divisions (A, B, C), and Days (Mon-Sat). Multi-select is supported for side-by-side comparison.",
      placement: "bottom",
    },
    {
      target: ".tt-zoom-controls",
      title: "Zoom & Fit to Screen Controls",
      desc: "Dynamically scale the timetable canvas from 50% to 150%. Clicking 'Fit to Screen' automatically scales the grid so all days and hours fit smoothly into your viewport.",
      placement: "bottom",
    },
    {
      target: ".tt-canvas-toolbar",
      title: "Interactive Timetable Grid & Drag-to-Swap",
      desc: "The core timetable matrix. Drag and drop theory lectures to swap their time slots with live clash verification, animated feedback, and full undo/redo support.",
      placement: "bottom",
    },
  ],

  "tab-dashboard": [
    {
      target: "#btn-goto-timetable-gen",
      title: "Open Timetable & Generate",
      desc: "Direct navigation shortcut that takes you straight to the Timetable Workbench and prepares the multi-agent solver for schedule generation.",
      placement: "bottom",
    },
    {
      target: "#btn-load-demo-dashboard",
      title: "Load Complete Demo Data",
      desc: "Populates realistic CMPN engineering data (SY & TY, 6 divisions, 12 batches A1-C2, 8 faculty, 13 rooms, 96 clash-free lecture slots) with 09:15-17:15 timing and 13:15-13:45 lunch break.",
      placement: "bottom",
    },
    {
      target: "#btn-clear-timetable",
      title: "Reset Timetable",
      desc: "Clears current timetable slots while preserving your master catalog of faculty, subjects, rooms, and academic divisions.",
      placement: "bottom",
    },
    {
      target: ".stat-grid",
      title: "Institutional Overview Metrics",
      desc: "High-level summary displaying active faculty count, registered subjects, divisions, required teaching hours, and scheduled vs unscheduled lectures.",
      placement: "bottom",
    },
    {
      target: ".agent-grid",
      title: "Multi-Agent Analytics & Workload",
      desc: "Click any agent card (FY, SY, TY, BE, or Orchestrator) to open the interactive workload modal featuring Daily, Weekly, and Monthly progress bars for curriculum coverage and faculty teaching hours.",
      placement: "top",
    },
    {
      target: "#agent-subview-logs",
      title: "Live Agent Decision & Reasoning Stream",
      desc: "Real-time decision log showing the step-by-step reasoning of heuristic agents, including MRV calculations, slot selection, and contention resolution.",
      placement: "bottom",
    },
  ],

  "tab-faculty": [
    {
      target: "#btn-open-add-faculty",
      title: "Add Faculty",
      desc: "Register a professor with their designation, department, staff room floor, maximum daily and weekly teaching hours, and eligible subject specializations.",
      placement: "bottom",
    },
    {
      target: "#table-faculty",
      title: "Faculty Directory & Workload Monitor",
      desc: "View all faculty members, their real-time scheduled teaching hours versus workload limits, eligible subjects, and edit options.",
      placement: "top",
    },
  ],

  "tab-subjects": [
    {
      target: "#btn-open-add-subject",
      title: "Add Subject",
      desc: "Create a course specifying Theory or Practical type, academic year, weekly lecture hours, single-lecture duration, and required room/lab type.",
      placement: "bottom",
    },
    {
      target: "#btn-open-assign-faculty",
      title: "Assign Faculty to Subjects",
      desc: "Map qualified professors to specific subjects and divisions/batches, setting primary teaching assignments for automatic timetable generation.",
      placement: "bottom",
    },
    {
      target: "#table-subjects",
      title: "Subject Catalog",
      desc: "Comprehensive curriculum registry organized by academic year with theory and practical course requirements.",
      placement: "top",
    },
    {
      target: "#table-assignments",
      title: "Explicit Teaching Assignments",
      desc: "Manage division-wise and batch-wise faculty allocations. The multi-agent scheduler uses these assignments as primary hard constraints.",
      placement: "top",
    },
  ],

  "tab-divisions": [
    {
      target: "#btn-open-add-division",
      title: "Add Division",
      desc: "Register an academic division under FY, SY, TY, or BE with designated student capacity and default home classroom.",
      placement: "bottom",
    },
    {
      target: "#btn-open-auto-split",
      title: "Auto-Split Lab Batches",
      desc: "Automatically subdivide a division into 2, 3, or 4 lab batches (e.g. A1 and A2) with synchronized student counts for practical sessions.",
      placement: "bottom",
    },
    {
      target: "#btn-open-add-batch",
      title: "Add Single Batch",
      desc: "Manually register an individual lab batch with custom naming and student count under any existing division.",
      placement: "bottom",
    },
    {
      target: "#year-grid-container",
      title: "Academic Hierarchy Matrix",
      desc: "Hierarchical breakdown of all divisions and their practical batches grouped by academic year.",
      placement: "top",
    },
  ],

  "tab-settings": [
    {
      target: "#settings-working-days",
      title: "Active Working Days",
      desc: "Configure institutional working days (Monday through Saturday) to match your college calendar.",
      placement: "bottom",
    },
    {
      target: "#set-day-start",
      title: "College Timings & Break Hours",
      desc: "Set the start and end of the college day (e.g. 09:15 to 17:15) and define institutional break intervals (e.g. Lunch Break 13:15 to 13:45) where no classes may be scheduled.",
      placement: "bottom",
    },
    {
      target: "#btn-jump-backup-import",
      title: "Data Backup & Migration",
      desc: "Export complete institution data (faculty, rooms, subjects, divisions, rules, timetables) as a single portable JSON file, or restore existing backups.",
      placement: "bottom",
    },
    {
      target: "#btn-open-add-room",
      title: "Classrooms & Laboratories",
      desc: "Register classrooms, seminar halls, and specialized laboratories (Software Lab, Database Lab, Network Lab, AI Lab) with seating capacities and equipment tags.",
      placement: "top",
    },
  ],
};

let currentTourTabId = null;
let currentTourSteps = [];
let currentTourStepIndex = 0;
let isHelpTourActive = false;

function setupInteractiveHelpTour() {
  // Global navbar Help button
  const navbarHelpBtn = document.getElementById("btn-navbar-help");
  if (navbarHelpBtn) {
    navbarHelpBtn.addEventListener("click", () => {
      const activePane = document.querySelector(".tab-pane.active");
      const tabId = activePane ? activePane.id : "tab-timetable";
      startHelpTour(tabId);
    });
  }

  // Per-tab Help buttons in header actions
  document.querySelectorAll(".btn-page-help").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const tabId = btn.getAttribute("data-tab-help") || "tab-timetable";
      startHelpTour(tabId);
    });
  });

  // Tour Popover Buttons
  const closeBtn = document.getElementById("help-tour-close-btn");
  if (closeBtn) closeBtn.addEventListener("click", exitHelpTour);

  const nextBtn = document.getElementById("help-tour-next-btn");
  if (nextBtn) nextBtn.addEventListener("click", nextTourStep);

  const prevBtn = document.getElementById("help-tour-prev-btn");
  if (prevBtn) prevBtn.addEventListener("click", prevTourStep);

  // Keyboard navigation: Esc to close, Arrow keys to navigate
  window.addEventListener("keydown", (e) => {
    if (!isHelpTourActive) return;
    if (e.key === "Escape") {
      e.preventDefault();
      exitHelpTour();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      nextTourStep();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      prevTourStep();
    }
  });

  // Window resize & scroll: keep spotlight and popover perfectly aligned
  window.addEventListener("resize", () => {
    if (isHelpTourActive && currentTourSteps[currentTourStepIndex]) {
      const step = currentTourSteps[currentTourStepIndex];
      const targetEl = document.querySelector(step.target);
      if (targetEl) positionSpotlightAndPopover(targetEl, step.placement || "bottom");
    }
  });

  window.addEventListener("scroll", () => {
    if (isHelpTourActive && currentTourSteps[currentTourStepIndex]) {
      const step = currentTourSteps[currentTourStepIndex];
      const targetEl = document.querySelector(step.target);
      if (targetEl) positionSpotlightAndPopover(targetEl, step.placement || "bottom");
    }
  }, true);

  // Click-to-Inspect in Help Tour Mode
  // When Help Tour is active, clicking ANY registered button on screen intercepts the action
  // and immediately jumps the spotlight and popover to explain what that button does!
  window.addEventListener("click", (e) => {
    if (!isHelpTourActive) return;

    // Allow normal clicking inside the popover itself (Back, Next, Close, Dots)
    const popover = document.getElementById("help-tour-popover");
    if (popover && popover.contains(e.target)) return;

    // If user clicks a tour target element on the page, intercept and jump to that step!
    const targetEl = e.target.closest("[data-tour-target-active='true']");
    if (targetEl) {
      e.preventDefault();
      e.stopPropagation();
      const stepIdxStr = targetEl.getAttribute("data-tour-step-idx");
      if (stepIdxStr !== null) {
        const stepIdx = parseInt(stepIdxStr, 10);
        if (!isNaN(stepIdx)) {
          renderTourStep(stepIdx);
          return;
        }
      }
    }

    // If click is on the backdrop outside target and popover, advance to next step
    const backdrop = document.getElementById("help-tour-backdrop");
    if (e.target === backdrop) {
      e.preventDefault();
      e.stopPropagation();
      nextTourStep();
    }
  }, true);
}

function startHelpTour(tabId, stepIndex = 0) {
  if (!tabId) {
    const activePane = document.querySelector(".tab-pane.active");
    tabId = activePane ? activePane.id : "tab-timetable";
  }

  // Ensure target tab is open
  const navBtn = document.querySelector(`.nav-item[data-tab="${tabId}"]`);
  if (navBtn && !navBtn.classList.contains("active")) {
    navBtn.click();
  }

  const rawSteps = PAGE_HELP_TOURS[tabId] || [];
  const steps = rawSteps.filter((s) => {
    const el = document.querySelector(s.target);
    return el && el.offsetParent !== null; // Element must exist and be visible
  });

  if (!steps.length) {
    showBanner("All guide elements on this page are currently hidden or not loaded.", "info");
    return;
  }

  currentTourTabId = tabId;
  currentTourSteps = steps;
  currentTourStepIndex = Math.max(0, Math.min(stepIndex, steps.length - 1));
  isHelpTourActive = true;

  document.body.classList.add("help-tour-active");
  const overlay = document.getElementById("help-tour-overlay");
  if (overlay) overlay.classList.remove("hidden");

  // Mark all target elements on the page for interactive click-to-inspect
  markTourTargetElements();

  // Render the active step
  renderTourStep(currentTourStepIndex);
}

function markTourTargetElements() {
  document.querySelectorAll("[data-tour-target-active]").forEach((el) => {
    el.removeAttribute("data-tour-target-active");
    el.removeAttribute("data-tour-step-idx");
    el.classList.remove("help-tour-current-target");
  });

  currentTourSteps.forEach((s, idx) => {
    const el = document.querySelector(s.target);
    if (el) {
      el.setAttribute("data-tour-target-active", "true");
      el.setAttribute("data-tour-step-idx", idx.toString());
      el.setAttribute("title", `Help Guide: ${s.title} (Click to inspect)`);
    }
  });
}

function renderTourStep(stepIndex) {
  if (!isHelpTourActive || !currentTourSteps.length) return;
  currentTourStepIndex = stepIndex;

  const step = currentTourSteps[stepIndex];
  const targetEl = document.querySelector(step.target);
  if (!targetEl) {
    if (stepIndex < currentTourSteps.length - 1) {
      renderTourStep(stepIndex + 1);
    }
    return;
  }

  // Highlight active target
  document.querySelectorAll(".help-tour-current-target").forEach((el) => {
    el.classList.remove("help-tour-current-target");
  });
  targetEl.classList.add("help-tour-current-target");

  // Scroll target smoothly into center view
  try {
    targetEl.scrollIntoView({ behavior: "instant", block: "center", inline: "nearest" });
  } catch (err) {
    targetEl.scrollIntoView(true);
  }

  // Update Popover Elements
  const stepBadge = document.getElementById("help-tour-step-badge");
  const tabBadge = document.getElementById("help-tour-tab-badge");
  const titleEl = document.getElementById("help-tour-title");
  const descEl = document.getElementById("help-tour-desc");
  const prevBtn = document.getElementById("help-tour-prev-btn");
  const nextBtn = document.getElementById("help-tour-next-btn");
  const dotsContainer = document.getElementById("help-tour-dots");

  if (stepBadge) {
    stepBadge.textContent = `Step ${stepIndex + 1} of ${currentTourSteps.length}`;
  }

  if (tabBadge) {
    const tabNameMap = {
      "tab-timetable": "Timetable Guide",
      "tab-dashboard": "Dashboard Guide",
      "tab-faculty": "Faculty Guide",
      "tab-subjects": "Subjects Guide",
      "tab-divisions": "Divisions Guide",
      "tab-settings": "Settings Guide",
    };
    tabBadge.textContent = tabNameMap[currentTourTabId] || "Page Guide";
  }

  if (titleEl) {
    titleEl.textContent = step.title;
  }

  if (descEl) {
    descEl.textContent = step.desc;
  }

  if (prevBtn) {
    prevBtn.disabled = stepIndex === 0;
    prevBtn.style.opacity = stepIndex === 0 ? "0.4" : "1";
    prevBtn.style.cursor = stepIndex === 0 ? "not-allowed" : "pointer";
  }

  if (nextBtn) {
    if (stepIndex === currentTourSteps.length - 1) {
      nextBtn.textContent = "Finish ✓";
      nextBtn.classList.remove("btn-primary");
      nextBtn.classList.add("btn-success");
    } else {
      nextBtn.textContent = "Next →";
      nextBtn.classList.remove("btn-success");
      nextBtn.classList.add("btn-primary");
    }
  }

  // Render navigation dots
  if (dotsContainer) {
    dotsContainer.innerHTML = "";
    currentTourSteps.forEach((_, idx) => {
      const dot = document.createElement("span");
      dot.className = `help-tour-dot ${idx === stepIndex ? "active" : ""}`;
      dot.title = `Jump to Step ${idx + 1}`;
      dot.addEventListener("click", () => renderTourStep(idx));
      dotsContainer.appendChild(dot);
    });
  }

  // Adjust spotlight and popover placement
  positionSpotlightAndPopover(targetEl, step.placement || "bottom");
}

function positionSpotlightAndPopover(targetEl, preferredPlacement = "bottom") {
  const spotlight = document.getElementById("help-tour-spotlight");
  const popover = document.getElementById("help-tour-popover");
  const arrow = document.getElementById("help-tour-arrow");

  if (!spotlight || !popover || !arrow) return;

  const rect = targetEl.getBoundingClientRect();
  const pad = 6;
  const x = Math.max(8, rect.left - pad);
  const y = Math.max(8, rect.top - pad);
  const w = Math.min(rect.width + pad * 2, window.innerWidth - x - 8);
  const maxSpotlightH = Math.min(window.innerHeight * 0.45, window.innerHeight - 100);
  const h = Math.min(rect.height + pad * 2, maxSpotlightH);

  // Position spotlight frame
  spotlight.style.top = `${Math.round(y)}px`;
  spotlight.style.left = `${Math.round(x)}px`;
  spotlight.style.width = `${Math.round(w)}px`;
  spotlight.style.height = `${Math.round(h)}px`;

  // Determine popover position & viewport clamping
  const popWidth = Math.min(360, window.innerWidth - 32);
  popover.style.width = `${popWidth}px`;
  const popHeight = Math.max(200, popover.offsetHeight || 220);
  const gap = 14;

  const spaceBelow = window.innerHeight - (y + h + gap);
  const spaceAbove = y - gap;

  let placement = preferredPlacement;
  if (placement === "bottom" && spaceBelow < popHeight + 10 && spaceAbove >= popHeight + 10) {
    placement = "top";
  } else if (placement === "top" && spaceAbove < popHeight + 10 && spaceBelow >= popHeight + 10) {
    placement = "bottom";
  } else if (spaceBelow < popHeight + 10 && spaceAbove < popHeight + 10) {
    placement = spaceBelow >= spaceAbove ? "bottom" : "top";
  }

  arrow.className = "help-tour-arrow";
  let top = 0;

  if (placement === "top") {
    top = Math.max(12, y - gap - popHeight);
    arrow.classList.add("arrow-bottom");
    arrow.style.top = "";
  } else {
    top = Math.min(window.innerHeight - popHeight - 12, y + h + gap);
    arrow.classList.add("arrow-top");
    arrow.style.top = "-8px";
  }

  const left = Math.max(12, Math.min(window.innerWidth - popWidth - 12, x + (w - popWidth) / 2));
  const arrowX = Math.max(20, Math.min(popWidth - 36, (x + w / 2) - left - 7));
  arrow.style.left = `${Math.round(arrowX)}px`;

  popover.style.top = `${Math.round(top)}px`;
  popover.style.left = `${Math.round(left)}px`;
}

function nextTourStep() {
  if (currentTourStepIndex < currentTourSteps.length - 1) {
    renderTourStep(currentTourStepIndex + 1);
  } else {
    exitHelpTour();
  }
}

function prevTourStep() {
  if (currentTourStepIndex > 0) {
    renderTourStep(currentTourStepIndex - 1);
  }
}

function exitHelpTour() {
  isHelpTourActive = false;
  document.body.classList.remove("help-tour-active");

  const overlay = document.getElementById("help-tour-overlay");
  if (overlay) overlay.classList.add("hidden");

  const backdrop = document.getElementById("help-tour-backdrop");
  if (backdrop) backdrop.style.clipPath = "none";

  document.querySelectorAll("[data-tour-target-active]").forEach((el) => {
    el.removeAttribute("data-tour-target-active");
    el.removeAttribute("data-tour-step-idx");
    el.classList.remove("help-tour-current-target");
  });
}

// =============================================================================
// Timetable Insights & Analytics Slide-out Panel
// =============================================================================
function initTimetableInsightsPanel() {
  const panel = document.getElementById("timetable-insights-panel");
  const toggleBtn1 = document.getElementById("btn-toggle-insights");
  const toggleBtn2 = document.getElementById("btn-toggle-insights-hdr");
  const closeBtn = document.getElementById("btn-close-insights");
  const refreshBtn = document.getElementById("btn-refresh-insights");

  function openPanel() {
    if (panel) {
      panel.classList.remove("hidden");
      panel.setAttribute("aria-hidden", "false");
      loadTimetableInsights();
    }
  }

  function closePanel() {
    if (panel) {
      panel.classList.add("hidden");
      panel.setAttribute("aria-hidden", "true");
    }
  }

  if (toggleBtn1) {
    toggleBtn1.addEventListener("click", () => {
      if (panel && panel.classList.contains("hidden")) {
        openPanel();
      } else {
        closePanel();
      }
    });
  }

  if (toggleBtn2) {
    toggleBtn2.addEventListener("click", () => {
      if (panel && panel.classList.contains("hidden")) {
        openPanel();
      } else {
        closePanel();
      }
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener("click", closePanel);
  }

  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      loadTimetableInsights();
      showBanner("Analytics & Insights refreshed.", "info");
    });
  }

  // Keyboard shortcut: Esc closes panel if open
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && panel && !panel.classList.contains("hidden")) {
      closePanel();
    }
  });

  // Tab switching inside panel
  const tabBtns = document.querySelectorAll(".insights-tab-btn");
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetTab = btn.getAttribute("data-insight-tab");
      tabBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      document.querySelectorAll(".insights-tab-content").forEach((c) => {
        c.classList.remove("active");
      });
      const activeContent = document.getElementById(`insights-tab-${targetTab}`);
      if (activeContent) activeContent.classList.add("active");
    });
  });
}

async function loadTimetableInsights() {
  try {
    const res = await fetch("/api/timetable/analytics");
    if (!res.ok) return;
    const analytics = await res.json();

    // 1. Clashes Tab
    renderInsightsClashes(analytics.clash_reports || []);

    // 2. Workload Tab
    renderInsightsWorkload(analytics.faculty_workload || []);

    // 3. Subjects Tab
    renderInsightsSubjects(analytics.subject_completion || []);

    // 4. Rooms Tab
    renderInsightsRooms(analytics.room_utilization || []);

    // 5. Logs Tab
    renderInsightsLogs(analytics.generation_logs || []);
  } catch (err) {
    console.error("Error loading timetable insights:", err);
  }
}

function renderInsightsClashes(reports) {
  const container = document.getElementById("insights-clashes-container");
  const countBadge = document.getElementById("insights-clash-count-badge");
  if (!container) return;

  if (countBadge) {
    if (reports.length > 0) {
      countBadge.textContent = reports.length;
      countBadge.style.display = "inline-block";
    } else {
      countBadge.style.display = "none";
    }
  }

  if (!reports || reports.length === 0) {
    container.innerHTML = `
      <div style="text-align:center; padding:32px 16px; color:#10b981; background:#ecfdf5; border-radius:8px; border:1px solid #a7f3d0;">
        <div style="font-size:24px; margin-bottom:6px;">✅</div>
        <div style="font-weight:700; font-size:14px;">100% Conflict Free!</div>
        <div style="font-size:12px; color:#047857; margin-top:4px;">No hard clashes or timing overlaps detected across all years, faculty, or rooms.</div>
      </div>
    `;
    return;
  }

  container.innerHTML = reports.map((r) => {
    const isWarning = r.severity === "warning";
    const entryId = r.entry_id || (r.affected_entry_ids && r.affected_entry_ids[0]) || "";
    return `
      <div class="insight-clash-card ${isWarning ? 'warning-type' : ''}" data-entry-id="${entryId}" onclick="focusTimetableEntry('${entryId}')">
        <div class="insight-card-header">
          <span class="insight-card-title">${r.type || 'Clash Detected'}</span>
          <span class="insight-card-time">${r.day || ''} ${r.slot || ''}</span>
        </div>
        <div class="insight-card-desc">${r.message}</div>
        <div class="insight-card-hint">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 16 16 12 12 8"></polyline><line x1="8" y1="12" x2="16" y2="12"></line></svg>
          <span>Click to navigate & highlight slot</span>
        </div>
      </div>
    `;
  }).join("");
}

function renderInsightsWorkload(facultyList) {
  const container = document.getElementById("insights-workload-container");
  if (!container) return;

  if (!facultyList || facultyList.length === 0) {
    container.innerHTML = `<div style="text-align:center; color:#64748b; padding:20px;">No faculty workload data available.</div>`;
    return;
  }

  container.innerHTML = facultyList.map((f) => {
    const maxH = f.max_weekly_hours || 16;
    const actualH = f.total_weekly_hours || 0;
    const pct = Math.min(Math.round((actualH / (maxH || 1)) * 100), 150);
    const isOverload = f.is_overloaded || actualH > maxH;
    const badgeClass = isOverload ? 'badge-overload' : (pct >= 70 ? 'badge-optimal' : 'badge-underload');
    const badgeText = isOverload ? `⚠️ Overloaded (+${actualH - maxH}h)` : `${actualH}/${maxH} hrs`;
    const barColor = isOverload ? '#ef4444' : (pct >= 85 ? '#f59e0b' : '#10b981');

    return `
      <div class="insight-metric-card">
        <div class="insight-metric-header">
          <span class="insight-metric-name">${f.faculty_name}</span>
          <span class="insight-metric-badge ${badgeClass}">${badgeText}</span>
        </div>
        <div class="insight-bar-track">
          <div class="insight-bar-fill" style="width: ${Math.min(pct, 100)}%; background: ${barColor};"></div>
        </div>
        <div class="insight-metric-details">
          <span>Weekly: ${actualH}h / ${maxH}h</span>
          <span>Max Daily: ${f.max_daily_hours || 4}h (Avg: ${f.daily_average || 0}h)</span>
        </div>
      </div>
    `;
  }).join("");
}

function renderInsightsSubjects(subjectList) {
  const container = document.getElementById("insights-subjects-container");
  if (!container) return;

  if (!subjectList || subjectList.length === 0) {
    container.innerHTML = `<div style="text-align:center; color:#64748b; padding:20px;">No subject completion data available.</div>`;
    return;
  }

  container.innerHTML = subjectList.map((s) => {
    const pct = s.completion_percentage || 0;
    const isComplete = pct >= 100;
    const isExtra = s.extra_lectures > 0;
    const badgeClass = isComplete ? 'badge-optimal' : 'badge-underload';
    const badgeText = isExtra ? `+${s.extra_lectures} Extra (${s.scheduled}/${s.required})` : `${pct}% (${s.scheduled}/${s.required})`;
    const barColor = isComplete ? '#10b981' : (pct >= 50 ? '#3b82f6' : '#f59e0b');

    return `
      <div class="insight-metric-card">
        <div class="insight-metric-header">
          <span class="insight-metric-name">${s.subject_name} <small style="color:#64748b; font-weight:normal;">(${s.division_name} ${s.type || ''})</small></span>
          <span class="insight-metric-badge ${badgeClass}">${badgeText}</span>
        </div>
        <div class="insight-bar-track">
          <div class="insight-bar-fill" style="width: ${Math.min(pct, 100)}%; background: ${barColor};"></div>
        </div>
        <div class="insight-metric-details">
          <span>Scheduled: ${s.scheduled} ${s.type === 'Practical' ? 'labs' : 'lectures'}</span>
          <span>Target: ${s.required} weekly</span>
        </div>
      </div>
    `;
  }).join("");
}

function renderInsightsRooms(roomList) {
  const container = document.getElementById("insights-rooms-container");
  if (!container) return;

  if (!roomList || roomList.length === 0) {
    container.innerHTML = `<div style="text-align:center; color:#64748b; padding:20px;">No room utilization data available.</div>`;
    return;
  }

  container.innerHTML = roomList.map((r) => {
    const pct = r.utilization_percentage || 0;
    const isLab = r.room_type === "Lab";
    const barColor = pct > 80 ? '#f59e0b' : '#3b82f6';

    return `
      <div class="insight-metric-card">
        <div class="insight-metric-header">
          <span class="insight-metric-name">${r.room_name} <span class="badge ${isLab ? 'badge-info' : 'badge-secondary'}" style="font-size:10px;">${r.room_type}</span></span>
          <span class="insight-metric-badge badge-optimal">${pct}% used</span>
        </div>
        <div class="insight-bar-track">
          <div class="insight-bar-fill" style="width: ${pct}%; background: ${barColor};"></div>
        </div>
        <div class="insight-metric-details">
          <span>Occupied: ${r.scheduled_hours || 0} hrs/week</span>
          <span>Floor: ${r.floor || 1} &bull; Capacity: ${r.capacity || 60}</span>
        </div>
      </div>
    `;
  }).join("");
}

function renderInsightsLogs(logs) {
  const container = document.getElementById("insights-logs-container");
  if (!container) return;

  if (!logs || logs.length === 0) {
    container.innerHTML = `<div style="color:#64748b; padding:12px;">No execution logs recorded yet.</div>`;
    return;
  }

  container.innerHTML = logs.map((l) => {
    const timeStr = l.timestamp ? new Date(l.timestamp).toLocaleTimeString() : "";
    return `
      <div class="insight-log-line">
        <span class="insight-log-time">[${timeStr}]</span>
        <span class="insight-log-step">${l.step || l.action || 'STEP'}</span>
        <span>${l.message || l.details || JSON.stringify(l)}</span>
      </div>
    `;
  }).join("");
}

// Function to focus, scroll, and highlight any timetable cell
window.focusTimetableEntry = function (entryId) {
  if (!entryId) return;

  // Make sure Timetable tab is selected
  const tabTimetableNav = document.querySelector('[data-tab="tab-timetable"]');
  if (tabTimetableNav) tabTimetableNav.click();

  // Look for elements with data-entry-id
  const targetEl = document.querySelector(`[data-entry-id="${entryId}"]`);
  if (targetEl) {
    targetEl.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
    targetEl.classList.remove("tt-entry-highlight-pulse");
    void targetEl.offsetWidth; // trigger reflow
    targetEl.classList.add("tt-entry-highlight-pulse");
    setTimeout(() => {
      targetEl.classList.remove("tt-entry-highlight-pulse");
    }, 2800);
  } else {
    showBanner(`Entry ${entryId} is not visible under current year filters. Switch to "All Years" to view it.`, "info");
  }
};


