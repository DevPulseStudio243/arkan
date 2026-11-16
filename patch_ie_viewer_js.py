import re

with open('arkan-ui.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Define the complete JavaScript module for E&I Interactive Plan Viewer
ie_viewer_js = '''
            // ═══════════════════════════════════════════════════════════════
            // ── VISUALISEUR INTERACTIF DU PLAN TECHNIQUE E&I (DWG/DXF/PDF) ──
            // ═══════════════════════════════════════════════════════════════
            window._ieCurrentPlanFile = null;
            window._ieCurrentPlanBlobUrl = null;
            window._ieCurrentPdfDoc = null;
            window._ieCurrentPdfPage = 1;
            window._ieTotalPdfPages = 1;
            window._ieServerPreviewPages = [];
            window._ieServerVisualUrl = null;
            window._iePlanZoom = 1.0;
            window._iePlanPan = { x: 0, y: 0 };
            window._iePlanRotation = 0;
            window._ieIsPanning = false;
            window._iePanStart = { x: 0, y: 0 };

            window.applyIePlanTransform = function() {
                var stage = document.getElementById('ie-plan-stage');
                if (!stage) return;
                stage.style.transform = 'translate(' + window._iePlanPan.x + 'px, ' + window._iePlanPan.y + 'px) scale(' + window._iePlanZoom + ') rotate(' + window._iePlanRotation + 'deg)';
                var zoomInd = document.getElementById('ie-zoom-indicator');
                if (zoomInd) zoomInd.textContent = Math.round(window._iePlanZoom * 100) + '%';
            };

            window.initIePlanViewer = function() {
                var viewport = document.getElementById('ie-plan-viewport');
                if (!viewport || viewport._initialized) return;
                viewport._initialized = true;

                viewport.addEventListener('mousedown', function(e) {
                    if (e.target.tagName === 'BUTTON' || e.target.closest('button')) return;
                    e.preventDefault();
                    window._ieIsPanning = true;
                    window._iePanStart = { x: e.clientX - window._iePlanPan.x, y: e.clientY - window._iePlanPan.y };
                    viewport.style.cursor = 'grabbing';
                });

                window.addEventListener('mousemove', function(e) {
                    if (!window._ieIsPanning) return;
                    window._iePlanPan.x = e.clientX - window._iePanStart.x;
                    window._iePlanPan.y = e.clientY - window._iePanStart.y;
                    window.applyIePlanTransform();
                });

                window.addEventListener('mouseup', function() {
                    if (window._ieIsPanning) {
                        window._ieIsPanning = false;
                        if (viewport) viewport.style.cursor = 'grab';
                    }
                });

                viewport.addEventListener('wheel', function(e) {
                    e.preventDefault();
                    var delta = e.deltaY < 0 ? 0.15 : -0.15;
                    window.iePlanViewerZoom(delta);
                }, { passive: false });

                viewport.addEventListener('dblclick', function(e) {
                    if (e.target.tagName === 'BUTTON' || e.target.closest('button')) return;
                    window.iePlanViewerFitWidth();
                });
            };

            window.iePlanViewerZoom = function(delta) {
                window._iePlanZoom = Math.max(0.10, Math.min(6.0, Number((window._iePlanZoom + delta).toFixed(2))));
                window.applyIePlanTransform();
            };

            window.iePlanViewerResetZoom = function() {
                window._iePlanZoom = 1.0;
                window._iePlanPan = { x: 0, y: 0 };
                window.applyIePlanTransform();
            };

            window.iePlanViewerFitWidth = function() {
                var viewport = document.getElementById('ie-plan-viewport');
                var canvas = document.getElementById('ie-plan-canvas');
                var img = document.getElementById('ie-plan-img');
                var isCanvas = (canvas && canvas.style.display !== 'none');
                var activeEl = isCanvas ? canvas : img;
                if (!viewport || !activeEl) return;

                var vpWidth = viewport.clientWidth - 40;
                var vpHeight = viewport.clientHeight - 40;
                var elWidth = 800, elHeight = 600;

                if (isCanvas) {
                    elWidth = parseFloat(canvas.style.width) || canvas.clientWidth || canvas.width || 800;
                    elHeight = parseFloat(canvas.style.height) || canvas.clientHeight || canvas.height || 600;
                } else if (img) {
                    elWidth = img.naturalWidth || img.clientWidth || 800;
                    elHeight = img.naturalHeight || img.clientHeight || 600;
                }

                if (elWidth > 0 && elHeight > 0 && vpWidth > 0 && vpHeight > 0) {
                    var scaleX = vpWidth / elWidth;
                    var scaleY = vpHeight / elHeight;
                    var bestScale = Math.min(scaleX, scaleY);
                    window._iePlanZoom = Math.max(0.15, Math.min(4.0, Number(bestScale.toFixed(2))));
                    window._iePlanPan = { x: 0, y: 0 };
                    window.applyIePlanTransform();
                }
            };

            window.iePlanViewerRotate = function() {
                window._iePlanRotation = (window._iePlanRotation + 90) % 360;
                window.applyIePlanTransform();
            };

            window.renderIePdfPage = async function(pageNum) {
                if (!window._ieCurrentPdfDoc) return;
                var canvas = document.getElementById('ie-plan-canvas');
                var loader = document.getElementById('ie-plan-loader');
                var pageNav = document.getElementById('ie-page-nav');
                var pageIndicator = document.getElementById('ie-page-indicator');
                var statusEl = document.getElementById('ie-viewer-status-text');
                var dimsEl = document.getElementById('ie-viewer-dims-text');

                try {
                    var page = await window._ieCurrentPdfDoc.getPage(pageNum);
                    var scale = 2.0;
                    var viewport = page.getViewport({ scale: scale });

                    canvas.width = viewport.width;
                    canvas.height = viewport.height;
                    canvas.style.width = (viewport.width / 2.0) + 'px';
                    canvas.style.height = (viewport.height / 2.0) + 'px';

                    var ctx = canvas.getContext('2d');
                    await page.render({ canvasContext: ctx, viewport: viewport }).promise;

                    canvas.style.display = 'block';
                    var img = document.getElementById('ie-plan-img');
                    if (img) img.style.display = 'none';

                    if (pageIndicator) pageIndicator.textContent = pageNum + ' / ' + window._ieTotalPdfPages;
                    if (pageNav) pageNav.style.display = window._ieTotalPdfPages > 1 ? 'inline-flex' : 'none';
                    if (statusEl) statusEl.textContent = 'Page ' + pageNum + '/' + window._ieTotalPdfPages + ' rendue en haute définition';
                    if (dimsEl) dimsEl.textContent = Math.round(viewport.width / 2) + ' × ' + Math.round(viewport.height / 2) + ' px';
                    if (loader) loader.style.display = 'none';
                } catch(err) {
                    console.error('[IE_VIEWER] Erreur rendu page PDF:', err);
                    if (loader) loader.style.display = 'none';
                }
            };

            window.iePlanViewerPrevPage = function() {
                if (window._ieCurrentPdfDoc && window._ieCurrentPdfPage > 1) {
                    window._ieCurrentPdfPage--;
                    window.renderIePdfPage(window._ieCurrentPdfPage);
                } else if (Array.isArray(window._ieServerPreviewPages) && window._ieServerPreviewPages.length > 1 && window._ieCurrentPdfPage > 1) {
                    window._ieCurrentPdfPage--;
                    window.showIeServerPage(window._ieCurrentPdfPage);
                }
            };

            window.iePlanViewerNextPage = function() {
                if (window._ieCurrentPdfDoc && window._ieCurrentPdfPage < window._ieTotalPdfPages) {
                    window._ieCurrentPdfPage++;
                    window.renderIePdfPage(window._ieCurrentPdfPage);
                } else if (Array.isArray(window._ieServerPreviewPages) && window._ieServerPreviewPages.length > 1 && window._ieCurrentPdfPage < window._ieServerPreviewPages.length) {
                    window._ieCurrentPdfPage++;
                    window.showIeServerPage(window._ieCurrentPdfPage);
                }
            };

            window.showIeServerPage = function(pageNum) {
                var pages = window._ieServerPreviewPages;
                if (!pages || pageNum < 1 || pageNum > pages.length) return;
                var img = document.getElementById('ie-plan-img');
                var canvas = document.getElementById('ie-plan-canvas');
                var pageIndicator = document.getElementById('ie-page-indicator');
                var pageNav = document.getElementById('ie-page-nav');
                var statusEl = document.getElementById('ie-viewer-status-text');

                if (img) {
                    img.src = pages[pageNum - 1];
                    img.style.display = 'block';
                }
                if (canvas) canvas.style.display = 'none';
                if (pageIndicator) pageIndicator.textContent = pageNum + ' / ' + pages.length;
                if (pageNav) pageNav.style.display = pages.length > 1 ? 'inline-flex' : 'none';
                if (statusEl) statusEl.textContent = 'Page ' + pageNum + '/' + pages.length + ' affichée (rendu vectoriel)';
            };

            window.loadIePlanInViewer = async function(fileOrData) {
                if (!fileOrData) return;
                if (typeof window.initIePlanViewer === 'function') window.initIePlanViewer();
                window.iePlanViewerResetZoom();

                var filenameEl = document.getElementById('ie-viewer-filename');
                var filetypeEl = document.getElementById('ie-viewer-filetype');
                var placeholder = document.getElementById('ie-plan-placeholder');
                var loader = document.getElementById('ie-plan-loader');
                var loaderText = document.getElementById('ie-plan-loader-text');
                var canvas = document.getElementById('ie-plan-canvas');
                var img = document.getElementById('ie-plan-img');
                var pageNav = document.getElementById('ie-page-nav');
                var statusEl = document.getElementById('ie-viewer-status-text');
                var dimsEl = document.getElementById('ie-viewer-dims-text');

                if (pageNav) pageNav.style.display = 'none';
                if (placeholder) placeholder.style.display = 'none';

                // Cas 1 : Données reçues du serveur (résultat backend)
                if (fileOrData.visual_url || fileOrData.preview_image || Array.isArray(fileOrData.plan_preview_pages)) {
                    var data = fileOrData;
                    var fname = data.filename || data.metadata?.filename || 'Plan I&E';
                    if (filenameEl) filenameEl.textContent = fname;
                    var ext = (fname.split('.').pop() || '').toLowerCase();
                    if (filetypeEl) filetypeEl.textContent = ext.toUpperCase() + ' • HD';

                    window._ieServerVisualUrl = data.visual_url || null;
                    window._ieServerPreviewPages = Array.isArray(data.plan_preview_pages) && data.plan_preview_pages.length > 0 
                        ? data.plan_preview_pages 
                        : (data.preview_image ? [data.preview_image] : []);
                    window._ieCurrentPdfPage = 1;

                    if (window._ieServerPreviewPages.length > 0 || data.visual_url) {
                        if (img) {
                            img.src = data.visual_url ? data.visual_url : window._ieServerPreviewPages[0];
                            img.style.display = 'block';
                            img.onload = function() {
                                if (dimsEl) dimsEl.textContent = img.naturalWidth + ' × ' + img.naturalHeight + ' px';
                                if (typeof window.iePlanViewerFitWidth === 'function') {
                                    window.iePlanViewerFitWidth();
                                }
                            };
                        }
                        if (canvas) canvas.style.display = 'none';
                        if (loader) loader.style.display = 'none';

                        if (window._ieServerPreviewPages.length > 1) {
                            if (pageNav) pageNav.style.display = 'inline-flex';
                            var pageIndicator = document.getElementById('ie-page-indicator');
                            if (pageIndicator) pageIndicator.textContent = '1 / ' + window._ieServerPreviewPages.length;
                        }
                        if (statusEl) statusEl.textContent = 'Plan ' + fname + ' rendu avec succès (' + window._ieServerPreviewPages.length + ' page(s))';
                        return;
                    }
                }

                // Cas 2 : Objet File direct sélectionné côté client
                var file = (fileOrData instanceof File || (fileOrData && fileOrData.name)) ? fileOrData : null;
                if (!file) return;

                window._ieCurrentPlanFile = file;
                var f_name = file.name || (file.path ? file.path.split(/[\\\\/]/).pop() : 'plan_ie');
                if (filenameEl) filenameEl.textContent = f_name;
                var f_ext = (f_name.split('.').pop() || '').toLowerCase();
                var sizeKb = file.size ? (file.size / 1024).toFixed(1) : 'Local';
                if (filetypeEl) filetypeEl.textContent = f_ext.toUpperCase() + ' • ' + sizeKb + ' KB';

                if (loader) loader.style.display = 'flex';
                if (loaderText) loaderText.textContent = 'Traitement et affichage du plan ' + f_name + '...';

                if (f_ext === 'pdf' && file instanceof File) {
                    try {
                        var arrayBuffer = await file.arrayBuffer();
                        if (typeof pdfjsLib !== 'undefined') {
                            var loadingTask = pdfjsLib.getDocument({ data: new Uint8Array(arrayBuffer) });
                            var pdf = await loadingTask.promise;
                            window._ieCurrentPdfDoc = pdf;
                            window._ieTotalPdfPages = pdf.numPages;
                            window._ieCurrentPdfPage = 1;
                            await window.renderIePdfPage(1);
                            window.iePlanViewerFitWidth();
                        } else {
                            throw new Error('PDF.js non initialisé');
                        }
                    } catch(e) {
                        console.warn('[IE_VIEWER] Rendu client PDF.js impossible, repli sur le serveur:', e);
                        if (loaderText) loaderText.textContent = 'Conversion du plan via le serveur ARKAN...';
                    }
                } else if (['png', 'jpg', 'jpeg', 'webp', 'svg'].includes(f_ext) && file instanceof File) {
                    var reader = new FileReader();
                    reader.onload = function(e) {
                        if (img) {
                            img.src = e.target.result;
                            img.style.display = 'block';
                            img.onload = function() {
                                if (dimsEl) dimsEl.textContent = img.naturalWidth + ' × ' + img.naturalHeight + ' px';
                                window.iePlanViewerFitWidth();
                            };
                        }
                        if (canvas) canvas.style.display = 'none';
                        if (loader) loader.style.display = 'none';
                    };
                    reader.readAsDataURL(file);
                } else if (['dwg', 'dxf'].includes(f_ext)) {
                    if (loaderText) loaderText.textContent = 'Génération du rendu vectoriel CAO pour ' + f_name + '...';
                    if (statusEl) statusEl.textContent = 'Extraction & rendu vectoriel CAO en cours...';
                }
            };

            window.toggleIePlanFullscreen = function() {
                var viewer = document.getElementById('ie-plan-viewer');
                if (!viewer) return;
                if (!document.fullscreenElement) {
                    viewer.requestFullscreen().catch(function(err) { console.warn('Fullscreen:', err); });
                } else {
                    document.exitFullscreen().catch(function(err) { console.warn('Exit Fullscreen:', err); });
                }
            };

            window.openIePlanNewTab = function() {
                if (window._ieServerVisualUrl) {
                    window.open(window._ieServerVisualUrl, '_blank');
                } else if (window._ieCurrentPlanFile instanceof File) {
                    var url = URL.createObjectURL(window._ieCurrentPlanFile);
                    window.open(url, '_blank');
                } else {
                    showToast('Aucun lien direct disponible pour ce plan.', 'info');
                }
            };

            window.downloadCurrentIePlan = function() {
                if (window._ieServerVisualUrl) {
                    var a = document.createElement('a');
                    a.href = window._ieServerVisualUrl;
                    a.download = window._ieServerVisualUrl.split('/').pop();
                    a.click();
                } else if (window._ieCurrentPlanFile && window._ieCurrentPlanFile.path) {
                    showToast('Fichier local : ' + window._ieCurrentPlanFile.path, 'info');
                } else {
                    showToast('Téléchargement non disponible.', 'info');
                }
            };
'''

# Replace initMtoIeView with init containing initIePlanViewer
target_init = '''            // Initialisation & chargement
            window.initMtoIeView = function() {
                console.log("[MTO_IE] Vue MTO I&E initialisée.");
            };'''

replacement_init = ie_viewer_js + '\n' + '''            // Initialisation & chargement
            window.initMtoIeView = function() {
                console.log("[MTO_IE] Vue MTO I&E initialisée.");
                if (typeof window.initIePlanViewer === 'function') {
                    window.initIePlanViewer();
                }
            };'''

assert target_init in content, "target_init not found in content"
content = content.replace(target_init, replacement_init)

# In processIeFile: add window.loadIePlanInViewer(file);
target_process = '''                if (uploadArea) uploadArea.classList.add('hidden');
                if (loadingSpinner) loadingSpinner.classList.remove('hidden');
                if (resultsSection) resultsSection.classList.add('hidden');'''

replacement_process = '''                if (uploadArea) uploadArea.classList.add('hidden');
                if (loadingSpinner) loadingSpinner.classList.remove('hidden');
                if (resultsSection) resultsSection.classList.add('hidden');

                if (typeof window.loadIePlanInViewer === 'function') {
                    try { window.loadIePlanInViewer(file); } catch(eView) { console.warn("[IE_VIEWER] Pre-load error:", eView); }
                }'''

assert target_process in content, "target_process not found in content"
content = content.replace(target_process, replacement_process)

# In renderIeMtoResults: add window.loadIePlanInViewer(data);
target_render = '''                // Rendu des anomalies & tableau
                window.renderIeMtoAnomalies(window.currentIeMtoAnomalies);
                window.renderIeMtoTable(window.currentIeMtoData);'''

replacement_render = '''                // Rendu dans le visualiseur interactif I&E
                if (typeof window.loadIePlanInViewer === 'function') {
                    window.loadIePlanInViewer(data);
                }

                // Rendu des anomalies & tableau
                window.renderIeMtoAnomalies(window.currentIeMtoAnomalies);
                window.renderIeMtoTable(window.currentIeMtoData);'''

assert target_render in content, "target_render not found in content"
content = content.replace(target_render, replacement_render)

with open('arkan-ui.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("JavaScript part of #ie-plan-viewer inserted successfully!")
