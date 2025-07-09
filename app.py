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
        'cnaps': request.form['cnaps']
    }

    files = ['photo_identite', 'carte_vitale', 'piece_identite']
    for field in files:
        uploaded_files = request.files.getlist(field)
        filenames = []
        for f in uploaded_files:
            if f.filename:
                filepath = os.path.join(UPLOAD_FOLDER, f.filename)
                f.save(filepath)
                filenames.append(f.filename)
        data[field] = filenames

    # Sauvegarde JSON
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

def send_confirmation_email(data):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = "Confirmation d’inscription – Intégrale Academy"
    msg['From'] = os.environ.get("MAIL_USER")
    msg['To'] = data['email']

    text = f"""Bonjour {data['prenom']},

Votre inscription a bien été prise en compte.

L’équipe Intégrale Academy"""

    html = f"""<html>
  <body style='font-family: Arial, sans-serif; color: #333;'>
    <div style='max-width: 600px; margin: auto; border: 1px solid #ccc; padding: 20px; border-radius: 10px;'>
      <div style='text-align: center;'>
        <img src='https://integraleacademy.com/wp-content/uploads/2023/11/cropped-integrale-academy-blanc.png' style='max-height: 80px;' />
      </div>
      <p>Bonjour <strong>{data['prenom']}</strong>,</p>
      <p>Votre inscription a bien été prise en compte.</p>
      <p style='margin-top: 30px;'>Merci pour votre confiance,<br>L’équipe <strong>Intégrale Academy</strong></p>
    </div>
  </body>
</html>"""

    msg.attach(MIMEText(text, 'plain'))
    msg.attach(MIMEText(html, 'html'))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.environ.get("MAIL_USER"), os.environ.get("MAIL_PASS"))
        server.sendmail(msg['From'], [msg['To']], msg.as_string())

if __name__ == '__main__':
    app.run(debug=True)
