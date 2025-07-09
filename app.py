from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
import os
import json
from datetime import datetime

app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
DATA_FILE = 'data.json'

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Chargement ou création des données
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'r') as f:
        data = json.load(f)
else:
    data = []

# Accueil
@app.route('/')
def index():
    return render_template('index.html')

# Soumission du formulaire
@app.route('/submit', methods=['POST'])
def submit():
    nom = request.form.get('nom')
    prenom = request.form.get('prenom')
    email = request.form.get('email')

    fichiers = {}
    for champ in ['identite', 'domicile', 'hebergeant']:
        fichiers[champ] = []
        if champ in request.files:
            for file in request.files.getlist(champ):
                if file.filename:
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
                    file.save(filepath)
                    fichiers[champ].append(file.filename)

    ligne = {
        "nom": nom,
        "prenom": prenom,
        "email": email,
        "fichiers": fichiers,
        "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "statut": "Non traité",
        "commentaire": ""
    }

    data.append(ligne)
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

    return render_template("merci.html")

# Admin
@app.route('/admin')
def admin():
    return render_template('admin.html', dossiers=data)

# Suppression
@app.route('/delete/<int:index>', methods=['POST'])
def delete(index):
    if 0 <= index < len(data):
        del data[index]
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    return redirect(url_for('admin'))

# Téléchargement
@app.route('/static/uploads/<filename>')
def download(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Mise à jour statut/commentaire
@app.route('/update/<int:index>', methods=['POST'])
def update(index):
    if 0 <= index < len(data):
        data[index]['statut'] = request.form.get('statut', data[index]['statut'])
        data[index]['commentaire'] = request.form.get('commentaire', data[index]['commentaire'])
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(debug=True)
