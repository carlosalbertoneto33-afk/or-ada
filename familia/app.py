import os, sqlite3
from functools import wraps
from flask import Flask, g, jsonify, request, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "troque-esta-chave")
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024
DB = os.path.join(os.path.dirname(__file__), "familia.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, pw TEXT, photo TEXT);
CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY, uid INT, name TEXT, role TEXT, age INT, allowance REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY, uid INT, title TEXT, amount REAL, type TEXT, category TEXT, method TEXT, date TEXT, member_id INT, recurring INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS goals(id INTEGER PRIMARY KEY, uid INT, title TEXT, target REAL, current REAL DEFAULT 0, deadline TEXT, member_id INT);
"""
T = {"members": ["name", "role", "age", "allowance"],
     "transactions": ["title", "amount", "type", "category", "method", "date", "member_id", "recurring"],
     "goals": ["title", "target", "current", "deadline", "member_id"]}


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close(_):
    d = g.pop("db", None)
    if d:
        d.close()


with sqlite3.connect(DB) as c:
    c.executescript(SCHEMA)


def err(msg, code=400):
    return jsonify(error=msg), code


def login(f):
    @wraps(f)
    def w(*a, **k):
        if "uid" not in session:
            return err("Não autenticado", 401)
        return f(*a, **k)
    return w


def user_json(r):
    return dict(id=r["id"], name=r["name"], email=r["email"], photo=r["photo"],
                role="Admin" if r["id"] == 1 else "Membro")


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.post("/api/register")
def register():
    d = request.json or {}
    name, email, pw = d.get("name", "").strip(), d.get("email", "").strip().lower(), d.get("password", "")
    if not name or "@" not in email or len(pw) < 6:
        return err("Preencha nome, e-mail válido e senha com 6+ caracteres")
    try:
        cur = db().execute("INSERT INTO users(name,email,pw) VALUES(?,?,?)", (name, email, generate_password_hash(pw)))
        db().commit()
    except sqlite3.IntegrityError:
        return err("E-mail já cadastrado")
    session["uid"] = cur.lastrowid
    return jsonify(ok=True)


@app.post("/api/login")
def do_login():
    d = request.json or {}
    r = db().execute("SELECT * FROM users WHERE email=?", (d.get("email", "").strip().lower(),)).fetchone()
    if not r or not check_password_hash(r["pw"], d.get("password", "")):
        return err("E-mail ou senha inválidos", 401)
    session["uid"] = r["id"]
    return jsonify(ok=True)


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
@login
def me():
    r = db().execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()
    return jsonify(user_json(r))


@app.post("/api/photo")
@login
def photo():
    db().execute("UPDATE users SET photo=? WHERE id=?", ((request.json or {}).get("photo"), session["uid"]))
    db().commit()
    return jsonify(ok=True)


def clean(d, cols):
    return [None if d.get(c) in ("", None) else d.get(c) for c in cols]


@app.route("/api/<t>", methods=["GET", "POST"])
@login
def coll(t):
    if t not in T:
        return err("Não encontrado", 404)
    if request.method == "GET":
        rows = db().execute(f"SELECT * FROM {t} WHERE uid=? ORDER BY id DESC", (session["uid"],)).fetchall()
        return jsonify([dict(r) for r in rows])
    cols = T[t]
    cur = db().execute(f"INSERT INTO {t}(uid,{','.join(cols)}) VALUES(?{',?' * len(cols)})",
                       [session["uid"]] + clean(request.json or {}, cols))
    db().commit()
    return jsonify(id=cur.lastrowid)


@app.route("/api/<t>/<int:i>", methods=["PUT", "DELETE"])
@login
def item(t, i):
    if t not in T:
        return err("Não encontrado", 404)
    if request.method == "DELETE":
        db().execute(f"DELETE FROM {t} WHERE id=? AND uid=?", (i, session["uid"]))
    else:
        cols = T[t]
        db().execute(f"UPDATE {t} SET {','.join(c + '=?' for c in cols)} WHERE id=? AND uid=?",
                     clean(request.json or {}, cols) + [i, session["uid"]])
    db().commit()
    return jsonify(ok=True)


@app.post("/api/goals/<int:i>/deposit")
@login
def deposit(i):
    v = float((request.json or {}).get("amount") or 0)
    if v <= 0:
        return err("Valor inválido")
    db().execute("UPDATE goals SET current=current+? WHERE id=? AND uid=?", (v, i, session["uid"]))
    db().commit()
    return jsonify(ok=True)


@app.post("/api/seed")
@login
def seed():
    d, uid, ids = db(), session["uid"], {}
    for n, r, a, m in [("Samira", "Mãe", 45, 1200), ("Amanda Laura", "Filha(a)", 14, 200),
                       ("Carlos Alberto", "Pai", 51, 0), ("Pedro Henrique", "Filho(a)", 18, 350)]:
        ids[n] = d.execute("INSERT INTO members(uid,name,role,age,allowance) VALUES(?,?,?,?,?)", (uid, n, r, a, m)).lastrowid
    tx = [
        ("Salário", 5500, "receita", "Outro", "Transferência", "2026-07-05", None, 0),
        ("Supermercado", 350, "despesa", "Alimentação", "Cartão", "2026-07-07", None, 0),
        ("Mesada do João", 300, "despesa", "Mesada", "Pix", "2026-07-08", "Pedro Henrique", 1),
        ("Salário", 5500, "receita", "Outro", "Transferência", "2026-08-05", None, 0),
        ("Trabalho extra", 1200, "receita", "Outro", "Pix", "2026-08-15", None, 0),
        ("Supermercado", 770, "despesa", "Alimentação", "Cartão", "2026-08-10", None, 0),
        ("Investimento mensal", 500, "despesa", "Investimento", "Transferência", "2026-08-12", None, 0),
        ("Salário", 5500, "receita", "Outro", "Transferência", "2026-09-05", None, 0),
        ("Verba mensal Ana", 1500, "despesa", "Moradia", "Transferência", "2026-09-05", "Samira", 1),
        ("Combustível", 200, "despesa", "Transporte", "Cartão", "2026-09-06", None, 0),
        ("Supermercado", 680, "despesa", "Alimentação", "Cartão", "2026-09-07", None, 0),
        ("Mesada da Maria", 200, "despesa", "Mesada", "Pix", "2026-09-08", "Amanda Laura", 1),
        ("Mesada do João", 300, "despesa", "Mesada", "Pix", "2026-09-08", "Pedro Henrique", 1),
        ("Almoço", 45, "despesa", "Alimentação", "Pix", "2026-09-09", None, 0),
        ("Curso do Pedro", 430, "despesa", "Educação", "Pix", "2026-09-10", "Pedro Henrique", 0),
        ("Consulta médica", 420, "despesa", "Saúde", "Cartão", "2026-09-12", "Samira", 0),
        ("Feira e padaria", 250, "despesa", "Alimentação", "Dinheiro", "2026-09-13", None, 0),
        ("Cinema", 60, "despesa", "Lazer", "Cartão", "2026-09-14", "Amanda Laura", 0),
    ]
    for t, a, ty, c, me, dt, mb, rc in tx:
        d.execute("INSERT INTO transactions(uid,title,amount,type,category,method,date,member_id,recurring) VALUES(?,?,?,?,?,?,?,?,?)",
                  (uid, t, a, ty, c, me, dt, ids.get(mb), rc))
    for t, tg, cu, dl, mb in [("Faculdade do Pedro Henrique", 50000, 12000, "2029-03-01", "Pedro Henrique"),
                              ("Reserva de Emergência", 10000, 3500, "2026-12-31", None),
                              ("Viagem em Família", 8000, 8000, "2026-07-15", None)]:
        d.execute("INSERT INTO goals(uid,title,target,current,deadline,member_id) VALUES(?,?,?,?,?,?)",
                  (uid, t, tg, cu, dl, ids.get(mb)))
    d.commit()
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
