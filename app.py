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

# === LIBS ===
from PIL import Image, ImageOps
from io import BytesIO
from docx import Document
from docx.shared import Mm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from PyPDF2 import PdfMerger, PdfReader

# =====================
#       CONSTANTES
# =====================
UPLOAD_FOLDER = '/mnt/data/uploads'
DATA_FILE = '/mnt/data/data.json'
ADMIN_USER = 'admin'
ADMIN_PASS = 'integrale2025'

# Optimisations rendu/recadrage
RENDER_DPI = 150
JPEG_QUALITY = 85
PDF_PAGE_LIMIT = 80

# Flask avec config statics explicite
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Création des dossiers nécessaires
os.makedirs("/mnt/data", exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs("static", exist_ok=True)  # au cas où

# =====================
#        HELPERS
# =====================
def clean_text(text):
    if not isinstance(text, str):
        text = str(text)
    return unicodedata.normalize('NFKD', text).encode('latin-1', 'ignore').decode('latin-1')

def save_data(entry):
    data = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
        except Exception as e:
            print(f"[data] lecture KO: {e}")
            data = []
    data.append(entry)
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def _norm(s):
    if not isinstance(s, str):
        s = str(s)
    return unicodedata.normalize('NFKC', s).strip().lower()

IMG_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp'}
PDF_EXTS = {'.pdf'}

def is_image_file(path):
    return os.path.splitext(path.lower())[1] in IMG_EXTS

def is_pdf_file(path):
    return os.path.splitext(path.lower())[1] in PDF_EXTS

def is_pdf_like(path: str) -> bool:
    try:
        with open(path, 'rb') as f:
            return f.read(5) == b'%PDF-'
    except Exception:
        return False

def is_image_like(path: str) -> bool:
    try:
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        return False

def list_all_user_files(folder):
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, f) for f in sorted(os.listdir(folder))]

def ensure_rgb(img):
    if img.mode in ('RGBA', 'LA'):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert('RGB') if img.mode != 'RGB' else img

def set_cell_border(cell, color="000000", size='8'):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for edge in ('top', 'left', 'bottom', 'right'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), size)
        el.set(qn('w:color'), color)
        tcPr.append(el)

# --- Gabarits d'impression (mm) ---
CARD_BOX_MM = (180, 120)
DOC_BOX_MM  = (140, 200)

CARD_HINTS = (
    "carte_vitale", "identity_file", "cni", "recto", "verso",
    "permis_conduire", "permis", "passeport", "passport", "carte"
)

def decide_orientation_and_box(filename: str):
    name = filename.lower()
    if any(h in name for h in CARD_HINTS):
        return "landscape", CARD_BOX_MM
    return "portrait", DOC_BOX_MM

# ---------- Conversion PDF -> images ----------
def pdf_iter_pages_to_jpegs(pdf_path: str, dpi: int = RENDER_DPI):
    out_paths = []
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(pdf_path)
        scale = dpi / 72.0
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=scale)
            pil = bitmap.to_pil()
            pil = ensure_rgb(pil)
            out = f"/mnt/data/_pdfpg_{os.path.basename(pdf_path)}_{i+1}.jpg"
            pil.save(out, 'JPEG', quality=JPEG_QUALITY, optimize=True)
            out_paths.append(out)
        if out_paths:
            return out_paths
    except Exception as e:
        print(f"[pdfpages] pypdfium2 KO: {e}")

    try:
        import fitz
        doc = fitz.open(pdf_path)
        for i in range(doc.page_count):
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=dpi)
            out = f"/mnt/data/_pdfpg_{os.path.basename(pdf_path)}_{i+1}.jpg"
            pix.save(out)
            out_paths.append(out)
        doc.close()
        if out_paths:
            return out_paths
    except Exception as e:
        print(f"[pdfpages] PyMuPDF KO: {e}")

    try:
        with Image.open(pdf_path) as im:
            i = 0
            while True:
                im.load()
                frame = ensure_rgb(im.copy())
                out = f"/mnt/data/_pdfpg_{os.path.basename(pdf_path)}_{i+1}.jpg"
                frame.save(out, 'JPEG', quality=JPEG_QUALITY, optimize=True)
                out_paths.append(out)
                i += 1
                im.seek(im.tell() + 1)
    except EOFError:
        pass
    except Exception as e:
        print(f"[pdfpages] Pillow KO: {e}")

    if not out_paths:
        raise RuntimeError("Impossible de rasteriser le PDF.")

    return out_paths

# =====================
#        ROUTES
# =====================
@app.route('/healthz')
def healthz():
    return "ok", 200

@app.route('/')
def index():
    try:
        return render_template('index.html')
    except Exception as e:
        return f"OK (index.html manquant ?) : {e}", 200

