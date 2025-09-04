from flask import Flask, render_template, request, redirect, send_file, session, url_for
import os, json, zipfile
from werkzeug.utils import secure_filename
from fpdf import FPDF
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import unicodedata
from urllib.parse import unquote  # <- ajouté
from io import BytesIO

# --- Ajouts images & docx ---
from PIL import Image
from docx import Document
from docx.shared import Mm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

UPLOAD_FOLDER = '/mnt/data/uploads'
DATA_FILE = '/mnt/data/data.json'
ADMIN_USER = 'admin'
ADMIN_PASS = 'integrale2025'

app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ------------------ Utils généraux ------------------

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

def _norm(s):
    if not isinstance(s, str):
        s = str(s)
    # normalise, retire espaces autour, met en minuscules
    return unicodedata.normalize('NFKC', s).strip().lower()

# ------------------ Helpers images / fichiers ------------------

IMG_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp'}

def is_image_file(path):
    _, ext = os.path.splitext(path.lower())
    return ext in IMG_EXTS

def list_person_files(person_folder, prefixes):
    """Retourne la liste des fichiers dans person_folder dont le nom commence par un des prefixes."""
    out = []
    if not os.path.isdir(person_folder):
        return out
    for f in sorted(os.listdir(person_folder)):
        if any(f.startswith(pfx) for pfx in prefixes):
            out.append(os.path.join(person_folder, f))
    return out

def ensure_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ('RGBA', 'LA'):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    if img.mode != 'RGB':
        return img.convert('RGB')
    return img

# ------------------ Génération PDF pièces d'identité ------------------

def build_ids_pdf(person_folder, out_pdf_path):
    """
    Construit un PDF A4 par document (CNI/passeport + carte vitale) où chaque image est
    recadrée/redimensionnée à une taille uniforme (TARGET_W x TARGET_H), centrée.
    """
    candidates = list_person_files(person_folder, ["identity_file_1", "identity_file_2", "carte_vitale"])
    candidates = [p for p in candidates if is_image_file(p)]
    if not candidates:
        raise FileNotFoundError("Aucune image trouvée (CNI/passeport/ca
