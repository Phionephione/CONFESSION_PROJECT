import os
import random
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "voidspeak_ultra_final_100")

# --- DATABASE ---
db_url = os.getenv("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- AI CONFIG ---
AI_KEY = os.getenv("GEMINI_API_KEY")
if AI_KEY:
    genai.configure(api_key=AI_KEY)
    model = genai.GenerativeModel('gemini-pro')
else:
    model = None

# --- DATABASE MODEL ---
class Confession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(500), nullable=False)
    author = db.Column(db.String(50), nullable=False)
    session_id = db.Column(db.String(100), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('confession.id'), nullable=True)
    replies = db.relationship('Confession', backref=db.backref('parent', remote_side=[id]), lazy=True, cascade="all, delete")

with app.app_context():
    db.create_all()

# --- THE FILTER (Layer 1: Manual, Layer 2: AI) ---
def is_toxic(text):
    msg = text.lower()
    # HARD BLOCK: Add any words you want to block 100% here
    bad_list = ["fuck", "bitch", "shit", "asshole", "bastard", "dick", "pussy", "f*ck"]
    for word in bad_list:
        if word in msg:
            return True, f"BLOCKLIST: [{word}]"

    if not model: return False, "CLEAN"
    
    try:
        s_s = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        }
        prompt = f"Moderate this: '{text}'. If toxic/profane/abusive, reply 'TOXIC'. Else 'CLEAN'."
        response = model.generate_content(prompt, safety_settings=s_s)
        res = response.text.strip().upper()
        print(f"--- AI DECISION FOR '{text}': {res} ---") # THIS MUST SHOW IN LOGS
        return ("TOXIC" in res), res
    except Exception as e:
        print(f"AI ERROR: {e}")
        return False, "CLEAN"

# --- ROUTES ---
@app.route('/')
def index(): return render_template('index.html')

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        adj = ["Cringe", "Salty", "Moody", "Epic", "Savage", "Neon"]
        noun = ["Potato", "Wizard", "Ninja", "Taco", "Panda", "Void"]
        session['username'] = f"{random.choice(adj)}{random.choice(noun)}{random.randint(10, 99)}"
        if 'user_id' not in session: session['user_id'] = os.urandom(16).hex()
        return redirect(url_for('wall'))
    return render_template('identity.html')

@app.route('/whisper', methods=['GET', 'POST'])
def whisper():
    if 'username' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        text = request.form.get('confession')
        toxic, reason = is_toxic(text)
        if toxic:
            flash(f"⚠️ {reason}. Please be respectful!", "danger")
            return render_template('whisper.html', last_text=text)
        
        new_post = Confession(content=text, author=session['username'], session_id=session['user_id'])
        db.session.add(new_post)
        db.session.commit()
        return redirect(url_for('wall'))
    return render_template('whisper.html')

@app.route('/wall', methods=['GET', 'POST'])
def wall():
    if 'username' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        text = request.form.get('confession')
        p_id = request.form.get('parent_id')
        toxic, _ = is_toxic(text)
        if toxic:
            flash("⚠️ Toxic reply blocked!", "danger")
        else:
            db.session.add(Confession(content=text, author=session['username'], session_id=session['user_id'], parent_id=p_id))
            db.session.commit()
    posts = Confession.query.filter_by(parent_id=None).order_by(Confession.id.desc()).all()
    return render_template('wall.html', posts=posts)

@app.route('/my-secrets')
def profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    posts = Confession.query.filter_by(session_id=session['user_id']).all()
    return render_template('profile.html', posts=posts)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST' and request.form.get('password') == "admin123":
        session['is_admin'] = True
    posts = Confession.query.all() if session.get('is_admin') else []
    return render_template('admin.html', posts=posts)

@app.route('/delete/<int:id>')
def delete_post(id):
    post = Confession.query.get(id)
    if post and (session.get('is_admin') or post.session_id == session.get('user_id')):
        db.session.delete(post)
        db.session.commit()
    return redirect(request.referrer or url_for('wall'))

if __name__ == '__main__':
    app.run(debug=True)
