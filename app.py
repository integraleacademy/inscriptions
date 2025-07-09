from flask import Flask, render_template, request, redirect, send_file, url_for
import os
import json
from datetime import datetime
from werkzeug.utils import secure_filename
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import uuid

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
DATA_FILE = 'data.json'

# Chargement des données persistantes
def load_data():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    nom = request.form['nom'].strip().upper()
    prenom = request.form['prenom'].strip().capitalize()
    email = request.form['email'].strip()

    files = request.files.getlist('pieces_identite')
    domicile = request.files.get('justificatif_domicile')
    hebergement = request.files.getlist('hebergement')

    dossier_id = str(uuid.uuid4())
    saved_files = []

    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], dossier_id), exist_ok=True)

    # Enregistrer et renommer les fichiers
    def save_and_rename(file, prefix):
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1]
            filename = f"{prefix}_{nom}_{prenom}{ext}"
            path = os.path.join(app.config['UPLOAD_FOLDER'], dossier_id, secure_filename(filename))
            file.save(path)
            return f"{dossier_id}/{secure_filename(filename)}"
        return None

    for i, f in enumerate(files):
        path = save_and_rename(f, f"CI{i+1}")
        if path:
            saved_files.append(path)

    dom_path = save_and_rename(domicile, "JUSTIFICATIF")
    if dom_path:
        saved_files.append(dom_path)

    for i, f in enumerate(hebergement):
        path = save_and_rename(f, f"HEBERGEMENT{i+1}")
        if path:
            saved_files.append(path)

    data = load_data()
    entry = {
        'nom': nom,
        'prenom': prenom,
        'email': email,
        'files': saved_files,
        'statut': 'COMPLET',
        'commentaire': '',
        'timestamp': datetime.now().isoformat()
    }
    data.append(entry)
    save_data(data)

    send_confirmation_email(entry)

    return render_template('index.html', confirmation=True)

@app.route('/admin')
def admin():
    data = load_data()
    return render_template('admin.html', data=data)

@app.route('/delete/<nom>/<prenom>', methods=['POST'])
def delete(nom, prenom):
    data = load_data()
    data = [d for d in data if not (d['nom'] == nom and d['prenom'] == prenom)]
    save_data(data)
    return redirect(url_for('admin'))

@app.route('/save/<nom>/<prenom>', methods=['POST'])
def save(nom, prenom):
    data = load_data()
    for d in data:
        if d['nom'] == nom and d['prenom'] == prenom:
            d['statut'] = request.form['statut']
            d['commentaire'] = request.form['commentaire']
    save_data(data)
    return redirect(url_for('admin'))

@app.route('/download/<path:filename>')
def download(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename), as_attachment=True)

def send_confirmation_email(data):
    sender_email = os.environ.get('EMAIL_ADDRESS')
    sender_password = os.environ.get('EMAIL_PASSWORD')

    receiver_email = data['email']
    subject = "Confirmation de dépôt de dossier - Intégrale Academy"

    html_email_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="text-align: center;">
                <img src="https://inscriptions-akou.onrender.com/static/logo.png" alt="Logo Intégrale Academy" style="width: 150px; margin-bottom: 20px;" />
                <h2>Bonjour {data['prenom']},</h2>
                <p>Nous avons bien reçu votre dossier. Il sera traité dans les plus brefs délais.</p>
                <p>Merci pour votre confiance.</p>
                <p>L'équipe Intégrale Academy</p>
            </div>
        </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = receiver_email

    html_part = MIMEText(html_email_content, "html")
    msg.attach(html_part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
    except Exception as e:
        print("Erreur lors de l'envoi de l'email :", e)

if __name__ == '__main__':
    app.run(debug=True)
