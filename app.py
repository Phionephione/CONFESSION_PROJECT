import os
import random
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

app = Flask(__name__)
# Secret key for sessions (Render uses the env var, local uses the fallback)
app.secret_key = os.getenv("SECRET_KEY", "voidspeak_production_secret_123")

# --- DATABASE CONFIG (PROD-READY) ---
db_url = os.getenv("DATABASE_URL")

# Auto-fix for Neon/Heroku postgres prefix
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Switches between Neon (Cloud) and SQLite (Local)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Timeout to prevent hanging on slow connections
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"connect_args": {"connect_timeout": 10}}

db = SQLAlchemy(app)

# --- GEMINI AI CONFIG ---
AI_KEY = os.getenv("GEMINI_API_KEY")
if AI_KEY:
    try:
        genai.configure(api_key=AI_KEY)
        model = genai.GenerativeModel('gemini-pro')
    except:
        model = None
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

# --- AUTO-CREATE TABLES (Fix for Render/Gunicorn) ---
with app.app_context():
    try:
        db.create_all()
        print("Database tables initialized successfully.")
    except Exception as e:
        print(f"Initial DB creation failed (might be network lock): {e}")

# --- UTILITIES ---
def generate_funny_name():
    adj = ["Cringe", "Salty", "Moody", "Epic", "Lonely", "Savage", "Goofy", "Ghostly", "Neon"]
    noun = ["Potato", "Wizard", "Cactus", "Ninja", "Banana", "Taco", "Panda", "Zombie", "Void"]
    return f"{random.choice(adj)}{random.choice(noun)}{random.randint(10, 99)}"

def check_toxicity(text):
    if not model: return "CLEAN"
    try:
        prompt = f"Analyze: '{text}'. If toxic/abusive, return 'TOXIC: [words]'. Else return 'CLEAN'."
        response = model.generate_content(prompt)
        return response.text.upper()
    except: return "CLEAN"

# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        session['username'] = generate_funny_name()
        if 'user_id' not in session:
            session['user_id'] = os.urandom(16).hex()
        return redirect(url_for('wall'))
    return render_template('identity.html')

@app.route('/whisper', methods=['GET', 'POST'])
def whisper():
    if 'username' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        text = request.form.get('confession')
        result = check_toxicity(text)
        if "TOXIC" in result:
            flash(f"⚠️ {result}", "danger")
            return render_template('whisper.html', last_text=text)
        new_post = Confession(content=text, author=session['username'], session_id=session['user_id'])
        db.session.add(new_post)
        db.session.commit()
        flash("Whisper absorbed by the void.", "success")
        return redirect(url_for('wall'))
    return render_template('whisper.html')

@app.route('/wall', methods=['GET', 'POST'])
def wall():
    if 'username' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        text = request.form.get('confession')
        p_id = request.form.get('parent_id')
        if "TOXIC" in check_toxicity(text):
            flash("⚠️ Toxic reply blocked.", "danger")
        else:
            reply = Confession(content=text, author=session['username'], session_id=session['user_id'], parent_id=p_id)
            db.session.add(reply)
            db.session.commit()
            flash("Reply added!", "success")
    posts = Confession.query.filter_by(parent_id=None).order_by(Confession.id.desc()).all()
    return render_template('wall.html', posts=posts)

@app.route('/my-secrets')
def profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    my_posts = Confession.query.filter_by(session_id=session['user_id']).all()
    return render_template('profile.html', posts=my_posts)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        if request.form.get('password') == "admin123":
            session['is_admin'] = True
    all_posts = Confession.query.all() if session.get('is_admin') else []
    return render_template('admin.html', posts=all_posts)

@app.route('/delete/<int:id>')
def delete_post(id):
    post = Confession.query.get(id)
    if post and (session.get('is_admin') or post.session_id == session.get('user_id')):
        db.session.delete(post)
        db.session.commit()
    return redirect(request.referrer or url_for('wall'))

if __name__ == '__main__':
    app.run(debug=True)