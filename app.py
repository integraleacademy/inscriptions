from flask import Flask, render_template, request, redirect, send_file, session, url_for
import os, json, zipfile
from werkzeug.utils import secure_filename
from fpdf import FPDF
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import unicodedata
from urllib.parse import unquote

# === AJOUTS ===
from PIL import Image, ImageOps
from io import BytesIO
from docx import Document
from docx.shared import Mm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from PyPDF2 import PdfMerger, PdfReader

UPLOAD_FOLDER = '/mnt/data/uploads'
DATA_FILE = '/mnt/data/data.json'
ADMIN_USER = 'admin'
ADMIN_PASS = 'integrale2025'

app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# =====================
#        HELPERS
# =====================
def clean_text(text):
    if not isinstance(text, str):
        text = str(text)
    return unicodedata.normalize('NFKD', text).encode('latin-1', 'ignore').decode('latin-1')

def save_data(entry):
    if not os.path.exists(DATA_FILE):
        data = []
    else:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
    data.append(entry)
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def _norm(s):
    if not isinstance(s, str):
        s = str(s)
    return unicodedata.normalize('NFKC', s).strip().lower()

IMG_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp'}
PDF_EXTS = {'.pdf'}

def is_image_file(path): return os.path.splitext(path.lower())[1] in IMG_EXTS
def is_pdf_file(path): return os.path.splitext(path.lower())[1] in PDF_EXTS

def list_all_user_files(folder):
    if not os.path.isdir(folder): return []
    return [os.path.join(folder, f) for f in sorted(os.listdir(folder))]

