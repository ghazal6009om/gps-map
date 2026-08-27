import http.server
import socketserver
import json
import io
import base64
import sqlite3
import hashlib
import os
import time
import traceback
from pathlib import Path
from http.cookies import SimpleCookie

import pillow_heif
from PIL import Image
from PIL.ExifTags import GPSTAGS

pillow_heif.register_heif_opener()

DIR = Path(__file__).parent
DB_PATH = DIR / "gps_app.db"
UPLOADS = DIR / "uploads"
UPLOADS.mkdir(exist_ok=True)


def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        lat REAL,
        lng REAL,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    conn.commit()
    conn.close()


def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def create_session_token():
    return hashlib.sha256(os.urandom(32)).hexdigest()


sessions = {}


def get_user_from_request(handler):
    cookie_header = handler.headers.get('Cookie', '')
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    if 'session' in cookie:
        token = cookie['session'].value
        return sessions.get(token)
    return None


def dms_to_dd(dms, ref):
    dd = float(dms[0]) + float(dms[1]) / 60 + float(dms[2]) / 3600
    if ref in ('S', 'W'):
        dd = -dd
    return round(dd, 6)


class GPSHandler(http.server.BaseHTTPRequestHandler):

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, path):
        if path.exists() and path.is_file():
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(path.read_bytes())
        else:
            self.send_response(404)
            self.end_headers()

    def send_static(self, path):
        if path.exists() and path.is_file():
            self.send_response(200)
            ext = path.suffix.lower()
            ct = {'.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
                  '.jpg': 'image/jpeg', '.png': 'image/png'}.get(ext, 'application/octet-stream')
            self.send_header('Content-Type', ct)
            self.end_headers()
            self.wfile.write(path.read_bytes())
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        path_str = self.path.split('?')[0]

        if path_str == '/' or path_str == '/index.html':
            user = get_user_from_request(self)
            if user:
                self.send_html(DIR / 'index.html')
            else:
                self.send_html(DIR / 'login.html')
        elif path_str == '/login.html':
            self.send_html(DIR / 'login.html')
        elif path_str.startswith('/uploads/'):
            self.send_static(DIR / path_str.lstrip('/'))
        elif path_str == '/me':
            user = get_user_from_request(self)
            if user:
                self.send_json({'ok': True, 'username': user['username']})
            else:
                self.send_json({'ok': False})
        elif path_str == '/my-photos':
            user = get_user_from_request(self)
            if not user:
                return self.send_json({'ok': False, 'error': 'غير مسجل الدخول'})
            try:
                conn = sqlite3.connect(str(DB_PATH))
                c = conn.cursor()
                c.execute('SELECT id, filename, lat, lng, uploaded_at FROM photos WHERE user_id=? ORDER BY uploaded_at DESC',
                          (user['id'],))
                rows = c.fetchall()
                conn.close()
                photos = [{'id': r[0], 'url': '/uploads/' + r[1], 'lat': r[2], 'lng': r[3], 'date': r[4]}
                          for r in rows if r[2] is not None]
                self.send_json({'ok': True, 'photos': photos})
            except Exception as e:
                traceback.print_exc()
                self.send_json({'ok': False, 'error': str(e)})
        else:
            static = DIR / path_str.lstrip('/')
            if static.exists() and static.is_file():
                self.send_static(static)
            else:
                self.send_response(404)
                self.end_headers()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)

        if self.path == '/register':
            try:
                data = json.loads(body)
                username = data.get('username', '').strip()
                password = data.get('password', '').strip()
                if not username or not password:
                    return self.send_json({'ok': False, 'error': 'أدخل اسم المستخدم وكلمة المرور'})
                if len(password) < 4:
                    return self.send_json({'ok': False, 'error': 'كلمة المرور قصيرة (4 أحرف على الأقل)'})

                conn = sqlite3.connect(str(DB_PATH))
                c = conn.cursor()
                try:
                    c.execute('INSERT INTO users (username, password) VALUES (?, ?)',
                              (username, hash_password(password)))
                    conn.commit()
                    self.send_json({'ok': True, 'msg': 'تم إنشاء الحساب بنجاح'})
                except sqlite3.IntegrityError:
                    self.send_json({'ok': False, 'error': 'اسم المستخدم موجود مسبقاً'})
                finally:
                    conn.close()
            except Exception as e:
                self.send_json({'ok': False, 'error': str(e)})

        elif self.path == '/login':
            try:
                data = json.loads(body)
                username = data.get('username', '').strip()
                password = data.get('password', '').strip()

                conn = sqlite3.connect(str(DB_PATH))
                c = conn.cursor()
                c.execute('SELECT id, username FROM users WHERE username=? AND password=?',
                          (username, hash_password(password)))
                row = c.fetchone()
                conn.close()

                if row:
                    token = create_session_token()
                    sessions[token] = {'id': row[0], 'username': row[1]}
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Set-Cookie', f'session={token}; Path=/; HttpOnly')
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': True}).encode())
                else:
                    self.send_json({'ok': False, 'error': 'اسم المستخدم أو كلمة المرور خاطئة'})
            except Exception as e:
                self.send_json({'ok': False, 'error': str(e)})

        elif self.path == '/logout':
            cookie_header = self.headers.get('Cookie', '')
            cookie = SimpleCookie()
            cookie.load(cookie_header)
            if 'session' in cookie:
                sessions.pop(cookie['session'].value, None)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Set-Cookie', 'session=; Path=/; Max-Age=0')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True}).encode())

        elif self.path == '/me':
            user = get_user_from_request(self)
            if user:
                self.send_json({'ok': True, 'username': user['username']})
            else:
                self.send_json({'ok': False})

        elif self.path == '/convert':
            user = get_user_from_request(self)
            if not user:
                return self.send_json({'ok': False, 'error': 'غير مسجل الدخول'})

            try:
                data = json.loads(body)
                file_b64 = data.get('file', '')
                filename = data.get('name', 'photo.jpg')
                raw = base64.b64decode(file_b64)

                img = Image.open(io.BytesIO(raw))

                gps_result = {}
                try:
                    exif = img.getexif()
                    gps_ifd = exif.get_ifd(0x8825)
                    if gps_ifd:
                        lat_ref = gps_ifd.get(1, 'N')
                        lat_vals = gps_ifd.get(2)
                        lon_ref = gps_ifd.get(3, 'E')
                        lon_vals = gps_ifd.get(4)
                        if lat_vals and lon_vals:
                            gps_result['lat'] = dms_to_dd(lat_vals, lat_ref)
                            gps_result['lng'] = dms_to_dd(lon_vals, lon_ref)
                except Exception:
                    pass

                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=90)
                jpg_bytes = buf.getvalue()

                out_name = f"{user['id']}_{int(time.time())}_{Path(filename).stem}.jpg"
                out_path = UPLOADS / out_name
                with open(out_path, 'wb') as f:
                    f.write(jpg_bytes)

                conn = sqlite3.connect(str(DB_PATH))
                c = conn.cursor()
                c.execute('INSERT INTO photos (user_id, filename, lat, lng) VALUES (?, ?, ?, ?)',
                          (user['id'], out_name,
                           gps_result.get('lat'), gps_result.get('lng')))
                conn.commit()
                conn.close()

                jpg_b64 = base64.b64encode(jpg_bytes).decode()
                self.send_json({
                    'ok': True,
                    'jpg': jpg_b64,
                    'gps': gps_result,
                    'url': '/uploads/' + out_name
                })
            except Exception as e:
                traceback.print_exc()
                self.send_json({'ok': False, 'error': str(e)})

        elif self.path == '/my-photos':
            user = get_user_from_request(self)
            if not user:
                return self.send_json({'ok': False, 'error': 'غير مسجل الدخول'})
            try:
                conn = sqlite3.connect(str(DB_PATH))
                c = conn.cursor()
                c.execute('SELECT id, filename, lat, lng, uploaded_at FROM photos WHERE user_id=? ORDER BY uploaded_at DESC',
                          (user['id'],))
                rows = c.fetchall()
                conn.close()
                photos = [{'id': r[0], 'url': '/uploads/' + r[1], 'lat': r[2], 'lng': r[3], 'date': r[4]}
                          for r in rows if r[2] is not None]
                self.send_json({'ok': True, 'photos': photos})
            except Exception as e:
                self.send_json({'ok': False, 'error': str(e)})

        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        print(format % args)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


if __name__ == '__main__':
    init_db()
    PORT = 8000
    print(f'Server running at http://localhost:{PORT}')
    server = ThreadedHTTPServer(('127.0.0.1', PORT), GPSHandler)
    server.serve_forever()
