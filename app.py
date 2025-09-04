from flask import Flask, render_template, request, redirect, send_file, session, url_for
import os, json, zipfile
from werkzeug.utils import secure_filename
from fpdf import FPDF
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import unicodedata
from urllib.parse import unquote  # <- ajouté

# --- AJOUTS ---
from PIL import Image
from io import BytesIO
from docx import Document
from docx.shared import Mm, Pt
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

def clean_text(text):
    """Nettoie les caractères non supportés par fpdf (latin-1)"""
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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    form = request.form
    files = request.files

    # --- mini-changes: strip des noms pour éviter espaces traînants ---
    nom = form['nom'].strip()
    prenom = form['prenom'].strip()
    email = form['email']
    full_name = f"{nom}_{prenom}".replace(" ", "_")
    person_folder = os.path.join(app.config['UPLOAD_FOLDER'], full_name)
    os.makedirs(person_folder, exist_ok=True)

    saved_files = []

    all_files = {
        'photo_identite': files.get('photo_identite'),
        'carte_vitale': files.get('carte_vitale'),
        'identity_file_1': files.get('identity_file_1'),
        'identity_file_2': files.get('identity_file_2')
    }

    for field_name, f in all_files.items():
        if f and f.filename:
            filename = secure_filename(f"{field_name}_{f.filename}")
            path = os.path.join(person_folder, filename)
            f.save(path)
            saved_files.append(path)

    if form.get('formation') == 'A3P':
        a3p_files = {
            'assurance_rc': files.get('assurance_rc'),
            'certificat_medical': files.get('certificat_medical'),
            'permis_conduire': files.get('permis_conduire')
        }

        for key, f in a3p_files.items():
            if f and f.filename:
                renamed = secure_filename(f"{key}_{f.filename}")
                full_path = os.path.join(person_folder, renamed)
                f.save(full_path)
                saved_files.append(full_path)

    entry = {
        "nom": nom,
        "prenom": prenom,
        "email": email,
        "secu": form['secu'],
        "naissance": form['naissance'],
        "ville_naissance": form['ville_naissance'],
        "pays_naissance": form['pays_naissance'],
        "nationalite": form['nationalite'],
        "sexe": form['sexe'],
        "adresse": form['adresse'],
        "cp": form['cp'],
        "ville": form['ville'],
        "cnaps": form['cnaps'],
        "folder": full_name,
        "status": "INCOMPLET",
        "commentaire": ""
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

# --- Helpers robustesse ---
def _norm(s):
    if not isinstance(s, str):
        s = str(s)
    # normalise, retire espaces autour, met en minuscules
    return unicodedata.normalize('NFKC', s).strip().lower()

@app.route('/fiche/<prenom>/<nom>')
def fiche(prenom, nom):
    # Nettoyer/decoder les paramètres d’URL
    prenom = _norm(unquote(prenom))
    nom = _norm(unquote(nom))

    if not os.path.exists(DATA_FILE):
        return "Données manquantes"
    with open(DATA_FILE) as f:
        data = json.load(f)

    # Recherche tolérante sur prénom/nom
    personne = next((d for d in data if _norm(d.get('nom')) == nom and _norm(d.get('prenom')) == prenom), None)
    if not personne:
        return "Stagiaire non trouvé"

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for k, v in personne.items():
        if k != "folder":
            ligne = clean_text(f"{k.upper()}: {v}")
            pdf.cell(200, 10, txt=ligne, ln=True)

    path = f"/mnt/data/fiche_{clean_text(personne['prenom'])}_{clean_text(personne['nom'])}.pdf"
    pdf.output(path)
    return send_file(path, as_attachment=True)

def send_confirmation_email(data):
    html_email_content = """
    <html>
      <body>
        <p>Bonjour {prenom},</p>
        <p>Nous vous confirmons la bonne réception de votre dossier. L’équipe d’Intégrale Academy vous remercie.</p>
        <p>Nous restons disponibles pour toute question complémentaire.</p>
        <br>
        <p>Cordialement,<br>L’équipe Intégrale Academy</p>
      </body>
    </html>
    """
    msg = MIMEMultipart('alternative')
    msg['Subject'] = "Confirmation de dépôt de dossier – Intégrale Academy"
    msg['From'] = os.environ.get("MAIL_USER")
    msg['To'] = data['email']
    html = f"""{html_email_content.replace('{prenom}', data['prenom'])}"""
    msg.attach(MIMEText(html, 'html'))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.environ.get("MAIL_USER"), os.environ.get("MAIL_PASS"))
        server.sendmail(msg['From'], [msg['To']], msg.as_string())

