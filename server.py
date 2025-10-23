import os
import socket
import mimetypes
import time

# ensure common types exist even in slim images
mimetypes.init()
mimetypes.add_type("application/pdf", ".pdf")
mimetypes.add_type("image/png", ".png")
mimetypes.add_type("image/jpeg", ".jpg")
mimetypes.add_type("text/html; charset=utf-8", ".html")

import sys
from urllib.parse import unquote, quote
import datetime
from typing import Optional

PORT = int(os.environ.get("PORT", "8000"))
ALLOWED_EXTENSIONS = {".html", ".png", ".pdf", ".jpg"}


def file_size(num_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


def find_file_recursive(root_dir: str, filename: str) -> Optional[str]:
    """Search for a file recursively in root_dir. Returns absolute path or None."""
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if filename in filenames:
            return os.path.join(dirpath, filename)
    return None


def respond(conn, status, headers, body):
    head = [f"HTTP/1.1 {status}".encode()]
    for k, v in headers.items():
        head.append(f"{k}: {v}".encode())
    head.append(b"")
    head.append(b"")
    conn.sendall(b"\r\n".join(head) + body)


def _is_subpath(child: str, parent: str) -> bool:
    child_real = os.path.realpath(child)
    parent_real = os.path.realpath(parent)
    try:
        return os.path.commonpath([child_real, parent_real]) == parent_real
    except ValueError:
        return False


def _minimal_listing_html(req_path: str, abs_dir: str) -> bytes:
    try:
        all_entries = sorted(os.listdir(abs_dir))
        # Filter out specific files
        excluded_files = {'Dockerfile', 'README.md', 'client.py', 'server.py', 'docker-compose.yml', '.DS_Store', 'syllabus PR.pdf'}
        entries = [entry for entry in all_entries if entry not in excluded_files]
    except OSError:
        return b"<html><body><h1>Forbidden</h1></body></html>"

    lines = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Content of {req_path}</title>",
        "<style>",
        "table { border-collapse: collapse; width: 100%; }",
        "th, td { border: 1px solid black; padding: 8px; text-align: left; }",
        "</style>",
        "</head>",
        "<body>",
        "<header>",
        f"<h1>Content of {req_path}</h1>",
        "</header>",
        "<main>",
    ]

    # Add parent directory link outside the table
    if req_path != "/":
        parent = req_path.rstrip("/").rsplit("/", 1)[0]
        parent = "/" if not parent else parent + "/"
        lines.append(f'<a class="parent-link" href="{quote(parent)}">⬆ Parent directory</a>')

    # Add the table
    lines.extend([
        "<table>",
        "<thead><tr><th>Name</th><th>Size</th></tr></thead>",
        "<tbody>"
    ])

    for name in entries:
        full = os.path.join(abs_dir, name)
        if os.path.isdir(full):
            href = quote(name) + "/"
            row_class = "dir"
            size = "—"
        else:
            href = quote(name)
            row_class = "file"
            size = file_size(os.path.getsize(full))

        lines.append(
            f'<tr class="{row_class}">'
            f'<td><a href="{href}">{name if not os.path.isdir(full) else name + "/"}</a></td>'
            f"<td>{size}</td>"
            f"</tr>"
        )

    lines.append("</tbody></table></main></body></html>")
    return "\n".join(lines).encode("utf-8")


def _respond_301(conn, location: str):
    body = (f"<html><body>Moved: <a href=\"{location}\">{location}</a></body></html>").encode("utf-8")
    respond(conn, "301 Moved Permanently",
            {"Location": location,
             "Content-Type": "text/html; charset=utf-8",
             "Content-Length": str(len(body)),
             "Connection": "close"},
            body)


