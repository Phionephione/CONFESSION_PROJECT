import os
import random
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from datetime import timedelta

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "voidspeak_titan_final_ultra")

# --- SESSION SECURITY ---
# This makes the admin login "non-permanent" - it clears when the browser closes
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)

# --- DATABASE ---
db_url = os.getenv("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"connect_args": {"connect_timeout": 7}}

db = SQLAlchemy(app)

# --- GEMINI CONFIG ---
AI_KEY = os.getenv("GEMINI_API_KEY")
if AI_KEY:
    genai.configure(api_key=AI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    model = None

# --- MODELS ---
class Confession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(500), nullable=False)
    author = db.Column(db.String(50), nullable=False)
    session_id = db.Column(db.String(100), nullable=False)
    toxicity_score = db.Column(db.Integer, default=0)
    parent_id = db.Column(db.Integer, db.ForeignKey('confession.id'), nullable=True)
    replies = db.relationship('Confession', backref=db.backref('parent', remote_side=[id]), lazy=True, cascade="all, delete")

with app.app_context():
    db.create_all()

# --- THE ULTIMATE MULTI-LANGUAGE FILTER ---
def analyze_text(text):
    msg = text.lower()
    # Added Transliterated Slang (Kannada/Hindi/English) as hard backup
    bad_list = ["fuck", "bitch", "shit", "asshole", "ganndu", "bolimane", "loade", "bsdk", "gandu"]
    
    for word in bad_list:
        if word in msg:
            return True, f"SYSTEM BLOCK: Regional Slang detected [{word}]", 10

    if not model: return False, "CLEAN", 0
    
    try:
        s_s = { HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE }
        # UPDATED PROMPT: Explicitly asking for Indian Regional Slang detection
        prompt = f"""
        ACT AS A SOCIAL MEDIA MODERATOR FOR INDIA.
        Analyze this text: '{text}'
        The text might be in English, or Indian languages like Kannada, Hindi, etc., written in the ROMAN/ENGLISH alphabet.
        
        Detection Rules:
        1. Look for transliterated insults (e.g., 'ganndu', 'badava', 'punda', etc.)
        2. Look for toxic English words.
        
        Return ONLY a JSON: {{"status": "TOXIC" or "CLEAN", "score": 0-10, "reason": "short explanation"}}
        """
        response = model.generate_content(prompt, safety_settings=s_s)
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_json)
        
        is_toxic = (data.get('status') == "TOXIC" or data.get('score', 0) >= 7)
        return is_toxic, data.get('reason', 'CLEAN'), data.get('score', 0)
    except:
        return False, "CLEAN", 0

# --- ROUTES ---
@app.route('/')
def index(): return render_template('index.html')

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        adj = ["Cringe", "Salty", "Moody", "Epic", "Savage"]
        noun = ["Potato", "Wizard", "Ninja", "Taco", "Panda"]
        session['username'] = f"{random.choice(adj)}{random.choice(noun)}{random.randint(10, 99)}"
        session['user_id'] = os.urandom(16).hex()
        return redirect(url_for('wall'))
    return render_template('identity.html')

@app.route('/whisper', methods=['GET', 'POST'])
def whisper():
    if 'username' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        text = request.form.get('confession')
        toxic, reason, score = analyze_text(text)
        if toxic:
            flash(f"⚠️ {reason}. (Severity: {score}/10)", "danger")
            return render_template('whisper.html', last_text=text)
        db.session.add(Confession(content=text, author=session['username'], session_id=session['user_id'], toxicity_score=score))
        db.session.commit()
        return redirect(url_for('wall'))
    return render_template('whisper.html')

@app.route('/wall', methods=['GET', 'POST'])
def wall():
    if 'username' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        text = request.form.get('confession')
        p_id = request.form.get('parent_id')
        toxic, _, score = analyze_text(text)
        if not toxic:
            db.session.add(Confession(content=text, author=session['username'], session_id=session['user_id'], parent_id=p_id, toxicity_score=score))
            db.session.commit()
            flash("Reply added.", "success")
    posts = Confession.query.filter_by(parent_id=None).order_by(Confession.id.desc()).all()
    return render_template('wall.html', posts=posts)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        if request.form.get('password') == "admin123":
            session['is_admin'] = True
            session.permanent = False # Session dies when browser closes
            return redirect(url_for('admin'))
        else:
            flash("Wrong Password", "danger")

    if session.get('is_admin'):
        posts = Confession.query.order_by(Confession.toxicity_score.desc()).all()
    else:
        posts = []
    return render_template('admin.html', posts=posts)

@app.route('/admin-logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin'))

@app.route('/delete/<int:id>')
def delete_post(id):
    post = Confession.query.get(id)
    if post and (session.get('is_admin') or post.session_id == session.get('user_id')):
        db.session.delete(post)
        db.session.commit()
    return redirect(request.referrer or url_for('wall'))

if __name__ == '__main__':
    app.run(debug=True)
