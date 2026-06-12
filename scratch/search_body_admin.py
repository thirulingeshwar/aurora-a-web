import os

templates = ["templates/login.html", "templates/admin_dashboard.html", "templates/staff_attendance.html"]

for path in templates:
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if "<body" in line.lower():
            print(f"{path}: Line {i+1}: {line.strip()}")