@app.route('/update/<prenom>/<nom>', methods=['POST'])
def update(prenom, nom):
    if not session.get('admin'):
        return redirect('/admin')

    if not os.path.exists(DATA_FILE):
        return "Données introuvables"

    with open(DATA_FILE, 'r') as f:
        data = json.load(f)

    for d in data:
        if d['prenom'] == prenom and d['nom'] == nom:
            d['status'] = request.form.get('status')
            d['commentaire'] = request.form.get('commentaire')

    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

    return redirect('/admin')

@app.route('/delete/<prenom>/<nom>', methods=['POST'])
def delete(prenom, nom):
    if not session.get('admin'):
        return redirect('/admin')

    if not os.path.exists(DATA_FILE):
        return redirect('/admin')

    with open(DATA_FILE, 'r') as f:
        data = json.load(f)

    new_data = []
    for d in data:
        if d['prenom'] == prenom and d['nom'] == nom:
            folder_path = os.path.join(app.config['UPLOAD_FOLDER'], d['folder'])
            if os.path.exists(folder_path):
                import shutil
                shutil.rmtree(folder_path)
        else:
            new_data.append(d)

    with open(DATA_FILE, 'w') as f:
        json.dump(new_data, f, indent=2)

    return redirect('/admin')

# =========================
#      AJOUTS DEMANDÉS
# =========================

# --- Helpers images / fichiers ---
IMG_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp'}
PDF_EXTS = {'.pdf'}

def is_image_file(path):
    _, ext = os.path.splitext(path.lower())
    return ext in IMG_EXTS

def is_pdf_file(path):
    _, ext = os.path.splitext(path.lower())
    return ext in PDF_EXTS

def list_all_user_files(person_folder):
    out = []
    if not os.path.isdir(person_folder):
        return out
    for f in sorted(os.listdir(person_folder)):
        out.append(os.path.join(person_folder, f))
    return out

def ensure_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ('RGBA', 'LA'):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    if img.mode != 'RGB':
        return img.convert('RGB')
    return img

# --- Cadres cellule DOCX ---
def set_cell_border(cell, color="000000", size='8'):  # taille en huitièmes de point
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for edge in ('top', 'left', 'bottom', 'right'):
        element = OxmlElement(f'w:{edge}')
        element.set(qn('w:val'), 'single')
        element.set(qn('w:sz'), size)
        element.set(qn('w:color'), color)
        tcPr.append(element)

