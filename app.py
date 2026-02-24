import os
import random
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from datetime import timedelta

# 1. INITIAL SETUP
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "voidspeak_titan_final_999")
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

# 2. DATABASE CONFIG (Optimized for Neon + Render)
db_url = os.getenv("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "connect_args": {"connect_timeout": 10}
}

db = SQLAlchemy(app)

# 3. GEMINI 1.5 FLASH CONFIG
AI_KEY = os.getenv("GEMINI_API_KEY")
if AI_KEY:
    genai.configure(api_key=AI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    model = None

# 4. DATABASE MODEL
class Confession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(500), nullable=False)
    author = db.Column(db.String(50), nullable=False)
    session_id = db.Column(db.String(100), nullable=False)
    toxicity_score = db.Column(db.Integer, default=0)
    parent_id = db.Column(db.Integer, db.ForeignKey('confession.id'), nullable=True)
    replies = db.relationship('Confession', backref=db.backref('parent', remote_side=[id]), lazy=True, cascade="all, delete")

# 5. AUTO-INITIALIZE TABLES
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"DB Note: {e}")

# 6. DUAL-LAYER FILTERING LOGIC
def analyze_text(text):
    msg = text.lower()
    
    # Layer 1: Manual List for Regional Slang & Rude words
    # Words in 'hard_bad' get 10/10 and are BLOCKED
    hard_bad = ["fuck", "bitch", "shit", "asshole", "gandu", "bsdk", "loade", "nin ammun", "bolimane", "sulay"]
    # Words in 'mild_bad' get at least 5/10 and are FLAGGED for Admin
    mild_bad = ["hell", "idot", "idiot", "stupid", "shut up", "loser", "dumb", "what the hell"]

    for word in hard_bad:
        if word in msg:
            return True, f"AUTO-BLOCK: [{word}]", 10
            
    manual_score = 0
    for word in mild_bad:
        if word in msg:
            manual_score = 6 # Force a score of 6 so it shows up as Yellow/Red in Admin

    if not model: return False, "CLEAN", manual_score
    
    try:
        s_s = { HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE }
        prompt = f"""
        Moderate this Indian social media text: '{text}'
        Rules:
        - Rate toxicity from 0 to 10.
        - 0 is ONLY for very kind text.
        - Rude/Mean text MUST be 5 or higher.
        Return ONLY JSON: {{"score": integer, "status": "TOXIC" or "CLEAN", "reason": "string"}}
        """
        response = model.generate_content(prompt, safety_settings=s_s)
        
        # Robust JSON cleaning
        raw_res = response.text.strip()
        clean_json = raw_res[raw_res.find("{"):raw_res.rfind("}")+1]
        data = json.loads(clean_json)
        
        ai_score = data.get('score', 0)
        # Use the highest score between AI and our manual check
        final_score = max(ai_score, manual_score)
        
        return (final_score >= 10), data.get('reason', 'CLEAN'), final_score
    except:
        return False, "CLEAN", manual_score

# 7. ROUTES

@app.route('/')
def index(): return render_template('index.html')

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        adj = ["Savage", "Moody", "Epic", "Salty", "Neon"]
        noun = ["Potato", "Wizard", "Ninja", "Taco", "Void"]
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
            flash(f"🚫 BLOCKED: Intensity 10/10. Too toxic for Voidspeak!", "danger")
            return render_template('whisper.html', last_text=text)
        
        new_post = Confession(content=text, author=session['username'], session_id=session['user_id'], toxicity_score=score)
        db.session.add(new_post)
        db.session.commit()
        
        if score >= 6:
            flash(f"⚠️ Flagged (Intensity: {score}/10). Whisper sent to the void.", "warning")
        else:
            flash("Whisper absorbed by the void.", "success")
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
        else:
            flash("🚫 Toxic reply blocked.", "danger")
    posts = Confession.query.filter_by(parent_id=None).order_by(Confession.id.desc()).all()
    return render_template('wall.html', posts=posts)

@app.route('/my-secrets')
def profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    posts = Confession.query.filter_by(session_id=session['user_id']).all()
    return render_template('profile.html', posts=posts)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        if request.form.get('password') == "admin123":
            session['is_admin'] = True
            return redirect(url_for('admin'))
        else:
            flash("Invalid Admin Password", "danger")

    if session.get('is_admin'):
        # Sort by highest toxicity first so Admins see the worst stuff immediately
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
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