@app.route('/submit', methods=['POST'])
def submit():
    form, files = request.form, request.files
    nom, prenom, email = form['nom'].strip(), form['prenom'].strip(), form['email']
    full_name = f"{nom}_{prenom}".replace(" ", "_")
    person_folder = os.path.join(app.config['UPLOAD_FOLDER'], full_name)
    os.makedirs(person_folder, exist_ok=True)

    for field in ['photo_identite', 'carte_vitale', 'identity_file_1', 'identity_file_2']:
        f = files.get(field)
        if f and f.filename:
            f.save(os.path.join(person_folder, secure_filename(f"{field}_{f.filename}")))

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
        if request.form.get('user') == ADMIN_USER and request.form.get('pass') == ADMIN_PASS:
            session['admin'] = True
            return redirect('/admin')
        else:
            return "Accès refusé", 403
    if not session.get('admin'):
        return '''
        <form method="post">
            <input name="user" placeholder="Utilisateur"><br>
            <input name="pass" placeholder="Mot de passe" type="password"><br>
            <button type="submit">Connexion</button>
        </form>
        '''
    if not os.path.exists(DATA_FILE):
        return render_template('admin.html', data=[])
    with open(DATA_FILE) as f:
        data = json.load(f)
    return render_template('admin.html', data=data)

@app.route('/download/<folder>')
def download(folder):
    folder_path = os.path.join(app.config['UPLOAD_FOLDER'], folder)
    if not os.path.isdir(folder_path):
        return "Dossier introuvable", 404
    zip_path = f"/mnt/data/{folder}.zip"
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, _, files in os.walk(folder_path):
            for file in files:
                full_path = os.path.join(root, file)
                arc = os.path.relpath(full_path, folder_path)
                zipf.write(full_path, arcname=arc)
    if not os.path.exists(zip_path) or os.path.getsize(zip_path) == 0:
        return "Archive vide", 500
    return send_file(zip_path, as_attachment=True)

@app.route('/fiche/<prenom>/<nom>')
def fiche(prenom, nom):
    prenom = _norm(unquote(prenom))
    nom = _norm(unquote(nom))
    if not os.path.exists(DATA_FILE):
        return "Données manquantes", 404
    with open(DATA_FILE) as f:
        data = json.load(f)
    personne = next((d for d in data if _norm(d.get('nom')) == nom and _norm(d.get('prenom')) == prenom), None)
    if not personne:
        return "Stagiaire non trouvé", 404
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        for k, v in personne.items():
            if k != "folder":
                pdf.cell(200, 8, txt=clean_text(f"{k.upper()}: {v}"), ln=True)
        path = f"/mnt/data/fiche_{clean_text(personne['prenom'])}_{clean_text(personne['nom'])}.pdf"
        pdf.output(path)
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return "Erreur: PDF vide", 500
        return send_file(path, as_attachment=True)
    except Exception as e:
        print(f"[fiche] erreur: {e}")
        return f"Erreur fiche: {e}", 500

def send_confirmation_email(data):
    try:
        user = os.environ.get("MAIL_USER")
        pwd  = os.environ.get("MAIL_PASS")
        if not user or not pwd:
            print("[mail] MAIL_USER/MAIL_PASS absents → email non envoyé")
            return
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
        msg['From'] = user
        msg['To'] = data['email']
        msg.attach(MIMEText(html, 'html'))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(user, pwd)
            server.sendmail(msg['From'], [msg['To']], msg.as_string())
    except Exception as e:
        print(f"[mail] échec envoi: {e}")

# ----------- UPDATE -----------
@app.route('/update/<prenom>/<nom>', methods=['POST'])
def update(prenom, nom):
    if not session.get('admin'):
        return redirect('/admin')
    prenom_n = _norm(unquote(prenom))
    nom_n = _norm(unquote(nom))
    folder = request.form.get('folder', '')
    if not os.path.exists(DATA_FILE):
        return "Données introuvables", 404
    with open(DATA_FILE, 'r') as f:
        data = json.load(f)
    for d in data:
        same_folder = (folder and d.get('folder') == folder)
        same_name = (_norm(d.get('prenom', '')) == prenom_n and _norm(d.get('nom', '')) == nom_n)
        if same_folder or same_name:
            new_status = request.form.get('status', d.get('status'))
            if new_status in ["INCOMPLET", "COMPLET", "VALIDE", "NON_VALIDE"]:
                d['status'] = new_status
            d['commentaire'] = request.form.get('commentaire', d.get('commentaire', ''))
            break
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    return redirect('/admin')

# ----------- DELETE -----------
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
        else:
            new_data.append(d)
    with open(DATA_FILE, 'w') as f:
        json.dump(new_data, f, indent=2)
    return redirect('/admin')