# --- 1) PDF "tous documents sauf la photo" ---
# A4 (mm): 210x297 ; on place chaque IMAGE dans un cadre uniforme (ex: 180x120mm), centré.
# Pour les PDFs déjà fournis, on les MERGE tels quels.
def image_to_uniform_pdf_page(image_path, out_pdf_path, target_w_mm=180, target_h_mm=120):
    A4_W, A4_H = 210, 297
    X = (A4_W - target_w_mm) / 2.0
    Y = (A4_H - target_h_mm) / 2.0

    with Image.open(image_path) as im:
        im = ensure_rgb(im)
        # cover dans la box (crop si nécessaire) pour uniformiser visuellement
        img_w, img_h = im.size
        target_px_w = int(target_w_mm * 12)  # ~12 px/mm
        target_px_h = int(target_h_mm * 12)

        src_ratio = img_w / img_h
        dst_ratio = target_px_w / target_px_h
        if src_ratio > dst_ratio:
            new_h = target_px_h
            new_w = int(new_h * src_ratio)
        else:
            new_w = target_px_w
            new_h = int(new_w / src_ratio)

        im_resized = im.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - target_px_w)//2
        top  = (new_h - target_px_h)//2
        im_cropped = im_resized.crop((left, top, left+target_px_w, top+target_px_h))

        bio = BytesIO()
        im_cropped.save(bio, format='JPEG', quality=92)
        bio.seek(0)

    tmp_img = os.path.join('/mnt/data', f'_tmp_img_{os.path.basename(image_path)}.jpg')
    with open(tmp_img, 'wb') as f:
        f.write(bio.read())

    pdf = FPDF(unit='mm', format='A4')
    pdf.add_page()
    # cadre léger autour
    pdf.set_draw_color(200, 200, 200)
    pdf.rect(X, Y, target_w_mm, target_h_mm)
    pdf.image(tmp_img, x=X, y=Y, w=target_w_mm, h=target_h_mm)
    pdf.output(out_pdf_path)

    try:
        os.remove(tmp_img)
    except:
        pass

def build_all_docs_pdf(person_folder, out_pdf_path):
    """
    Construit un unique PDF avec TOUS les documents du dossier
    SAUF la/les 'photo_identite*'. Supporte images + PDFs.
    Images => pages A4 uniformisées (taille identique).
    PDFs => fusion tels quels.
    """
    files = list_all_user_files(person_folder)
    if not files:
        raise FileNotFoundError("Aucun fichier trouvé.")

    # Filtrer les photos d'identité
    files = [p for p in files if not os.path.basename(p).startswith('photo_identite')]

    # Ne garder que images et PDFs
    usable = [p for p in files if is_image_file(p) or is_pdf_file(p)]
    if not usable:
        raise FileNotFoundError("Aucun document compatible (images/PDF) trouvé (hors photo).")

    # Convertir chaque image en un petit PDF temporaire
    temp_pdfs = []
    for p in usable:
        if is_image_file(p):
            tmp_pdf = os.path.join('/mnt/data', f'_imgpage_{os.path.basename(p)}.pdf')
            image_to_uniform_pdf_page(p, tmp_pdf, target_w_mm=180, target_h_mm=120)
            temp_pdfs.append(tmp_pdf)
        elif is_pdf_file(p):
            # Vérifie lisibilité basique
            try:
                _ = PdfReader(p)  # s'assure que c'est un PDF lisible
                temp_pdfs.append(p)
            except Exception:
                # on ignore si non lisible
                pass

    if not temp_pdfs:
        raise FileNotFoundError("Impossible de préparer les documents (PDF/images).")

    # Fusion avec PyPDF2
    merger = PdfMerger()
    for pdf_path in temp_pdfs:
        try:
            merger.append(pdf_path)
        except Exception:
            # on ignore les PDFs problématiques
            continue

    merger.write(out_pdf_path)
    merger.close()

    # Nettoyage des PDFs temporaires image
    for p in temp_pdfs:
        if p.startswith('/mnt/data/_imgpage_'):
            try:
                os.remove(p)
            except:
                pass

# --- 2) DOCX "planche photos d'identité" via modèle .docx si dispo ---
def build_photos_docx_from_template(template_path, photo_path, out_docx_path):
    if not os.path.exists(template_path):
        raise FileNotFoundError("Modèle d'étiquettes introuvable (.docx).")

    doc = Document(template_path)

    PHOTO_W_MM, PHOTO_H_MM = 35, 45  # standard photo d'identité

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                text = (cell.text or "").strip()
                if text.lower() == "photo ici".lower() or text == "":
                    # purge contenu
                    for p in cell.paragraphs:
                        for run in list(p.runs):
                            run.clear()
                        p.text = ""
                    # insère image centrée
                    p = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    r = p.add_run()
                    r.add_picture(photo_path, width=Mm(PHOTO_W_MM), height=Mm(PHOTO_H_MM))
                    set_cell_border(cell, color="000000", size='8')

    for table in doc.tables:
        table.alignment = WD_TABLE_ALIGNMENT.CENTER

    doc.save(out_docx_path)

