import os
import random
import sqlite3
import json
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, Response

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cle_secrete_pour_la_session_traply")

# Configuration base de données et accès admin
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "SuperPassword2026!")

if DATABASE_URL:
    import psycopg2
    from psycopg2.extras import RealDictCursor


# ----------------------------------------------------
# GESTION BASE DE DONNÉES
# ----------------------------------------------------
def get_db():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
    else:
        conn = sqlite3.connect("resultats.db")
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    conn = get_db()
    if DATABASE_URL:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS participants (
                    id SERIAL PRIMARY KEY,
                    nom VARCHAR(255),
                    service VARCHAR(100),
                    score INTEGER,
                    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
    else:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT,
                service TEXT,
                score INTEGER,
                date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    conn.close()

init_db()


# ----------------------------------------------------
# SÉCURITÉ ADMIN
# ----------------------------------------------------
def require_admin_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASSWORD:
            return Response(
                "Accès refusé - Identifiants superviseur requis.",
                401,
                {"WWW-Authenticate": 'Basic realm="Mairie de L Isle-Adam - Espace Supervision"'}
            )
        return f(*args, **kwargs)
    return decorated


# ----------------------------------------------------
# ROUTE HEALTHCHECK
# ----------------------------------------------------
@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200


def load_all_emails():
    with open("emails.json", "r", encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------
# ROUTES PARTICIPANTS
# ----------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        session.clear()

        session["nom"] = request.form.get("nom", "").strip() or "Anonyme"
        session["service"] = request.form.get("service", "").strip() or "Non renseigné"
        session["current_index"] = 0
        session["score"] = 0

        all_emails = load_all_emails()

        faciles = [e for e in all_emails if e.get("difficulty") == "facile"]
        moyens = [e for e in all_emails if e.get("difficulty") == "moyen"]
        difficiles = [e for e in all_emails if e.get("difficulty") == "difficile"]

        tirage_faciles = random.sample(faciles, min(5, len(faciles)))
        tirage_moyens = random.sample(moyens, min(5, len(moyens)))
        tirage_difficiles = random.sample(difficiles, min(5, len(difficiles)))

        selected = tirage_faciles + tirage_moyens + tirage_difficiles

        if len(selected) < 15:
            restants = [e for e in all_emails if e not in selected]
            selected += random.sample(restants, min(15 - len(selected), len(restants)))

        session["email_ids"] = [e["id"] for e in selected]
        return redirect(url_for("simulation"))

    return render_template("index.html")


@app.route("/simulation", methods=["GET", "POST"])
def simulation():
    email_ids = session.get("email_ids", [])
    if not email_ids:
        return redirect(url_for("index"))

    idx = session.get("current_index", 0)

    if idx >= len(email_ids):
        nom = session.get("nom", "Anonyme")
        service = session.get("service", "Non renseigné")
        score_val = session.get("score", 0)

        conn = get_db()
        if DATABASE_URL:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO participants (nom, service, score)
                    VALUES (%s, %s, %s);
                """, (nom, service, score_val))
                conn.commit()
        else:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO participants (nom, service, score)
                VALUES (?, ?, ?);
            """, (nom, service, score_val))
            conn.commit()
        conn.close()

        return redirect(url_for("score"))

    all_emails = load_all_emails()
    current_id = email_ids[idx]
    current_email = next((e for e in all_emails if e.get("id") == current_id), all_emails[0])

    feedback = None
    if request.method == "POST":
        user_choice = (request.form.get("choice") == "suspect")
        is_correct = (user_choice == current_email.get("is_suspicious", False))

        if is_correct:
            session["score"] = session.get("score", 0) + 1

        feedback = {
            "correct": is_correct,
            "explanation": current_email.get("explanation", "Aucune explication fournie.")
        }

    is_last = ((idx + 1) == len(email_ids))

    return render_template(
        "simulation.html",
        email=current_email,
        idx=idx + 1,
        total=len(email_ids),
        feedback=feedback,