from functools import wraps
import json
import os
import random
import sqlite3
from flask import (
    Flask,
    Response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY", "cle_secrete_pour_la_session_traply"
)

# Configuration de la base de données et des accès superviseur
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
  # Correction du préfixe pour psycopg2 si Render fournit postgres://
  DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "SuperPassword2026!")

# Import conditionnel de psycopg2 si déployé avec PostgreSQL
if DATABASE_URL:
  import psycopg2
  from psycopg2.extras import RealDictCursor


# ----------------------------------------------------
# GESTION DE LA BASE DE DONNÉES (PostgreSQL ou SQLite)
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
# SÉCURITÉ : AUTHENTIFICATION HTTP BASIQUE (DSI)
# ----------------------------------------------------
def require_admin_auth(f):

  @wraps(f)
  def decorated(*args, **kwargs):
    auth = request.authorization
    if not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASSWORD:
      return Response(
          "Accès refusé - Identifiants superviseur requis.",
          401,
          {"WWW-Authenticate": 'Basic realm="Espace Supervision Traply"'},
      )
    return f(*args, **kwargs)

  return decorated


# ----------------------------------------------------
# 1. ROUTE ANTI-VEILLE (HEALTHCHECK POUR CRON-JOB)
# ----------------------------------------------------
@app.route("/ping", methods=["GET"])
def ping():
  """Route appelée toutes les 10 min par cron-job.org pour empêcher l'endormissement."""
  return "pong", 200


# ----------------------------------------------------
# CHARGEMENT DES CAS PRATIQUES
# ----------------------------------------------------
def load_all_emails():
  with open("emails.json", "r", encoding="utf-8") as f:
    return json.load(f)


# ----------------------------------------------------
# ROUTES UTILISATEURS / AGENTS
# ----------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
  if request.method == "POST":
    session["nom"] = request.form.get("nom")
    session["service"] = request.form.get("service")
    session["current_index"] = 0
    session["score"] = 0

    all_emails = load_all_emails()
    selected_emails = random.sample(all_emails, min(10, len(all_emails)))
    session["session_emails"] = selected_emails

    return redirect(url_for("simulation"))
  return render_template("index.html")


@app.route("/simulation", methods=["GET", "POST"])
def simulation():
  emails = session.get("session_emails", [])
  idx = session.get("current_index", 0)

  # Si tous les e-mails ont été traités, on enregistre le résultat final
  if idx >= len(emails):
    nom = session.get("nom", "Anonyme")
    service = session.get("service", "Non renseigné")
    score_val = session.get("score", 0)

    conn = get_db()
    if DATABASE_URL:
      with conn.cursor() as cur:
        cur.execute(
            """
                    INSERT INTO participants (nom, service, score)
                    VALUES (%s, %s, %s);
                """,
            (nom, service, score_val),
        )
        conn.commit()
    else:
      cur = conn.cursor()
      cur.execute(
          """
                INSERT INTO participants (nom, service, score)
                VALUES (?, ?, ?);
            """,
          (nom, service, score_val),
      )
      conn.commit()
    conn.close()

    return redirect(url_for("score"))

  current_email = emails[idx]
  feedback = None

  if request.method == "POST":
    user_choice = request.form.get("choice") == "suspect"
    is_correct = user_choice == current_email["is_suspicious"]

    if is_correct:
      session["score"] = session.get("score", 0) + 1

    feedback = {
        "correct": is_correct,
        "explanation": current_email["explanation"],
    }

  return render_template(
      "simulation.html",
      email=current_email,
      idx=idx + 1,
      total=len(emails),
      feedback=feedback,
  )


@app.route("/next")
def next_email():
  session["current_index"] = session.get("current_index", 0) + 1
  return redirect(url_for("simulation"))


@app.route("/score")
def score():
    emails = session.get("session_emails", [])
    nom = session.get("nom", "Agent")
    service = session.get("service", "Mairie")
    score_val = session.get("score", 0)
    total = len(emails)

    return render_template(
        "score.html",
        nom=nom,
        service=service,
        score=score_val,
        total=total
    )


# ----------------------------------------------------
# ESPACE SUPERVISEUR / DSI
# ----------------------------------------------------
@app.route("/admin/scores", methods=["GET"])
@require_admin_auth
def admin_scores():
  """Tableau de bord complet réservé à la supervision pour consulter tous les résultats."""
  conn = get_db()

  if DATABASE_URL:
    with conn.cursor() as cur:
      cur.execute("""
                SELECT nom, service, score, 
                       TO_CHAR(date, 'DD/MM/YYYY HH24:MI') AS date_formatee 
                FROM participants 
                ORDER BY score DESC, date DESC;
            """)
      agents = cur.fetchall()

      cur.execute("""
                SELECT COUNT(*) AS total_agents, COALESCE(SUM(score), 0) AS total_points, COALESCE(AVG(score), 0) AS moyenne 
                FROM participants;
            """)
      stats = cur.fetchone()
  else:
    cur = conn.cursor()
    cur.execute("""
            SELECT nom, service, score, 
                   strftime('%d/%m/%Y %H:%M', date) AS date_formatee 
            FROM participants 
            ORDER BY score DESC, date DESC;
        """)
    agents = cur.fetchall()

    cur.execute("""
            SELECT COUNT(*) AS total_agents, COALESCE(SUM(score), 0) AS total_points, COALESCE(AVG(score), 0) AS moyenne 
            FROM participants;
        """)
    row = cur.fetchone()
    stats = {
        "total_agents": row["total_agents"],
        "total_points": row["total_points"],
        "moyenne": row["moyenne"],
    }

  conn.close()
  return render_template("admin_scores.html", agents=agents, stats=stats)


@app.route("/reset-scores")
@require_admin_auth
def reset_scores():
  """Réinitialisation de la base (désormais protégée par mot de passe)."""
  conn = get_db()
  if DATABASE_URL:
    with conn.cursor() as cur:
      cur.execute("DELETE FROM participants;")
      conn.commit()
  else:
    cur = conn.cursor()
    cur.execute("DELETE FROM participants")
    conn.commit()
  conn.close()
  return redirect(url_for("admin_scores"))


if __name__ == "__main__":
  app.run(debug=True, host="0.0.0.0", port=5000)
