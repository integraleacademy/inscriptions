from flask import Flask, render_template, request, redirect, send_file, session, url_for
import os, json, zipfile
from werkzeug.utils import secure_filename
from fpdf import FPDF
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import unicodedata
from urllib.parse import unquote

# === AJOUTS ===
from PIL import Image, ImageOps
from io import BytesIO
from docx import Document
from docx.shared import Mm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from PyPDF2 import PdfMerger, PdfReader

UPLOAD_FOLDER = '/mnt/data/uploads'
DATA_FILE = '/mnt/data/data.json'
ADMIN_USER = 'admin'
ADMIN_PASS = 'integrale2025'

app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ========== HELPERS ==========
def clean_text(text):
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
    return unicodedata.normalize('NFKC', s).strip().lower()

IMG_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp'}
PDF_EXTS = {'.pdf'}

def is_image_file(path): return os.path.splitext(path.lower())[1] in IMG_EXTS
def is_pdf_file(path): return os.path.splitext(path.lower())[1] in PDF_EXTS

def list_all_user_files(folder):
    if not os.path.isdir(folder): return []
    return [os.path.join(folder, f) for f in sorted(os.listdir(folder))]

def ensure_rgb(img):
    if img.mode in ('RGBA','LA'):
        bg = Image.new('RGB', img.size, (255,255,255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert('RGB') if img.mode!='RGB' else img

def set_cell_border(cell, color="000000", size='8'):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for edge in ('top','left','bottom','right'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'),'single')
        el.set(qn('w:sz'), size)
        el.set(qn('w:color'), color)
        tcPr.append(el)

# ========== ROUTES ==========
@app.route('/')
def index(): return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    form, files = request.form, request.files
    nom, prenom, email = form['nom'].strip(), form['prenom'].strip(), form['email']
    full_name = f"{nom}_{prenom}".replace(" ","_")
    person_folder = os.path.join(app.config['UPLOAD_FOLDER'], full_name)
    os.makedirs(person_folder, exist_ok=True)

    # Sauvegarde fichiers principaux
    for field in ['photo_identite','carte_vitale','identity_file_1','identity_file_2']:
        f = files.get(field)
        if f and f.filename:
            f.save(os.path.join(person_folder, secure_filename(f"{field}_{f.filename}")))

    # Sauvegarde A3P si demandé
    if form.get('formation')=='A3P':
        for field in ['assurance_rc','certificat_medical','permis_conduire']:
            f = files.get(field)
            if f and f.filename:
                f.save(os.path.join(person_folder, secure_filename(f"{field}_{f.filename}")))

    entry = {
        "nom":nom,"prenom":prenom,"email":email,
        "secu":form['secu'],"naissance":form['naissance'],
        "ville_naissance":form['ville_naissance'],
        "pays_naissance":form['pays_naissance'],
        "nationalite":form['nationalite'],"sexe":form['sexe'],
        "adresse":form['adresse'],"cp":form['cp'],"ville":form['ville'],
        "cnaps":form['cnaps'],
        "folder":full_name,"status":"INCOMPLET","commentaire":""
    }
    save_data(entry); send_confirmation_email(entry)
    return render_template('submit.html')

@app.route('/admin', methods=['GET','POST'])
def admin():
    if request.method=='POST':
        if request.form['user']==ADMIN_USER and request.form['pass']==ADMIN_PASS:
            session['admin']=True; return redirect('/admin')
        return "Accès refusé"
    if not session.get('admin'):
        return '<form method="post"><input name="user"><br><input name="pass" type="password"><br><button>Connexion</button></form>'
    if not os.path.exists(DATA_FILE): return "Aucune donnée"
    with open(DATA_FILE) as f: data=json.load(f)
    return render_template('admin.html', data=data)

@app.route('/download/<folder>')
def download(folder):
    folder_path=os.path.join(app.config['UPLOAD_FOLDER'], folder)
    zip_path=f"/mnt/data/{folder}.zip"
    with zipfile.ZipFile(zip_path,'w') as z:
        for root,_,files in os.walk(folder_path):
            for f in files: z.write(os.path.join(root,f),arcname=f)
    return send_file(zip_path,as_attachment=True)

@app.route('/fiche/<prenom>/<nom>')
def fiche(prenom,nom):
    prenom,nom=_norm(unquote(prenom)),_norm(unquote(nom))
    if not os.path.exists(DATA_FILE): return "Données manquantes"
    with open(DATA_FILE) as f: data=json.load(f)
    pers=next((d for d in data if _norm(d['nom'])==nom and _norm(d['prenom'])==prenom),None)
    if not pers: return "Stagiaire non trouvé"
    pdf=FPDF(); pdf.add_page(); pdf.set_font("Arial",size=12)
    for k,v in pers.items():
        if k!="folder": pdf.cell(200,10,txt=clean_text(f"{k.upper()}: {v}"),ln=True)
    path=f"/mnt/data/fiche_{clean_text(pers['prenom'])}_{clean_text(pers['nom'])}.pdf"
    pdf.output(path); return send_file(path,as_attachment=True)

def send_confirmation_email(data):
    html=f"""
    <html><body><p>Bonjour {data['prenom']},</p>
    <p>Nous vous confirmons la bonne réception de votre dossier.</p>
    <p>Cordialement,<br>Intégrale Academy</p></body></html>"""
    msg=MIMEMultipart('alternative')
    msg['Subject']="Confirmation de dépôt – Intégrale Academy"
    msg['From']=os.environ.get("MAIL_USER"); msg['To']=data['email']
    msg.attach(MIMEText(html,'html'))
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
        s.login(os.environ.get("MAIL_USER"),os.environ.get("MAIL_PASS"))
        s.sendmail(msg['From'],[msg['To']],msg.as_string())

@app.route('/update/<prenom>/<nom>', methods=['POST'])
def update(prenom,nom):
    if not session.get('admin'): return redirect('/admin')
    with open(DATA_FILE) as f: data=json.load(f)
    for d in data:
        if d['prenom']==prenom and d['nom']==nom:
            d['status']=request.form.get('status')
            d['commentaire']=request.form.get('commentaire')
    with open(DATA_FILE,'w') as f: json.dump(data,f,indent=2)
    return redirect('/admin')

@app.route('/delete/<prenom>/<nom>', methods=['POST'])
def delete(prenom,nom):
    if not session.get('admin'): return redirect('/admin')
    with open(DATA_FILE) as f: data=json.load(f)
    new=[]
    for d in data:
        if d['prenom']==prenom and d['nom']==nom:
            folder=os.path.join(app.config['UPLOAD_FOLDER'],d['folder'])
            if os.path.exists(folder): import shutil; shutil.rmtree(folder)
        else: new.append(d)
    with open(DATA_FILE,'w') as f: json.dump(new,f,indent=2)
    return redirect('/admin')

# ========== PDF TOUS DOCS SAUF PHOTO ==========
def image_to_uniform_pdf_page(image_path, out_pdf_path, w_mm=180,h_mm=120):
    A4_W,A4_H=210,297; X=(A4_W-w_mm)/2; Y=(A4_H-h_mm)/2
    target_px_w,target_px_h=int(w_mm*12),int(h_mm*12)
    with Image.open(image_path) as im:
        im=ImageOps.exif_transpose(im); im=ensure_rgb(im)
        scale=min(target_px_w/im.width,target_px_h/im.height)
        new_w,new_h=int(im.width*scale),int(im.height*scale)
        im=im.resize((new_w,new_h),Image.LANCZOS)
        canvas=Image.new('RGB',(target_px_w,target_px_h),(255,255,255))
        canvas.paste(im,((target_px_w-new_w)//2,(target_px_h-new_h)//2))
        bio=BytesIO(); canvas.save(bio,'JPEG',quality=92); bio.seek(0)
    tmp='/mnt/data/_tmpimg.jpg'; open(tmp,'wb').write(bio.read())
    pdf=FPDF(unit='mm',format='A4'); pdf.add_page()
    pdf.rect(X,Y,w_mm,h_mm); pdf.image(tmp,x=X,y=Y,w=w_mm,h=h_mm); pdf.output(out_pdf_path)
    os.remove(tmp)

def build_all_docs_pdf(folder,out_pdf):
    files=[f for f in list_all_user_files(folder) if not os.path.basename(f).startswith('photo_identite')]
    usable=[f for f in files if is_image_file(f) or is_pdf_file(f)]
    if not usable: raise FileNotFoundError("Aucun doc trouvé")
    temps=[]
    for f in usable:
        if is_image_file(f):
            t=f"/mnt/data/_p_{os.path.basename(f)}.pdf"
            image_to_uniform_pdf_page(f,t); temps.append(t)
        elif is_pdf_file(f): temps.append(f)
    merger=PdfMerger(); [merger.append(p) for p in temps]; merger.write(out_pdf); merger.close()
    [os.remove(p) for p in temps if p.startswith('/mnt/data/_p_')]

@app.route('/idpack/<prenom>/<nom>')
def idpack(prenom,nom):
    prenom,nom=_norm(unquote(prenom)),_norm(unquote(nom))
    with open(DATA_FILE) as f: data=json.load(f)
    pers=next((d for d in data if _norm(d['nom'])==nom and _norm(d['prenom'])==prenom),None)
    if not pers: return "Stagiaire non trouvé"
    folder=os.path.join(app.config['UPLOAD_FOLDER'],pers['folder'])
    out=f"/mnt/data/IDs_{pers['prenom']}_{pers['nom']}.pdf"
    build_all_docs_pdf(folder,out)
    return send_file(out,as_attachment=True)

# ========== DOCX PHOTO IDENTITE ==========
def prepare_portrait_photo(src,out):
    with Image.open(src) as im:
        im=ImageOps.exif_transpose(im); im=ensure_rgb(im)
        if im.width>im.height: im=im.rotate(-90,expand=True)
        im.save(out,'JPEG',quality=92)

def build_single_photo_docx(photo,full_name,out_docx):
    PHOTO_W,PHOTO_H=35,45
    doc=Document()
    table=doc.add_table(rows=1,cols=1); table.alignment=WD_TABLE_ALIGNMENT.LEFT
    cell=table.cell(0,0)
    p=cell.paragraphs[0]; p.alignment=WD_ALIGN_PARAGRAPH.LEFT
    p.add_run().add_picture(photo,width=Mm(PHOTO_W),height=Mm(PHOTO_H))
    p2=cell.add_paragraph(); p2.alignment=WD_ALIGN_PARAGRAPH.LEFT; p2.add_run(full_name)
    set_cell_border(cell); doc.save(out_docx)

@app.route('/photosheet/<prenom>/<nom>')
def photosheet(prenom,nom):
    prenom,nom=_norm(unquote(prenom)),_norm(unquote(nom))
    with open(DATA_FILE) as f: data=json.load(f)
    pers=next((d for d in data if _norm(d['nom'])==nom and _norm(d['prenom'])==prenom),None)
    if not pers: return "Stagiaire non trouvé"
    folder=os.path.join(app.config['UPLOAD_FOLDER'],pers['folder'])
    photos=[os.path.join(folder,f) for f in os.listdir(folder) if f.startswith('photo_identite') and is_image_file(f)]
    if not photos: return "Aucune photo"
    tmp="/mnt/data/_tmp_photo.jpg"; prepare_portrait_photo(photos[0],tmp)
    out=f"/mnt/data/PHOTOS_{pers['prenom']}_{pers['nom']}.docx"
    build_single_photo_docx(tmp,f"{pers['nom']} {pers['prenom']}",out)
    os.remove(tmp); return send_file(out,as_attachment=True)
