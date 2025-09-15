from flask import Flask, render_template, request, redirect, send_file, session, url_for, send_from_directory
import os, json, unicodedata
from werkzeug.utils import secure_filename
from docx import Document
from docx.shared import Mm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from urllib.parse import unquote
import smtplib
from email.mime.text import MIMEText

UPLOAD_FOLDER = '/mnt/data/uploads'
DATA_FILE = '/mnt/data/data.json'
ADMIN_USER = 'admin'
ADMIN_PASS = 'integrale2025'

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

os.makedirs("/mnt/data", exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs("static", exist_ok=True)

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
        except:
            data = []
    data.append(entry)
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE) as f:
        return json.load(f)

def write_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def _norm(s):
    if not isinstance(s, str):
        s = str(s)
    return unicodedata.normalize('NFKC', s).strip().lower()

def set_cell_border(cell, color="000000", size='8'):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for edge in ('top', 'left', 'bottom', 'right'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), size)
        el.set(qn('w:color'), color)
        tcPr.append(el)

# ========= ROUTE POUR SERVIR LES UPLOADS =========
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/healthz')
def healthz():
    return "ok", 200

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

    for field in ['photo_identite', 'carte_vitale', 'identity_file_1', 'identity_file_2']:
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
    return render_template('submit.html')

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST' and not session.get('admin'):
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
    data = load_data()
    return render_template('admin.html', data=data)

@app.route('/update/<prenom>/<nom>', methods=['POST'])
def update(prenom, nom):
    data = load_data()
    pers = next((d for d in data if _norm(d['nom']) == _norm(nom) and _norm(d['prenom']) == _norm(prenom)), None)
    if not pers:
        return "Stagiaire non trouvé", 404
    pers['status'] = request.form.get('status', pers['status'])
    pers['commentaire'] = request.form.get('commentaire', pers['commentaire'])
    write_data(data)

    # === Si NON VALIDE → envoi mail au stagiaire ===
    if pers['status'] == "NON VALIDE":
        send_nonvalide_mail(pers)

    return redirect('/admin')

def send_nonvalide_mail(pers):
    sender = os.environ.get("MAIL_USER")
    password = os.environ.get("MAIL_PASS")
    if not sender or not password:
        print("⚠️ MAIL_USER ou MAIL_PASS non configuré")
        return

    msg = MIMEText(f"""
Bonjour {pers['prenom']} {pers['nom']},

Après analyse de votre dossier, vos documents sont NON CONFORMES.

Merci de renvoyer vos documents via le lien suivant :
https://inscriptions-akou.onrender.com/

Commentaire de l'administrateur :
{pers.get('commentaire','(aucun)')}

Cordialement,
Intégrale Academy
    """, "plain", "utf-8")

    msg["Subject"] = "Intégrale Academy – Dossier NON VALIDE"
    msg["From"] = sender
    msg["To"] = pers['email']

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.send_message(msg)
        print(f"📩 Mail envoyé à {pers['email']}")
    except Exception as e:
        print("❌ Erreur envoi mail :", e)
