import re

with open('arkan-ui.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Prepare HTML block for #ie-plan-viewer
ie_viewer_html = '''
                <!-- Visualiseur Interactif Dédié Électricité & Instrumentation (E&I) -->
                <div id="ie-plan-viewer" style="display:flex; flex-direction:column; background:var(--bg-sidebar); border:1px solid var(--border-color); border-radius:var(--radius-lg); overflow:hidden; min-height:620px; box-shadow:0 8px 32px rgba(0,0,0,0.35);">
                    <!-- Toolbar du visualiseur I&E -->
                    <div style="display:flex; align-items:center; justify-content:space-between; padding:12px 18px; border-bottom:1px solid var(--border-color); background:rgba(15,23,42,0.95); gap:12px; flex-wrap:wrap;">
                        <div style="display:flex; align-items:center; gap:12px;">
                            <div style="width:36px; height:36px; border-radius:8px; background:linear-gradient(135deg, rgba(59,130,246,0.2), rgba(16,185,129,0.15)); border:1px solid rgba(59,130,246,0.3); display:flex; align-items:center; justify-content:center; color:var(--accent-primary); font-size:20px;">
                                <i class="ph ph-lightning"></i>
                            </div>
                            <div>
                                <div style="display:flex; align-items:center; gap:8px;">
                                    <span style="font-weight:700; font-size:14px; color:var(--text-primary); letter-spacing:0.5px;">Visualisation Haute Définition du Plan I&E</span>
                                    <span id="ie-viewer-filetype" style="font-size:10px; color:var(--accent-primary); background:rgba(59,130,246,0.15); border:1px solid rgba(59,130,246,0.3); padding:2px 8px; border-radius:4px; font-weight:700; text-transform:uppercase;">EN ATTENTE</span>
                                </div>
                                <div style="display:flex; align-items:center; gap:8px; margin-top:3px;">
                                    <span id="ie-viewer-filename" style="font-size:11px; color:var(--text-secondary); font-family:monospace;">Aucun plan chargé</span>
                                </div>
                            </div>
                        </div>

                        <!-- Contrôles interactifs du plan (Pages SLD, Zoom, Pan, Rotation, Fullscreen) -->
                        <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                            <!-- Sélecteur de page pour schémas unifilaires (SLD multi-pages) -->
                            <div id="ie-page-nav" style="display:none; align-items:center; gap:4px; background:var(--bg-surface); padding:3px 8px; border-radius:var(--radius-sm); border:1px solid var(--border-color); margin-right:6px;">
                                <button type="button" onclick="window.iePlanViewerPrevPage()" title="Page précédente" style="background:none; border:none; color:var(--text-primary); cursor:pointer; font-size:13px; padding:2px 6px; border-radius:4px;"><i class="ph ph-caret-left"></i></button>
                                <span id="ie-page-indicator" style="font-size:11px; color:var(--text-primary); font-weight:600; min-width:60px; text-align:center;">1 / 1</span>
                                <button type="button" onclick="window.iePlanViewerNextPage()" title="Page suivante" style="background:none; border:none; color:var(--text-primary); cursor:pointer; font-size:13px; padding:2px 6px; border-radius:4px;"><i class="ph ph-caret-right"></i></button>
                            </div>

                            <!-- Contrôles de zoom -->
                            <div style="display:flex; align-items:center; gap:2px; background:var(--bg-surface); padding:2px; border-radius:var(--radius-sm); border:1px solid var(--border-color);">
                                <button type="button" onclick="window.iePlanViewerZoom(-0.2)" title="Zoom arrière (-)" style="background:none; border:none; color:var(--text-primary); cursor:pointer; padding:6px 8px; font-size:12px; border-radius:4px;"><i class="ph ph-magnifying-glass-minus"></i></button>
                                <span id="ie-zoom-indicator" onclick="window.iePlanViewerResetZoom()" title="Cliquez pour réinitialiser le zoom à 100%" style="font-size:11px; color:var(--text-secondary); min-width:44px; text-align:center; cursor:pointer; user-select:none; font-weight:600;">100%</span>
                                <button type="button" onclick="window.iePlanViewerZoom(0.2)" title="Zoom avant (+)" style="background:none; border:none; color:var(--text-primary); cursor:pointer; padding:6px 8px; font-size:12px; border-radius:4px;"><i class="ph ph-magnifying-glass-plus"></i></button>
                                <button type="button" onclick="window.iePlanViewerFitWidth()" title="Ajuster à la largeur" style="background:none; border:none; color:var(--text-primary); cursor:pointer; padding:6px 8px; font-size:12px; border-radius:4px;"><i class="ph ph-arrows-out-line-horizontal"></i></button>
                            </div>

                            <!-- Rotation 90° -->
                            <button type="button" onclick="window.iePlanViewerRotate()" title="Pivoter 90° dans le sens horaire" style="background:var(--bg-surface); border:1px solid var(--border-color); color:var(--text-primary); border-radius:var(--radius-sm); padding:6px 10px; cursor:pointer; font-size:12px; display:flex; align-items:center; gap:4px;">
                                <i class="ph ph-arrow-clockwise"></i> 90°
                            </button>

                            <!-- Actions : Ouvrir, Télécharger, Plein écran -->
                            <button type="button" onclick="window.openIePlanNewTab()" title="Ouvrir le visuel dans un nouvel onglet" style="background:var(--bg-surface); border:1px solid var(--border-color); color:var(--text-primary); border-radius:var(--radius-sm); padding:6px 10px; cursor:pointer; font-size:12px; display:flex; align-items:center; gap:4px;">
                                <i class="ph ph-arrow-square-out"></i>
                            </button>
                            <button type="button" onclick="window.downloadCurrentIePlan()" title="Télécharger le fichier source / visuel" style="background:var(--bg-surface); border:1px solid var(--border-color); color:var(--text-primary); border-radius:var(--radius-sm); padding:6px 10px; cursor:pointer; font-size:12px; display:flex; align-items:center; gap:4px;">
                                <i class="ph ph-download-simple"></i>
                            </button>
                            <button type="button" onclick="window.toggleIePlanFullscreen()" title="Passer en plein écran" style="background:var(--accent-primary); border:none; color:#18181A; border-radius:var(--radius-sm); padding:6px 14px; cursor:pointer; font-size:12px; font-weight:700; display:flex; align-items:center; gap:6px; box-shadow:0 0 12px rgba(59,130,246,0.35);">
                                <i class="ph ph-frame-corners"></i> Plein écran
                            </button>
                        </div>
                    </div>

                    <!-- Zone de rendu interactive (Viewport avec Pan & Zoom) -->
                    <div id="ie-plan-viewport" style="position:relative; width:100%; height:580px; background:#121214; overflow:hidden; display:flex; align-items:center; justify-content:center; cursor:grab; user-select:none;">
                        <!-- Stage transformé pour pan/zoom -->
                        <div id="ie-plan-stage" style="transform-origin:center center; transition:transform 0.05s ease-out; display:flex; align-items:center; justify-content:center; flex-shrink:0;">
                            <!-- HTML5 Canvas pour PDF.js (haute résolution vectorielle) -->
                            <canvas id="ie-plan-canvas" style="display:none; max-width:none; max-height:none; box-shadow:0 8px 32px rgba(0,0,0,0.8); border-radius:4px; background:#FFFFFF; pointer-events:none;"></canvas>
                            <!-- Image directe (PNG rendu CAO DWG/DXF ou fallback serveur) -->
                            <img id="ie-plan-img" src="" alt="Plan technique I&E" draggable="false" style="display:none; max-width:none; max-height:none; box-shadow:0 8px 32px rgba(0,0,0,0.8); border-radius:4px; background:#FFFFFF; pointer-events:none; user-select:none; -webkit-user-drag:none;" />
                        </div>

                        <!-- Overlay de chargement / conversion CAO -->
                        <div id="ie-plan-loader" style="position:absolute; inset:0; background:rgba(18,18,20,0.95); display:none; flex-direction:column; align-items:center; justify-content:center; gap:12px; z-index:10;">
                            <div class="loader-spinner" style="width:36px; height:36px; border:3px solid rgba(59,130,246,0.2); border-top-color:var(--accent-primary); border-radius:50%; animation:spin 0.8s linear infinite;"></div>
                            <div id="ie-plan-loader-text" style="font-size:13px; color:var(--text-primary); font-weight:600;">Chargement du plan technique I&E...</div>
                        </div>

                        <!-- Placeholder -->
                        <div id="ie-plan-placeholder" style="width:100%; height:100%; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:12px; color:var(--text-secondary);">
                            <i class="ph ph-lightning" style="font-size:42px; opacity:0.4;"></i>
                            <span style="font-size:13px;">Téléversez ou sélectionnez un plan pour l'afficher en haute définition</span>
                        </div>
                    </div>

                    <!-- Barre d'état inférieure -->
                    <div style="display:flex; align-items:center; justify-content:space-between; padding:8px 18px; border-top:1px solid var(--border-color); background:rgba(15,23,42,0.8); font-size:11px; color:var(--text-secondary);">
                        <div style="display:flex; align-items:center; gap:8px;">
                            <span id="ie-viewer-status-dot" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#10B981;"></span>
                            <span id="ie-viewer-status-text">Prêt pour affichage de plan</span>
                        </div>
                        <div style="display:flex; align-items:center; gap:16px;">
                            <span id="ie-viewer-dims-text"></span>
                            <span>Molette : Zoom • Glisser : Panoramique • Double-clic : Ajuster</span>
                        </div>
                    </div>
                </div>
'''

# Find insertion point: right after the middle section </div> and before <!-- Extraction Table Container -->
target_middle = '''                    <!-- Reserves & Anomalies Lifecycle Column -->
                    <div style="background:var(--bg-card); border:1px solid var(--border-color); border-radius:10px; padding:18px; display:flex; flex-direction:column; gap:14px;">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <h4 style="font-size:14px; font-weight:700; color:var(--text-primary); margin:0; display:flex; align-items:center; gap:8px;">
                                <i class="ph ph-shield-warning" style="color:#F59E0B; font-size:18px;"></i> Réserves & Anomalies Techniques ARKAN
                            </h4>
                            <span id="ie-reserves-counter" style="font-size:11px; font-weight:700; padding:2px 8px; border-radius:10px; background:rgba(239,68,68,0.15); color:#F87171;">0 Réserves</span>
                        </div>
                        <p style="font-size:12px; color:var(--text-secondary); margin:0;">
                            Contrôle automatisé selon normes CEI 60364, ISA-5.1 et NF C 15-100. Validez une réserve pour insérer automatiquement l'article normalisé dans le tableau d'extraction et le classeur Excel.
                        </p>
                        <div id="ie-anomalies-list" style="display:flex; flex-direction:column; gap:12px; max-height:480px; overflow-y:auto; padding-right:4px;">
                            <!-- Injected dynamically -->
                        </div>
                    </div>
                </div>'''

replacement_middle = target_middle + '\n' + ie_viewer_html

assert target_middle in content, "target_middle not found in content"
content = content.replace(target_middle, replacement_middle)

# Update Cartouche preview container with click-to-scroll to viewer
old_preview_box = '''                        <div id="ie-preview-container" style="background:#000; border-radius:8px; overflow:hidden; min-height:220px; display:flex; align-items:center; justify-content:center; border:1px solid var(--border-color);">
                            <img id="ie-preview-img" style="max-width:100%; max-height:360px; object-fit:contain; display:none;" alt="Prévisualisation Plan I&E">
                            <span id="ie-preview-placeholder" style="color:var(--text-secondary); font-size:12px;">Aucun aperçu graphique disponible</span>
                        </div>'''

new_preview_box = '''                        <div id="ie-preview-container" style="background:#000; border-radius:8px; overflow:hidden; min-height:200px; display:flex; flex-direction:column; align-items:center; justify-content:center; border:1px solid var(--border-color); cursor:pointer; position:relative;" onclick="document.getElementById('ie-plan-viewer').scrollIntoView({behavior:'smooth'}); window.iePlanViewerFitWidth();" title="Cliquer pour afficher dans le visualiseur haute définition">
                            <img id="ie-preview-img" style="max-width:100%; max-height:300px; object-fit:contain; display:none;" alt="Prévisualisation Plan I&E">
                            <span id="ie-preview-placeholder" style="color:var(--text-secondary); font-size:12px; padding:20px;">Aucun aperçu graphique disponible</span>
                            <div style="width:100%; padding:6px; background:rgba(15,23,42,0.85); border-top:1px solid var(--border-color); display:flex; align-items:center; justify-content:center; gap:6px; font-size:11px; color:#60A5FA; font-weight:600;">
                                <i class="ph ph-magnifying-glass-plus"></i> Agrandir dans le visualiseur interactif
                            </div>
                        </div>'''

assert old_preview_box in content, "old_preview_box not found in content"
content = content.replace(old_preview_box, new_preview_box)

with open('arkan-ui.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("HTML part of #ie-plan-viewer inserted successfully!")
