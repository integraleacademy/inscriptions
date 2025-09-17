from flask import Flask, render_template, request, redirect, send_file, session, url_for, flash
import os, json, zipfile
from werkzeug.utils import secure_filename
from fpdf import FPDF
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import unicodedata

UPLOAD_FOLDER = '/mnt/data/uploads'
DATA_FILE = '/mnt/data/data.json'
MAIL_LOG = '/mnt/data/mails_envoyes.json'
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

def log_mail(entry):
    """Sauvegarde une trace du mail envoyé"""
    if os.path.exists(MAIL_LOG):
        with open(MAIL_LOG, 'r') as f:
            mails = json.load(f)
    else:
        mails = []
    mails.append(entry)
    with open(MAIL_LOG, 'w') as f:
        json.dump(mails, f, indent=2)

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
        if k != "folder":
            ligne = clean_text(f"{k.upper()}: {v}")
            pdf.cell(200, 10, txt=ligne, ln=True)

    path = f"/mnt/data/fiche_{prenom}_{nom}.pdf"
    pdf.output(path)
    return send_file(path, as_attachment=True)

def send_confirmation_email(data):
    try:
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

        log_mail({
            "prenom": data['prenom'],
            "nom": data['nom'],
            "to": data['email'],
            "subject": msg['Subject'],
            "content": html,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    except Exception as e:
        print(f"❌ Erreur envoi mail confirmation: {str(e)}")

def send_non_conforme_email(data):
    try:
        html_email_content = f"""
        <html>
          <body style="font-family: Arial, sans-serif; color:#333;">
            <div style="border:2px solid #e74c3c; padding:15px; border-radius:10px;">
              <h2 style="color:#e74c3c;">❌ Documents non conformes</h2>
              <p>Bonjour {data['prenom']},</p>
              <p>Après vérification, les documents que vous avez transmis sont <b style="color:#e74c3c;">non conformes</b>.</p>
              <p><b>📝 Commentaire :</b> {data.get('commentaire', 'Aucun')}</p>
              <p>👉 Nous vous remercions de bien vouloir déposer vos documents conformes en cliquant sur le lien ci-dessous :</p>
              <p><a href="https://inscriptions-akou.onrender.com/" style="background:#27ae60;color:white;padding:10px 15px;border-radius:5px;text-decoration:none;">🔗 Refaire ma demande</a></p>
              
              <br>
              <p>📩 L’équipe <b>Intégrale Academy</b> reste à votre disposition.</p>
            </div>
          </body>
        </html>
        """
        msg = MIMEMultipart('alternative')
        msg['Subject'] = "❌ Documents non conformes – Intégrale Academy"
        msg['From'] = os.environ.get("MAIL_USER")
        msg['To'] = data['email']
        msg.attach(MIMEText(html_email_content, 'html'))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(os.environ.get("MAIL_USER"), os.environ.get("MAIL_PASS"))
            server.sendmail(msg['From'], [msg['To']], msg.as_string())

        log_mail({
            "prenom": data['prenom'],
            "nom": data['nom'],
            "to": data['email'],
            "subject": msg['Subject'],
            "content": html_email_content,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    except Exception as e:
        print(f"❌ Erreur envoi mail NON CONFORME: {str(e)}")

@app.route('/update/<prenom>/<nom>', methods=['POST'])
def update(prenom, nom):
    if not session.get('admin'):
        return redirect('/admin')

    if not os.path.exists(DATA_FILE):
        return "Données introuvables"

    with open(DATA_FILE, 'r') as f:
        data = json.load(f)

    status_value = request.form.get('status') or request.form.get('status_select')
    commentaire_value = request.form.get('commentaire')

    for d in data:
        if d['prenom'] == prenom and d['nom'] == nom:
            d['status'] = status_value
            d['commentaire'] = commentaire_value

            if status_value == "NON CONFORME":
                send_non_conforme_email(d)
                flash(f"📧 Demande de mise en conformité envoyée à {d['email']}", "success")

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

@app.route('/mail/<prenom>/<nom>')
def voir_mail(prenom, nom):
    if not os.path.exists(MAIL_LOG):
        return "Aucun mail envoyé"

    with open(MAIL_LOG, 'r') as f:
        mails = json.load(f)

    mails_personne = [m for m in mails if m['prenom'] == prenom and m['nom'] == nom]
    if not mails_personne:
        return f"Aucun mail trouvé pour {prenom} {nom}"

    dernier_mail = mails_personne[-1]
    return f"""
    <h2>Mail envoyé à {dernier_mail['to']}</h2>
    <p><b>Date :</b> {dernier_mail['date']}</p>
    <p><b>Sujet :</b> {dernier_mail['subject']}</p>
    <hr>
    {dernier_mail['content']}
    """
