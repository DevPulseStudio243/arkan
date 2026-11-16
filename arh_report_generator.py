"""
arh_report_generator.py
=======================
Générateur Automatique de Rapports Officiels d'Inspection et de Conformité ARH (PDF).

Produit un document PDF de qualité professionnelle conforme aux exigences d'audit ARH.
"""

from __future__ import annotations
import os
import datetime
from pathlib import Path
from typing import Dict, List, Any

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


class ARHReportGenerator:
    def __init__(self, output_dir: str = "generated_visuals"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_pdf_report(self, audit_result: Dict[str, Any]) -> str:
        """
        Génère le rapport PDF officiel d'inspection réglementaire ARH.
        """
        dossier_id = audit_result.get("dossier_id", "DOSSIER_ARH")
        pdf_filename = f"RAPPORT_CONFORMITE_ARH_{dossier_id}.pdf"
        pdf_path = self.output_dir / pdf_filename

        if REPORTLAB_AVAILABLE:
            return self._build_reportlab_pdf(audit_result, str(pdf_path))
        else:
            return self._build_fallback_text_report(audit_result, str(pdf_path))

    def _build_reportlab_pdf(self, res: Dict[str, Any], pdf_path: str) -> str:
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            leftMargin=36, rightMargin=36,
            topMargin=36, bottomMargin=36
        )

        styles = getSampleStyleSheet()
        
        # Styles personnalisés
        title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=colors.HexColor('#0F2942'), alignment=1)
        subtitle_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor('#008080'), alignment=1)
        h2_style = ParagraphStyle('Heading2Custom', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=13, leading=16, textColor=colors.HexColor('#0F2942'), spaceBefore=12, spaceAfter=6)
        body_style = ParagraphStyle('BodyCustom', parent=styles['Normal'], fontName='Helvetica', fontSize=9.5, leading=13, textColor=colors.HexColor('#2C3E50'))
        body_bold = ParagraphStyle('BodyBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9.5, leading=13, textColor=colors.HexColor('#0F2942'))

        story = []

        # En-tête Officiel
        story.append(Paragraph("RÉPUBLIQUE ALGÉRIENNE DÉMOCRATIQUE ET POPULAIRE", subtitle_style))
        story.append(Paragraph("AUTORITÉ DE RÉGULATION DES HYDROCARBURES (ARH)", subtitle_style))
        story.append(Spacer(1, 10))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#0F2942'), spaceBefore=5, spaceAfter=15))

        story.append(Paragraph("RAPPORT D'INSPECTION & DE CONFORMITÉ RÉGLEMENTAIRE ARH", title_style))
        story.append(Spacer(1, 5))
        story.append(Paragraph(f"Dossier N° : <b>{res.get('dossier_id')}</b> | Date : <b>{res.get('created_at')}</b>", subtitle_style))
        story.append(Spacer(1, 15))

        # Tableau Récapitulatif
        status_color = "#27AE60" if res.get("status") == "APPROVED" else ("#F39C12" if "COMMENTS" in res.get("status") else "#C0392B")
        summary_data = [
            [Paragraph("Projet :", body_bold), Paragraph(res.get("project_name", ""), body_style), Paragraph("Score Global :", body_bold), Paragraph(f"<b>{res.get('compliance_score')}%</b>", body_style)],
            [Paragraph("Unité / Équipement :", body_bold), Paragraph(f"{res.get('unit_name')} / {res.get('equipment_tag')}", body_style), Paragraph("Statut ARH :", body_bold), Paragraph(f"<font color='{status_color}'><b>{res.get('status')}</b></font>", body_style)],
            [Paragraph("Type Équipement :", body_bold), Paragraph(res.get("equipment_label", ""), body_style), Paragraph("Inspection IA :", body_bold), Paragraph("ARKAN Virtual ARH Inspector", body_style)]
        ]

        t_summary = Table(summary_data, colWidths=[110, 180, 100, 130])
        t_summary.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8F9F9')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#BDC3C7')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#ECF0F1')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(t_summary)
        story.append(Spacer(1, 15))

        # Décrets applicables
        story.append(Paragraph("1. Réglementation Officielle Applicable", h2_style))
        decrees_list = res.get("applicable_decrees", [])
        dec_data = [[Paragraph("Décret / Réglementation", body_bold), Paragraph("Objet & Champ d'Application", body_bold)]]
        for d in decrees_list:
            dec_data.append([Paragraph(f"<b>{d['title']}</b>", body_style), Paragraph(d["description"], body_style)])

        t_dec = Table(dec_data, colWidths=[200, 320])
        t_dec.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0F2942')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#0F2942')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#BDC3C7')),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(t_dec)
        story.append(Spacer(1, 15))

        # Relevé des Remarques et Anomalies (Phase 2 & 3)
        story.append(Paragraph("2. Fiches de Remarques & Anomalies Techniques", h2_style))
        comments = res.get("comments", [])

        if not comments:
            story.append(Paragraph("<b>Aucune anomalie ni non-conformité détectée. Le dossier est 100% conforme.</b>", body_style))
        else:
            comm_data = [[
                Paragraph("Réf / Titre", body_bold),
                Paragraph("Criticité", body_bold),
                Paragraph("Document & Emplacement Exact", body_bold),
                Paragraph("Article / Décret Violé", body_bold),
                Paragraph("Action Corrective Exigée", body_bold)
            ]]
            for c in comments:
                prio = c.get('priority', 'MINOR')
                prio_col = "#C0392B" if prio == "CRITICAL" else ("#E67E22" if prio == "MAJOR" else "#F1C40F")
                doc_name = c.get('document_concerned', 'Dossier Technique')
                page_str = c.get('page', 'Page 1')
                snippet = c.get('quote_snippet', '')
                snippet_txt = f"<br/><font size=7 color='#555555'><i>« {snippet[:130]}... »</i></font>" if snippet else ""

                comm_data.append([
                    Paragraph(f"<b>{c.get('id', 'N/A')}</b><br/>{c.get('title', 'Anomalie')}", body_style),
                    Paragraph(f"<font color='{prio_col}'><b>{prio}</b></font>", body_style),
                    Paragraph(f"<b>{doc_name}</b><br/><font color='#0284C7'><b>📍 {page_str}</b></font>{snippet_txt}", body_style),
                    Paragraph(f"{c.get('regulation_ref', 'Décret Général ARH')}<br/><b>{c.get('article', c.get('article_number', 'N/A'))}</b>", body_style),
                    Paragraph(c.get('correction_method', c.get('action_required', 'Voir rapport détaillé')), body_style)
                ])

            t_comm = Table(comm_data, colWidths=[110, 55, 145, 95, 135])
            t_comm.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#34495E')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#34495E')),
                ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#BDC3C7')),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('TOPPADDING', (0,0), (-1,-1), 5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ]))
            story.append(t_comm)

        story.append(Spacer(1, 20))
        # Signature Virtuelle
        story.append(KeepTogether([
            HRFlowable(width="100%", thickness=1, color=colors.HexColor('#BDC3C7'), spaceBefore=10, spaceAfter=10),
            Paragraph("<b>CERTIFICATION D'AUDIT VIRTUEL ARKAN ARH</b>", body_bold),
            Paragraph("Ce rapport a été généré automatiquement par le Moteur Réglementaire ARKAN ARH Management suite à la vérification croisée des documents, calculs et normes appliqués au dossier.", body_style),
            Spacer(1, 5),
            Paragraph(f"Empreinte Numérique Certifiée : <i>ARKAN-ARH-{res.get('dossier_id')}-APPROVED</i>", ParagraphStyle('Foot', parent=styles['Italic'], fontSize=8, textColor=colors.HexColor('#7F8C8D')))
        ]))

        doc.build(story)
        return pdf_path

    def _build_fallback_text_report(self, res: Dict[str, Any], pdf_path: str) -> str:
        txt_path = pdf_path.replace(".pdf", ".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("=================================================================================\n")
            f.write("AUTORITÉ DE RÉGULATION DES HYDROCARBURES (ARH) - RAPPORT DE CONFORMITÉ ARKAN\n")
            f.write("=================================================================================\n")
            f.write(f"Dossier ID: {res.get('dossier_id')}\n")
            f.write(f"Projet: {res.get('project_name')}\n")
            f.write(f"Équipement: {res.get('equipment_tag')} ({res.get('equipment_label')})\n")
            f.write(f"Score de Conformité: {res.get('compliance_score')}%\n")
            f.write(f"Statut ARH: {res.get('status')}\n\n")

            f.write("--- ANOMALIES & REMARQUES ARH ---\n")
            for c in res.get("comments", []):
                doc_name = c.get('document_concerned', 'Dossier Technique')
                page_str = c.get('page', 'Page 1')
                snippet = c.get('quote_snippet', '')
                f.write(f"\u2022 [{c.get('priority','MINOR')}] {c.get('title','Anomalie')}\n")
                f.write(f"  Emplacement exact : {doc_name} (📍 {page_str})\n")
                if snippet:
                    f.write(f"  Preuve textuelle   : « {snippet} »\n")
                f.write(f"  Réf Réglementaire : {c.get('regulation_ref','Décret ARH')} ({c.get('article', c.get('article_number','N/A'))})\n")
                f.write(f"  Action requise    : {c.get('correction_method', c.get('action_required', 'Voir rapport'))}\n\n")

        return txt_path
