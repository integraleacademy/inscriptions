from flask import Flask, render_template, request, redirect, send_file, session, url_for
import os, json, zipfile
from werkzeug.utils import secure_filename
from fpdf import FPDF
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
from PyPDF2 import PdfMerger

# =====================
#       CONSTANTES
# =====================
UPLOAD_FOLDER = '/mnt/data/uploads'
DATA_FILE = '/mnt/data/data.json'
ADMIN_USER = 'admin'
ADMIN_PASS = 'integrale2025'

RENDER_DPI = 150
JPEG_QUALITY = 85
PDF_PAGE_LIMIT = 80

# Flask config
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Folders
os.makedirs("/mnt/data", exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs("static", exist_ok=True)

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

# =====================
#       EMAILS
# =====================
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

def send_nonvalide_email(data):
    try:
        user = os.environ.get("MAIL_USER")
        pwd  = os.environ.get("MAIL_PASS")
        if not user or not pwd:
            print("[mail] MAIL_USER/MAIL_PASS absents → email non envoyé")
            return

        commentaire = data.get('commentaire', '').strip()
        if not commentaire:
            commentaire = "Merci de vérifier vos documents et de les renvoyer."

        redrop_link = "https://inscriptions-akou.onrender.com/"  # lien dépôt

        html = f"""
        <html><body>
          <p>Bonjour {data['prenom']} {data['nom']},</p>
          <p>Après vérification, nous vous informons que les documents que vous avez fournis sont <b>non conformes</b>.</p>
          <p>Merci de bien vouloir nous renvoyer vos documents corrigés dans les plus brefs délais.</p>
          <p><b>Commentaires :</b> {commentaire}</p>
          <br>
          <p>➡️ Cliquez sur le lien ci-dessous pour redéposer vos documents :</p>
          <p><a href="{redrop_link}" style="background:#28a745;color:white;padding:10px 15px;text-decoration:none;border-radius:5px;">📤 Déposer mes documents</a></p>
          <br>
          <p>Cordialement,<br>L’équipe Intégrale Academy</p>
        </body></html>
        """

        msg = MIMEMultipart('alternative')
        msg['Subject'] = "⚠️ Dossier non valide – Intégrale Academy"
        msg['From'] = user
        msg['To'] = data['email']
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(user, pwd)
            server.sendmail(msg['From'], [msg['To']], msg.as_string())

        print(f"[mail] Notification NON VALIDE envoyée à {data['email']}")
    except Exception as e:
        print(f"[mail] échec envoi NON VALIDE: {e}")

# =====================
#       UPDATE
# =====================
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

    updated_entry = None

    for d in data:
        same_folder = (folder and d.get('folder') == folder)
        same_name = (_norm(d.get('prenom', '')) == prenom_n and _norm(d.get('nom', '')) == nom_n)
        if same_folder or same_name:
            new_status = request.form.get('status', d.get('status'))
            commentaire = request.form.get('commentaire', d.get('commentaire', ''))
            if new_status in ["INCOMPLET", "COMPLET", "VALIDE", "NON_VALIDE"]:
                d['status'] = new_status
            d['commentaire'] = commentaire
            updated_entry = d
            break

    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

    # ✅ envoi mail si NON VALIDE
    if updated_entry and updated_entry['status'] == "NON_VALIDE":
        send_nonvalide_email(updated_entry)

    return redirect('/admin')

# =====================
#       DELETE
# =====================
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
