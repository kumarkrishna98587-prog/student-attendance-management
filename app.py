import csv
import io
import os
import sqlite3
from datetime import date, datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, make_response
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "attendance.db")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key-before-deployment")


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roll_no TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                course TEXT NOT NULL,
                semester TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                attendance_date TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('Present', 'Absent', 'Leave')),
                UNIQUE(student_id, attendance_date),
                FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
            )
        """)
        admin = db.execute("SELECT id FROM admins WHERE username = ?", ("admin",)).fetchone()
        if not admin:
            db.execute(
                "INSERT INTO admins(username, password_hash) VALUES (?, ?)",
                ("admin", generate_password_hash("admin12345"))
            )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with get_db() as db:
            admin = db.execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            session.clear()
            session["admin_id"] = admin["id"]
            session["username"] = admin["username"]
            return redirect(url_for("dashboard"))
        flash("Username या password सही नहीं है।", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("आप लॉग आउट हो गए हैं।", "success")
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    today = date.today().isoformat()
    with get_db() as db:
        total_students = db.execute("SELECT COUNT(*) AS n FROM students").fetchone()["n"]
        total_records = db.execute("SELECT COUNT(*) AS n FROM attendance").fetchone()["n"]
        present_today = db.execute(
            "SELECT COUNT(*) AS n FROM attendance WHERE attendance_date=? AND status='Present'",
            (today,)
        ).fetchone()["n"]
        absent_today = db.execute(
            "SELECT COUNT(*) AS n FROM attendance WHERE attendance_date=? AND status='Absent'",
            (today,)
        ).fetchone()["n"]
        recent = db.execute("""
            SELECT a.attendance_date, a.status, s.roll_no, s.name
            FROM attendance a JOIN students s ON s.id=a.student_id
            ORDER BY a.attendance_date DESC, s.roll_no ASC LIMIT 8
        """).fetchall()
    return render_template(
        "dashboard.html", total_students=total_students, total_records=total_records,
        present_today=present_today, absent_today=absent_today, today=today, recent=recent
    )


@app.route("/students", methods=["GET", "POST"])
@login_required
def students():
    if request.method == "POST":
        roll_no = request.form.get("roll_no", "").strip()
        name = request.form.get("name", "").strip()
        course = request.form.get("course", "").strip()
        semester = request.form.get("semester", "").strip()
        if not all([roll_no, name, course, semester]):
            flash("सभी fields भरना जरूरी है।", "error")
        else:
            try:
                with get_db() as db:
                    db.execute(
                        "INSERT INTO students(roll_no, name, course, semester) VALUES (?, ?, ?, ?)",
                        (roll_no, name, course, semester)
                    )
                flash("विद्यार्थी सफलतापूर्वक जोड़ दिया गया।", "success")
                return redirect(url_for("students"))
            except sqlite3.IntegrityError:
                flash("यह Roll Number पहले से मौजूद है।", "error")

    search = request.args.get("q", "").strip()
    with get_db() as db:
        if search:
            pattern = f"%{search}%"
            rows = db.execute("""
                SELECT * FROM students
                WHERE roll_no LIKE ? OR name LIKE ? OR course LIKE ?
                ORDER BY roll_no
            """, (pattern, pattern, pattern)).fetchall()
        else:
            rows = db.execute("SELECT * FROM students ORDER BY roll_no").fetchall()
    return render_template("students.html", students=rows, search=search)


@app.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required
def delete_student(student_id):
    with get_db() as db:
        db.execute("DELETE FROM students WHERE id = ?", (student_id,))
    flash("विद्यार्थी और उसके attendance records हटा दिए गए।", "success")
    return redirect(url_for("students"))


@app.route("/attendance", methods=["GET", "POST"])
@login_required
def attendance():
    selected_date = request.values.get("attendance_date", date.today().isoformat())
    try:
        datetime.strptime(selected_date, "%Y-%m-%d")
    except ValueError:
        selected_date = date.today().isoformat()
        flash("तारीख सही नहीं थी; आज की तारीख दिखाई जा रही है।", "error")

    if request.method == "POST":
        with get_db() as db:
            students_list = db.execute("SELECT id FROM students").fetchall()
            for student in students_list:
                status = request.form.get(f"status_{student['id']}", "Absent")
                if status not in ("Present", "Absent", "Leave"):
                    status = "Absent"
                db.execute("""
                    INSERT INTO attendance(student_id, attendance_date, status)
                    VALUES (?, ?, ?)
                    ON CONFLICT(student_id, attendance_date)
                    DO UPDATE SET status=excluded.status
                """, (student["id"], selected_date, status))
        flash(f"{selected_date} की attendance सेव हो गई।", "success")
        return redirect(url_for("attendance", attendance_date=selected_date))

    with get_db() as db:
        students_list = db.execute("""
            SELECT s.id, s.roll_no, s.name, s.course, s.semester, a.status
            FROM students s
            LEFT JOIN attendance a
              ON a.student_id=s.id AND a.attendance_date=?
            ORDER BY s.roll_no
        """, (selected_date,)).fetchall()
    return render_template("attendance.html", students=students_list, selected_date=selected_date)


@app.route("/reports")
@login_required
def reports():
    search = request.args.get("q", "").strip()
    with get_db() as db:
        query = """
            SELECT s.id, s.roll_no, s.name, s.course, s.semester,
                   COUNT(a.id) AS total_marked,
                   SUM(CASE WHEN a.status='Present' THEN 1 ELSE 0 END) AS present_count,
                   SUM(CASE WHEN a.status='Absent' THEN 1 ELSE 0 END) AS absent_count,
                   SUM(CASE WHEN a.status='Leave' THEN 1 ELSE 0 END) AS leave_count
            FROM students s LEFT JOIN attendance a ON s.id=a.student_id
        """
        params = []
        if search:
            query += " WHERE s.roll_no LIKE ? OR s.name LIKE ? OR s.course LIKE ?"
            pattern = f"%{search}%"
            params = [pattern, pattern, pattern]
        query += " GROUP BY s.id ORDER BY s.roll_no"
        rows = db.execute(query, params).fetchall()
    report_rows = []
    for row in rows:
        total = row["total_marked"] or 0
        present = row["present_count"] or 0
        percentage = round((present / total) * 100, 2) if total else 0
        report_rows.append({
            "roll_no": row["roll_no"], "name": row["name"], "course": row["course"],
            "semester": row["semester"], "total": total, "present": present,
            "absent": row["absent_count"] or 0, "leave": row["leave_count"] or 0,
            "percentage": percentage
        })
    return render_template("reports.html", rows=report_rows, search=search)


@app.route("/reports/export")
@login_required
def export_report():
    with get_db() as db:
        rows = db.execute("""
            SELECT s.roll_no, s.name, s.course, s.semester,
                   COUNT(a.id) AS total_marked,
                   SUM(CASE WHEN a.status='Present' THEN 1 ELSE 0 END) AS present_count,
                   SUM(CASE WHEN a.status='Absent' THEN 1 ELSE 0 END) AS absent_count,
                   SUM(CASE WHEN a.status='Leave' THEN 1 ELSE 0 END) AS leave_count
            FROM students s LEFT JOIN attendance a ON s.id=a.student_id
            GROUP BY s.id ORDER BY s.roll_no
        """).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Roll Number", "Name", "Course", "Semester", "Total Marked", "Present", "Absent", "Leave", "Attendance %"])
    for row in rows:
        total = row["total_marked"] or 0
        present = row["present_count"] or 0
        percentage = round(present * 100 / total, 2) if total else 0
        writer.writerow([
            row["roll_no"], row["name"], row["course"], row["semester"],
            total, present, row["absent_count"] or 0, row["leave_count"] or 0, percentage
        ])
    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=attendance_report.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old = request.form.get("old_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        with get_db() as db:
            admin = db.execute("SELECT * FROM admins WHERE id=?", (session["admin_id"],)).fetchone()
            if not check_password_hash(admin["password_hash"], old):
                flash("पुराना password सही नहीं है।", "error")
            elif len(new) < 8:
                flash("नया password कम से कम 8 characters का होना चाहिए।", "error")
            elif new != confirm:
                flash("नया password और confirm password समान नहीं हैं।", "error")
            else:
                db.execute("UPDATE admins SET password_hash=? WHERE id=?",
                           (generate_password_hash(new), session["admin_id"]))
                flash("Password बदल गया। अगली बार नए password से login करें।", "success")
                return redirect(url_for("change_password"))
    return render_template("change_password.html")


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


init_db()

if __name__ == "__main__":
    app.run(debug=True)