def _respond_404(conn):
    body = b"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>404 Not Found</title>
            <style>
                body {
                    text-align: center;
                    padding: 50px;
                }
            </style>
        </head>
            </style>
        </head>
        <body>
        <body>
            <h1>404</h1>
            <p>The page you are looking for does not exist.</p>
            <p><a href="/">Back to homepage</a></p>
        </body>
        </html>
        """
    respond(conn, "404 Not Found",
            {"Content-Type": "text/html; charset=utf-8",
             "Content-Length": str(len(body)),
             "Connection": "close"},
            body)


def main():
    if len(sys.argv) != 2:
        print("Usage: python server.py <directory>")
        sys.exit(1)

    root_dir = sys.argv[1]
    if not os.path.isdir(root_dir):
        print(f"Error: Directory '{root_dir}' does not exist.")
        sys.exit(1)

    root_dir = os.path.abspath(root_dir)
    content_dir = root_dir  # Always serve the root directory

    print(f"Serving directory: {content_dir}")

    # creates new tcp socket with IPv4 and TCP
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # allows restart without "Address already in use"
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", PORT))

    # handles one client at a time
    s.listen(1)
    print(f"Server running on http://0.0.0.0:{PORT}")
    print(f"Access locally: http://localhost:{PORT}")
    print(f"Press Ctrl+C to stop")

    while True:
        # returns a conn socket and client's address
        conn, addr = s.accept()
        print(f"Connection from {addr}")
        try:
            data = conn.recv(4096)
            line = data.split(b"\r\n", 1)[0].decode(errors="replace")
            print(f"Request: {line}")
            parts = line.split()
            if len(parts) != 3:
                respond(
                    conn,
                    "400 Bad Request",
                    {
                        "Content-Type": "text/plain",
                        "Connection": "close"
                    },
                    b"Bad Request"
                )
                continue
            method, target, version = parts
            if method != "GET":
                respond(conn, "405 Method Not Allowed",
                        {"Allow": "GET",
                         "Content-Type": "text/plain",
                         "Connection": "close"},
                        b"Only GET is allowed")
                continue

            # ensure URL path starts with "/"
            if not target.startswith("/"):
                target = "/"

            # decode URL encoded characters
            target = unquote(target)
            # map URL to relative path under root
            if target == "/":
                requested_rel = ""  # root directory
            else:
                requested_rel = target.lstrip("/")

            requested_abs = os.path.realpath(os.path.join(content_dir, requested_rel))
            # 1) reject traversal
            if not _is_subpath(requested_abs, content_dir):
                _respond_404(conn)
                continue

            # 2) if it's a directory
            if os.path.isdir(requested_abs):
                # enforce trailing slash for directories
                if not target.endswith("/"):
                    _respond_301(conn, target + "/")
                    continue

                # always show listing
                body = _minimal_listing_html(target, requested_abs)
                respond(conn, "200 OK",
                        {"Content-Type": "text/html; charset=utf-8",
                         "Content-Length": str(len(body)),
                         "Connection": "close"},
                        body)
                continue

            # 3) regular file flow
            # First check if it exists at the specified path
            if not os.path.isfile(requested_abs):
                # If not found at direct path, try searching recursively for just the filename
                filename = os.path.basename(requested_rel)
                found_path = find_file_recursive(content_dir, filename)

                if found_path:
                    requested_abs = found_path
                    print(f"Found file via recursive search: {found_path}")
                else:
                    _respond_404(conn)
                    continue

            ext = os.path.splitext(requested_abs)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                _respond_404(conn)
                continue

            mime_type, _ = mimetypes.guess_type(requested_abs)
            if mime_type is None:
                _respond_404(conn)
                continue

            try:
                with open(requested_abs, "rb") as f:
                    body = f.read()
                time.sleep(0.5)
                respond(conn, "200 OK",
                        {"Content-Type": mime_type,
                         "Content-Length": str(len(body)),
                         "Connection": "close"},
                        body)
                print(f"Served: {requested_rel} ({mime_type})")
            except OSError:
                respond(conn, "500 Internal Server Error",
                        {"Content-Type": "text/plain",
                         "Connection": "close"},
                        b"Internal Server Error")

        except Exception as e:
            print(f"Error handling request: {e}")
        finally:
            conn.close()


if __name__ == "__main__":
    main()