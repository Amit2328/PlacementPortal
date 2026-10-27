import os
import sqlite3
from functools import wraps
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, g
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "local-development-key-change-before-deployment"
)

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "placement.db"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DATABASE) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL,
                job_type TEXT NOT NULL,
                description TEXT NOT NULL,
                eligibility TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                job_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending',
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(student_id, job_id),
                FOREIGN KEY(student_id) REFERENCES students(id),
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        """)

        demo_jobs = [
            (
                1, "Junior Web Developer - Demo",
                "Demo Technology Company", "Remote / India",
                "Demo listing", 
                "Sample practice listing for the Placement Portal project. This is not a verified vacancy.",
                "HTML, CSS and basic JavaScript"
            ),
            (
                2, "Python Developer Trainee - Demo",
                "Sample Software Labs", "Patna / Remote",
                "Demo listing",
                "Sample practice listing to demonstrate searching and applying. This is not a verified vacancy.",
                "Basic Python and problem-solving"
            ),
            (
                3, "Frontend Developer - Demo",
                "Placement Portal Demo Labs", "Remote / India",
                "Demo listing",
                "Sample frontend role for testing the portal workflow. This is not a verified vacancy.",
                "HTML, CSS and JavaScript basics"
            )
        ]

        db.executemany("""
            INSERT OR IGNORE INTO jobs
            (id, title, company, location, job_type, description, eligibility)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, demo_jobs)


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "student_id" not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if "student_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Please fill in every field.", "error")
        elif len(name) > 100 or len(email) > 254:
            flash("Name or email is too long.", "error")
        elif len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
        else:
            try:
                db = get_db()
                cursor = db.execute(
                    "INSERT INTO students (name, email, password_hash) VALUES (?, ?, ?)",
                    (name, email, generate_password_hash(password))
                )
                db.commit()
                session.clear()
                session["student_id"] = cursor.lastrowid
                session["student_name"] = name
                flash("Registration successful. Welcome!", "success")
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                flash("This email is already registered.", "error")

    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "student_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        student = get_db().execute(
            "SELECT * FROM students WHERE email = ?", (email,)
        ).fetchone()

        if student and check_password_hash(student["password_hash"], password):
            session.clear()
            session["student_id"] = student["id"]
            session["student_name"] = student["name"]
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("auth.html", mode="login")


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    student = db.execute(
        "SELECT id, name, email, created_at FROM students WHERE id = ?",
        (session["student_id"],)
    ).fetchone()

    if student is None:
        session.clear()
        return redirect(url_for("login"))

    application_count = db.execute(
        "SELECT COUNT(*) FROM applications WHERE student_id = ?",
        (session["student_id"],)
    ).fetchone()[0]

    return render_template(
        "dashboard.html",
        student=student,
        application_count=application_count
    )


@app.route("/jobs")
def jobs():
    query = request.args.get("q", "").strip()
    search_term = f"%{query}%"
    student_id = session.get("student_id", -1)

    job_list = get_db().execute("""
        SELECT jobs.*,
               EXISTS (
                   SELECT 1 FROM applications
                   WHERE applications.job_id = jobs.id
                   AND applications.student_id = ?
               ) AS applied
        FROM jobs
        WHERE title LIKE ?
           OR company LIKE ?
           OR location LIKE ?
           OR description LIKE ?
        ORDER BY jobs.id
    """, (student_id, search_term, search_term, search_term, search_term)).fetchall()

    return render_template("jobs.html", jobs=job_list, query=query)


@app.route("/apply/<int:job_id>", methods=["POST"])
@login_required
def apply(job_id):
    db = get_db()
    job = db.execute(
        "SELECT id FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()

    if job is None:
        flash("That job listing was not found.", "error")
        return redirect(url_for("jobs"))

    try:
        db.execute(
            "INSERT INTO applications (student_id, job_id) VALUES (?, ?)",
            (session["student_id"], job_id)
        )
        db.commit()
        flash("Application submitted successfully for this demo listing.", "success")
    except sqlite3.IntegrityError:
        flash("You have already applied for this job.", "error")

    return redirect(url_for("applications"))


@app.route("/applications")
@login_required
def applications():
    application_list = get_db().execute("""
        SELECT applications.id, applications.status, applications.applied_at,
               jobs.title, jobs.company, jobs.location
        FROM applications
        JOIN jobs ON jobs.id = applications.job_id
        WHERE applications.student_id = ?
        ORDER BY applications.applied_at DESC
    """, (session["student_id"],)).fetchall()

    return render_template("applications.html", applications=application_list)


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


init_db()

if __name__ == "__main__":
    app.run(debug=True)
