import os
import random
import sqlite3
import json
import csv
import io
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, Response

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cle_secrete_pour_la_session_traply")

# Configuration de la base de données et des accès superviseur
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
        is_last=is_last
    )


@app.route("/next")
def next_email():
    session["current_index"] = session.get("current_index", 0) + 1
    return redirect(url_for("simulation"))


@app.route("/score")
def score():
    email_ids = session.get("email_ids", [])
    nom = session.get("nom", "Agent")
    service = session.get("service", "Mairie")
    score_val = session.get("score", 0)
    total = len(email_ids) if email_ids else 15

    return render_template(
        "score.html",
        nom=nom,
        service=service,
        score=score_val,
        total=total
    )


@app.route("/classement")
def classement():
    """Podium public limité au top 3 pour les utilisateurs."""
    conn = get_db()
    if DATABASE_URL:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    service,
                    COUNT(*) AS nb_participants,
                    ROUND(AVG(score)::numeric, 1) AS score_moyen,
                    MAX(score) AS meilleur_score
                FROM participants
                GROUP BY service
                ORDER BY score_moyen DESC, nb_participants DESC
                LIMIT 3;
            """)
            podium_services = cur.fetchall()
    else:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                service,
                COUNT(*) AS nb_participants,
                ROUND(AVG(score), 1) AS score_moyen,
                MAX(score) AS meilleur_score
            FROM participants
            GROUP BY service
            ORDER BY score_moyen DESC, nb_participants DESC
            LIMIT 3;
        """)
        podium_services = cur.fetchall()
    conn.close()

    return render_template("classement.html", podium_services=podium_services)


@app.route("/quitter")
def quitter():
    session.clear()
    return redirect(url_for("index"))


# ----------------------------------------------------
# ESPACE SUPERVISEUR / DSI
# ----------------------------------------------------
@app.route("/admin/scores", methods=["GET"])
@require_admin_auth
def admin_scores():
    conn = get_db()

    if DATABASE_URL:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    service,
                    COUNT(*) AS nb_participants,
                    ROUND(AVG(score)::numeric, 1) AS score_moyen,
                    MAX(score) AS meilleur_score
                FROM participants
                GROUP BY service
                ORDER BY score_moyen DESC, nb_participants DESC;
            """)
            classement_services = cur.fetchall()

            cur.execute("""
                SELECT id, nom, service, score, 
                       TO_CHAR(date, 'DD/MM/YYYY HH24:MI') AS date_formatee 
                FROM participants 
                ORDER BY score DESC, date DESC;
            """)
            classement_personnel = cur.fetchall()

            cur.execute("""
                SELECT COUNT(*) AS total_agents, COALESCE(SUM(score), 0) AS total_points, COALESCE(AVG(score), 0) AS moyenne 
                FROM participants;
            """)
            stats = cur.fetchone()
    else:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                service,
                COUNT(*) AS nb_participants,
                ROUND(AVG(score), 1) AS score_moyen,
                MAX(score) AS meilleur_score
            FROM participants
            GROUP BY service
            ORDER BY score_moyen DESC, nb_participants DESC;
        """)
        classement_services = cur.fetchall()

        cur.execute("""
            SELECT id, nom, service, score, 
                   strftime('%d/%m/%Y %H:%M', date) AS date_formatee 
            FROM participants 
            ORDER BY score DESC, date DESC;
        """)
        classement_personnel = cur.fetchall()

        cur.execute("""
            SELECT COUNT(*) AS total_agents, COALESCE(SUM(score), 0) AS total_points, COALESCE(AVG(score), 0) AS moyenne 
            FROM participants;
        """)
        row = cur.fetchone()
        stats = {
            "total_agents": row["total_agents"],
            "total_points": row["total_points"],
            "moyenne": row["moyenne"]
        }

    conn.close()
    return render_template(
        "admin_scores.html", 
        classement_services=classement_services, 
        classement_personnel=classement_personnel, 
        stats=stats
    )


@app.route("/admin/export/csv")
@require_admin_auth
def export_csv():
    """Exporte l'ensemble des résultats au format CSV avec support Excel français."""
    conn = get_db()
    if DATABASE_URL:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT nom, service, score, TO_CHAR(date, 'DD/MM/YYYY HH24:MI') AS date_formatee
                FROM participants
                ORDER BY score DESC, date DESC;
            """)
            rows = cur.fetchall()
    else:
        cur = conn.cursor()
        cur.execute("""
            SELECT nom, service, score, strftime('%d/%m/%Y %H:%M', date) AS date_formatee
            FROM participants
            ORDER BY score DESC, date DESC;
        """)
        rows = cur.fetchall()
    conn.close()

    output = io.StringIO()
    # Le BOM UTF-8 permet à Excel d'ouvrir directement les accents sans problème d'encodage
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=";")

    # En-têtes des colonnes
    writer.writerow(["Rang", "Nom et Prénom", "Service / Direction", "Score (/15)", "Date et Heure"])

    for idx, row in enumerate(rows, start=1):
        writer.writerow([idx, row["nom"], row["service"], row["score"], row["date_formatee"]])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=resultats_sensibilisation_cyber.csv"
    return response


@app.route("/admin/delete/<int:participant_id>")
@require_admin_auth
def delete_participant(participant_id):
    conn = get_db()
    if DATABASE_URL:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM participants WHERE id = %s;", (participant_id,))
            conn.commit()
    else:
        cur = conn.cursor()
        cur.execute("DELETE FROM participants WHERE id = ?;", (participant_id,))
        conn.commit()
    conn.close()
    return redirect(url_for("admin_scores"))


@app.route("/reset-scores")
@require_admin_auth
def reset_scores():
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