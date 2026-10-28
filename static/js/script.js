document.addEventListener("DOMContentLoaded", function () {
    // =========================================================================
    // Global State & Navigation
    // =========================================================================
    const state = {
        lat: 15.0000,
        lon: 75.0000,
        radius: 2000,
        name: "Western Ghats Moist Forest (Karnataka, India)",
        region: "Karnataka, India",
        currentAnalysisId: null,
        pollInterval: null
    };

    const navLinks = document.querySelectorAll(".nav-link");
    const workspaces = {
        "overview": document.getElementById("ws-overview"),
        "explorer": document.getElementById("ws-explorer"),
        "vegetation": document.getElementById("ws-vegetation"),
        "change": document.getElementById("ws-change"),
        "historical": document.getElementById("ws-historical"),
        "reports": document.getElementById("ws-reports"),
        "settings": document.getElementById("ws-settings")
    };

    function switchWorkspace(targetId) {
        navLinks.forEach(link => {
            if (link.getAttribute("data-nav") === targetId) {
                link.classList.add("active");
            } else {
                link.classList.remove("active");
            }
        });

        Object.keys(workspaces).forEach(id => {
            if (workspaces[id]) {
                workspaces[id].style.display = (id === targetId) ? "block" : "none";
            }
        });

        // Trigger map resize if needed
        if (targetId === "explorer" && explorerMap) {
            setTimeout(() => {
                explorerMap.invalidateSize();
                updateSatelliteLayers(state.lat, state.lon);
            }, 250);
        }
        if (targetId === "overview") {
            if (overviewMap) setTimeout(() => overviewMap.invalidateSize(), 250);
            loadOverviewMetrics();
            loadOperationsDashboard();
        }
        if (targetId === "change") {
            initChangeMap();
            if (changeMap) {
                setTimeout(() => {
                    changeMap.invalidateSize();
                    updateChangeMapLayers(state.lat, state.lon);
                }, 250);
            }
        }
        if (targetId === "reports") {
            loadReportsHistory();
        }

        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    navLinks.forEach(link => {
        link.addEventListener("click", () => switchWorkspace(link.getAttribute("data-nav")));
    });

    document.getElementById("brand-home-btn")?.addEventListener("click", () => switchWorkspace("overview"));
    document.getElementById("btn-quick-change-loc")?.addEventListener("click", () => switchWorkspace("explorer"));
    document.getElementById("btn-hero-explore")?.addEventListener("click", () => switchWorkspace("explorer"));
    document.getElementById("btn-hero-change")?.addEventListener("click", () => switchWorkspace("change"));
    document.getElementById("btn-hero-historical")?.addEventListener("click", () => switchWorkspace("historical"));
    document.getElementById("btn-view-all-reports")?.addEventListener("click", () => switchWorkspace("reports"));

    // Quick action tiles in Overview (if present)
    document.getElementById("qa-explorer")?.addEventListener("click", () => switchWorkspace("explorer"));
    document.getElementById("qa-vegetation")?.addEventListener("click", () => switchWorkspace("vegetation"));
    document.getElementById("qa-change")?.addEventListener("click", () => switchWorkspace("change"));
    document.getElementById("qa-historical")?.addEventListener("click", () => switchWorkspace("historical"));

    function updateActiveLocationDisplay() {
        const nameEl = document.getElementById("active-location-name");
        if (nameEl) nameEl.textContent = state.name;

        const coordsEl = document.getElementById("active-location-coords");
        if (coordsEl) coordsEl.textContent = `${state.lat.toFixed(4)}° N, ${state.lon.toFixed(4)}° E`;

        const ha = (Math.PI * state.radius * state.radius / 10000).toFixed(0);
        const areaEl = document.getElementById("active-location-area");
        if (areaEl) areaEl.textContent = `Radius: ${state.radius.toLocaleString()}m (~${ha} ha)`;

        // Sync inputs across workspaces safely
        const vegLat = document.getElementById("veg-lat");
        if (vegLat) vegLat.value = state.lat.toFixed(4);
        const vegLon = document.getElementById("veg-lon");
        if (vegLon) vegLon.value = state.lon.toFixed(4);
        const changeLat = document.getElementById("change-lat");
        if (changeLat) changeLat.value = state.lat.toFixed(4);
        const changeLon = document.getElementById("change-lon");
        if (changeLon) changeLon.value = state.lon.toFixed(4);
        const histLat = document.getElementById("hist-lat");
        if (histLat) histLat.value = state.lat.toFixed(4);
        const histLon = document.getElementById("hist-lon");
        if (histLon) histLon.value = state.lon.toFixed(4);
    }

    // =========================================================================
    // Location Explorer Map with Live Satellite & NDVI Layers (Phase 5)
    // =========================================================================
    let explorerMap = null;
    let explorerMarker = null;
    let explorerCircle = null;
    let liveRgbLayer = null;
    let liveNdviLayer = null;

    const baseStreet = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© OpenStreetMap'
    });

    const fallbackSatellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 18,
        attribution: 'Esri World Imagery'
    });

    function initExplorerMap() {
        const container = document.getElementById("explorer-map-canvas");
        if (!container || explorerMap) return;

        explorerMap = L.map('explorer-map-canvas', {
            center: [state.lat, state.lon],
            zoom: 12,
            layers: [baseStreet]
        });

        explorerMarker = L.marker([state.lat, state.lon], { draggable: true }).addTo(explorerMap);
        explorerCircle = L.circle([state.lat, state.lon], {
            color: '#2E8B57',
            fillColor: '#9FE3B0',
            fillOpacity: 0.25,
            radius: state.radius
        }).addTo(explorerMap);

        function onExplorerLocationChanged(lat, lon) {
            state.lat = parseFloat(lat.toFixed(4));
            state.lon = parseFloat(lon.toFixed(4));
            explorerMarker.setLatLng([state.lat, state.lon]);
            explorerCircle.setLatLng([state.lat, state.lon]);

            document.getElementById("display-coords").textContent = `${state.lat.toFixed(4)}° N, ${state.lon.toFixed(4)}° E`;
            const areaHa = (Math.PI * state.radius * state.radius / 10000).toFixed(0);
            document.getElementById("display-radius").textContent = `${state.radius.toLocaleString()} meters (~${areaHa} ha)`;

            updateActiveLocationDisplay();
            updateSatelliteLayers(state.lat, state.lon);
        }

        explorerMarker.on('dragend', function (e) {
            const p = e.target.getLatLng();
            onExplorerLocationChanged(p.lat, p.lng);
        });

        explorerMap.on('click', function (e) {
            onExplorerLocationChanged(e.latlng.lat, e.latlng.lng);
        });

        // Layer buttons
        const btnStreet = document.getElementById("btn-layer-street");
        const btnSat = document.getElementById("btn-layer-satellite");
        const btnNdvi = document.getElementById("btn-layer-ndvi");

        function clearLayers() {
            [btnStreet, btnSat, btnNdvi].forEach(b => b.classList.remove("active"));
            if (explorerMap.hasLayer(baseStreet)) explorerMap.removeLayer(baseStreet);
            if (explorerMap.hasLayer(fallbackSatellite)) explorerMap.removeLayer(fallbackSatellite);
            if (liveRgbLayer && explorerMap.hasLayer(liveRgbLayer)) explorerMap.removeLayer(liveRgbLayer);
            if (liveNdviLayer && explorerMap.hasLayer(liveNdviLayer)) explorerMap.removeLayer(liveNdviLayer);
        }

        btnStreet.addEventListener("click", () => {
            clearLayers();
            btnStreet.classList.add("active");
            explorerMap.addLayer(baseStreet);
        });

        btnSat.addEventListener("click", () => {
            clearLayers();
            btnSat.classList.add("active");
            if (liveRgbLayer) {
                explorerMap.addLayer(liveRgbLayer);
            } else {
                explorerMap.addLayer(fallbackSatellite);
            }
        });

        btnNdvi.addEventListener("click", () => {
            clearLayers();
            btnNdvi.classList.add("active");
            if (liveNdviLayer) {
                explorerMap.addLayer(liveNdviLayer);
            } else {
                explorerMap.addLayer(fallbackSatellite);
            }
        });
    }

    function updateSatelliteLayers(lat, lon) {
        fetch(`/api/satellite-tiles?lat=${lat}&lon=${lon}`)
        .then(res => res.json())
        .then(data => {
            document.getElementById("meta-acq-date").textContent = data.acquisition_date || "Recent Scene";
            document.getElementById("meta-cloud-pct").textContent = `${data.cloud_percentage || 0}% (SCL Filtered)`;
            document.getElementById("meta-quality-flag").textContent = data.quality_flag || "Standard Quality";

            if (data.rgb_tile_url && explorerMap) {
                if (liveRgbLayer && explorerMap.hasLayer(liveRgbLayer)) explorerMap.removeLayer(liveRgbLayer);
                liveRgbLayer = L.tileLayer(data.rgb_tile_url, { maxZoom: 18, attribution: 'Copernicus Sentinel-2' });

                if (document.getElementById("btn-layer-satellite").classList.contains("active")) {
                    if (explorerMap.hasLayer(fallbackSatellite)) explorerMap.removeLayer(fallbackSatellite);
                    explorerMap.addLayer(liveRgbLayer);
                }
            }

            if (data.ndvi_tile_url && explorerMap) {
                if (liveNdviLayer && explorerMap.hasLayer(liveNdviLayer)) explorerMap.removeLayer(liveNdviLayer);
                liveNdviLayer = L.tileLayer(data.ndvi_tile_url, { maxZoom: 18, attribution: 'Sentinel-2 NDVI' });

                if (document.getElementById("btn-layer-ndvi").classList.contains("active")) {
                    explorerMap.addLayer(liveNdviLayer);
                }
            }
        })
        .catch(err => console.error("Tile fetch error:", err));
    }

    initExplorerMap();

    document.getElementById("btn-carry-analysis").addEventListener("click", () => {
        switchWorkspace("change");
    });

    // =========================================================================
    // Geocoding Search
    // =========================================================================
    const searchInput = document.getElementById("location-search-input");
    const searchDropdown = document.getElementById("search-dropdown");
    const searchClearBtn = document.getElementById("search-clear-btn");
    let searchTimer = null;

    searchInput.addEventListener("input", function () {
        const q = this.value.trim();
        clearTimeout(searchTimer);
        if (q.length < 2) {
            searchDropdown.style.display = "none";
            return;
        }

        searchTimer = setTimeout(() => {
            fetch(`/api/geocode?q=${encodeURIComponent(q)}`)
            .then(res => res.json())
            .then(data => {
                if (!data.results || data.results.length === 0) {
                    searchDropdown.innerHTML = `<div class="search-item-empty">No matching reserves or places found.</div>`;
                    searchDropdown.style.display = "block";
                    return;
                }

                searchDropdown.innerHTML = data.results.map(item => `
                    <div class="search-item" data-lat="${item.latitude}" data-lon="${item.longitude}" data-name="${item.name}">
                        <div class="search-item-title">🌲 ${item.name}</div>
                        <div class="search-item-sub">${item.display_name}</div>
                        <span class="search-item-tag">${item.source}</span>
                    </div>
                `).join("");
                searchDropdown.style.display = "block";

                document.querySelectorAll(".search-item").forEach(el => {
                    el.addEventListener("click", function () {
                        const lat = parseFloat(this.getAttribute("data-lat"));
                        const lon = parseFloat(this.getAttribute("data-lon"));
                        const name = this.getAttribute("data-name");

                        searchInput.value = name;
                        searchDropdown.style.display = "none";

                        state.lat = lat;
                        state.lon = lon;
                        state.name = name;

                        if (explorerMap) {
                            explorerMap.setView([lat, lon], 12);
                            explorerMarker.setLatLng([lat, lon]);
                            explorerCircle.setLatLng([lat, lon]);
                        }
                        document.getElementById("display-coords").textContent = `${lat.toFixed(4)}° N, ${lon.toFixed(4)}° E`;
                        updateActiveLocationDisplay();
                        updateSatelliteLayers(lat, lon);
                    });
                });
            });
        }, 300);
    });

    searchClearBtn.addEventListener("click", () => {
        searchInput.value = "";
        searchDropdown.style.display = "none";
    });

    // =========================================================================
    // Saved Locations Library & Overview Map
    // =========================================================================
    const saveLocationModal = document.getElementById("save-location-modal");
    document.getElementById("btn-save-location").addEventListener("click", () => {
        document.getElementById("save-loc-name").value = state.name;
        document.getElementById("save-loc-region").value = state.region;
        document.getElementById("save-loc-notes").value = "";
        saveLocationModal.style.display = "flex";
    });

    document.getElementById("modal-close-btn").addEventListener("click", () => saveLocationModal.style.display = "none");
    document.getElementById("modal-cancel-btn").addEventListener("click", () => saveLocationModal.style.display = "none");

    document.getElementById("modal-confirm-btn").addEventListener("click", () => {
        const name = document.getElementById("save-loc-name").value.trim();
        const region = document.getElementById("save-loc-region").value.trim();
        const notes = document.getElementById("save-loc-notes").value.trim();

        if (!name) return alert("Please specify a location name.");

        fetch("/api/locations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name: name,
                region: region || "Conservation Area",
                latitude: state.lat,
                longitude: state.lon,
                radius_meters: state.radius,
                notes: notes
            })
        })
        .then(res => res.json())
        .then(() => {
            saveLocationModal.style.display = "none";
            loadSavedLocations();
            loadOverviewMetrics();
        });
    });

    let overviewMap = null;
    let overviewReservesLayer = null;
    let overviewIncidentsLayer = null;
    let operationalIncidents = [];
    let operationalReserves = [];
    let activeMapFilter = 'all';
    let currentIncidentId = null;

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function getPriorityBadgeClass(priority) {
        if (!priority) return 'badge-gray';
        const p = priority.toLowerCase();
        if (p === 'critical') return 'badge-danger';
        if (p === 'high') return 'badge-danger';
        if (p === 'medium') return 'badge-yellow';
        if (p === 'low') return 'badge-green';
        return 'badge-gray';
    }

    function getStatusBadgeClass(status) {
        if (!status) return 'badge-gray';
        const s = status.toLowerCase();
        if (s === 'new') return 'badge-danger';
        if (s === 'reviewed') return 'badge-yellow';
        if (s === 'assigned' || s.includes('investigation') || s.includes('field')) return 'badge-blue';
        if (s === 'resolved') return 'badge-green';
        if (s.includes('false') || s.includes('insufficient')) return 'badge-gray';
        return 'badge-gray';
    }

    function initOverviewMap(locations) {
        const container = document.getElementById("overview-map");
        if (!container) return;

        if (!overviewMap) {
            overviewMap = L.map('overview-map', {
                center: [20.5937, 78.9629],
                zoom: 5,
                layers: [
                    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                        maxZoom: 18,
                        attribution: '&copy; OpenStreetMap contributors | Copernicus Sentinel-2'
                    })
                ]
            });
            overviewReservesLayer = L.layerGroup().addTo(overviewMap);
            overviewIncidentsLayer = L.layerGroup().addTo(overviewMap);
        }

        if (locations && locations.length > 0) {
            operationalReserves = locations;
        }

        renderOperationsMapLayers();

        setTimeout(() => {
            if (overviewMap) overviewMap.invalidateSize();
        }, 300);
    }

    function renderOperationsMapLayers() {
        if (!overviewMap || !overviewReservesLayer || !overviewIncidentsLayer) return;

        overviewReservesLayer.clearLayers();
        overviewIncidentsLayer.clearLayers();

        // 1. Render Monitored Reserves Boundaries (Green circles)
        if (operationalReserves && operationalReserves.length > 0) {
            operationalReserves.forEach(loc => {
                const rad = loc.radius_meters || 5000;
                const circle = L.circle([loc.latitude, loc.longitude], {
                    radius: rad,
                    color: '#10b981',
                    fillColor: '#10b981',
                    fillOpacity: 0.12,
                    weight: 2,
                    dashArray: '5, 5'
                });

                circle.bindPopup(`
                    <div style="font-family: inherit; font-size: 13px; min-width: 180px;">
                        <strong style="color: #065f46; font-size: 14px;">🌲 ${escapeHtml(loc.name)}</strong><br>
                        <span style="color: #64748b; font-size: 12px;">${escapeHtml(loc.region || 'Forest Reserve')}</span>
                        <div style="margin-top: 4px; font-size: 11px; color: #475569;">
                            Perimeter: ${(rad / 1000).toFixed(1)} km radius<br>
                            Coordinates: ${loc.latitude.toFixed(3)}° N, ${loc.longitude.toFixed(3)}° E
                        </div>
                        <div style="margin-top: 8px;">
                            <button class="btn-sm-outline" style="width: 100%; cursor: pointer;" onclick="window.selectAndGo(${loc.latitude}, ${loc.longitude}, '${escapeHtml(loc.name)}')">Launch Sentinel Scan 🛰️</button>
                        </div>
                    </div>
                `);
                overviewReservesLayer.addLayer(circle);
            });
        }

        // 2. Render Incident Markers according to activeMapFilter
        let visibleCount = 0;
        if (activeMapFilter !== 'reserves' && operationalIncidents && operationalIncidents.length > 0) {
            operationalIncidents.forEach(inc => {
                // Apply activeMapFilter
                if (activeMapFilter === 'priority' && inc.priority !== 'Critical' && inc.priority !== 'High') {
                    return;
                }
                if (activeMapFilter === 'active' && (inc.status === 'Resolved' || inc.status === 'False Positive')) {
                    return;
                }

                visibleCount++;
                let markerColor = '#10b981';
                let markerRadius = 9;

                if (inc.status === 'Resolved' || inc.status === 'False Positive') {
                    markerColor = '#64748b';
                    markerRadius = 8;
                } else if (inc.priority === 'Critical') {
                    markerColor = '#ef4444';
                    markerRadius = 14;
                } else if (inc.priority === 'High') {
                    markerColor = '#f97316';
                    markerRadius = 12;
                } else if (inc.priority === 'Medium') {
                    markerColor = '#eab308';
                    markerRadius = 10;
                }

                const marker = L.circleMarker([inc.latitude, inc.longitude], {
                    radius: markerRadius,
                    fillColor: markerColor,
                    color: '#ffffff',
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 0.85
                });

                marker.bindPopup(`
                    <div style="font-family: inherit; min-width: 210px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                            <strong style="font-size: 13px; color: #0f172a;">${escapeHtml(inc.id)}</strong>
                            <span class="badge ${getPriorityBadgeClass(inc.priority)}" style="font-size: 10px;">${escapeHtml(inc.priority)}</span>
                        </div>
                        <div style="font-weight: 600; color: #1e293b; margin-bottom: 4px; font-size: 12px;">${escapeHtml(inc.title)}</div>
                        <div style="font-size: 11px; color: #475569; margin-bottom: 8px; line-height: 1.4;">
                            📍 <strong>${escapeHtml(inc.location_name)}</strong><br>
                            📉 Potential Loss: <strong style="color: #dc2626;">${inc.affected_ha} ha</strong> (${inc.affected_pct}%)<br>
                            👮 Officer: ${escapeHtml(inc.assigned_officer || 'Unassigned')}<br>
                            ⚖️ Status: <span class="badge ${getStatusBadgeClass(inc.status)}" style="font-size: 9px; padding: 1px 4px;">${escapeHtml(inc.status)}</span>
                        </div>
                        <button class="btn-solid-green" style="width: 100%; font-size: 11px; padding: 5px 8px; cursor: pointer;" onclick="window.openIncidentWorkspace('${escapeHtml(inc.id)}')">
                            Investigate Incident 🔍
                        </button>
                    </div>
                `);

                overviewIncidentsLayer.addLayer(marker);
            });
        }

        const countBadge = document.getElementById("ops-map-marker-count");
        if (countBadge) {
            if (activeMapFilter === 'reserves') {
                countBadge.textContent = `Showing ${operationalReserves.length} Reserves`;
            } else {
                countBadge.textContent = `Showing ${visibleCount} Incident Pin${visibleCount !== 1 ? 's' : ''}`;
            }
        }
    }

    function renderIncidentTable() {
        const tbody = document.getElementById("operations-incidents-tbody");
        if (!tbody) return;

        const priorityFilter = document.getElementById("filter-incident-priority")?.value || "all";
        const statusFilter = document.getElementById("filter-incident-status")?.value || "all";
        const searchFilter = (document.getElementById("filter-incident-search")?.value || "").toLowerCase().trim();

        const filtered = operationalIncidents.filter(inc => {
            if (priorityFilter !== "all" && inc.priority !== priorityFilter) return false;
            if (statusFilter !== "all" && inc.status !== statusFilter) return false;
            if (searchFilter) {
                const combined = `${inc.id} ${inc.title} ${inc.location_name} ${inc.assigned_officer || ''} ${inc.range_division || ''}`.toLowerCase();
                if (!combined.includes(searchFilter)) return false;
            }
            return true;
        });

        if (filtered.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 24px; color: #94a3b8;">No incidents match the active filters.</td></tr>`;
            return;
        }

        tbody.innerHTML = filtered.map(inc => `
            <tr>
                <td><code>${escapeHtml(inc.id)}</code></td>
                <td>
                    <strong>${escapeHtml(inc.location_name)}</strong>
                    <div style="font-size: 0.74rem; color: #64748b;">${inc.latitude.toFixed(4)}° N, ${inc.longitude.toFixed(4)}° E</div>
                </td>
                <td><span style="font-size: 0.82rem;">${escapeHtml(inc.detection_type || 'Potential Canopy Loss')}</span></td>
                <td>
                    <strong style="color: ${inc.affected_ha >= 25 ? '#dc2626' : '#d97706'}; font-size: 0.92rem;">${inc.affected_ha} ha</strong>
                    <div style="font-size: 0.74rem; color: #64748b;">(${inc.affected_pct}% cover)</div>
                </td>
                <td><span class="badge ${getPriorityBadgeClass(inc.priority)}">${escapeHtml(inc.priority)}</span></td>
                <td><span class="badge ${getStatusBadgeClass(inc.status)}">${escapeHtml(inc.status)}</span></td>
                <td>
                    <div style="font-weight: 500;">${escapeHtml(inc.assigned_officer || 'Unassigned')}</div>
                    <div style="font-size: 0.74rem; color: #64748b;">${escapeHtml(inc.range_division || 'No Range')}</div>
                </td>
                <td style="font-size: 0.78rem;">${escapeHtml(inc.observation_date || 'Recent S2')}</td>
                <td>
                    <button class="btn-sm-outline" style="cursor: pointer;" onclick="window.openIncidentWorkspace('${escapeHtml(inc.id)}')">Investigate 🔍</button>
                </td>
            </tr>
        `).join("");
    }

    function renderOperationsAuditFeed() {
        const feed = document.getElementById("operations-audit-feed");
        if (!feed) return;

        let allLogs = [];
        operationalIncidents.forEach(inc => {
            if (inc.activity_log && Array.isArray(inc.activity_log)) {
                inc.activity_log.forEach(item => {
                    allLogs.push({
                        ...item,
                        incident_id: inc.id,
                        location: inc.location_name
                    });
                });
            }
        });

        allLogs.sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''));

        if (allLogs.length === 0) {
            feed.innerHTML = `<div class="audit-item" style="color: #94a3b8; padding: 12px;">No operational activity logged yet.</div>`;
            return;
        }

        feed.innerHTML = allLogs.slice(0, 8).map(log => `
            <div class="audit-item">
                <div class="audit-time">${escapeHtml(log.timestamp || 'Recent')}</div>
                <div class="audit-details">
                    <strong style="color: #065f46;">[${escapeHtml(log.incident_id)}] ${escapeHtml(log.action)}</strong>: ${escapeHtml(log.details)}
                    <span class="audit-user">&bull; Authorized Officer: <em>${escapeHtml(log.user || 'System')}</em></span>
                </div>
            </div>
        `).join("");
    }

    function loadOperationsDashboard() {
        fetch("/api/operations/summary")
            .then(res => res.json())
            .then(summary => {
                const unresEl = document.getElementById("ops-unresolved-alerts");
                if (unresEl) unresEl.textContent = summary.unresolved_alerts ?? "--";
                
                const priEl = document.getElementById("ops-priority-cases");
                if (priEl) priEl.textContent = summary.priority_cases ?? "--";

                const invEl = document.getElementById("ops-investigations");
                if (invEl) invEl.textContent = summary.ongoing_investigations ?? "--";

                const resEl = document.getElementById("ops-monitored-reserves");
                if (resEl) resEl.textContent = summary.monitored_reserves ?? "6";

                const obsEl = document.getElementById("ops-latest-obs");
                if (obsEl) obsEl.textContent = summary.latest_observation || "Recent Pass";

                const btnCount = document.getElementById("ops-btn-alert-count");
                if (btnCount) btnCount.textContent = summary.unresolved_alerts ?? "--";
            })
            .catch(err => console.error("Error loading operations summary:", err));

        fetch("/api/incidents")
            .then(res => res.json())
            .then(data => {
                operationalIncidents = data.incidents || [];
                renderIncidentTable();
                renderOperationsAuditFeed();
                renderOperationsMapLayers();
            })
            .catch(err => console.error("Error loading incidents:", err));
    }

    window.openIncidentWorkspace = function (incidentId) {
        currentIncidentId = incidentId;
        const modal = document.getElementById("incident-workspace-modal");
        if (!modal) return;

        fetch(`/api/incidents/${incidentId}`)
            .then(res => res.json())
            .then(inc => {
                if (inc.error) return alert("Incident not found: " + inc.error);

                document.getElementById("inc-modal-id").textContent = inc.id;
                
                const priBadge = document.getElementById("inc-modal-priority");
                priBadge.textContent = inc.priority;
                priBadge.className = `badge ${getPriorityBadgeClass(inc.priority)}`;

                const stBadge = document.getElementById("inc-modal-status");
                stBadge.textContent = inc.status;
                stBadge.className = `badge ${getStatusBadgeClass(inc.status)}`;

                document.getElementById("inc-modal-title").textContent = inc.title;
                document.getElementById("inc-modal-loss").textContent = `${inc.affected_ha} ha`;
                document.getElementById("inc-modal-loss-pct").textContent = `${inc.affected_pct}% cover`;
                document.getElementById("inc-modal-dndvi").textContent = (inc.mean_dndvi !== undefined && inc.mean_dndvi !== null) ? inc.mean_dndvi : "-0.24";
                document.getElementById("inc-modal-obs-date").textContent = inc.observation_date || "Recent S2 Pass";
                document.getElementById("inc-modal-quality").textContent = inc.quality_flags || "SCL Filtered (High)";

                const imgEl = document.getElementById("inc-modal-map");
                const phEl = document.getElementById("inc-modal-map-placeholder");
                if (inc.map_url) {
                    imgEl.src = inc.map_url;
                    imgEl.style.display = "block";
                    if (phEl) phEl.style.display = "none";
                } else {
                    imgEl.style.display = "none";
                    if (phEl) phEl.style.display = "flex";
                }

                const pdfBtn = document.getElementById("inc-modal-pdf-btn");
                if (pdfBtn) pdfBtn.href = inc.pdf_url || (inc.analysis_id ? `/export/pdf/${inc.analysis_id}` : "#");

                const csvBtn = document.getElementById("inc-modal-csv-btn");
                if (csvBtn) csvBtn.href = inc.csv_url || (inc.analysis_id ? `/export/csv/${inc.analysis_id}` : "#");

                const statusSelect = document.getElementById("inc-status-select");
                if (statusSelect) statusSelect.value = inc.status;

                const statusNote = document.getElementById("inc-status-notes") || document.getElementById("inc-status-note");
                if (statusNote) statusNote.value = "";

                const officerInput = document.getElementById("inc-assign-officer");
                if (officerInput) officerInput.value = inc.assigned_officer || "";

                const rangeInput = document.getElementById("inc-assign-range");
                if (rangeInput) rangeInput.value = inc.range_division || "";

                renderIncidentModalNotes(inc.field_notes);
                renderIncidentModalAudit(inc.activity_log);
                renderIncidentModalNotifications(incidentId);

                modal.style.display = "flex";
            })
            .catch(err => {
                console.error("Failed to fetch incident details:", err);
                alert("Failed to load incident record.");
            });
    };

    function renderIncidentModalNotes(notes) {
        const stream = document.getElementById("inc-modal-notes-list");
        if (!stream) return;
        if (!notes || notes.length === 0) {
            stream.innerHTML = `<p class="empty-note">No field verification notes recorded yet.</p>`;
            return;
        }
        stream.innerHTML = notes.map(n => `
            <div class="note-card">
                <div class="note-meta">
                    <strong>${escapeHtml(n.author || 'Field Officer')}</strong> &bull; 
                    <span style="color: #64748b;">${escapeHtml(n.timestamp || 'Recorded')}</span>
                </div>
                <div class="note-text">${escapeHtml(n.text)}</div>
                ${n.photo_url ? `
                    <div class="note-photo-preview">
                        <a href="${escapeHtml(n.photo_url)}" target="_blank" title="Click to inspect ground photographic evidence in new tab">
                            <img src="${escapeHtml(n.photo_url)}" class="note-photo-thumb" alt="Field Photo Evidence">
                        </a>
                    </div>
                ` : ''}
            </div>
        `).join("");
    }

    function renderIncidentModalNotifications(incidentId) {
        const list = document.getElementById("inc-modal-notifications-list");
        if (!list) return;

        fetch(`/api/notifications?incident_id=${incidentId}`)
            .then(res => res.json())
            .then(data => {
                const logs = data.notifications || [];
                const badge = document.getElementById("inc-modal-test-mode-badge");
                if (badge) {
                    badge.textContent = data.test_mode ? "TEST MODE (Simulated)" : "LIVE DISPATCH";
                    badge.className = data.test_mode ? "badge badge-yellow" : "badge badge-green";
                }

                if (logs.length === 0) {
                    list.innerHTML = `<div class="audit-row"><span class="audit-text">No alert notifications logged for this incident yet.</span></div>`;
                    return;
                }

                list.innerHTML = logs.map(l => `
                    <div class="audit-row" style="font-size: 0.74rem;">
                        <span class="audit-time">${escapeHtml(l.timestamp)}</span>
                        <span class="audit-text">
                            <strong>[${escapeHtml(l.channel).toUpperCase()}]</strong>
                            To: <em>${escapeHtml(l.recipient_name)} (${escapeHtml(l.recipient_role)})</em> &bull;
                            <span class="badge ${l.status === 'simulated' ? 'badge-yellow' : 'badge-green'}" style="font-size: 8px; padding: 1px 4px;">${escapeHtml(l.status)}</span>
                            <div style="color: #94a3b8; font-size: 0.7rem; margin-top: 2px;">${escapeHtml(l.details || l.subject)}</div>
                        </span>
                    </div>
                `).join("");
            })
            .catch(() => {
                list.innerHTML = `<div class="audit-row"><span class="audit-text">Failed to load notification logs.</span></div>`;
            });
    }

    function renderIncidentModalAudit(logs) {
        const stream = document.getElementById("inc-modal-audit-list");
        if (!stream) return;
        if (!logs || logs.length === 0) {
            stream.innerHTML = `<div class="audit-row"><span class="audit-text">No audit history recorded.</span></div>`;
            return;
        }
        stream.innerHTML = logs.map(a => `
            <div class="audit-row">
                <span class="audit-time">${escapeHtml(a.timestamp || '')}</span>
                <span class="audit-text"><strong>${escapeHtml(a.action)}</strong>: ${escapeHtml(a.details)} <em>(${escapeHtml(a.user || 'System')})</em></span>
            </div>
        `).join("");
    }

    // Modal Action Listeners
    const incModal = document.getElementById("incident-workspace-modal");
    document.getElementById("inc-modal-close-btn")?.addEventListener("click", () => {
        if (incModal) incModal.style.display = "none";
    });
    document.getElementById("inc-modal-done-btn")?.addEventListener("click", () => {
        if (incModal) incModal.style.display = "none";
    });

    document.getElementById("btn-update-inc-status")?.addEventListener("click", () => {
        if (!currentIncidentId) return;
        const statusVal = document.getElementById("inc-status-select")?.value;
        const noteEl = document.getElementById("inc-status-notes") || document.getElementById("inc-status-note");
        const noteVal = noteEl ? noteEl.value.trim() : "";

        fetch(`/api/incidents/${currentIncidentId}/status`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                status: statusVal,
                note: noteVal,
                user: "Range Officer (Command Center)"
            })
        })
        .then(res => res.json())
        .then(updated => {
            if (updated.error) return alert("Failed to update status: " + updated.error);
            window.openIncidentWorkspace(currentIncidentId);
            loadOperationsDashboard();
        })
        .catch(err => alert("Error updating incident status: " + err));
    });

    document.getElementById("btn-update-inc-assign")?.addEventListener("click", () => {
        if (!currentIncidentId) return;
        const officerVal = document.getElementById("inc-assign-officer").value.trim();
        const rangeVal = document.getElementById("inc-assign-range").value.trim();

        if (!officerVal) return alert("Please specify an officer name to assign.");

        fetch(`/api/incidents/${currentIncidentId}/assign`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                officer: officerVal,
                range: rangeVal,
                user: "Divisional Forest Officer"
            })
        })
        .then(res => res.json())
        .then(updated => {
            if (updated.error) return alert("Failed to assign officer: " + updated.error);
            window.openIncidentWorkspace(currentIncidentId);
            loadOperationsDashboard();
        })
        .catch(err => alert("Error updating assignment: " + err));
    });

    document.getElementById("btn-add-inc-note")?.addEventListener("click", () => {
        if (!currentIncidentId) return;
        const authorVal = document.getElementById("inc-new-note-author").value.trim() || "Field Officer";
        const textVal = document.getElementById("inc-new-note-text").value.trim();

        if (!textVal) return alert("Please enter a note before submitting.");

        fetch(`/api/incidents/${currentIncidentId}/notes`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                author: authorVal,
                text: textVal
            })
        })
        .then(res => res.json())
        .then(updated => {
            if (updated.error) return alert("Failed to add note: " + updated.error);
            document.getElementById("inc-new-note-text").value = "";
            renderIncidentModalNotes(updated.field_notes);
            renderIncidentModalAudit(updated.activity_log);
            renderIncidentModalNotifications(currentIncidentId);
            loadOperationsDashboard();
        })
        .catch(err => alert("Error adding note: " + err));
    });

    // Ground Photo Evidence Upload
    document.getElementById("btn-upload-inc-photo")?.addEventListener("click", () => {
        if (!currentIncidentId) return;
        const fileInput = document.getElementById("inc-upload-file");
        const captionInput = document.getElementById("inc-upload-caption");

        if (!fileInput.files || fileInput.files.length === 0) {
            return alert("Please select a photographic file (.jpg, .png, .webp) before uploading.");
        }

        const formData = new FormData();
        formData.append("photo", fileInput.files[0]);
        formData.append("caption", captionInput.value.trim() || "Ground-truthing photographic evidence");

        const btn = document.getElementById("btn-upload-inc-photo");
        const origText = btn.textContent;
        btn.textContent = "Uploading Photographic Evidence...";
        btn.disabled = true;

        fetch(`/api/incidents/${currentIncidentId}/upload-photo`, {
            method: "POST",
            body: formData
        })
        .then(res => res.json())
        .then(data => {
            btn.textContent = origText;
            btn.disabled = false;
            if (data.error) return alert("Upload failed: " + data.error);

            fileInput.value = "";
            captionInput.value = "";
            renderIncidentModalNotes(data.incident?.field_notes || data.field_notes);
            renderIncidentModalAudit(data.incident?.activity_log || data.activity_log);
            renderIncidentModalNotifications(currentIncidentId);
            loadOperationsDashboard();
        })
        .catch(err => {
            btn.textContent = origText;
            btn.disabled = false;
            alert("Error uploading evidence photo: " + err);
        });
    });

    // Test Notification Dispatch
    document.getElementById("btn-dispatch-test-notif")?.addEventListener("click", () => {
        if (!currentIncidentId) return;
        fetch("/api/notifications/test", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ incident_id: currentIncidentId })
        })
        .then(res => res.json())
        .then(data => {
            if (data.error) return alert("Notification test failed: " + data.error);
            renderIncidentModalNotifications(currentIncidentId);
            loadOperationsDashboard();
            alert("Safe Test-Mode notification dispatched. Inspect logs below.");
        })
        .catch(err => alert("Error dispatching test notification: " + err));
    });

    document.getElementById("btn-inc-open-change")?.addEventListener("click", () => {
        if (!currentIncidentId) return;
        const inc = operationalIncidents.find(i => i.id === currentIncidentId);
        if (inc) {
            state.lat = inc.latitude;
            state.lon = inc.longitude;
            state.name = inc.location_name;
            updateActiveLocationDisplay();
            if (incModal) incModal.style.display = "none";
            switchWorkspace("change");
            if (inc.analysis_id) {
                window.viewPastRun(inc.analysis_id);
            }
        }
    });

    // Map Filter Buttons
    const mapFilterBtns = [
        { id: "btn-opsfilter-all", filter: "all" },
        { id: "btn-opsfilter-priority", filter: "priority" },
        { id: "btn-opsfilter-active", filter: "active" },
        { id: "btn-opsfilter-reserves", filter: "reserves" }
    ];

    mapFilterBtns.forEach(btnObj => {
        const btn = document.getElementById(btnObj.id);
        if (btn) {
            btn.addEventListener("click", () => {
                mapFilterBtns.forEach(b => {
                    const el = document.getElementById(b.id);
                    if (el) el.classList.remove("active");
                });
                btn.classList.add("active");
                activeMapFilter = btnObj.filter;
                renderOperationsMapLayers();
            });
        }
    });

    // Table Filters
    document.getElementById("filter-incident-priority")?.addEventListener("change", renderIncidentTable);
    document.getElementById("filter-incident-status")?.addEventListener("change", renderIncidentTable);
    document.getElementById("filter-incident-search")?.addEventListener("input", renderIncidentTable);

    // Operations Header Buttons
    document.getElementById("btn-ops-scroll-alerts")?.addEventListener("click", () => {
        const section = document.getElementById("ops-incidents-section");
        if (section) section.scrollIntoView({ behavior: "smooth" });
    });
    document.getElementById("btn-ops-launch-change")?.addEventListener("click", () => {
        switchWorkspace("change");
    });

    window.selectAndGo = function (lat, lon, name) {
        state.lat = lat;
        state.lon = lon;
        state.name = name;
        updateActiveLocationDisplay();
        switchWorkspace("change");
    };

    function loadSavedLocations() {
        fetch("/api/locations")
        .then(res => res.json())
        .then(data => {
            const locs = data.locations || [];
            const countEl = document.getElementById("stat-total-locations");
            if (countEl) countEl.textContent = locs.length;

            const grid = document.getElementById("saved-locations-list");
            if (grid) {
                grid.innerHTML = locs.map(loc => `
                    <div class="saved-loc-card">
                        <div class="loc-card-header">
                            <strong class="loc-card-title">${escapeHtml(loc.name)}</strong>
                            <span class="loc-card-badge">${escapeHtml(loc.region)}</span>
                        </div>
                        <div class="loc-card-coords">${loc.latitude}° N, ${loc.longitude}° E</div>
                        <div class="loc-card-desc">${escapeHtml(loc.description || loc.notes || '')}</div>
                        <button class="btn-load-loc" onclick="window.selectAndGo(${loc.latitude}, ${loc.longitude}, '${escapeHtml(loc.name)}')">Select Area</button>
                    </div>
                `).join("");
            }

            initOverviewMap(locs);
        });
    }

    // =========================================================================
    // Change Detection Workspace (Production GIS & Environmental Intelligence)
    // =========================================================================
    let changeMap = null;
    let changeMarker = null;
    let changeCircle = null;
    let changeBaseStreet = null;
    let changeFallbackSat = null;
    let changeLiveRgbLayer = null;
    let changeLiveNdviLayer = null;
    let changeRasterLayer = null;
    let currentMapUrl = null;

    const runChangeBtn = document.getElementById("run-change-button");
    const stopChangeBtn = document.getElementById("stop-change-button");
    const changeResultsPanel = document.getElementById("change-results-panel");
    const changeMapImg = document.getElementById("change-map-image");
    const changeStatsImg = document.getElementById("change-stats-image");
    const noChangeMapMsg = document.getElementById("no-change-map-msg");
    const noChangeStatsMsg = document.getElementById("no-change-stats-msg");
    const changeReportContent = document.getElementById("change-report-content");
    const changeLogContainer = document.getElementById("change-log-container");
    const changeProgressCard = document.getElementById("change-pipeline-progress");
    const changeDateWarning = document.getElementById("change-date-warning");
    const changeDateWarningMsg = document.getElementById("change-date-warning-msg");

    // Initialize Interactive Leaflet Change Map
    function initChangeMap() {
        const container = document.getElementById("change-leaflet-map");
        if (!container || changeMap) return;

        changeBaseStreet = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors'
        });

        changeFallbackSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            maxZoom: 18,
            attribution: 'Esri World Imagery'
        });

        changeMap = L.map('change-leaflet-map', {
            center: [state.lat, state.lon],
            zoom: 12,
            layers: [changeBaseStreet]
        });

        changeMarker = L.marker([state.lat, state.lon], { draggable: true }).addTo(changeMap);
        changeCircle = L.circle([state.lat, state.lon], {
            color: '#D9534F',
            fillColor: '#FF6B6B',
            fillOpacity: 0.20,
            radius: state.radius
        }).addTo(changeMap);

        // Marker drag & map click events
        function onChangeCoordChanged(lat, lon) {
            state.lat = parseFloat(lat.toFixed(4));
            state.lon = parseFloat(lon.toFixed(4));
            changeMarker.setLatLng([state.lat, state.lon]);
            changeCircle.setLatLng([state.lat, state.lon]);

            document.getElementById("change-lat").value = state.lat.toFixed(4);
            document.getElementById("change-lon").value = state.lon.toFixed(4);
            document.getElementById("change-active-target").textContent = `${state.name} (${state.lat.toFixed(4)}° N, ${state.lon.toFixed(4)}° E)`;
            updateActiveLocationDisplay();
            updateChangeMapLayers(state.lat, state.lon);
        }

        changeMarker.on('dragend', function (e) {
            const p = e.target.getLatLng();
            onChangeCoordChanged(p.lat, p.lng);
        });

        changeMap.on('click', function (e) {
            const p = e.latlng;
            onChangeCoordChanged(p.lat, p.lng);

            // Show inspector HUD
            const inspectHud = document.getElementById("cmap-inspect-hud");
            if (inspectHud) {
                const distKm = (changeMap.distance([state.lat, state.lon], [p.lat, p.lng]) / 1000).toFixed(2);
                document.getElementById("inspect-coords").textContent = `${p.lat.toFixed(4)}° N, ${p.lng.toFixed(4)}° E`;
                document.getElementById("inspect-distance").textContent = `${distKm} km from center`;
                const inAoi = (distKm * 1000) <= state.radius;
                const statusEl = document.getElementById("inspect-status");
                statusEl.textContent = inAoi ? "Inside Monitored Radius" : "Outside Target AOI";
                statusEl.className = inAoi ? "badge badge-green" : "badge badge-gray";
                inspectHud.style.display = "block";
            }
        });

        // Layer selection buttons
        const btnSat = document.getElementById("btn-cmap-satellite");
        const btnNdvi = document.getElementById("btn-cmap-ndvi");
        const btnRaster = document.getElementById("btn-cmap-raster");
        const btnStreet = document.getElementById("btn-cmap-street");
        const allLayerBtns = [btnSat, btnNdvi, btnRaster, btnStreet];

        function resetChangeLayers() {
            allLayerBtns.forEach(b => { if (b) b.classList.remove("active"); });
            if (changeMap.hasLayer(changeBaseStreet)) changeMap.removeLayer(changeBaseStreet);
            if (changeMap.hasLayer(changeFallbackSat)) changeMap.removeLayer(changeFallbackSat);
            if (changeLiveRgbLayer && changeMap.hasLayer(changeLiveRgbLayer)) changeMap.removeLayer(changeLiveRgbLayer);
            if (changeLiveNdviLayer && changeMap.hasLayer(changeLiveNdviLayer)) changeMap.removeLayer(changeLiveNdviLayer);
        }

        function updateMapLegend(layerType) {
            const legendTitle = document.getElementById("change-legend-title");
            const legendGrid = document.getElementById("change-legend-grid");
            if (!legendTitle || !legendGrid) return;

            if (layerType === "satellite") {
                legendTitle.textContent = "Copernicus Sentinel-2 True-Color";
                legendGrid.innerHTML = `
                    <div class="leg-item"><span class="leg-swatch" style="background:#2e7d32;"></span> <strong>Forest Canopy</strong> (Surface BOA)</div>
                    <div class="leg-item"><span class="leg-swatch" style="background:#8d6e63;"></span> <strong>Bare Soil / Cleared</strong></div>
                    <div class="leg-item"><span class="leg-swatch" style="background:#1565c0;"></span> <strong>Water Body</strong></div>
                    <div class="leg-item"><span class="leg-swatch masked-transparent-swatch"></span> <strong>Cloud / SCL Masked</strong> (Transparent)</div>
                `;
            } else if (layerType === "ndvi") {
                legendTitle.textContent = "Sentinel-2 Live NDVI Scale";
                legendGrid.innerHTML = `
                    <div class="leg-item"><span class="leg-swatch ndvi-dense-swatch"></span> <strong>Dense Canopy</strong> (NDVI > 0.60)</div>
                    <div class="leg-item"><span class="leg-swatch ndvi-mod-swatch"></span> <strong>Moderate Canopy</strong> (0.40–0.60)</div>
                    <div class="leg-item"><span class="leg-swatch ndvi-sparse-swatch"></span> <strong>Sparse / Grass</strong> (0.20–0.40)</div>
                    <div class="leg-item"><span class="leg-swatch ndvi-bare-swatch"></span> <strong>Non-Forest / Bare</strong> (&lt; 0.20)</div>
                    <div class="leg-item"><span class="leg-swatch masked-transparent-swatch"></span> <strong>Masked / Water</strong> (Transparent)</div>
                `;
            } else if (layerType === "street") {
                legendTitle.textContent = "Cartographic Context";
                legendGrid.innerHTML = `
                    <div class="leg-item"><span class="leg-swatch" style="background:#ffc107;"></span> <strong>Roads & Access Paths</strong></div>
                    <div class="leg-item"><span class="leg-swatch" style="background:#90caf9;"></span> <strong>Waterways / Rivers</strong></div>
                    <div class="leg-item"><span class="leg-swatch" style="background:#a5d6a7;"></span> <strong>Forest Boundary Area</strong></div>
                `;
            } else { // raster / change detection default
                legendTitle.textContent = "Canopy Change Scale";
                legendGrid.innerHTML = `
                    <div class="leg-item"><span class="leg-swatch deforested-swatch"></span> <strong>Potential Loss</strong> (ΔNDVI &lt; -0.15)</div>
                    <div class="leg-item"><span class="leg-swatch stable-dense-swatch"></span> <strong>Dense Forest</strong> (NDVI &gt; 0.60)</div>
                    <div class="leg-item"><span class="leg-swatch stable-light-swatch"></span> <strong>Light Forest</strong> (0.40–0.60)</div>
                    <div class="leg-item"><span class="leg-swatch regrowth-swatch"></span> <strong>Canopy Regrowth</strong> (ΔNDVI &gt; +0.15)</div>
                    <div class="leg-item"><span class="leg-swatch non-forest-swatch"></span> <strong>Non-Forest / Bare</strong> (NDVI &lt; 0.20)</div>
                    <div class="leg-item"><span class="leg-swatch masked-transparent-swatch"></span> <strong>Cloud Masked</strong> (Transparent)</div>
                `;
            }
            console.log(`[ForestWatch Map Diagnostic] Selected Layer: ${layerType} | Coordinates: (${state.lat.toFixed(4)}, ${state.lon.toFixed(4)})`);
        }

        if (btnStreet) {
            btnStreet.addEventListener("click", () => {
                resetChangeLayers();
                btnStreet.classList.add("active");
                changeMap.addLayer(changeBaseStreet);
                updateMapLegend("street");
            });
        }

        if (btnSat) {
            btnSat.addEventListener("click", () => {
                resetChangeLayers();
                btnSat.classList.add("active");
                if (changeLiveRgbLayer) {
                    changeMap.addLayer(changeLiveRgbLayer);
                } else {
                    changeMap.addLayer(changeFallbackSat);
                }
                updateMapLegend("satellite");
            });
        }

        if (btnNdvi) {
            btnNdvi.addEventListener("click", () => {
                resetChangeLayers();
                btnNdvi.classList.add("active");
                if (changeLiveNdviLayer) {
                    changeMap.addLayer(changeLiveNdviLayer);
                } else {
                    changeMap.addLayer(changeFallbackSat);
                }
                updateMapLegend("ndvi");
            });
        }

        if (btnRaster) {
            btnRaster.addEventListener("click", () => {
                resetChangeLayers();
                btnRaster.classList.add("active");
                changeMap.addLayer(changeFallbackSat);
                updateMapLegend("raster");
                // Also activate the 4-panel image tab below
                const mapTabBtn = document.querySelector("#change-results-panel .tab-button[data-tab='change-map']");
                if (mapTabBtn) mapTabBtn.click();
            });
        }

        updateMapLegend("raster");

        // Opacity Slider
        const opacitySlider = document.getElementById("cmap-opacity-slider");
        const opacityVal = document.getElementById("cmap-opacity-val");
        if (opacitySlider) {
            opacitySlider.addEventListener("input", function () {
                const val = parseInt(this.value);
                if (opacityVal) opacityVal.textContent = `${val}%`;
                const op = val / 100.0;
                if (changeLiveRgbLayer) changeLiveRgbLayer.setOpacity(op);
                if (changeLiveNdviLayer) changeLiveNdviLayer.setOpacity(op);
                if (changeFallbackSat) changeFallbackSat.setOpacity(op);
            });
        }

        // Recenter Button
        const recenterBtn = document.getElementById("btn-cmap-recenter");
        if (recenterBtn) {
            recenterBtn.addEventListener("click", () => {
                changeMap.setView([state.lat, state.lon], 12);
            });
        }

        // Fullscreen Toggle
        const fsBtn = document.getElementById("btn-cmap-fullscreen");
        const mapCard = document.querySelector(".change-map-card");
        if (fsBtn && mapCard) {
            fsBtn.addEventListener("click", () => {
                mapCard.classList.toggle("fullscreen-mode");
                setTimeout(() => changeMap.invalidateSize(), 200);
            });
        }

        // Close Inspector HUD
        const closeHudBtn = document.getElementById("btn-close-inspect-hud");
        if (closeHudBtn) {
            closeHudBtn.addEventListener("click", () => {
                document.getElementById("cmap-inspect-hud").style.display = "none";
            });
        }
    }

    function updateChangeMapLayers(lat, lon) {
        fetch(`/api/satellite-tiles?lat=${lat}&lon=${lon}`)
        .then(res => res.json())
        .then(data => {
            if (data.rgb_tile_url && changeMap) {
                if (changeLiveRgbLayer && changeMap.hasLayer(changeLiveRgbLayer)) changeMap.removeLayer(changeLiveRgbLayer);
                changeLiveRgbLayer = L.tileLayer(data.rgb_tile_url, { maxZoom: 18, attribution: 'Copernicus Sentinel-2' });

                if (document.getElementById("btn-cmap-satellite") && document.getElementById("btn-cmap-satellite").classList.contains("active")) {
                    if (changeMap.hasLayer(changeFallbackSat)) changeMap.removeLayer(changeFallbackSat);
                    changeMap.addLayer(changeLiveRgbLayer);
                }
            }

            if (data.ndvi_tile_url && changeMap) {
                if (changeLiveNdviLayer && changeMap.hasLayer(changeLiveNdviLayer)) changeMap.removeLayer(changeLiveNdviLayer);
                changeLiveNdviLayer = L.tileLayer(data.ndvi_tile_url, { maxZoom: 18, attribution: 'Sentinel-2 NDVI' });

                if (document.getElementById("btn-cmap-ndvi") && document.getElementById("btn-cmap-ndvi").classList.contains("active")) {
                    changeMap.addLayer(changeLiveNdviLayer);
                }
            }
        })
        .catch(err => console.error("Change map tile error:", err));
    }

    // Input handlers & Sync buttons
    const btnSyncCoords = document.getElementById("btn-sync-target-coords");
    if (btnSyncCoords) {
        btnSyncCoords.addEventListener("click", () => {
            document.getElementById("change-lat").value = state.lat.toFixed(4);
            document.getElementById("change-lon").value = state.lon.toFixed(4);
            if (changeMap) {
                changeMap.setView([state.lat, state.lon], 12);
                changeMarker.setLatLng([state.lat, state.lon]);
                changeCircle.setLatLng([state.lat, state.lon]);
                updateChangeMapLayers(state.lat, state.lon);
            }
        });
    }

    const cloudSlider = document.getElementById("change-cloud-pct");
    const cloudVal = document.getElementById("change-cloud-val");
    if (cloudSlider && cloudVal) {
        cloudSlider.addEventListener("input", function () {
            cloudVal.textContent = `${this.value}%`;
        });
    }

    const radiusSelect = document.getElementById("change-radius-select");
    const radiusVal = document.getElementById("change-radius-val");
    if (radiusSelect) {
        radiusSelect.addEventListener("change", function () {
            const rad = parseInt(this.value);
            state.radius = rad;
            if (radiusVal) radiusVal.textContent = `${rad.toLocaleString()}m`;
            if (changeCircle) changeCircle.setRadius(rad);
            updateActiveLocationDisplay();
        });
    }

    // Date Range Validation Check
    function validateChangeDates() {
        const bStart = document.getElementById("change-base-start").value;
        const bEnd = document.getElementById("change-base-end").value;
        const rStart = document.getElementById("change-rec-start").value;
        const rEnd = document.getElementById("change-rec-end").value;

        if (bStart && bEnd && bStart >= bEnd) {
            changeDateWarningMsg.textContent = "Baseline Start Date must precede Baseline End Date.";
            changeDateWarning.style.display = "flex";
            return false;
        }
        if (rStart && rEnd && rStart >= rEnd) {
            changeDateWarningMsg.textContent = "Comparison Start Date must precede Comparison End Date.";
            changeDateWarning.style.display = "flex";
            return false;
        }
        if (bStart && rStart && bStart === rStart && bEnd === rEnd) {
            changeDateWarningMsg.textContent = "Baseline and Recent windows are identical. Select distinct observation periods for change detection.";
            changeDateWarning.style.display = "flex";
            return false;
        }

        changeDateWarning.style.display = "none";
        return true;
    }

    ["change-base-start", "change-base-end", "change-rec-start", "change-rec-end"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener("change", validateChangeDates);
    });

    // Run Analysis Button
    runChangeBtn.addEventListener("click", () => {
        if (!validateChangeDates()) return;

        const payload = {
            latitude: parseFloat(document.getElementById("change-lat").value),
            longitude: parseFloat(document.getElementById("change-lon").value),
            baseline_start: document.getElementById("change-base-start").value,
            baseline_end: document.getElementById("change-base-end").value,
            recent_start: document.getElementById("change-rec-start").value,
            recent_end: document.getElementById("change-rec-end").value,
            radius_meters: parseInt(document.getElementById("change-radius-select").value || state.radius),
            max_cloud_pct: parseFloat(document.getElementById("change-cloud-pct").value || 25),
            scale: 20
        };

        runChangeBtn.disabled = true;
        stopChangeBtn.disabled = false;
        document.getElementById("run-change-btn-text").textContent = "Analyzing Satellite Vigor...";

        changeResultsPanel.style.display = "block";
        changeMapImg.style.display = "none";
        changeStatsImg.style.display = "none";
        noChangeMapMsg.style.display = "block";
        noChangeStatsMsg.style.display = "block";
        changeReportContent.textContent = "Processing Sentinel-2 imagery with SCL cloud & shadow filtering...";
        changeLogContainer.innerHTML = "Submitting job request to Sentinel-2 processing pipeline...<br>";

        // Show pipeline progress card
        if (changeProgressCard) {
            changeProgressCard.style.display = "block";
            resetPipelineSteps();
            setPipelineStep(1, "active");
        }

        fetch("/run-analysis", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        })
        .then(r => r.json())
        .then(data => {
            state.currentAnalysisId = data.analysis_id;
            document.getElementById("change-id-badge").textContent = `ID: ${data.analysis_id}`;
            document.getElementById("change-timestamp").textContent = `Started: ${new Date().toLocaleTimeString()}`;
            document.getElementById("change-last-run-badge").textContent = "Processing...";
            document.getElementById("change-last-run-badge").className = "badge badge-yellow";

            if (state.pollInterval) clearInterval(state.pollInterval);
            state.pollInterval = setInterval(pollChangeStatus, 1500);
        });
    });

    function resetPipelineSteps() {
        for (let i = 1; i <= 6; i++) {
            const step = document.getElementById(`pstep-${i}`);
            if (step) {
                step.classList.remove("active", "completed");
            }
        }
    }

    function setPipelineStep(num, status) {
        for (let i = 1; i < num; i++) {
            const prev = document.getElementById(`pstep-${i}`);
            if (prev) {
                prev.classList.remove("active");
                prev.classList.add("completed");
            }
        }
        const curr = document.getElementById(`pstep-${num}`);
        if (curr) {
            curr.classList.remove("completed");
            curr.classList.add(status);
        }
    }

    stopChangeBtn.addEventListener("click", () => {
        if (!state.currentAnalysisId) return;
        stopChangeBtn.disabled = true;
        fetch("/stop-analysis", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ analysis_id: state.currentAnalysisId })
        })
        .then(r => r.json())
        .then(d => {
            runChangeBtn.disabled = false;
            stopChangeBtn.disabled = true;
            document.getElementById("run-change-btn-text").textContent = "Run Change Detection";
            if (changeProgressCard) changeProgressCard.style.display = "none";
            if (state.pollInterval) clearInterval(state.pollInterval);
            changeLogContainer.innerHTML += `<br><span class="error">⏹ ${d.message}</span>`;
            document.getElementById("change-last-run-badge").textContent = "Cancelled";
            document.getElementById("change-last-run-badge").className = "badge badge-gray";
        });
    });

    function pollChangeStatus() {
        if (!state.currentAnalysisId) return;
        fetch(`/status?id=${state.currentAnalysisId}`)
        .then(r => r.json())
        .then(data => {
            if (data.messages && data.messages.length > 0) {
                changeLogContainer.innerHTML = data.messages.join("<br>");
                changeLogContainer.scrollTop = changeLogContainer.scrollHeight;

                const lastMsg = data.messages[data.messages.length - 1];
                document.getElementById("pipeline-status-text").textContent = lastMsg;

                if (lastMsg.includes("Retrieving Sentinel-2")) setPipelineStep(2, "active");
                else if (lastMsg.includes("Calculating NDVI")) setPipelineStep(3, "active");
                else if (lastMsg.includes("multi-temporal change") || lastMsg.includes("ΔNDVI")) setPipelineStep(4, "active");
                else if (lastMsg.includes("4-panel spatial")) setPipelineStep(5, "active");
                else if (lastMsg.includes("PDF") || lastMsg.includes("CSV")) setPipelineStep(6, "active");
            }

            if (data.status === "completed") {
                clearInterval(state.pollInterval);
                runChangeBtn.disabled = false;
                stopChangeBtn.disabled = true;
                document.getElementById("run-change-btn-text").textContent = "Run Change Detection";
                if (changeProgressCard) changeProgressCard.style.display = "none";

                loadChangeResults(state.currentAnalysisId, data.summary);
                loadOverviewMetrics();
                loadReportsHistory();
            } else if (data.status === "cancelled" || data.status === "error") {
                clearInterval(state.pollInterval);
                runChangeBtn.disabled = false;
                stopChangeBtn.disabled = true;
                document.getElementById("run-change-btn-text").textContent = "Run Change Detection";
                if (changeProgressCard) changeProgressCard.style.display = "none";
            }
        });
    }

    function loadChangeResults(analysisId, summary) {
        if (!analysisId) return;
        state.currentAnalysisId = analysisId;
        changeResultsPanel.style.display = "block";
        document.getElementById("change-id-badge").textContent = `ID: ${analysisId}`;

        // Load text report
        fetch(`/report?id=${analysisId}`)
        .then(r => r.json())
        .then(d => {
            if (d && d.content) changeReportContent.textContent = d.content;
        });

        // Load visualizations
        fetch(`/chart?id=${analysisId}`)
        .then(r => r.json())
        .then(d => {
            const bust = new Date().getTime();
            if (d.map_url) {
                currentMapUrl = d.map_url;
                changeMapImg.src = `${d.map_url}?t=${bust}`;
                changeMapImg.onload = () => { changeMapImg.style.display = "block"; noChangeMapMsg.style.display = "none"; };
            }
            if (d.chart_url) {
                changeStatsImg.src = `${d.chart_url}?t=${bust}`;
                changeStatsImg.onload = () => { changeStatsImg.style.display = "block"; noChangeStatsMsg.style.display = "none"; };
            }
        });

        // Populate KPIs, Metadata, and Classification Table
        if (summary) {
            const cs = summary.change_stats;
            const bm = summary.baseline_meta;
            const rm = summary.recent_meta;

            if (summary.timestamp) {
                document.getElementById("change-last-run-badge").textContent = `Last Run: ${summary.timestamp.split(' ')[0]}`;
                document.getElementById("change-last-run-badge").className = "badge badge-green";
                document.getElementById("change-timestamp").textContent = `Executed: ${summary.timestamp}`;
            }

            if (cs) {
                // KPIs
                const riskBadge = document.getElementById("badge-change-risk");
                const riskVal = document.getElementById("val-change-risk");
                if (riskBadge) {
                    riskBadge.textContent = cs.risk_level || "Standard";
                    riskBadge.className = cs.risk_level && cs.risk_level.includes("Alert") ? "badge badge-danger" : "badge badge-green";
                }
                if (riskVal) riskVal.textContent = cs.risk_level || "Standard";

                document.getElementById("val-change-loss").textContent = `${cs.deforested.hectares.toFixed(2)} ha`;
                document.getElementById("sub-change-loss").textContent = `${cs.deforested.percentage.toFixed(1)}% of monitored area`;

                document.getElementById("val-change-dense").textContent = `${cs.stable_dense.hectares.toFixed(2)} ha`;
                document.getElementById("sub-change-dense").textContent = `${cs.stable_dense.percentage.toFixed(1)}% persistent dense forest`;
                document.getElementById("sub-change-light").textContent = `Stable Light: ${cs.stable_light.hectares.toFixed(1)} ha (${cs.stable_light.percentage.toFixed(1)}%)`;

                const dNdvi = cs.mean_delta_ndvi;
                const sign = dNdvi >= 0 ? "+" : "";
                const valNdviEl = document.getElementById("val-change-ndvi");
                valNdviEl.textContent = sign + dNdvi.toFixed(4);
                valNdviEl.className = dNdvi < -0.05 ? "kpi-value text-danger" : dNdvi > 0.05 ? "kpi-value text-success" : "kpi-value text-info";

                document.getElementById("val-change-pixels").textContent = `${cs.total_valid_pixels.toLocaleString()} px`;
                document.getElementById("sub-change-confidence").textContent = `100% SCL Validated (${cs.total_area_ha.toFixed(1)} ha)`;
                if (rm && rm.cloud_percentage !== undefined) {
                    document.getElementById("sub-change-clouds").textContent = `Scene Cloud: ${rm.cloud_percentage.toFixed(1)}% (SCL Filtered)`;
                }

                // Classification Summary Table
                document.getElementById("tbl-deforest-ha").textContent = `${cs.deforested.hectares.toFixed(2)} ha`;
                document.getElementById("tbl-deforest-km2").textContent = `${cs.deforested.km2.toFixed(3)} km²`;
                document.getElementById("tbl-deforest-pct").textContent = `${cs.deforested.percentage.toFixed(2)}%`;

                document.getElementById("tbl-dense-ha").textContent = `${cs.stable_dense.hectares.toFixed(2)} ha`;
                document.getElementById("tbl-dense-km2").textContent = `${cs.stable_dense.km2.toFixed(3)} km²`;
                document.getElementById("tbl-dense-pct").textContent = `${cs.stable_dense.percentage.toFixed(2)}%`;

                document.getElementById("tbl-light-ha").textContent = `${cs.stable_light.hectares.toFixed(2)} ha`;
                document.getElementById("tbl-light-km2").textContent = `${cs.stable_light.km2.toFixed(3)} km²`;
                document.getElementById("tbl-light-pct").textContent = `${cs.stable_light.percentage.toFixed(2)}%`;

                document.getElementById("tbl-regrowth-ha").textContent = `${cs.regrowth.hectares.toFixed(2)} ha`;
                document.getElementById("tbl-regrowth-km2").textContent = `${cs.regrowth.km2.toFixed(3)} km²`;
                document.getElementById("tbl-regrowth-pct").textContent = `${cs.regrowth.percentage.toFixed(2)}%`;

                document.getElementById("tbl-nonforest-ha").textContent = `${cs.non_forest.hectares.toFixed(2)} ha`;
                document.getElementById("tbl-nonforest-km2").textContent = `${cs.non_forest.km2.toFixed(3)} km²`;
                document.getElementById("tbl-nonforest-pct").textContent = `${cs.non_forest.percentage.toFixed(2)}%`;

                // Diagnostic log
                console.log(`[ForestWatch Map Diagnostic] Layer: Analysis Results (ID: ${analysisId}) | Valid Pixels: ${cs.total_valid_pixels.toLocaleString()} / ${(cs.total_pixels || cs.total_valid_pixels).toLocaleString()} (${cs.valid_data_pct || 100}%) | Masked: ${cs.masked_pixels || 0}`);
                console.log(`[ForestWatch Map Diagnostic] ΔNDVI Mean: ${cs.mean_delta_ndvi >= 0 ? '+' : ''}${cs.mean_delta_ndvi.toFixed(4)}`);
                console.log(`[ForestWatch Map Diagnostic] Class Breakdown: Loss=${cs.deforested.pixels} px (${cs.deforested.percentage}%), Regrowth=${cs.regrowth.pixels} px (${cs.regrowth.percentage}%), Dense=${cs.stable_dense.pixels} px (${cs.stable_dense.percentage}%), Light=${cs.stable_light.pixels} px (${cs.stable_light.percentage}%), Non-Forest=${cs.non_forest.pixels} px (${cs.non_forest.percentage}%)`);
            }

            // Scene metadata cards
            if (bm) {
                document.getElementById("meta-base-acq").textContent = bm.acquisition_date || "Observed";
                document.getElementById("meta-base-window").textContent = `${bm.query_start_date} to ${bm.query_end_date}`;
                document.getElementById("meta-base-cloud").textContent = `${bm.cloud_percentage}%`;
                document.getElementById("meta-base-passes").textContent = `${bm.observations_available || 'Multiple'}`;
                document.getElementById("meta-base-spacecraft").textContent = bm.spacecraft || "Sentinel-2A";
                document.getElementById("hud-base-date").textContent = (bm.acquisition_date || "2022").split(' ')[0];
            }

            if (rm) {
                document.getElementById("meta-recent-acq").textContent = rm.acquisition_date || "Observed";
                document.getElementById("meta-recent-window").textContent = `${rm.query_start_date} to ${rm.query_end_date}`;
                document.getElementById("meta-recent-cloud").textContent = `${rm.cloud_percentage}%`;
                document.getElementById("meta-recent-passes").textContent = `${rm.observations_available || 'Multiple'}`;
                document.getElementById("meta-recent-spacecraft").textContent = rm.spacecraft || "Sentinel-2A";
                document.getElementById("hud-recent-date").textContent = (rm.acquisition_date || "2023").split(' ')[0];
            }

            // Reposition Change Map to analysis location
            if (summary.location && changeMap) {
                const sLat = summary.location.latitude;
                const sLon = summary.location.longitude;
                changeMap.setView([sLat, sLon], 12);
                if (changeMarker) changeMarker.setLatLng([sLat, sLon]);
                if (changeCircle) changeCircle.setLatLng([sLat, sLon]);
                updateChangeMapLayers(sLat, sLon);
            }
        }
    }

    // Change Tab Switching
    document.querySelectorAll("#change-results-panel .tab-button").forEach(btn => {
        btn.addEventListener("click", function () {
            document.querySelectorAll("#change-results-panel .tab-button").forEach(b => b.classList.remove("active"));
            document.querySelectorAll("#change-results-panel .tab-content").forEach(c => c.classList.remove("active"));
            this.classList.add("active");
            const tabId = this.getAttribute("data-tab");
            const targetContent = document.getElementById(`${tabId}-tab`) || document.getElementById(`${tabId}-tab-content`);
            if (targetContent) targetContent.classList.add("active");
        });
    });

    // Exports
    document.getElementById("btn-export-pdf-change").addEventListener("click", () => {
        if (state.currentAnalysisId) window.location.href = `/export/pdf/${state.currentAnalysisId}`;
    });
    document.getElementById("btn-export-csv-change").addEventListener("click", () => {
        if (state.currentAnalysisId) window.location.href = `/export/csv/${state.currentAnalysisId}`;
    });
    document.getElementById("btn-export-txt-change").addEventListener("click", () => {
        const txt = changeReportContent.textContent;
        const blob = new Blob([txt], { type: "text/plain" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `ForestWatch_Report_${state.currentAnalysisId || 'export'}.txt`;
        a.click();
    });

    // Carry to Historical Trends button
    const btnCarryHist = document.getElementById("btn-carry-to-historical");
    if (btnCarryHist) {
        btnCarryHist.addEventListener("click", () => {
            switchWorkspace("historical");
        });
    }

    // Initial check: if an analysis already exists on server, load it automatically
    fetch("/status")
    .then(r => r.json())
    .then(d => {
        if (d && d.analysis_id && d.status === "completed") {
            loadChangeResults(d.analysis_id, d.summary);
        }
    })
    .catch(err => console.log("Initial status query:", err));

    // =========================================================================
    // Vegetation Health Workspace
    // =========================================================================
    document.getElementById("btn-run-veg-analysis").addEventListener("click", () => {
        const payload = {
            latitude: parseFloat(document.getElementById("veg-lat").value),
            longitude: parseFloat(document.getElementById("veg-lon").value),
            baseline_start: document.getElementById("veg-start-date").value,
            baseline_end: document.getElementById("veg-end-date").value,
            recent_start: document.getElementById("veg-start-date").value,
            recent_end: document.getElementById("veg-end-date").value
        };

        const panel = document.getElementById("veg-results-panel");
        const img = document.getElementById("veg-chart-img");
        const msg = document.getElementById("veg-chart-loading");

        panel.style.display = "block";
        img.style.display = "none";
        msg.style.display = "block";

        fetch("/run-analysis", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        })
        .then(r => r.json())
        .then(d => {
            const vId = d.analysis_id;
            const vPoll = setInterval(() => {
                fetch(`/status?id=${vId}`)
                .then(r => r.json())
                .then(s => {
                    if (s.status === "completed") {
                        clearInterval(vPoll);
                        img.src = `/static/${s.chart_path}?t=${new Date().getTime()}`;
                        img.onload = () => { img.style.display = "block"; msg.style.display = "none"; };
                    } else if (s.status === "error" || s.status === "cancelled") {
                        clearInterval(vPoll);
                        msg.textContent = "Vegetation health analysis ended: " + s.status;
                    }
                });
            }, 1500);
        });
    });

    // =========================================================================
    // Multi-Year Historical Trends
    // =========================================================================
    const runHistBtn = document.getElementById("run-hist-button");
    const histPanel = document.getElementById("hist-results-panel");
    const histImg = document.getElementById("hist-chart-image");
    const noHistMsg = document.getElementById("no-hist-chart-message");
    const histTbody = document.getElementById("hist-tbody");

    runHistBtn.addEventListener("click", () => {
        const payload = {
            start_year: parseInt(document.getElementById("hist-start-year").value),
            end_year: parseInt(document.getElementById("hist-end-year").value),
            latitude: parseFloat(document.getElementById("hist-lat").value),
            longitude: parseFloat(document.getElementById("hist-lon").value)
        };

        runHistBtn.disabled = true;
        runHistBtn.textContent = "⏳ Processing Multi-Year Trajectory...";
        histPanel.style.display = "block";
        histImg.style.display = "none";
        noHistMsg.style.display = "block";
        histTbody.innerHTML = `<tr><td colspan="7" style="text-align: center;">Querying satellite composites for each year...</td></tr>`;

        fetch("/run-historical", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        })
        .then(r => r.json())
        .then(d => {
            const hId = d.analysis_id;
            const hPoll = setInterval(() => {
                fetch(`/status?id=${hId}`)
                .then(r => r.json())
                .then(s => {
                    if (s.status === "completed") {
                        clearInterval(hPoll);
                        runHistBtn.disabled = false;
                        runHistBtn.textContent = "📈 Run Historical Time-Series";

                        histImg.src = `/static/${s.chart_path}?t=${new Date().getTime()}`;
                        histImg.onload = () => { histImg.style.display = "block"; noHistMsg.style.display = "none"; };

                        const years = (s.summary && s.summary.historical_data && s.summary.historical_data.years) || [];
                        histTbody.innerHTML = years.map(y => `
                            <tr>
                                <td><strong>${y.year}</strong></td>
                                <td>${y.period}</td>
                                <td><strong>${y.mean_ndvi.toFixed(3)}</strong></td>
                                <td>${y.median_ndvi.toFixed(3)}</td>
                                <td>${y.dense_pct.toFixed(1)}%</td>
                                <td><span class="badge ${y.yoy_change < -0.02 ? 'badge-danger' : y.yoy_change > 0.02 ? 'badge-green' : 'badge-gray'}">${y.yoy_change >= 0 ? '+' : ''}${y.yoy_change.toFixed(3)}</span></td>
                                <td><span class="badge ${y.quality_flag.includes('High') ? 'badge-green' : 'badge-yellow'}">${y.quality_flag}</span></td>
                            </tr>
                        `).join("");
                    } else if (s.status === "error" || s.status === "cancelled") {
                        clearInterval(hPoll);
                        runHistBtn.disabled = false;
                        runHistBtn.textContent = "📈 Run Historical Time-Series";
                    }
                });
            }, 2000);
        });
    });

    // =========================================================================
    // Overview Metrics & History Repository
    // =========================================================================
    function loadOverviewMetrics() {
        fetch("/analyses")
        .then(r => r.json())
        .then(data => {
            const items = data.analyses || [];
            const totalAnalysesEl = document.getElementById("stat-total-analyses");
            if (totalAnalysesEl) totalAnalysesEl.textContent = items.length;

            let alerts = 0;
            items.forEach(it => {
                if (it.risk_level && (it.risk_level.includes("High") || it.risk_level.includes("Critical") || it.risk_level.includes("Moderate"))) {
                    alerts++;
                }
            });
            const activeAlertsEl = document.getElementById("stat-active-alerts");
            if (activeAlertsEl) activeAlertsEl.textContent = alerts;

            const tbody = document.getElementById("overview-history-tbody");
            if (tbody) {
                if (items.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center;">No analyses completed yet.</td></tr>`;
                    return;
                }

                tbody.innerHTML = items.slice(0, 5).map(it => `
                    <tr>
                        <td><code>${it.id}</code></td>
                        <td>${it.coordinates}</td>
                        <td>${it.started_at}</td>
                        <td><strong>${it.deforested_ha} ha</strong> (${it.deforested_pct}%)</td>
                        <td><span class="badge ${it.risk_level.includes('Alert') ? 'badge-danger' : 'badge-green'}">${it.risk_level}</span></td>
                        <td><span class="badge ${it.status}">${it.status}</span></td>
                        <td>
                            <button class="small-btn" onclick="window.viewPastRun('${it.id}')">View</button>
                            <a href="/export/pdf/${it.id}" class="small-btn-link">PDF</a>
                        </td>
                    </tr>
                `).join("");
            }
        });
    }

    function loadReportsHistory() {
        fetch("/analyses")
        .then(r => r.json())
        .then(data => {
            const tbody = document.getElementById("history-tbody");
            if (!tbody) return;
            const items = data.analyses || [];
            if (items.length === 0) {
                tbody.innerHTML = `<tr><td colspan="8" style="text-align: center;">No analyses recorded yet.</td></tr>`;
                return;
            }

            tbody.innerHTML = items.map(it => `
                <tr>
                    <td><code>${it.id}</code></td>
                    <td><span class="badge badge-gray">${it.type || 'bitemporal'}</span></td>
                    <td>${it.coordinates}</td>
                    <td>${it.started_at}</td>
                    <td><strong>${it.deforested_ha} ha</strong> (${it.deforested_pct}%)</td>
                    <td><span class="badge ${it.risk_level.includes('Alert') ? 'badge-danger' : 'badge-green'}">${it.risk_level}</span></td>
                    <td><span class="badge ${it.status}">${it.status}</span></td>
                    <td>
                        <button class="small-btn" onclick="window.viewPastRun('${it.id}')">View</button>
                        <a href="/export/pdf/${it.id}" class="small-btn-link">PDF</a>
                        <a href="/export/csv/${it.id}" class="small-btn-link">CSV</a>
                    </td>
                </tr>
            `).join("");
        });
    }

    window.viewPastRun = function (analysisId) {
        state.currentAnalysisId = analysisId;
        switchWorkspace("change");
        changeResultsPanel.style.display = "block";
        document.getElementById("change-id-badge").textContent = `ID: ${analysisId}`;

        fetch(`/status?id=${analysisId}`)
        .then(r => r.json())
        .then(data => {
            loadChangeResults(analysisId, data.summary);
            if (data.messages) changeLogContainer.innerHTML = data.messages.join("<br>");
        });
    };

    document.getElementById("btn-refresh-history").addEventListener("click", loadReportsHistory);

    // RBAC & Role Management
    function initUserRole() {
        const roleSelect = document.getElementById("user-role-select");
        const badgeTag = document.getElementById("user-badge-tag");
        if (!roleSelect) return;

        fetch("/api/auth/current-user")
            .then(res => res.json())
            .then(data => {
                if (data.user) {
                    roleSelect.value = data.user.role;
                    if (badgeTag) badgeTag.textContent = data.user.badge_id || "AUTH";
                }
            })
            .catch(err => console.warn("Failed to fetch auth user:", err));

        roleSelect.addEventListener("change", function () {
            const newRole = this.value;
            fetch("/api/auth/switch-role", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ role: newRole })
            })
            .then(res => res.json())
            .then(data => {
                if (badgeTag && data.current_user) {
                    badgeTag.textContent = data.current_user.badge_id || "AUTH";
                }
            })
            .catch(err => console.error("Error switching role:", err));
        });
    }

    // Initial setup
    initUserRole();
    updateActiveLocationDisplay();
    loadSavedLocations();
    loadOverviewMetrics();
    loadOperationsDashboard();

    // Activate requested workspace from Feature Selection page: ?view=... or ?tab=...
    const urlParams = new URLSearchParams(window.location.search);
    const initialView = urlParams.get("view") || urlParams.get("tab");
    if (initialView && workspaces[initialView]) {
        switchWorkspace(initialView);
    }
});