def ensure_rgb(img):
    if img.mode in ('RGBA','LA'):
        bg = Image.new('RGB', img.size, (255,255,255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert('RGB') if img.mode!='RGB' else img

def set_cell_border(cell, color="000000", size='8'):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for edge in ('top','left','bottom','right'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'),'single')
        el.set(qn('w:sz'), size)      # huitièmes de point
        el.set(qn('w:color'), color)
        tcPr.append(el)

# --- Gabarits d'impression (mm) ---
CARD_BOX_MM = (180, 120)   # cartes: CNI, Vitale, permis, passeport...
DOC_BOX_MM  = (140, 200)   # justificatifs/attestations (portrait)

CARD_HINTS = (
    "carte_vitale", "identity_file", "cni", "recto", "verso",
    "permis_conduire", "permis", "passeport", "passport", "carte"
)

def decide_orientation_and_box(filename: str):
    """
    Retourne (orientation, (w_mm,h_mm)) selon le nom du fichier.
    - 'landscape' pour cartes/passeports/permis
    - 'portrait' pour le reste (factures, justificatifs, attestations...)
    """
    name = filename.lower()
    if any(h in name for h in CARD_HINTS):
        return "landscape", CARD_BOX_MM
    return "portrait", DOC_BOX_MM

# =====================
#        ROUTES
# =====================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    form, files = request.form, request.files
    nom, prenom, email = form['nom'].strip(), form['prenom'].strip(), form['email']
    full_name = f"{nom}_{prenom}".replace(" ", "_")
    person_folder = os.path.join(app.config['UPLOAD_FOLDER'], full_name)
    os.makedirs(person_folder, exist_ok=True)

    # Fichiers principaux
    for field in ['photo_identite', 'carte_vitale', 'identity_file_1', 'identity_file_2']:
        f = files.get(field)
        if f and f.filename:
            f.save(os.path.join(person_folder, secure_filename(f"{field}_{f.filename}"))

            )

    # A3P si présent
    if form.get('formation') == 'A3P':
        for field in ['assurance_rc', 'certificat_medical', 'permis_conduire']:
            f = files.get(field)
            if f and f.filename:
                f.save(os.path.join(person_folder, secure_filename(f"{field}_{f.filename}")))

    entry = {
        "nom": nom, "prenom": prenom, "email": email,
        "secu": form['secu'], "naissance": form['naissance'],
        "ville_naissance": form['ville_naissance'],
        "pays_naissance": form['pays_naissance'],
        "nationalite": form['nationalite'], "sexe": form['sexe'],
        "adresse": form['adresse'], "cp": form['cp'], "ville": form['ville'],
        "cnaps": form['cnaps'],
        "folder": full_name, "status": "INCOMPLET", "commentaire": ""
    }
    save_data(entry)
    send_confirmation_email(entry)
    return render_template('submit.html')

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        if request.form['user'] == ADMIN_USER and request.form['pass'] == ADMIN_PASS:
            session['admin'] = True
            return redirect('/admin')
        else:
            return "Accès refusé"
    if not session.get('admin'):
        return '''
        <form method="post">
            <input name="user" placeholder="Utilisateur"><br>
            <input name="pass" placeholder="Mot de passe" type="password"><br>
            <button type="submit">Connexion</button>
        </form>
        '''
    if not os.path.exists(DATA_FILE):
        return "Aucune donnée"
    with open(DATA_FILE) as f:
        data = json.load(f)
    return render_template('admin.html', data=data)

@app.route('/download/<folder>')
def download(folder):
    folder_path = os.path.join(app.config['UPLOAD_FOLDER'], folder)
    zip_path = f"/mnt/data/{folder}.zip"
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, _, files in os.walk(folder_path):
            for file in files:
                full_path = os.path.join(root, file)
                zipf.write(full_path, arcname=file)
    return send_file(zip_path, as_attachment=True)

@app.route('/fiche/<prenom>/<nom>')
def fiche(prenom, nom):
    prenom = _norm(unquote(prenom))
    nom = _norm(unquote(nom))
    if not os.path.exists(DATA_FILE):
        return "Données manquantes"
    with open(DATA_FILE) as f:
        data = json.load(f)
    personne = next((d for d in data if _norm(d.get('nom')) == nom and _norm(d.get('prenom')) == prenom), None)
    if not personne:
        return "Stagiaire non trouvé"

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for k, v in personne.items():
        if k != "folder":
            pdf.cell(200, 10, txt=clean_text(f"{k.upper()}: {v}"), ln=True)

    path = f"/mnt/data/fiche_{clean_text(personne['prenom'])}_{clean_text(personne['nom'])}.pdf"
    pdf.output(path)
    return send_file(path, as_attachment=True)

def send_confirmation_email(data):
    html = f"""
    <html><body>
      <p>Bonjour {data['prenom']},</p>
      <p>Nous vous confirmons la bonne réception de votre dossier. L’équipe d’Intégrale Academy vous remercie.</p>
      <p>Nous restons disponibles pour toute question complémentaire.</p>
      <br><p>Cordialement,<br>L’équipe Intégrale Academy</p>
    </body></html>
    """
    msg = MIMEMultipart('alternative')
    msg['Subject'] = "Confirmation de dépôt de dossier – Intégrale Academy"
    msg['From'] = os.environ.get("MAIL_USER")
    msg['To'] = data['email']
    msg.attach(MIMEText(html, 'html'))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.environ.get("MAIL_USER"), os.environ.get("MAIL_PASS"))
        server.sendmail(msg['From'], [msg['To']], msg.as_string())

# ----------- UPDATE (tolérant + ciblage par folder) -----------
@app.route('/update/<prenom>/<nom>', methods=['POST'])
def update(prenom, nom):
    if not session.get('admin'):
        return redirect('/admin')

    prenom_n = _norm(unquote(prenom))
    nom_n = _norm(unquote(nom))
    folder = request.form.get('folder', '')

    if not os.path.exists(DATA_FILE):
        return "Données introuvables"

    with open(DATA_FILE, 'r') as f:
        data = json.load(f)

    for d in data:
        same_folder = (folder and d.get('folder') == folder)
        same_name = (_norm(d.get('prenom', '')) == prenom_n and _norm(d.get('nom', '')) == nom_n)
        if same_folder or same_name:
            d['status'] = request.form.get('status', d.get('status'))
            d['commentaire'] = request.form.get('commentaire', d.get('commentaire', ''))
            break

    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

    return redirect('/admin')

# ----------- DELETE (tolérant + robustesse FS) -----------
@app.route('/delete/<prenom>/<nom>', methods=['POST'])
def delete(prenom, nom):
    if not session.get('admin'):
        return redirect('/admin')

    prenom_n = _norm(unquote(prenom))
    nom_n = _norm(unquote(nom))

    if not os.path.exists(DATA_FILE):
        return redirect('/admin')

    with open(DATA_FILE, 'r') as f:
        data = json.load(f)

    new_data = []
    for d in data:
        if _norm(d.get('prenom', '')) == prenom_n and _norm(d.get('nom', '')) == nom_n:
            folder_path = os.path.join(app.config['UPLOAD_FOLDER'], d.get('folder', ''))
            if os.path.isdir(folder_path):
                import shutil
                try:
                    shutil.rmtree(folder_path)
                except Exception as e:
                    print(f"[delete] Impossible de supprimer {folder_path}: {e}")
            # on n'ajoute pas cette entrée -> supprimée
        else:
            new_data.append(d)

    with open(DATA_FILE, 'w') as f:
        json.dump(new_data, f, indent=2)

    return redirect('/admin')

# ==========================================
#     PDF "TOUS LES DOCS SAUF LA PHOTO"
# ==========================================
def image_to_uniform_pdf_page(image_path, out_pdf_path, orientation="landscape", box_mm=(180,120)):
    """
    Place une image sur A4 :
      - Correction EXIF
      - Orientation forcée ('landscape'/'portrait')
      - Redimensionnement SANS rognage (fit contain)
      - Fond blanc + cadre léger
    """
    w_mm, h_mm = box_mm
    A4_W, A4_H = 210, 297
    X, Y = (A4_W - w_mm) / 2.0, (A4_H - h_mm) / 2.0
    target_px_w, target_px_h = int(w_mm * 12), int(h_mm * 12)  # ~300 dpi

    with Image.open(image_path) as im:
        im = ImageOps.exif_transpose(im)
        im = ensure_rgb(im)

        # Orientation forcée selon le type
        if orientation == "landscape" and im.height > im.width:
            im = im.rotate(90, expand=True)
        elif orientation == "portrait" and im.width > im.height:
            im = im.rotate(90, expand=True)

        # Fit contain (aucun rognage)
        scale = min(target_px_w / im.width, target_px_h / im.height)
        new_w, new_h = max(1, int(im.width * scale)), max(1, int(im.height * scale))
        im_resized = im.resize((new_w, new_h), Image.LANCZOS)

        # Canevas blanc centré
        canvas = Image.new('RGB', (target_px_w, target_px_h), (255,255,255))
        off_x, off_y = (target_px_w - new_w) // 2, (target_px_h - new_h) // 2
        canvas.paste(im_resized, (off_x, off_y))

        bio = BytesIO()
        canvas.save(bio, format='JPEG', quality=92)
        bio.seek(0)

    tmp = f"/mnt/data/_tmp_{os.path.basename(image_path)}.jpg"
    with open(tmp, 'wb') as f: f.write(bio.read())

    pdf = FPDF(unit='mm', format='A4')
    pdf.add_page()
    pdf.set_draw_color(200, 200, 200)
    pdf.rect(X, Y, w_mm, h_mm)
    pdf.image(tmp, x=X, y=Y, w=w_mm, h=h_mm)
    pdf.output(out_pdf_path)

    try: os.remove(tmp)
    except: pass

def build_all_docs_pdf(folder, out_pdf):
    """
    Fusionne tous les documents (images + PDFs) SAUF les photo_identite*.
      - Cartes/passeports/permis => paysage + CARD_BOX_MM
      - Justificatifs/attestations => portrait + DOC_BOX_MM
      - PDFs natifs => fusion tels quels
    """
    files = [p for p in list_all_user_files(folder) if not os.path.basename(p).startswith('photo_identite')]
    usable = [p for p in files if is_image_file(p) or is_pdf_file(p)]
    if not usable:
        raise FileNotFoundError("Aucun document compatible (hors photo).")

    temp_pages = []
    for p in usable:
        if is_image_file(p):
            orientation, box_mm = decide_orientation_and_box(os.path.basename(p))
            tmp_pdf = f"/mnt/data/_p_{os.path.basename(p)}.pdf"
            image_to_uniform_pdf_page(p, tmp_pdf, orientation=orientation, box_mm=box_mm)
            temp_pages.append(tmp_pdf)
        elif is_pdf_file(p):
            try:
                _ = PdfReader(p)  # valide
                temp_pages.append(p)
            except Exception:
                pass  # ignore PDF corrompu

    if not temp_pages:
        raise FileNotFoundError("Impossible de préparer les documents.")

    merger = PdfMerger()
    for page in temp_pages:
        try:
            merger.append(page)
        except Exception:
            continue
    merger.write(out_pdf)
    merger.close()

    # Nettoyage des PDF temporaires issus d'images
    for p in temp_pages:
        if p.startswith('/mnt/data/_p_'):
            try: os.remove(p)
            except: pass

@app.route('/idpack/<prenom>/<nom>')
def idpack(prenom, nom):
    prenom, nom = _norm(unquote(prenom)), _norm(unquote(nom))
    if not os.path.exists(DATA_FILE):
        return "Données manquantes"
    with open(DATA_FILE) as f:
        data = json.load(f)
    pers = next((d for d in data if _norm(d['nom']) == nom and _norm(d['prenom']) == prenom), None)
    if not pers:
        return "Stagiaire non trouvé"
    folder = os.path.join(app.config['UPLOAD_FOLDER'], pers['folder'])
    out = f"/mnt/data/IDs_{clean_text(pers['prenom'])}_{clean_text(pers['nom'])}.pdf"
    try:
        build_all_docs_pdf(folder, out)
    except Exception as e:
        return f"Erreur génération PDF: {e}"
    return send_file(out, as_attachment=True)

# ==========================================
#     DOCX "PHOTO D'IDENTITÉ" (1 seule)
# ==========================================
def prepare_portrait_photo(src, out):
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        im = ensure_rgb(im)
        # Mettre en portrait seulement si vraiment paysage
        if im.width > im.height:
            im = im.rotate(90, expand=True)
        im.save(out, 'JPEG', quality=92)

def build_single_photo_docx(photo, full_name, out_docx):
    PHOTO_W, PHOTO_H = 35, 45  # taille photo identité
    doc = Document()
    # Table 1x1 haut-gauche
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    cell = table.cell(0, 0)

    # Vider la cellule et insérer la photo
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.add_run().add_picture(photo, width=Mm(PHOTO_W), height=Mm(PHOTO_H))

    # Nom/Prénom en dessous
    p2 = cell.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p2.add_run(full_name)

    # Cadre
    set_cell_border(cell, color="000000", size='8')

    doc.save(out_docx)

@app.route('/photosheet/<prenom>/<nom>')
def photosheet(prenom, nom):
    prenom, nom = _norm(unquote(prenom)), _norm(unquote(nom))
    if not os.path.exists(DATA_FILE):
        return "Données manquantes"
    with open(DATA_FILE) as f:
        data = json.load(f)
    pers = next((d for d in data if _norm(d['nom']) == nom and _norm(d['prenom']) == prenom), None)
    if not pers:
        return "Stagiaire non trouvé"

    folder = os.path.join(app.config['UPLOAD_FOLDER'], pers['folder'])
    photos = [os.path.join(folder, f) for f in os.listdir(folder)
              if f.startswith('photo_identite') and is_image_file(f)]
    if not photos:
        return "Aucune photo d'identité trouvée pour ce dossier."

    src_photo = photos[0]
    tmp = f"/mnt/data/_tmp_photo_{os.path.basename(src_photo)}.jpg"
    try:
        prepare_portrait_photo(src_photo, tmp)
        out = f"/mnt/data/PHOTOS_{clean_text(pers['prenom'])}_{clean_text(pers['nom'])}.docx"
        full_name = f"{pers['nom']} {pers['prenom']}"
        build_single_photo_docx(tmp, full_name, out)
        return send_file(out, as_attachment=True)
    finally:
        try: os.remove(tmp)
        except: pass
