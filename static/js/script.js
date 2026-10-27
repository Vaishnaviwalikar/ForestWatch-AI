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

    document.getElementById("brand-home-btn").addEventListener("click", () => switchWorkspace("overview"));
    document.getElementById("btn-quick-change-loc").addEventListener("click", () => switchWorkspace("explorer"));
    document.getElementById("btn-hero-explore").addEventListener("click", () => switchWorkspace("explorer"));
    document.getElementById("btn-hero-change").addEventListener("click", () => switchWorkspace("change"));
    document.getElementById("btn-hero-historical").addEventListener("click", () => switchWorkspace("historical"));
    document.getElementById("btn-view-all-reports").addEventListener("click", () => switchWorkspace("reports"));

    // Quick action tiles in Overview
    document.getElementById("qa-explorer").addEventListener("click", () => switchWorkspace("explorer"));
    document.getElementById("qa-vegetation").addEventListener("click", () => switchWorkspace("vegetation"));
    document.getElementById("qa-change").addEventListener("click", () => switchWorkspace("change"));
    document.getElementById("qa-historical").addEventListener("click", () => switchWorkspace("historical"));

    function updateActiveLocationDisplay() {
        document.getElementById("active-location-name").textContent = state.name;
        document.getElementById("active-location-coords").textContent = `${state.lat.toFixed(4)}° N, ${state.lon.toFixed(4)}° E`;
        const ha = (Math.PI * state.radius * state.radius / 10000).toFixed(0);
        document.getElementById("active-location-area").textContent = `Radius: ${state.radius.toLocaleString()}m (~${ha} ha)`;

        // Sync inputs across workspaces
        document.getElementById("veg-lat").value = state.lat.toFixed(4);
        document.getElementById("veg-lon").value = state.lon.toFixed(4);
        document.getElementById("change-lat").value = state.lat.toFixed(4);
        document.getElementById("change-lon").value = state.lon.toFixed(4);
        document.getElementById("hist-lat").value = state.lat.toFixed(4);
        document.getElementById("hist-lon").value = state.lon.toFixed(4);
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
    let overviewMarkersLayer = null;

    function initOverviewMap(locations) {
        const container = document.getElementById("overview-map");
        if (!container) return;

        if (!overviewMap) {
            overviewMap = L.map('overview-map', {
                center: [20.0, 78.0],
                zoom: 4,
                layers: [L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png')]
            });
            overviewMarkersLayer = L.layerGroup().addTo(overviewMap);
        } else if (overviewMarkersLayer) {
            overviewMarkersLayer.clearLayers();
        }

        // Add markers for all saved locations
        locations.forEach(loc => {
            const m = L.marker([loc.latitude, loc.longitude]);
            m.bindPopup(`
                <strong>${loc.name}</strong><br>
                ${loc.region}<br>
                <button class="btn-sm-outline" style="margin-top:6px;" onclick="window.selectAndGo(${loc.latitude}, ${loc.longitude}, '${loc.name}')">Launch Analysis</button>
            `);
            overviewMarkersLayer.addLayer(m);
        });

        setTimeout(() => {
            if (overviewMap) overviewMap.invalidateSize();
        }, 300);
    }

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
            document.getElementById("stat-total-locations").textContent = locs.length;

            const grid = document.getElementById("saved-locations-list");
            if (grid) {
                grid.innerHTML = locs.map(loc => `
                    <div class="saved-loc-card">
                        <div class="loc-card-header">
                            <strong class="loc-card-title">${loc.name}</strong>
                            <span class="loc-card-badge">${loc.region}</span>
                        </div>
                        <div class="loc-card-coords">${loc.latitude}° N, ${loc.longitude}° E</div>
                        <div class="loc-card-desc">${loc.description || loc.notes || ''}</div>
                        <button class="btn-load-loc" onclick="window.selectAndGo(${loc.latitude}, ${loc.longitude}, '${loc.name}')">Select Area</button>
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

        if (btnStreet) {
            btnStreet.addEventListener("click", () => {
                resetChangeLayers();
                btnStreet.classList.add("active");
                changeMap.addLayer(changeBaseStreet);
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
            });
        }

        if (btnRaster) {
            btnRaster.addEventListener("click", () => {
                resetChangeLayers();
                btnRaster.classList.add("active");
                changeMap.addLayer(changeFallbackSat);
                // Also activate the 4-panel image tab below
                const mapTabBtn = document.querySelector("#change-results-panel .tab-button[data-tab='change-map']");
                if (mapTabBtn) mapTabBtn.click();
            });
        }

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
            document.getElementById("stat-total-analyses").textContent = items.length;

            let alerts = 0;
            items.forEach(it => {
                if (it.risk_level && (it.risk_level.includes("High") || it.risk_level.includes("Critical") || it.risk_level.includes("Moderate"))) {
                    alerts++;
                }
            });
            document.getElementById("stat-active-alerts").textContent = alerts;

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

    // Initial setup
    updateActiveLocationDisplay();
    loadSavedLocations();
    loadOverviewMetrics();

    // Activate requested workspace from Feature Selection page: ?view=... or ?tab=...
    const urlParams = new URLSearchParams(window.location.search);
    const initialView = urlParams.get("view") || urlParams.get("tab");
    if (initialView && workspaces[initialView]) {
        switchWorkspace(initialView);
    }
});