def build_photos_docx_fallback(photo_path, out_docx_path):
    ROWS, COLS = 4, 3
    PHOTO_W_MM, PHOTO_H_MM = 35, 45
    CELL_W_MM, CELL_H_MM = 45, 55  # un peu plus grand pour le cadre

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Mm(10)
    section.bottom_margin = Mm(10)
    section.left_margin = Mm(10)
    section.right_margin = Mm(10)

    table = doc.add_table(rows=ROWS, cols=COLS)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for r in range(ROWS):
        row = table.rows[r]
        for c in range(COLS):
            cell = row.cells[c]
            for p in cell.paragraphs:
                for run in list(p.runs):
                    run.clear()
                p.text = ""
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run()
            run.add_picture(photo_path, width=Mm(PHOTO_W_MM), height=Mm(PHOTO_H_MM))
            row.height = Mm(CELL_H_MM)
            cell.width = Mm(CELL_W_MM)
            set_cell_border(cell, color="000000", size='8')

    doc.save(out_docx_path)

# --- Routes exports ---

@app.route('/idpack/<prenom>/<nom>')
def idpack(prenom, nom):
    # PDF "tous les docs sauf la photo"
    prenom_n = _norm(unquote(prenom))
    nom_n = _norm(unquote(nom))

    if not os.path.exists(DATA_FILE):
        return "Données manquantes"
    with open(DATA_FILE) as f:
        data = json.load(f)

    personne = next((d for d in data if _norm(d.get('nom')) == nom_n and _norm(d.get('prenom')) == prenom_n), None)
    if not personne:
        return "Stagiaire non trouvé"

    person_folder = os.path.join(app.config['UPLOAD_FOLDER'], personne['folder'])
    out_path = f"/mnt/data/IDs_{clean_text(personne['prenom'])}_{clean_text(personne['nom'])}.pdf"
    try:
        build_all_docs_pdf(person_folder, out_path)
    except FileNotFoundError as e:
        return str(e)
    except Exception as e:
        return f"Erreur génération PDF: {e}"
    return send_file(out_path, as_attachment=True)

@app.route('/photosheet/<prenom>/<nom>')
def photosheet(prenom, nom):
    prenom_n = _norm(unquote(prenom))
    nom_n = _norm(unquote(nom))

    if not os.path.exists(DATA_FILE):
        return "Données manquantes"
    with open(DATA_FILE) as f:
        data = json.load(f)

    personne = next((d for d in data if _norm(d.get('nom')) == nom_n and _norm(d.get('prenom')) == prenom_n), None)
    if not personne:
        return "Stagiaire non trouvé"

    person_folder = os.path.join(app.config['UPLOAD_FOLDER'], personne['folder'])

    # Récupère la première photo d'identité image
    photos = [os.path.join(person_folder, f) for f in os.listdir(person_folder)
              if f.startswith("photo_identite") and os.path.splitext(f.lower())[1] in IMG_EXTS]
    if not photos:
        return "Aucune photo d'identité trouvée pour ce dossier."

    photo_path = photos[0]

    # Normalise la photo (RGB)
    with Image.open(photo_path) as im:
        im = ensure_rgb(im)
        tmp_photo = f"/mnt/data/_tmp_photo_{os.path.basename(photo_path)}.jpg"
        im.save(tmp_photo, format='JPEG', quality=92)

    out_path = f"/mnt/data/PHOTOS_{clean_text(personne['prenom'])}_{clean_text(personne['nom'])}.docx"
    template_path = "/mnt/data/templates/photo_stagiaire.docx"
    try:
        if os.path.exists(template_path):
            build_photos_docx_from_template(template_path, tmp_photo, out_path)
        else:
            build_photos_docx_fallback(tmp_photo, out_path)
    finally:
        try:
            os.remove(tmp_photo)
        except:
            pass

    return send_file(out_path, as_attachment=True)
