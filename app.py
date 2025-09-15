from flask import Flask, render_template, request, redirect, send_file, session, url_for
import os, json, unicodedata
from werkzeug.utils import secure_filename
from docx import Document
from docx.shared import Mm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from urllib.parse import unquote   # ✅ import ajouté

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

# === EDIT PHOTO ===
@app.route('/editphoto/<prenom>/<nom>', methods=['GET'])
def editphoto(prenom, nom):
    prenom, nom = _norm(unquote(prenom)), _norm(unquote(nom))
    if not os.path.exists(DATA_FILE):
        return "Données manquantes", 404
    with open(DATA_FILE) as f:
        data = json.load(f)
    pers = next((d for d in data if _norm(d.get('nom')) == nom and _norm(d.get('prenom')) == prenom), None)
    if not pers:
        return "Stagiaire non trouvé", 404
    folder = os.path.join(app.config['UPLOAD_FOLDER'], pers['folder'])
    photo_file = None
    for f in os.listdir(folder):
        if f.lower().startswith("photo_identite"):
            photo_file = f
            break
    if not photo_file:
        return "Pas de photo trouvée", 404
    return render_template("editphoto.html", prenom=pers['prenom'], nom=pers['nom'], folder=pers['folder'], photo=photo_file)

@app.route('/editphoto/<prenom>/<nom>', methods=['POST'])
def save_editphoto(prenom, nom):
    prenom, nom = _norm(unquote(prenom)), _norm(unquote(nom))
    if not os.path.exists(DATA_FILE):
        return "Données manquantes", 404
    with open(DATA_FILE) as f:
        data = json.load(f)
    pers = next((d for d in data if _norm(d.get('nom')) == nom and _norm(d.get('prenom')) == prenom), None)
    if not pers:
        return "Stagiaire non trouvé", 404
    folder = os.path.join(app.config['UPLOAD_FOLDER'], pers['folder'])
    os.makedirs(folder, exist_ok=True)
    f = request.files['croppedImage']
    save_path = os.path.join(folder, "photo_identite_recadree.jpg")
    f.save(save_path)
    return "ok"

# === PHOTOSHEET DOCX ===
@app.route('/photosheet/<prenom>/<nom>')
def photosheet(prenom, nom):
    prenom, nom = _norm(unquote(prenom)), _norm(unquote(nom))
    if not os.path.exists(DATA_FILE):
        return "Données manquantes", 404
    with open(DATA_FILE) as f:
        data = json.load(f)
    pers = next((d for d in data if _norm(d['nom']) == nom and _norm(d['prenom']) == prenom), None)
    if not pers:
        return "Stagiaire non trouvé", 404
    folder = os.path.join(app.config['UPLOAD_FOLDER'], pers['folder'])
    recadree = os.path.join(folder, "photo_identite_recadree.jpg")
    if os.path.exists(recadree):
        photo_path = recadree
    else:
        photo_path = None
        for f in os.listdir(folder):
            if f.lower().startswith("photo_identite"):
                photo_path = os.path.join(folder, f)
                break
        if not photo_path:
            return "Aucune photo trouvée", 404
    out = f"/mnt/data/PHOTOS_{clean_text(pers['prenom'])}_{clean_text(pers['nom'])}.docx"
    doc = Document()
    table = doc.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.add_run().add_picture(photo_path, width=Mm(35), height=Mm(45))
    p2 = cell.add_paragraph()
    p2.add_run(f"{pers['nom']} {pers['prenom']}")
    set_cell_border(cell, color="000000", size='8')
    doc.save(out)
    return send_file(out, as_attachment=True)

# === IDPACK PDF (corrigé) ===
@app.route('/idpack/<prenom>/<nom>')
def idpack(prenom, nom):
    prenom, nom = _norm(unquote(prenom)), _norm(unquote(nom))
    if not os.path.exists(DATA_FILE):
        return "Données manquantes", 404
    with open(DATA_FILE) as f:
        data = json.load(f)
    pers = next((d for d in data if _norm(d['nom']) == nom and _norm(d['prenom']) == prenom), None)
    if not pers:
        return "Stagiaire non trouvé", 404
    # 👉 ici tu mets ton code qui génère l’ID PDF comme avant
    return f"TODO: génération ID PDF pour {pers['prenom']} {pers['nom']}"
