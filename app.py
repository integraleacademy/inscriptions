
from flask import Flask, render_template, request, redirect, send_file, session, url_for
import os, json, zipfile
from werkzeug.utils import secure_filename
from fpdf import FPDF
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

UPLOAD_FOLDER = '/mnt/data/uploads'
DATA_FILE = '/mnt/data/data.json'
ADMIN_USER = 'admin'
ADMIN_PASS = 'integrale2025'

app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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

    nom = form['nom']
    prenom = form['prenom']
    email = form['email']
    full_name = f"{nom}_{prenom}".replace(" ", "_")
    person_folder = os.path.join(app.config['UPLOAD_FOLDER'], full_name)
    os.makedirs(person_folder, exist_ok=True)

    doc_fields = ['photo_identite', 'carte_vitale', 'piece_identite']
    saved_files = []

    for field in doc_fields:
        uploaded = files.getlist(field)
        for f in uploaded:
            if f and f.filename:
                filename = secure_filename(f.filename)
                path = os.path.join(person_folder, filename)
                f.save(path)
                saved_files.append(path)

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
    return "Merci, votre dossier a bien été transmis."

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
    if not os.path.exists(DATA_FILE):
        return "Données manquantes"
    with open(DATA_FILE) as f:
        data = json.load(f)
    personne = next((d for d in data if d['nom'] == nom and d['prenom'] == prenom), None)
    if not personne:
        return "Stagiaire non trouvé"

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for k, v in personne.items():
        if k not in ["folder"]:
            pdf.cell(200, 10, txt=f"{k.upper()}: {v}", ln=True)
    path = f"/mnt/data/fiche_{prenom}_{nom}.pdf"
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
import json


@app.route("/toggle_status/<prenom>/<nom>", methods=["POST"])
def toggle_status(prenom, nom):
    with open("data.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    for d in data:
        if d["prenom"] == prenom and d["nom"] == nom:
            if d.get("status") == "COMPLET":
                d["status"] = "INCOMPLET"
            else:
                d["status"] = "COMPLET"
            break

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return redirect("/admin")
