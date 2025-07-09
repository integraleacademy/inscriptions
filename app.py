from flask import Flask, render_template, request, redirect, send_file, url_for
import os
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
DATA_FILE = 'data.json'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    data = {
        'nom': request.form['nom'],
        'prenom': request.form['prenom'],
        'email': request.form['email'],
        'secu': request.form['secu'],
        'naissance': request.form['naissance'],
        'ville_naissance': request.form['ville_naissance'],
        'pays_naissance': request.form['pays_naissance'],
        'nationalite': request.form['nationalite'],
        'sexe': request.form['sexe'],
        'adresse': request.form['adresse'],
        'cp': request.form['cp'],
        'ville': request.form['ville'],
        'cnaps': request.form['cnaps'],
        'statut': 'INCOMPLET',
        'commentaire': ''
    }

    files = ['photo_identite', 'carte_vitale', 'piece_identite']
    all_filenames = []
    for field in files:
        uploaded_files = request.files.getlist(field)
        filenames = []
        for f in uploaded_files:
            if f.filename:
                filepath = os.path.join(UPLOAD_FOLDER, f.filename)
                f.save(filepath)
                filenames.append(f.filename)
                all_filenames.append(f.filename)
        data[field] = filenames

    data['files'] = all_filenames

    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            try:
                all_data = json.load(f)
            except:
                all_data = []
    else:
        all_data = []

    all_data.append(data)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    send_confirmation_email(data)
    return redirect('/')

@app.route('/admin')
def admin():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except:
                data = []
    else:
        data = []
    return render_template('admin.html', data=data)

@app.route('/delete/<nom>/<prenom>', methods=['POST'])
def delete(nom, prenom):
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except:
                data = []
    else:
        data = []

    data = [d for d in data if not (d['nom'] == nom and d['prenom'] == prenom)]

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return redirect('/admin')

def send_confirmation_email(data):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = "Confirmation d’inscription – Intégrale Academy"
    msg['From'] = os.environ.get("MAIL_USER")
    msg['To'] = data['email']

    text = f"""Bonjour {data['prenom']},

Votre inscription a bien été prise e
