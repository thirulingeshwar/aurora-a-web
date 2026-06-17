import requests
from datetime import datetime, timedelta

BASE_URL = "http://localhost:5000"

def test_custom_dates():
    session = requests.Session()
    today_str = datetime.now().strftime('%Y-%m-%d')
    tomorrow_str = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    print(f"Testing Dates: Today={today_str}, Tomorrow={tomorrow_str}")

    # 1. Login as admin
    print("\n--- 1. Login as Admin ---")
    resp = session.post(f"{BASE_URL}/api/login", json={
        "username": "admin",
        "password": "admin@123"
    })
    print("Login Status:", resp.status_code)
    assert resp.json().get("success") is True

    # 2. Impersonate Staff (thirulingeshwar)
    print("\n--- 2. Impersonate Staff ---")
    resp = session.post(f"{BASE_URL}/api/admin_impersonate", json={
        "username": "thirulingeshwar",
        "password": "thiruli334"
    })
    print("Impersonate Status:", resp.status_code)
    assert resp.json().get("success") is True

    # 3. Clean up existing student with target phone if any
    resp = session.get(f"{BASE_URL}/api/students")
    students = resp.json()
    for s in students:
        if s.get("phone") == "9998887776":
            print(f"Found existing test student {s['name']} (ID: {s['id']}), deleting...")
            session.delete(f"{BASE_URL}/api/students/{s['id']}")

    # 4. Create Student with period-wise timetable
    print("\n--- 4. Register Student with 2 periods ---")
    student_payload = {
        "name": "Test Custom Date Student",
        "phone": "9998887776",
        "class": "Chemistry Class",
        "branch": "Science",
        "parentName": "Parent Name",
        "parentPhone": "0987654321",
        "address": "123 Street",
        "totalClassDays": 30,
        "inTime": "09:00",
        "outTime": "11:00",
        "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "feeAmount": 2500,
        "minAttendanceLimit": 75,
        "timetable": [
            {"startTime": "09:00", "endTime": "10:00", "subject": "Chemistry"},
            {"startTime": "10:00", "endTime": "11:00", "subject": "Lab"}
        ]
    }
    resp = session.post(f"{BASE_URL}/api/students", json=student_payload)
    print("Register Status:", resp.status_code)
    student_data = resp.json().get("student")
    assert student_data is not None
    student_id = student_data["id"]

    # 5. Mark Attendance with Custom Dates: Slot 1 -> Present on Today, Slot 2 -> Absent on Tomorrow
    print("\n--- 5. Save attendance with custom dates (Slot 1: Today, Slot 2: Tomorrow) ---")
    attendance_payload = {
        "date": today_str,  # Default global date
        "attendance": [
            {
                "studentId": student_id,
                "studentName": "Test Custom Date Student",
                "class": "Chemistry Class",
                "branch": "Science",
                "status": "Present",
                "inTime": "09:00",
                "outTime": "10:00",
                "startTime": "09:00",
                "endTime": "10:00",
                "subject": "Chemistry",
                "date": today_str  # Specific custom date
            },
            {
                "studentId": student_id,
                "studentName": "Test Custom Date Student",
                "class": "Chemistry Class",
                "branch": "Science",
                "status": "Absent",
                "inTime": "10:00",
                "outTime": "11:00",
                "startTime": "10:00",
                "endTime": "11:00",
                "subject": "Lab",
                "date": tomorrow_str  # Specific custom date
            }
        ]
    }
    resp = session.post(f"{BASE_URL}/api/attendance", json=attendance_payload)
    print("Save Attendance Status:", resp.status_code)
    print("Save Attendance Response:", resp.json())
    assert resp.status_code == 201

    # 6. Verify marked records for Today
    print("\n--- 6. Verify marked records for Today ---")
    resp = session.get(f"{BASE_URL}/api/attendance?date={today_str}")
    records_today = [r for r in resp.json() if r["studentId"] == student_id]
    print(f"Records found on Today ({today_str}):")
    for r in records_today:
        print(f"Slot: {r.get('startTime')}-{r.get('endTime')} | Subject: {r.get('subject')} | Status: {r.get('status')} | Date: {r.get('date')}")
    assert len(records_today) == 1
    assert records_today[0]["subject"] == "Chemistry"
    assert records_today[0]["status"] == "Present"
    assert records_today[0]["date"] == today_str

    # 7. Verify marked records for Tomorrow
    print("\n--- 7. Verify marked records for Tomorrow ---")
    resp = session.get(f"{BASE_URL}/api/attendance?date={tomorrow_str}")
    records_tomorrow = [r for r in resp.json() if r["studentId"] == student_id]
    print(f"Records found on Tomorrow ({tomorrow_str}):")
    for r in records_tomorrow:
        print(f"Slot: {r.get('startTime')}-{r.get('endTime')} | Subject: {r.get('subject')} | Status: {r.get('status')} | Date: {r.get('date')}")
    assert len(records_tomorrow) == 1
    assert records_tomorrow[0]["subject"] == "Lab"
    assert records_tomorrow[0]["status"] == "Absent"
    assert records_tomorrow[0]["date"] == tomorrow_str

    # 8. Clean up Student
    print("\n--- 8. Clean up test student ---")
    del_resp = session.delete(f"{BASE_URL}/api/students/{student_id}")
    print("Clean up Status:", del_resp.status_code)

    print("\n=== ALL CUSTOM DATE TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    test_custom_dates()
