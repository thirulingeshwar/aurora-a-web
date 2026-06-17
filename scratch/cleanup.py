with open('templates/staff_attendance.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Verify correct boundary lines
start_line = lines[1873]
end_line = lines[2287] # index 2287 is line 2288: "    });\n"
print("Starting deletion at:", start_line.strip()[:100])
print("Ending deletion at:", end_line.strip()[:100])

if "dbWarningBanner" in start_line and "});" in end_line:
    print("Match successful. Executing replacement...")
    lines[1873:2289] = ['<script>\n']
    with open('templates/staff_attendance.html', 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print("Replacement complete.")
else:
    print("Error: Boundary lines do not match expectations.")
