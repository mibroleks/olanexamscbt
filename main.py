from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
import sqlite3, csv, os
from io import StringIO

# ---------------------------------------------
# APP INITIALIZATION
# ---------------------------------------------
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="super-secret-session-key")

os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_FILE = "school.db"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# ---------------------------------------------
# DATABASE INITIALIZATION
# ---------------------------------------------
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            admission_number TEXT UNIQUE NOT NULL,
            class_name TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            class_name TEXT NOT NULL,
            is_active INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------
# STUDENT LOGIN
# ---------------------------------------------
@app.get("/", response_class=HTMLResponse)
def student_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def handle_student_login(request: Request, username: str = Form(...)):
    conn = get_db_connection()
    student = conn.execute("SELECT * FROM students WHERE admission_number = ?", (username,)).fetchone()
    active_link = None
    if student:
        active_link = conn.execute(
            "SELECT url FROM links WHERE class_name = ? AND is_active = 1 LIMIT 1",
            (student["class_name"],)
        ).fetchone()
    conn.close()

    if student:
        if active_link:
            return RedirectResponse(url=active_link["url"], status_code=302)
        return templates.TemplateResponse(
            "student_dashboard.html",
            {"request": request, "msg": "No active form link set."}
        )
    return templates.TemplateResponse(
        "login.html", {"request": request, "msg": "Invalid Admission Number."}
    )

# ---------------------------------------------
# ADMIN LOGIN
# ---------------------------------------------
@app.get("/admin/login", response_class=HTMLResponse)
def admin_login(request: Request, msg: str = ""):
    return templates.TemplateResponse("admin_login.html", {"request": request, "msg": msg})

@app.post("/admin/login")
def handle_admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        request.session["admin"] = True
        return RedirectResponse("/admin/dashboard", status_code=303)
    return RedirectResponse("/admin/login?msg=Invalid+credentials", status_code=303)

@app.get("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login?msg=Logged+out", status_code=303)

# ---------------------------------------------
# ADMIN DASHBOARD (CLASS FILTER + PAGINATION)
# ---------------------------------------------
@app.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request, class_name: str = None, page: int = 1, per_page: int = 10):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login?msg=Please+login", status_code=303)

    conn = get_db_connection()
    classes = [r["class_name"] for r in conn.execute(
        "SELECT DISTINCT class_name FROM students ORDER BY class_name"
    ).fetchall()]

    # Students pagination
    student_query = "SELECT * FROM students"
    params = []
    if class_name:
        student_query += " WHERE class_name = ?"
        params.append(class_name)
    total_students = conn.execute(f"SELECT COUNT(*) FROM ({student_query})", params).fetchone()[0]
    offset = (page - 1) * per_page
    student_query += " LIMIT ? OFFSET ?"
    params.extend([per_page, offset])
    students = conn.execute(student_query, params).fetchall()

    # Links pagination
    link_query = "SELECT * FROM links"
    link_params = []
    if class_name:
        link_query += " WHERE class_name = ?"
        link_params.append(class_name)
    total_links = conn.execute(f"SELECT COUNT(*) FROM ({link_query})", link_params).fetchone()[0]
    link_query += " LIMIT ? OFFSET ?"
    link_params.extend([per_page, offset])
    links = conn.execute(link_query, link_params).fetchall()

    active_link = conn.execute(
        "SELECT * FROM links WHERE class_name = ? AND is_active = 1 LIMIT 1",
        (class_name,) if class_name else ("JSS1",)
    ).fetchone()

    conn.close()

    total_pages_students = (total_students + per_page - 1) // per_page
    total_pages_links = (total_links + per_page - 1) // per_page

    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "students": students,
        "links": links,
        "classes": classes,
        "selected_class": class_name,
        "active_link": active_link,
        "page": page,
        "total_pages_students": total_pages_students,
        "total_pages_links": total_pages_links
    })

# ---------------------------------------------
# ADMIN STUDENT MANAGEMENT
# ---------------------------------------------
@app.post("/admin/upload_csv")
async def upload_csv(csv_file: UploadFile = File(...)):
    content = await csv_file.read()
    reader = csv.reader(StringIO(content.decode("utf-8")))
    conn = get_db_connection()
    for row in reader:
        if len(row) >= 3:
            name, adm, class_name = row[0].strip(), row[1].strip(), row[2].strip()
            try:
                conn.execute(
                    "INSERT INTO students (name, admission_number, class_name) VALUES (?, ?, ?)",
                    (name, adm, class_name)
                )
            except sqlite3.IntegrityError:
                continue
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/add_student")
def add_student(name: str = Form(...), admission_number: str = Form(...), class_name: str = Form(...)):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO students (name, admission_number, class_name) VALUES (?, ?, ?)",
            (name, admission_number, class_name)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/delete_student")
def delete_student(admission_number: str = Form(...)):
    conn = get_db_connection()
    conn.execute("DELETE FROM students WHERE admission_number = ?", (admission_number,))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/delete_all_students")
def delete_all_students():
    conn = get_db_connection()
    conn.execute("DELETE FROM students")
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

# ---------------------------------------------
# ADMIN LINKS MANAGEMENT
# ---------------------------------------------
@app.post("/admin/upload_link")
def upload_link(name: str = Form(...), link: str = Form(...), class_name: str = Form(...)):
    conn = get_db_connection()
    conn.execute("INSERT INTO links (name, url, class_name) VALUES (?, ?, ?)", (name, link, class_name))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/set_active_link")
def set_active_link(link_id: str = Form(...), class_name: str = Form(...)):
    conn = get_db_connection()
    conn.execute("UPDATE links SET is_active = 0 WHERE class_name = ?", (class_name,))
    conn.execute("UPDATE links SET is_active = 1 WHERE id = ?", (int(link_id),))
    conn.commit()
    conn.close()
    return RedirectResponse(f"/admin/dashboard?class_name={class_name}", status_code=303)

# ---------------------------------------------
# JSON STUDENT LOGIN (API)
# ---------------------------------------------
@app.post("/student_login")
async def student_login_json(data: dict):
    admission_number = data.get("admission_number")
    if not admission_number:
        return JSONResponse({"detail": "Admission number required."}, status_code=400)

    conn = get_db_connection()
    student = conn.execute(
        "SELECT * FROM students WHERE admission_number = ?", (admission_number,)
    ).fetchone()
    if not student:
        conn.close()
        return JSONResponse({"detail": "Invalid Admission Number."}, status_code=401)

    active_link = conn.execute(
        "SELECT url FROM links WHERE class_name = ? AND is_active = 1 LIMIT 1",
        (student["class_name"],)
    ).fetchone()
    conn.close()

    if not active_link:
        return JSONResponse({"detail": "No active form link."}, status_code=404)

    return JSONResponse({"form_link": active_link["url"]})

# ---------------------------------------------
# GLOBAL ERROR HANDLERS
# ---------------------------------------------
@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    print(f"🔥 Internal error: {exc}")
    return PlainTextResponse(f"Internal Server Error: {exc}", status_code=500)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return PlainTextResponse(f"HTTP Error: {exc.detail}", status_code=exc.status_code)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return PlainTextResponse(f"Validation Error: {exc}", status_code=422)
